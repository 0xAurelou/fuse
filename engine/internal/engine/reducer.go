package engine

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"slices"
	"strings"
)

func Apply(before State, c Command) (State, Event, error) {
	if c.Key == "" || len(c.Key) > 200 || c.At <= 0 || c.At < before.At {
		return before, Event{}, reject("missing key or regressing time")
	}
	if before.Policy.Mode == "local" {
		if before.Local == nil && c.Kind != "local_bind" {
			return before, Event{}, reject("local deployment not bound")
		}
		if before.Local != nil && before.Local.Halted != "" && c.Kind != "local_halt" {
			return before, Event{}, reject("local coordinator halted; preserve claims and reconcile")
		}
		if c.Kind == "resume" {
			return before, Event{}, reject("local resume must be observed from AccessController")
		}
		if before.Local != nil && before.Local.Pending != "" && c.Kind != "local_block" && c.Kind != "local_halt" {
			return before, Event{}, reject("local transaction pending reconciliation")
		}
		switch c.Kind {
		case "lp_fund", "deposit", "ack_deposit", "refund_deposit", "paper_settle", "paper_pay":
			return before, Event{}, reject("simulated money commands are disabled in local contract mode")
		}
	} else if strings.HasPrefix(c.Kind, "local_") {
		return before, Event{}, reject("local commands require local policy")
	}
	s := clone(before)
	s.Sequence++
	s.At = c.At
	// Time advancement is part of the same durable command. Rejected commands do
	// not commit it; the independent tick worker will commit expired outcomes.
	if !strings.HasPrefix(c.Kind, "local_") {
		s.advance(c.At)
	}
	s.advanceRecovery(c.At)
	result, err := s.execute(c)
	if err != nil {
		return before, Event{}, err
	}
	if err = s.Check(); err != nil {
		return before, Event{}, fmt.Errorf("invariant: %w", err)
	}
	raw, _ := json.Marshal(result)
	notices := map[string]json.RawMessage{}
	// Sort once per event, rather than once per account. Notice ordering and
	// commitments remain identical as the account/stage population grows.
	stageIDs := keys(s.Stages)
	for id := range s.Accounts {
		balance := s.Balance(id)
		changed := Hash(before.Balance(id)) != Hash(balance)
		stages := []Stage{}
		for _, sid := range stageIDs {
			p := s.Stages[sid]
			if p.Terms.Account == id && Hash(before.Stages[sid]) != Hash(p) {
				stages = append(stages, *p)
				changed = true
			}
		}
		if changed || c.Actor == id {
			v := struct {
				Account BalanceView `json:"account"`
				Stages  []Stage     `json:"stages"`
				Result  any         `json:"result,omitempty"`
			}{balance, stages, nil}
			if c.Actor == id {
				v.Result = result
			}
			notices[id], _ = json.Marshal(v)
		}
	}
	e := Event{Sequence: s.Sequence, PreviousHash: before.JournalHash, StateHash: s.Digest(), Command: c, Result: raw, Postings: postings(before, s), Notices: notices}
	e.Hash = eventHash(e)
	s.JournalHash = e.Hash
	return s, e, nil
}
func (s *State) execute(c Command) (any, error) {
	if c.Asset != "" && c.Kind != "quote" {
		return nil, reject("asset is selected on the quote")
	}
	if c.Multiplier != 0 && c.Kind != "quote" {
		return nil, reject("multiplier is selected on the quote; accepted terms cannot be overridden")
	}
	a := s.Accounts[c.Actor]
	if strings.HasPrefix(c.Kind, "local_") {
		return s.local(c)
	}
	switch c.Kind {
	case "policy_update":
		var p Policy
		decoder := json.NewDecoder(bytes.NewReader(c.Raw))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&p); err != nil {
			return nil, reject("invalid policy JSON")
		}
		var extra any
		if err := decoder.Decode(&extra); err != io.EOF {
			return nil, reject("invalid trailing policy JSON")
		}
		if p.Mode != s.Policy.Mode {
			return nil, reject("operating mode is immutable")
		}
		if Hash(p.Recovery) != Hash(s.Policy.Recovery) {
			return nil, reject("recovery policy is immutable; limits cannot be reset by policy updates")
		}
		if err := p.Validate(); err != nil {
			return nil, reject(err.Error())
		}
		if _, exists := s.PolicyHistory[p.Version]; exists {
			return nil, reject("policy version already exists")
		}
		for asset, oldModel := range s.Policy.Markets {
			model, enabled := p.Markets[asset]
			if enabled && Hash(model) != Hash(oldModel) && model.Version == oldModel.Version {
				return nil, reject("changed market pricing requires a new model version")
			}
			if !enabled {
				for _, stage := range s.Stages {
					if stage.Terms.Asset == asset && (stage.Status == "active" || stage.Status == "pending") {
						return nil, reject("cannot disable a market with open stages")
					}
				}
			}
		}
		if Hash(p.Model) != Hash(s.Policy.Model) && p.Model.Version == s.Policy.Model.Version {
			return nil, reject("changed pricing requires a new model version")
		}
		_, _, active := s.Exposure()
		if active > 0 && (p.MaxGapMS != s.Policy.MaxGapMS || p.DisagreementMS != s.Policy.DisagreementMS || p.VoidDelayMS != s.Policy.VoidDelayMS) {
			return nil, reject("cannot change accepted outage timing while stages remain open")
		}
		s.PolicyHistory[p.Version] = p
		s.Policy = p
		return p, nil
	case "tick":
		return map[string]any{"healthy": s.Healthy(c.At)}, nil
	case "oracle":
		return nil, s.observe(c)
	case "pause":
		s.Paused = true
		return nil, nil
	case "resume":
		if !s.Healthy(c.At) {
			return nil, reject("oracle unhealthy")
		}
		s.Paused = false
		return nil, s.capacity()
	case "lp_fund":
		if c.Amount <= 0 || c.Amount > Limit-s.LP {
			return nil, reject("invalid LP funding")
		}
		s.LP += c.Amount
		return s.LP, nil
	case "deposit":
		if c.Actor == "" || c.ID == "" || c.Amount <= 0 || c.Amount > Limit-s.Custody || s.Deposits[c.ID] != nil {
			return nil, reject("invalid or duplicate deposit")
		}
		s.account(c.Actor)
		d := &Deposit{c.ID, c.Actor, c.Amount, "pending"}
		s.Deposits[c.ID] = d
		s.Custody += c.Amount
		return d, nil
	case "ack_deposit", "refund_deposit":
		d := s.Deposits[c.ID]
		if d == nil || d.Status != "pending" {
			return nil, reject("deposit is not pending")
		}
		if c.Kind == "ack_deposit" {
			s.account(d.Account).Available += d.Amount
			d.Status = "credited"
		} else {
			s.Custody -= d.Amount
			d.Status = "refunded"
		}
		return d, nil
	case "quote":
		return s.quote(c)
	case "enter":
		q, ok := s.Quotes[c.ID]
		if !ok || q.Account != c.Actor || q.PolicyVersion != s.Policy.Version || a == nil || c.At >= q.ValidUntil || q.OracleSequence != s.AssetOracle(q.Asset).Sequence || !s.HealthyAsset(q.Asset, c.At) || s.Paused || !s.Policy.HasAsset(q.Asset) || c.At >= s.Policy.AssetModel(q.Asset).ValidUntil {
			return nil, reject("quote expired, unavailable or stale")
		}
		if a.head(q.Asset) != q.Previous {
			return nil, reject("run changed")
		}
		var funded, debt int64
		if q.Previous != "" {
			previous := s.Stages[q.Previous]
			if previous == nil || previous.Status != "survived" || a.EarnedFunded+a.EarnedUnfunded != q.Stake {
				return nil, reject("rollover unavailable")
			}
			funded, debt = a.EarnedFunded, a.EarnedUnfunded
			a.EarnedFunded = 0
			a.EarnedUnfunded = 0
		} else {
			if a.Available+a.Unfunded < q.Stake {
				return nil, reject("insufficient funds")
			}
			funded = q.Stake
			if funded > a.Available {
				funded = a.Available
			}
			debt = q.Stake - funded
			a.Available -= funded
			a.Unfunded -= debt
		}
		if q.Payout-funded > q.MaxLPLiability {
			return nil, reject("quote funding composition changed")
		}
		id := fmt.Sprintf("stage-%d", s.Sequence)
		p := &Stage{AcceptedSequence: s.Sequence, ID: id, Terms: q, Start: c.At, Expiry: c.At + q.DurationMS, Status: "active", Funded: funded, Debt: debt}
		s.Stages[id] = p
		a.setHead(q.Asset, id)
		if err := s.capacity(); err != nil {
			return nil, err
		}
		delete(s.Quotes, c.ID)
		return p, nil
	case "cashout":
		if a == nil || a.RunHead == "" || a.RunHead != c.ID || s.Stages[a.RunHead].Status != "survived" {
			return nil, reject("no survived stage to cash out")
		}
		a.Available += a.EarnedFunded
		a.Unfunded += a.EarnedUnfunded
		a.EarnedFunded = 0
		a.EarnedUnfunded = 0
		a.RunHead = ""
		return a, nil
	case "withdraw":
		if a == nil || a.Withdrawal != "" || c.Amount <= 0 || c.Amount > a.Available+a.Unfunded {
			return nil, reject("withdrawal unavailable or entitlement already locked")
		}
		f := c.Amount
		if f > a.Available {
			f = a.Available
		}
		a.Available -= f
		a.Unfunded -= c.Amount - f
		a.WithdrawalFunded = f
		a.WithdrawalUnfunded = c.Amount - f
		id := fmt.Sprintf("withdrawal-%d", s.Sequence)
		w := &Withdrawal{ID: id, Account: c.Actor, Recipient: c.Actor, Amount: c.Amount, Cumulative: a.Withdrawn + c.Amount, Status: "pending"}
		s.Withdrawals[id] = w
		a.Withdrawal = id
		return w, nil
	case "paper_settle":
		return s.settle()
	case "paper_pay":
		w := s.Withdrawals[c.ID]
		if w == nil || w.Status != "funded" {
			return nil, reject("withdrawal not funded")
		}
		a = s.account(w.Account)
		if a.Withdrawal != w.ID || a.WithdrawalFunded != w.Amount || a.WithdrawalUnfunded != 0 || s.Custody < w.Amount {
			return nil, reject("withdrawal reconciliation failed")
		}
		a.Withdrawn = w.Cumulative
		a.WithdrawalFunded = 0
		a.Withdrawal = ""
		s.Custody -= w.Amount
		w.Status = "paid"
		return w, nil
	default:
		return nil, reject("unsupported command")
	}
}
func (s *State) quote(c Command) (any, error) {
	asset := AssetName(c.Asset)
	if !s.Policy.HasAsset(asset) {
		return nil, reject("market not enabled")
	}
	oracle, model := s.AssetOracle(asset), s.Policy.AssetModel(asset)
	if c.Actor == "" || !s.HealthyAsset(asset, c.At) || s.Paused || c.At >= model.ValidUntil {
		return nil, reject("oracle or model unavailable")
	}
	a := s.account(c.Actor)
	if asset != "BTC" && a.RunHead != "" && s.Stages[a.RunHead].Terms.Product != SingleStage {
		return nil, reject("finish the historical run before opening another market")
	}
	index := 1
	initial, stake := c.Amount, c.Amount
	single := s.Policy.Product == SingleStage
	if single && (c.Previous != "" || !slices.Contains(s.Policy.MultiplierOptions(), c.Multiplier)) {
		return nil, reject(fmt.Sprintf("single-stage quotes require an integer multiplier from %v and no previous stage", s.Policy.MultiplierOptions()))
	}
	if !single && c.Multiplier != 0 {
		return nil, reject("multiplier selection requires a single-stage policy")
	}
	if c.Previous != "" {
		p := s.Stages[c.Previous]
		if p == nil || p.Terms.Account != c.Actor || p.Status != "survived" || a.RunHead != c.Previous || p.Terms.Index >= 8 {
			return nil, reject("invalid rollover")
		}
		index = p.Terms.Index + 1
		initial = p.Terms.Initial
		stake = p.Terms.Payout
	} else if a.head(asset) != "" || stake < s.Policy.MinStake || stake > s.Policy.MaxStake {
		return nil, reject("invalid stake or unfinished run")
	}
	if stake > a.Available+a.Unfunded && c.Previous == "" {
		return nil, reject("insufficient funds")
	}
	var payout int64
	var err error
	if single {
		payout, err = MulDiv(stake, c.Multiplier, 1)
	} else {
		payout, err = MulDiv(initial, s.Policy.PayoutTable[index], Scale)
	}
	if err != nil || payout <= stake {
		return nil, reject("invalid rounded payout")
	}
	m := model
	var delta int64
	var widthPPB int64
	if single && m.DNT != nil {
		widthPPB, err = m.DNT.WidthPPB(c.Multiplier)
		if err == nil {
			delta, err = MulDiv(oracle.Price, widthPPB, 1_000_000_000)
		}
	} else if single {
		delta, err = MulDiv(oracle.Price, m.MultiplierWidthsPPM[c.Multiplier], 1_000_000)
	} else if m.BaseWidthPPM > 0 {
		delta, err = MulDiv(oracle.Price, m.BaseWidthPPM, 1_000_000)
	} else {
		width := m.BaseWidthBPS
		if len(oracle.ReturnsBPS) > 0 {
			var sum int64
			for _, r := range oracle.ReturnsBPS {
				sum += r
			}
			width += (sum / int64(len(oracle.ReturnsBPS))) * m.VolatilityFactor
		}
		drift := width - m.ControlWidthBPS
		if drift < 0 {
			drift = -drift
		}
		if width > m.MaxWidthBPS || drift > m.MaxDriftBPS {
			return nil, reject("pricing width or control drift limit")
		}
		delta, err = MulDiv(oracle.Price, width, 10_000)

	}
	if err != nil || delta <= 0 || oracle.Price+delta > Limit {
		return nil, reject("invalid corridor")
	}
	funded := stake
	if c.Previous != "" {
		funded = a.EarnedFunded
	} else if funded > a.Available {
		funded = a.Available
	}
	exposure, byAccount, active := s.Exposure()
	replace := int64(0)
	if c.Previous != "" {
		replace = a.EarnedUnfunded
	} else if single {
		replace = stake - funded
	}
	liability := payout - funded
	if single && byAccount[c.Actor]-replace+liability > s.Policy.MaxAccountExposure {
		return nil, reject("account exposure limit")
	}
	if err := s.CheckRecovery(payout - stake); err != nil {
		return nil, err
	}
	if exposure-replace+liability+s.Policy.LPBuffer > s.LPAvailable() || exposure-replace+liability > s.Policy.MaxExposure || active >= s.Policy.MaxActive {
		return nil, reject("LP capacity insufficient")
	}
	q := Quote{ID: fmt.Sprintf("quote-%d", s.Sequence), Account: c.Actor, Asset: asset, Previous: c.Previous, Index: index, Initial: initial, Stake: stake, Payout: payout, Price: oracle.Price, Lower: oracle.Price - delta, Upper: oracle.Price + delta, Issued: c.At, ValidUntil: c.At + s.Policy.QuoteTTLMS, DurationMS: s.Policy.DurationMS, OracleSequence: oracle.Sequence, MaxLPLiability: liability, PolicyVersion: s.Policy.Version, ModelVersion: m.Version, Admission: s.Policy.Admission, GapRule: s.Policy.GapRule, Window: "[start,expiry); touches fail"}
	if single {
		q.Product, q.Multiplier = SingleStage, c.Multiplier
		if m.DNT != nil {
			q.PricingRule, q.VolatilityPPM, q.HouseEdgeBPS, q.WidthPPB = m.DNT.Rule, m.DNT.VolatilityPPM, m.DNT.HouseEdgeBPS, widthPPB
			q.TargetSurvivalPPB, _ = MulDiv(10_000-m.DNT.HouseEdgeBPS, 100_000, c.Multiplier)
		}
	}
	// Quotes are short lived; pruning is deterministic and does not change accepted terms.
	for id, old := range s.Quotes {
		if old.ValidUntil <= c.At || (old.Account == c.Actor && old.Asset == asset) {
			delete(s.Quotes, id)
		}
	}
	s.Quotes[q.ID] = q
	return q, nil
}
func (s *State) fundSettlement() error {
	debt := s.Debt()
	net := debt - s.LossClearing
	if net > s.LPAvailable() || -net > s.Custody-s.PendingDeposits() {
		return reject("settlement not funded")
	}
	s.LP -= net
	s.Custody += net
	s.LossClearing = 0
	s.LPProfit -= net
	if s.LPProfit > s.ProfitHWM {
		s.ProfitHWM = s.LPProfit
	}
	for _, a := range s.Accounts {
		a.Available += a.Unfunded
		a.Unfunded = 0
		a.EarnedFunded += a.EarnedUnfunded
		a.EarnedUnfunded = 0
		a.WithdrawalFunded += a.WithdrawalUnfunded
		a.WithdrawalUnfunded = 0
	}
	for _, p := range s.Stages {
		if p.Status == "active" || p.Status == "pending" {
			p.Funded += p.Debt
			p.Debt = 0
		}
	}
	if err := s.Check(); err != nil {
		return err
	}
	return nil
}
func (s *State) settle() (any, error) {
	net := s.Debt() - s.LossClearing
	if err := s.fundSettlement(); err != nil {
		return nil, err
	}
	from := uint64(1)
	prior := ""
	if len(s.Epochs) > 0 {
		prev := s.Epochs[len(s.Epochs)-1]
		from = prev.To + 1
		prior = prev.Root
	}
	exposure, _, _ := s.Exposure()
	if s.LPAvailable() < exposure+s.Policy.LPBuffer {
		return nil, reject("post-settlement capital buffer insufficient")
	}
	e := Epoch{Number: uint64(len(s.Epochs) + 1), From: from, To: s.Sequence - 1, PriorRoot: prior, Root: s.Digest(), JournalHash: s.JournalHash, OracleHash: s.OracleCommitment(), NetTraderPnL: net, Liability: s.FundedLiability(), Exposure: exposure, RequiredLP: exposure + s.Policy.LPBuffer, Status: "paper-confirmed"}
	// A paper checkpoint is explicitly not an onchain transaction or claim.
	s.Epochs = append(s.Epochs, e)
	for _, w := range s.Withdrawals {
		if w.Status == "pending" {
			w.Status = "funded"
			w.Epoch = e.Number
			w.StateHash = Hash(s.Balance(w.Account))
		}
	}
	return e, nil
}
