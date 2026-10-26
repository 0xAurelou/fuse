package localdev

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"math/big"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"fuse/engine/internal/api"
	"fuse/engine/internal/engine"
	"fuse/engine/internal/oracle"
	"fuse/engine/internal/rewards"
	"fuse/engine/internal/storage"
	"github.com/ethereum/go-ethereum/common"
)

type evidenceLog struct {
	mu     sync.Mutex
	file   *os.File
	err    error
	counts map[string]int
}

func (l *evidenceLog) write(kind string, value any) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.counts[kind]++
	if l.err == nil {
		l.err = json.NewEncoder(l.file).Encode(map[string]any{"received_at": time.Now().UTC().Format(time.RFC3339Nano), "kind": kind, "data": value})
	}
}
func (l *evidenceLog) count(kind string) int { l.mu.Lock(); defer l.mu.Unlock(); return l.counts[kind] }

type simulatedTrader struct {
	Name           string         `json:"name"`
	Wallet         int            `json:"wallet_index"`
	Account        string         `json:"account"`
	Stake          int64          `json:"initial_stake_usdc_units"`
	WidthPPB       int64          `json:"width_ppb,omitempty"`
	WidthPPM       int64          `json:"width_ppm,omitempty"`
	Width          int64          `json:"width_bps"`
	Target         int            `json:"target_stages"`
	Multiplier     int64          `json:"multiplier,omitempty"`
	Deposit        int64          `json:"deposit_usdc_units"`
	Stages         []string       `json:"stage_ids"`
	Withdrawn      int64          `json:"withdrawn_usdc_units"`
	PnL            int64          `json:"pnl_usdc_units"`
	USDC           string         `json:"wallet_usdc_units"`
	FUSE           string         `json:"wallet_fuse_units"`
	Status         string         `json:"status"`
	FinalOutcome   string         `json:"final_outcome"`
	RedemptionPaid int64          `json:"redemption_paid_usdc_units"`
	Strategy       string         `json:"strategy"`
	Cohort         int            `json:"cohort"`
	PricingGroup   string         `json:"pricing_group"`
	MaxRuns        int            `json:"max_runs"`
	Run            int            `json:"run"`
	RunsCompleted  int            `json:"runs_completed"`
	EntryDelayMS   int64          `json:"entry_delay_ms"`
	ReentryDelayMS int64          `json:"reentry_delay_ms"`
	CashoutDelayMS int64          `json:"cashout_delay_ms"`
	Outcomes       map[string]int `json:"outcomes"`
	cashoutAt      time.Time
	observedStage  string

	token         string
	loginAt       time.Time
	head          string
	readyAt       time.Time
	entryDeadline time.Time
}

// SimulationOptions fixes population timing, capture length and control allocation
// before any live outcome is observed.
type SimulationOptions struct {
	CaptureDuration time.Duration `json:"capture_duration_ns"`
	CohortSize      int           `json:"cohort_size"`
	CohortInterval  time.Duration `json:"cohort_interval_ns"`
	ControlEvery    int           `json:"control_every"`
}

func (o SimulationOptions) validate(count int, policy engine.Policy) error {
	if count < 2 || count > MaxLocalTraders || o.CohortSize < 0 || o.CohortSize > MaxLocalTraders || o.ControlEvery < 0 || o.ControlEvery == 1 {
		return fmt.Errorf("invalid population, cohort size or control frequency")
	}
	if o.CaptureDuration < 0 || o.CaptureDuration > time.Hour || o.CohortInterval < 0 || o.CohortInterval > 10*time.Minute {
		return fmt.Errorf("capture must be 0..1h; cohort interval 0..10m")
	}
	if o.ControlEvery > 0 && policy.Model.BaseWidthPPM <= 0 {
		return fmt.Errorf("control population requires a frozen fractional-width policy")
	}
	if o.ControlEvery > 0 && policy.Product == engine.SingleStage {
		return fmt.Errorf("legacy fixed-width controls do not calibrate single-stage multiplier pricing")
	}
	size := o.CohortSize
	if size == 0 {
		size = count
	}
	if time.Duration((count-1)/size)*o.CohortInterval > time.Hour {
		return fmt.Errorf("cohort schedule exceeds one hour")
	}
	return nil
}

func (o SimulationOptions) profiles(count int, seed int64, policy engine.Policy) ([]*simulatedTrader, error) {
	if err := o.validate(count, policy); err != nil {
		return nil, err
	}
	traders, err := traderProfiles(count, seed, policy)
	if err != nil {
		return nil, err
	}
	size := o.CohortSize
	if size == 0 {
		size = count
	}
	for i, trader := range traders {
		trader.Cohort = i/size + 1
		trader.EntryDelayMS += int64(i/size) * o.CohortInterval.Milliseconds()
		trader.PricingGroup = "varied-width-stress"
		if o.ControlEvery > 0 && i%o.ControlEvery == 0 {
			trader.Width, trader.WidthPPM = 0, policy.Model.BaseWidthPPM
			trader.PricingGroup = "frozen-width-control"
		}
	}
	return traders, nil
}

// Simulate preserves the single-cohort live runner's default behavior.
func Simulate(parent context.Context, endpoint, manifest, config, database, feed, output string, traderCount int, seed int64) error {
	return SimulateWithOptions(parent, endpoint, manifest, config, database, feed, output, traderCount, seed, SimulationOptions{})
}

// SimulateWithOptions runs real signatures, HTTP, PostgreSQL and contract writes.
// Only external oracle receivers supply trading prices; ticks use wall time.
func SimulateWithOptions(parent context.Context, endpoint, manifest, config, database, feed, output string, traderCount int, seed int64, options SimulationOptions) (resultErr error) {
	size := options.CohortSize
	if size <= 0 {
		size = max(1, traderCount)
	}
	span := time.Duration(max(0, traderCount-1)/size) * options.CohortInterval
	ctx, cancel := context.WithTimeout(parent, 12*time.Minute+min(time.Hour, max(0, options.CaptureDuration))+min(time.Hour, max(0, span)))
	defer cancel()
	if database == "" {
		return fmt.Errorf("DATABASE_URL required")
	}
	if feed != "wss://api.hyperliquid.xyz/ws" {
		return fmt.Errorf("live simulation requires the official HyperCore endpoint")
	}
	if err := os.MkdirAll(output, 0700); err != nil {
		return err
	}
	file, err := os.OpenFile(filepath.Join(output, "events.jsonl"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer file.Close()
	log := &evidenceLog{file: file, counts: map[string]int{}}
	defer func() {
		if resultErr != nil {
			log.write("run_failed", map[string]string{"error": resultErr.Error()})
		}
		if err := file.Sync(); resultErr == nil && err != nil {
			resultErr = err
		}
	}()
	env, err := Load(ctx, manifest, endpoint)
	if err != nil {
		return err
	}
	raw, err := os.ReadFile(config)
	if err != nil {
		return err
	}
	var policy engine.Policy
	if err = json.Unmarshal(raw, &policy); err != nil {
		return err
	}
	if policy.Mode != "local" {
		return fmt.Errorf("local policy required")
	}
	traders, err := options.profiles(traderCount, seed, policy)
	if err != nil {
		return err
	}
	policy.Version = fmt.Sprintf("local-live-%d-trader-v2", traderCount)
	policy.Model.Version = "live-experiment-width-v1"
	if policy.Model.BaseWidthPPM == 0 {
		policy.Model.Dataset = "live HyperCore BTC oraclePx; research widths, no training"
		policy.Model.TrainingWindow = "untrained local experiment"
		policy.Model.OutOfSampleError = "unknown; not calibrated"
	}
	db, err := storage.OpenPostgres(ctx, database)
	if err != nil {
		return err
	}
	defer func() { _ = db.Close(context.Background()) }()
	q, err := engine.Open(ctx, policy, db)
	if err != nil {
		return err
	}
	if q.Snapshot().Sequence != 0 {
		return fmt.Errorf("live E2E requires a fresh isolated database")
	}
	c, err := NewController(ctx, env, q)
	if err != nil {
		return err
	}
	if err = c.Sync(ctx); err != nil {
		return err
	}
	if q.Snapshot().LP != 250_000_000_000 {
		return fmt.Errorf("live E2E requires exactly 250,000 USDC initial LP")
	}
	// Retain partial state and complete journal on failure as well as success.
	defer func() {
		if err := writeEvidence(output, "final-state.json", q.Snapshot()); resultErr == nil && err != nil {
			resultErr = err
		}
		journal, e := os.OpenFile(filepath.Join(output, "journal.jsonl"), os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
		if e == nil {
			enc := json.NewEncoder(journal)
			for after := uint64(0); ; {
				batch := q.Events(after, 256)
				if len(batch) == 0 {
					break
				}
				for _, event := range batch {
					if e = enc.Encode(event); e != nil {
						break
					}
					after = event.Sequence
				}
				if e != nil {
					break
				}
			}
			_ = journal.Close()
		}
		if resultErr == nil && e != nil {
			resultErr = e
		}
	}()
	operator := common.Bytes2Hex([]byte(fmt.Sprintf("local-simulation-%d", time.Now().UnixNano())))
	base := &api.Server{Q: q, Auth: api.NewLocalAuth("http://fuse-local-simulation"), AdminToken: operator, Origin: "http://fuse-local-simulation", Now: c.Now}
	server := httptest.NewServer(c.Handler(base))
	defer server.Close()
	client := &http.Client{Timeout: 120 * time.Second, Transport: &http.Transport{Proxy: nil}}
	requestOnce := func(method, path, token, key string, payload, out any) error {
		var body bytes.Buffer
		if payload != nil {
			if err := json.NewEncoder(&body).Encode(payload); err != nil {
				return err
			}
		}
		r, err := http.NewRequestWithContext(ctx, method, server.URL+path, &body)
		if err != nil {
			return err
		}
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Authorization", "Bearer "+token)
		if key != "" {
			r.Header.Set("Idempotency-Key", key)
		}
		res, err := client.Do(r)
		if err != nil {
			return err
		}
		defer res.Body.Close()
		b, err := io.ReadAll(io.LimitReader(res.Body, 2<<20))
		if err != nil {
			return err
		}
		if res.StatusCode != 200 {
			log.write("http_rejected", map[string]any{"path": path, "status": res.StatusCode, "body": string(b)})
			return fmt.Errorf("%s: status %d: %s", path, res.StatusCode, b)
		}
		if out != nil {
			return json.Unmarshal(b, out)
		}
		return nil
	}
	request := func(method, path, token, key string, payload, out any) error {
		for attempt := 0; ; attempt++ {
			err := requestOnce(method, path, token, key, payload, out)
			if err == nil {
				return nil
			}
			text := strings.ToLower(err.Error())
			retryable := transientRPC(err) || strings.Contains(text, "context deadline exceeded") || strings.Contains(text, "unexpected eof") || strings.Contains(text, "reconciliation unavailable") || strings.Contains(text, "rpc temporarily unavailable")
			// Only repeat idempotent operations, preserving each original key.
			if attempt >= 2 || !retryable || (key == "" && !strings.HasSuffix(path, "/authorization")) {
				return err
			}
			log.write("rpc_transient_retry", map[string]any{"path": path, "attempt": attempt + 1, "error": err.Error()})
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(time.Second):
			}
		}
	}
	if err = writeEvidence(output, "initial-policy.json", policy); err != nil {
		return err
	}
	if err = writeEvidence(output, "simulation-options.json", options); err != nil {
		return err
	}
	log.write("run_started", map[string]any{"initial_lp_usdc": 250000, "traders": traderCount, "seed": seed, "market_feed": feed, "outcomes": "oraclePx only", "bbo": "evidence only", "stage_duration_seconds": 30, "widths": "explicit untrained experiment; versioned per quote", "deployment": env.Deployment, "initial_policy": policy})
	fmt.Printf("Live E2E: %d traders; LP 250,000 USDC; backend %s\nEvidence: %s\n", traderCount, server.URL, output)
	if err = writeEvidence(output, "profiles.json", traders); err != nil {
		return err
	}
	for _, t := range traders {
		t.Outcomes = map[string]int{}
		t.token, err = Login(ctx, server.URL, t.Wallet)
		if err != nil {
			return err
		}
		t.loginAt = time.Now()
		if err = env.Direct(ctx, t.Wallet, "CustomerCustodyVault", "deposit", big.NewInt(t.Deposit), Wallet(t.Wallet)); err != nil {
			return err
		}
		log.write("deposit_submitted", t)
	}
	if err = c.Sync(ctx); err != nil {
		return err
	}
	for _, t := range traders {
		if a := q.Snapshot().Accounts[t.Account]; a == nil || a.Available != 0 {
			return fmt.Errorf("pending deposit became spendable before acknowledgement")
		}
	}
	workerCtx, stopWorkers := context.WithCancel(ctx)
	var workers sync.WaitGroup
	workerErrors := make(chan error, 1)
	workers.Add(2)
	go func() {
		defer workers.Done()
		oracle.Collector{Assets: policy.Assets(), URL: feed, Sequencer: q, Log: slog.Default(), Observe: func(source, channel string, raw json.RawMessage) {
			log.write("market_"+channel, map[string]any{"source": source, "raw": raw})
		}, Submit: func(ctx context.Context, source string, raw json.RawMessage) error {
			return q.Exclusive(func(w *engine.Writer) error {
				s := w.Snapshot()
				_, err := w.Execute(ctx, engine.Command{Key: fmt.Sprintf("live/oracle/%s/%d", source, s.Sequence+1), Kind: "oracle", Source: source, At: max(time.Now().UnixMilli(), s.At), Raw: raw})
				return err
			})
		}}.Run(workerCtx)
	}()
	go func() {
		defer workers.Done()
		tick := time.NewTicker(500 * time.Millisecond)
		defer tick.Stop()
		for {
			select {
			case <-workerCtx.Done():
				return
			case <-tick.C:
				err := c.Sync(workerCtx)
				if err == nil {
					err = q.Exclusive(func(w *engine.Writer) error {
						s := w.Snapshot()
						_, e := w.Execute(workerCtx, engine.Command{Key: fmt.Sprintf("live/tick/%d", s.Sequence+1), Kind: "tick", At: max(time.Now().UnixMilli(), s.At)})
						return e
					})
				}
				if err != nil && workerCtx.Err() == nil {
					if transientRPC(err) {
						log.write("rpc_transient_retry", map[string]any{"operation": "sync", "error": err.Error()})
						continue
					}
					select {
					case workerErrors <- err:
					default:
					}
					return
				}
			}
		}
	}()
	defer func() { stopWorkers(); workers.Wait() }()
	wait := func(duration time.Duration) error {
		timer := time.NewTimer(duration)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			return ctx.Err()
		case err := <-workerErrors:
			return err
		case <-timer.C:
			return nil
		}
	}
	deadline := time.Now().Add(45 * time.Second)
	for !q.Snapshot().Healthy(time.Now().UnixMilli()) || log.count("market_bbo") == 0 {
		if time.Now().After(deadline) {
			return fmt.Errorf("live HyperCore oracle/BBO did not become healthy; no fixture fallback")
		}
		if err = wait(100 * time.Millisecond); err != nil {
			return err
		}
	}
	if err = request("POST", "/local/checkpoints", operator, "live/deposits", map[string]any{}, nil); err != nil {
		return err
	}
	for _, t := range traders {
		if q.Snapshot().Accounts[t.Account].Available != t.Deposit {
			return fmt.Errorf("deposit acknowledgement missing for %s", t.Name)
		}
	}
	log.write("deposits_acknowledged", map[string]any{"checkpoint": q.Snapshot().Epochs, "custody": q.Snapshot().Custody})
	start := time.Now()
	for _, t := range traders {
		t.scheduleEntry(start.Add(time.Duration(t.EntryDelayMS) * time.Millisecond))
	}
	attempt := 0
	refreshSession := func(t *simulatedTrader) error {
		if time.Since(t.loginAt) < 25*time.Minute {
			return nil
		}
		token, err := Login(ctx, server.URL, t.Wallet)
		if err == nil {
			t.token, t.loginAt = token, time.Now()
		}
		return err
	}
	enter := func(t *simulatedTrader) error {
		if err := refreshSession(t); err != nil {
			return err
		}
		attempt++
		p := q.Snapshot().Policy
		if p.Product != engine.SingleStage && (p.Model.BaseWidthBPS != t.Width || p.Model.BaseWidthPPM != t.WidthPPM || p.Model.ControlWidthBPS != t.Width) {
			p.Version = fmt.Sprintf("local-live-width-%d", attempt)
			p.Model.Version = fmt.Sprintf("live-width-%d", attempt)
			p.Model.BaseWidthBPS = t.Width
			p.Model.ControlWidthBPS = t.Width
			p.Model.BaseWidthPPM = t.WidthPPM
			policyRaw, _ := json.Marshal(p)
			if err := request("POST", "/admin/commands", operator, "", engine.Command{Key: fmt.Sprintf("admin/live-policy/%d", attempt), Kind: "policy_update", Raw: policyRaw}, nil); err != nil {
				return err
			}
		}
		var quote struct{ Result engine.Quote }
		key := fmt.Sprintf("live/%s/run-%d/attempt-%d", t.Name, t.Run, attempt)
		if err := request("POST", "/v1/quotes", t.token, key+"/quote", map[string]any{"amount": t.Stake, "previous": t.head, "multiplier": t.Multiplier}, &quote); err != nil {
			return err
		}
		var stage struct{ Result engine.Stage }
		if err := request("POST", "/v1/stages", t.token, key+"/enter", map[string]string{"id": quote.Result.ID}, &stage); err != nil {
			return err
		}
		t.head = stage.Result.ID
		t.Stages = append(t.Stages, t.head)
		t.Status = "active"
		log.write("stage_entered", map[string]any{"trader": t.Name, "stage": stage.Result})
		fmt.Printf("%s stage %d: stake %.6f USDC; width %.4f bps; oracle %.6f; [%.6f, %.6f]\n", t.Name, stage.Result.Terms.Index, float64(stage.Result.Terms.Stake)/1e6, t.widthBPS(), float64(stage.Result.Terms.Price)/1e6, float64(stage.Result.Terms.Lower)/1e6, float64(stage.Result.Terms.Upper)/1e6)
		return nil
	}
	lastRisk := time.Time{}
	lastSettlement := time.Now()
	checkpointCount := 0
	for {
		done := 0
		entriesThisPass := 0
		s := q.Snapshot()
		for _, t := range traders {
			if t.Status == "complete" {
				done++
				continue
			}
			if t.Status == "waiting" {
				if time.Now().Before(t.readyAt) || entriesThisPass >= 8 {
					continue
				}
				if t.entryDeadline.IsZero() {
					log.write("entry_queue_wait", map[string]any{"trader": t.Name, "delay_ms": time.Since(t.readyAt).Milliseconds()})
					t.entryDeadline = time.Now().Add(60 * time.Second)
				}
				if time.Now().After(t.entryDeadline) {
					return fmt.Errorf("%s could not obtain an admissible quote", t.Name)
				}
				entriesThisPass++
				if err = enter(t); err != nil {
					log.write("entry_retry", map[string]any{"trader": t.Name, "error": err.Error()})
					t.readyAt = time.Now().Add(500 * time.Millisecond)
				}
				continue
			}
			stage := s.Stages[t.head]
			if stage.Status == "active" || stage.Status == "pending" {
				continue
			}
			if t.observedStage != stage.ID {
				log.write("stage_outcome", map[string]any{"trader": t.Name, "run": t.Run, "stage": stage, "oracle": s.Oracle})
				fmt.Printf("%s run %d stage %d: %s\n", t.Name, t.Run, stage.Terms.Index, stage.Status)
				t.observedStage = stage.ID
				t.Outcomes[stage.Status]++
			}
			if stage.Status == "survived" && stage.Terms.Product != engine.SingleStage {
				// Risk-aware traders stop after a survived stage with appreciable oracle
				// displacement, rather than rolling blindly toward the original target.
				displacement := s.Oracle.Price - stage.Terms.Price
				if displacement < 0 {
					displacement = -displacement
				}
				adverse := t.Strategy == "risk-aware" && float64(displacement)/float64(stage.Terms.Price)*10_000 >= t.widthBPS()/3
				if stage.Terms.Index < t.Target && !adverse {
					t.Status = "waiting"
					t.scheduleEntry(time.Now().Add(time.Duration(t.ReentryDelayMS) * time.Millisecond))
					continue
				}
				if t.cashoutAt.IsZero() {
					t.cashoutAt = time.Now().Add(time.Duration(t.CashoutDelayMS) * time.Millisecond)
				}
				if time.Now().Before(t.cashoutAt) {
					continue
				}
				if err = request("POST", "/v1/cashout", t.token, fmt.Sprintf("live/%s/run-%d/cashout", t.Name, t.Run), map[string]string{"id": t.head}, nil); err != nil {
					return err
				}
				log.write("cashout", map[string]any{"trader": t.Name, "run": t.Run, "stage": t.head, "risk_aware_exit": adverse})
			}
			t.FinalOutcome = stage.Status
			t.RunsCompleted++
			if t.Run < t.MaxRuns {
				t.Run++
				t.head = ""
				t.cashoutAt = time.Time{}
				t.Status = "waiting"
				t.scheduleEntry(time.Now().Add(time.Duration(t.ReentryDelayMS) * time.Millisecond))
				continue
			}
			t.Status = "complete"
			done++
		}

		s = q.Snapshot()
		if time.Since(lastRisk) > 5*time.Second {
			exposure, _, active := s.Exposure()
			log.write("risk_snapshot", map[string]any{"lp_usdc_units": s.LP, "exposure_usdc_units": exposure, "lp_buffer_usdc_units": s.Policy.LPBuffer, "active": active, "custody_usdc_units": s.Custody, "loss_clearing_usdc_units": s.LossClearing, "healthy": s.Healthy(time.Now().UnixMilli()), "sequence": s.Sequence})
			lastRisk = time.Now()
		}
		if time.Since(lastSettlement) >= 15*time.Second {
			checkpointCount++
			if err = request("POST", "/local/checkpoints", operator, fmt.Sprintf("live/periodic/%d", checkpointCount), map[string]any{}, nil); err != nil {
				return err
			}
			log.write("periodic_settlement", q.Snapshot().Epochs[len(q.Snapshot().Epochs)-1])
			lastSettlement = time.Now()
		}
		if done == traderCount && time.Since(start) >= options.CaptureDuration {
			break
		}
		if err = wait(250 * time.Millisecond); err != nil {
			return err
		}
	}
	stopWorkers()
	workers.Wait()
	if err = request("POST", "/local/checkpoints", operator, "live/final-settlement", map[string]any{}, nil); err != nil {
		return err
	}
	for _, t := range traders {
		a := q.Snapshot().Accounts[t.Account]
		if err = refreshSession(t); err != nil {
			return err
		}
		amount := a.Available + a.Unfunded
		if amount > 0 {
			var withdrawal struct{ Result engine.Withdrawal }
			if err = request("POST", "/v1/withdrawals", t.token, "live/"+t.Name+"/withdraw", map[string]any{"amount": amount}, &withdrawal); err != nil {
				return err
			}
			var ticket engine.LocalTicket
			if err = request("POST", "/v1/withdrawals/"+withdrawal.Result.ID+"/authorization", t.token, "", map[string]any{}, &ticket); err != nil {
				return err
			}
			if err = env.ClaimWithdrawal(ctx, t.Wallet, ticket); err != nil {
				return err
			}
			if err = c.Sync(ctx); err != nil {
				return err
			}
			if q.Snapshot().Withdrawals[withdrawal.Result.ID].Status != "paid" {
				return fmt.Errorf("withdrawal not confirmed")
			}
			// The contract must reject a second payment of the exact same authorization.
			if e := env.ClaimWithdrawal(ctx, t.Wallet, ticket); e == nil {
				return fmt.Errorf("withdrawal replay paid twice")
			}
			log.write("withdrawal_paid", map[string]any{"trader": t.Name, "amount_usdc_units": amount, "ticket": ticket, "replay_rejected": true})
		}
	}
	// Rewards require a checkpoint that includes all finalized outcomes.
	budget := new(big.Int).Mul(big.NewInt(1000), big.NewInt(1e18))
	finalized := 0
	for _, stage := range q.Snapshot().Stages {
		if stage.Status == "survived" || stage.Status == "exploded" {
			finalized++
		}
	}
	if finalized > 0 {
		if err = request("POST", "/local/rewards", operator, "live/rewards", map[string]string{"budget": budget.String()}, nil); err != nil {
			return err
		}
		record := q.Snapshot().Local.Rewards["1"]
		for _, allocation := range record.Allocations {
			wallet := 0
			for _, t := range traders {
				if t.Account == allocation.Account {
					wallet = t.Wallet
				}
			}
			if wallet == 0 {
				return fmt.Errorf("unknown reward recipient")
			}
			amount, ok := new(big.Int).SetString(allocation.Amount, 10)
			if !ok {
				return fmt.Errorf("invalid reward allocation")
			}
			proof := []common.Hash{}
			for _, p := range allocation.Proof {
				proof = append(proof, common.HexToHash(p))
			}
			if err = env.Direct(ctx, wallet, "RewardDistributor", "claim", uint64(1), new(big.Int).SetUint64(allocation.Index), Wallet(wallet), amount, proof); err != nil {
				return err
			}
		}
		if err = c.Sync(ctx); err != nil {
			return err
		}
		log.write("rewards_claimed", q.Snapshot().Local.Rewards["1"])
	} else {
		log.write("rewards_skipped", "no scored finalized stages; oracle gaps voided all positions")
	}
	s := q.Snapshot()
	allocation, err := env.Uint(ctx, "LPVault", "reserveAllocationBps", 0)
	if err != nil {
		return err
	}
	lastCapital, err := env.Uint(ctx, "LPVault", "requiredCapitalUSDC", 0)
	if err != nil {
		return err
	}
	contribution, _, _, err := rewards.ReserveContributionV2(max(s.LPProfit, 0), s.ProfitHWM, s.ConsumedProfit, s.LP, max(s.Policy.LPBuffer, lastCapital.Int64()), allocation.Int64())
	if err != nil {
		return err
	}
	if contribution > 0 && finalized > 0 {
		redemptionDuration := max(120, traderCount*3)
		if err = request("POST", "/local/reserve", operator, "live/reserve", map[string]any{"amount": contribution}, nil); err != nil {
			return err
		}
		if err = request("POST", "/local/redemptions", operator, "live/redemption", map[string]any{"duration": redemptionDuration, "penalty_bps": 1000}, nil); err != nil {
			return err
		}
		// Trading has ended. Chain-only time advancement opens/closes the redemption
		// window; no engine clock or synthetic oracle prices are introduced.
		if err = env.RPC.Advance(ctx, 3); err != nil {
			return err
		}
		for _, t := range traders {
			balance, e := env.Uint(ctx, "FUSEToken", "balanceOf", 0, Wallet(t.Wallet))
			if e != nil {
				return e
			}
			if balance.Sign() == 0 {
				continue
			}
			if err = env.Direct(ctx, t.Wallet, "FUSEToken", "approve", env.Address("RedemptionReserve"), balance); err != nil {
				return err
			}
			if err = env.Direct(ctx, t.Wallet, "RedemptionReserve", "requestRedeem", balance); err != nil {
				return err
			}
		}
		if err = c.Sync(ctx); err != nil {
			return err
		}
		if err = env.RPC.Advance(ctx, uint64(redemptionDuration+10)); err != nil {
			return err
		}
		for _, t := range traders {
			record := q.Snapshot().Local.Redemptions["1/"+t.Account]
			if record == nil || record.Accrued == 0 {
				continue
			}
			if err = env.Direct(ctx, t.Wallet, "RedemptionReserve", "claimRedeemedUSDC", uint64(1)); err != nil {
				return err
			}
		}
		if err = c.Sync(ctx); err != nil {
			return err
		}
		log.write("redemptions_paid", q.Snapshot().Local.Redemptions)
	} else {
		log.write("reserve_redemption_skipped", "no distributable realized LP profit; no reserve money invented")
	}
	if err = c.Sync(ctx); err != nil {
		return err
	}
	s = q.Snapshot()
	disclosures, viewErr := c.TokenomicsView(ctx)
	if viewErr != nil {
		return viewErr
	}
	if err = writeEvidence(output, "tokenomics.json", disclosures); err != nil {
		return err
	}
	if s.Local.Halted != "" {
		return fmt.Errorf("local controller halted: %s", s.Local.Halted)
	}
	if err = s.Check(); err != nil {
		return err
	}
	exposure, _, active := s.Exposure()
	if active != 0 || exposure != 0 || s.LossClearing != 0 {
		return fmt.Errorf("unreconciled open risk")
	}
	total := new(big.Int)
	addresses := []common.Address{Wallet(Governance), env.Address("CustomerCustodyVault"), env.Address("LPVault"), env.Address("RedemptionReserve")}
	for _, t := range traders {
		u, e := env.Uint(ctx, "USDC", "balanceOf", 0, Wallet(t.Wallet))
		if e != nil {
			return e
		}
		f, e := env.Uint(ctx, "FUSEToken", "balanceOf", 0, Wallet(t.Wallet))
		if e != nil {
			return e
		}
		t.USDC = u.String()
		t.FUSE = f.String()
		t.Withdrawn = s.Accounts[t.Account].Withdrawn
		t.PnL = t.Withdrawn - t.Deposit
		if r := s.Local.Redemptions["1/"+t.Account]; r != nil {
			t.RedemptionPaid = r.Paid
		}
		addresses = append(addresses, Wallet(t.Wallet))
	}
	for _, address := range addresses {
		n, e := env.Uint(ctx, "USDC", "balanceOf", 0, address)
		if e != nil {
			return e
		}
		total.Add(total, n)
	}
	supply, err := env.Uint(ctx, "USDC", "totalSupply", 0)
	if err != nil {
		return err
	}
	if supply.Cmp(total) != 0 {
		return fmt.Errorf("USDC supply conservation failed")
	}
	if s.Custody != 0 {
		return fmt.Errorf("customer custody not fully paid out")
	}
	if log.count("market_bbo") == 0 || len(s.Oracle.Sources) != 2 {
		return fmt.Errorf("missing live market evidence")
	}
	// Stop the writer and prove exact durable replay before calling the run passed.
	before := engine.Hash(s)
	if err = db.Close(ctx); err != nil {
		return err
	}
	reopened, err := storage.OpenPostgres(ctx, database)
	if err != nil {
		return err
	}
	defer reopened.Close(context.Background())
	replay, err := engine.Open(ctx, policy, reopened)
	if err != nil {
		return err
	}
	if engine.Hash(replay.Snapshot()) != before {
		return fmt.Errorf("PostgreSQL replay changed final state")
	}
	reserveCoverage := "skipped: no distributable realized LP profit"
	if contribution > 0 && finalized > 0 {
		reserveCoverage = "confirmed funding, burn and USDC claim"
	}
	summary := map[string]any{"reserve_redemption_coverage": reserveCoverage, "passed": true, "initial_lp_usdc_units": int64(250_000_000_000), "final_lp_usdc_units": s.LP, "lp_realized_pnl_usdc_units": s.LPProfit, "reserve_usdc_units": s.Reserve, "custody_usdc_units": s.Custody, "exposure_usdc_units": exposure, "usdc_total_supply_units": supply.String(), "usdc_sum_balances_units": total.String(), "journal_events": s.Sequence, "chain_events": s.Local.ChainEvents, "checkpoints": len(s.Epochs), "oracle_messages": log.count("market_activeAssetCtx"), "bbo_messages": log.count("market_bbo"), "elapsed_seconds": time.Since(start).Seconds(), "traders": traders, "trader_count": traderCount, "strategy_seed": seed, "outcomes": stageCounts(s), "postgres_replay_verified": true, "state_hash": before, "feed": feed, "settlement_price": "HyperCore BTC oraclePx", "policy": "local experiment; widths uncalibrated; 30 second stages; two connections to one upstream"}
	if err = writeSettlementEvidence(ctx, env, q, output, summary); err != nil {
		return err
	}
	summary["simulation_options"] = options
	if err = writeEvidence(output, "summary.json", summary); err != nil {
		return err
	}
	var report strings.Builder
	fmt.Fprintf(&report, "# Live local E2E\n\nPassed. Initial LP: 250,000 USDC. Final LP: %.6f USDC.\n\nLive HyperCore BTC BBO is logged; barrier outcomes use oraclePx. All amounts in JSON use USDC atomic units (6 decimals). Widths are uncalibrated local experiment policies.\n\n| Trader | Stake USDC | Width bps | Strategy | Target | Runs | Stages entered | Withdrawn USDC | Trading PnL USDC | Final outcome |\n|---|---:|---:|---|---:|---:|---:|---:|---:|---|\n", float64(s.LP)/1e6)
	for _, t := range traders {
		fmt.Fprintf(&report, "| %s | %.2f | %.4f | %s | %d | %d | %d | %.6f | %.6f | %s |\n", t.Name, float64(t.Stake)/1e6, t.widthBPS(), t.Strategy, t.Target, t.RunsCompleted, len(t.Stages), float64(t.Withdrawn)/1e6, float64(t.PnL)/1e6, t.FinalOutcome)
	}
	fmt.Fprintf(&report, "\nReserve/redemption: %s. Realized LP PnL: %.6f USDC.\n", reserveCoverage, float64(s.LPProfit)/1e6)
	fmt.Fprintf(&report, "\nOutcomes: %v. Oracle messages: %d. BBO messages: %d.\n\nVerified: confirmed deposits before credit, signed checkpoint settlement, customer payouts, withdrawal replay rejection, reward claims where scored outcomes exist, conditional profit-backed reserve/redemption, zero open risk, USDC conservation, exact PostgreSQL replay.\n\nEvidence: events.jsonl (market and actions), journal.jsonl (ordered ledger plus canonical chain evidence), final-state.json, summary.json. Deployed artifact pins and chain identity are in deployment.json in the parent directory.\n", stageCounts(s), log.count("market_activeAssetCtx"), log.count("market_bbo"))
	if err = os.WriteFile(filepath.Join(output, "report.md"), []byte(report.String()), 0600); err != nil {
		return err
	}
	log.mu.Lock()
	err = log.err
	log.mu.Unlock()
	if err != nil {
		return err
	}
	log.write("run_passed", summary)
	if err = file.Sync(); err != nil {
		return err
	}
	fmt.Printf("PASS: LP %.6f USDC; outcomes %v; %d BBO messages; exact PostgreSQL replay verified\nReport: %s\n", float64(s.LP)/1e6, stageCounts(s), log.count("market_bbo"), filepath.Join(output, "report.md"))
	return nil
}
func writeEvidence(directory, name string, value any) error {
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(directory, name), append(raw, '\n'), 0600)
}
func stageCounts(s engine.State) map[string]int {
	counts := map[string]int{}
	for _, stage := range s.Stages {
		counts[stage.Status]++
	}
	return counts
}

func (t *simulatedTrader) widthBPS() float64 {
	if t.WidthPPB > 0 {
		return float64(t.WidthPPB) / 100_000
	}
	if t.WidthPPM > 0 {
		return float64(t.WidthPPM) / 100
	}
	return float64(t.Width)
}
