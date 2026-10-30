package localdev

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"testing"
	"time"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/dailyrelay"
	"fuse/engine/internal/engine"
	"fuse/engine/internal/storage"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

type dailyLimitsABI struct {
	PerBet                                                    *big.Int
	PerMarket                                                 [3]*big.Int
	Total, AdmissionBuffer, DistributionBuffer, BackingBuffer *big.Int
}
type dailyDepositABI struct {
	Owner    common.Address
	Amount   *big.Int
	Id       [32]byte
	Deadline uint64
}
type dailyCloseABI struct {
	Day, Watermark                                         uint64
	BetSequence, Allowance, PendingCredit, StandardNeed30d *big.Int
	JournalHash                                            [32]byte
	Deadline                                               uint64
}
type dailyTestSigner struct{ calls int }
type dailyReorgRPC struct {
	base            dailyrelay.RPC
	block           uint64
	corrupt         bool
	corruptTransfer common.Hash
	usdc            common.Address
}

func (r *dailyReorgRPC) ReadRPC(ctx context.Context, method string, params any, out any) error {
	var raw json.RawMessage
	if err := r.base.ReadRPC(ctx, method, params, &raw); err != nil {
		return err
	}
	if r.corrupt && method == "eth_getBlockByNumber" {
		args := params.([]any)
		if args[0] == hexutil.EncodeUint64(r.block) {
			var object map[string]any
			if err := json.Unmarshal(raw, &object); err != nil {
				return err
			}
			object["hash"] = crypto.Keccak256Hash([]byte("replacement finalized block")).Hex()
			raw, _ = json.Marshal(object)
		}
	}
	if method == "eth_getTransactionReceipt" && r.corruptTransfer != (common.Hash{}) {
		var receipt types.Receipt
		if err := json.Unmarshal(raw, &receipt); err != nil {
			return err
		}
		if receipt.TxHash == r.corruptTransfer {
			for _, log := range receipt.Logs {
				if log.Address == r.usdc && len(log.Topics) > 0 && log.Topics[0] == crypto.Keccak256Hash([]byte("Transfer(address,address,uint256)")) {
					log.Data[31] ^= 1
				}
			}
			raw, _ = json.Marshal(receipt)
		}
	}
	return json.Unmarshal(raw, out)
}

func (s *dailyTestSigner) SignDigest(_ context.Context, role string, digest common.Hash) ([]byte, error) {
	s.calls++
	switch role {
	case "SETTLEMENT_SIGNER":
		return sign(SettlementSigner, digest)
	case "RISK_SIGNER":
		return sign(RiskSigner, digest)
	}
	return nil, fmt.Errorf("unexpected signer role")
}

// Actual isolated Anvil + PostgreSQL, using the existing guarded local sender.
// No production deployment, private key or public RPC is used by the relay.
func TestDailySharedEngineBindingsE2E(t *testing.T) {
	endpoint, manifest, database, output := os.Getenv("FUSE_DAILY_E2E_RPC"), os.Getenv("FUSE_DAILY_E2E_MANIFEST"), os.Getenv("FUSE_DAILY_E2E_DATABASE"), os.Getenv("FUSE_DAILY_E2E_OUTPUT")
	if endpoint == "" || manifest == "" || database == "" {
		t.Skip("run scripts/daily_settlement_e2e.py for isolated daily relay rehearsal")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	env, err := Load(ctx, manifest, endpoint)
	if err != nil {
		t.Fatal(err)
	}
	if output == "" {
		output = t.TempDir()
	}
	if err = os.MkdirAll(output, 0700); err != nil {
		t.Fatal(err)
	}
	check := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	deploy := func(module, contract, source string, args ...any) {
		t.Helper()
		a, err := readArtifact(filepath.Join("../../../out", source+".sol", contract+".json"))
		check(err)
		data, err := a.ABI.Pack("", args...)
		check(err)
		receipt, err := env.RPC.Send(ctx, Governance, nil, append(a.Bytecode, data...))
		check(err)
		a.Module.Address = receipt.ContractAddress
		env.ABIs[module] = a.ABI
		env.Deployment.Modules[module] = a.Module
	}
	access, usdc := env.Address("AccessController"), env.Address("USDC")
	zero := new(big.Int)
	caps := dailyLimitsABI{big.NewInt(1_000_000_000_000), [3]*big.Int{big.NewInt(2_000_000_000_000), big.NewInt(2_000_000_000_000), big.NewInt(2_000_000_000_000)}, big.NewInt(3_000_000_000_000), zero, zero, zero}
	deploy("DailyLPVault", "DailyLPVault", "DailyLPVault", access, usdc, Wallet(Governance), caps)
	deploy("DailyBetCustody", "DailyBetCustody", "DailyBetCustody", access, usdc, env.Address("DailyLPVault"), big.NewInt(2_000_000_000_000), big.NewInt(1024))
	deploy("DailyReserve", "RedemptionReserve", "RedemptionReserve", access, usdc, env.Address("FUSEToken"), env.Address("DailyLPVault"))
	check(env.Direct(ctx, Governance, "DailyLPVault", "configure", env.Address("DailyBetCustody"), env.Address("DailyReserve")))
	check(env.Direct(ctx, Governance, "USDC", "mint", env.Address("DailyReserve"), big.NewInt(125_000_000)))
	check(env.Direct(ctx, Governance, "AccessController", "pauseTrading"))
	for i, entry := range []struct {
		wallet int
		amount int64
	}{{Governance, 2_000_000_000}, {Bob, 1_000_000_000}} {
		check(env.Direct(ctx, Governance, "USDC", "mint", Wallet(entry.wallet), big.NewInt(entry.amount)))
		check(env.Direct(ctx, entry.wallet, "USDC", "approve", env.Address("DailyLPVault"), big.NewInt(entry.amount)))
		now, err := env.RPC.Timestamp(ctx)
		check(err)
		a := dailyDepositABI{Wallet(entry.wallet), big.NewInt(entry.amount), crypto.Keccak256Hash([]byte(fmt.Sprint("daily-deposit/", i))), now + 300}
		v, err := env.Read(ctx, "DailyLPVault", "hashDeposit", 0, a)
		check(err)
		digest := common.Hash(v[0].([32]byte))
		s, err := sign(SettlementSigner, digest)
		check(err)
		r, err := sign(RiskSigner, digest)
		check(err)
		check(env.Direct(ctx, entry.wallet, "DailyLPVault", "deposit", a, s, r))
	}
	check(env.Direct(ctx, Governance, "USDC", "mint", Wallet(Alice), big.NewInt(100_000_000)))
	check(env.Direct(ctx, Alice, "USDC", "approve", env.Address("DailyBetCustody"), big.NewInt(100_000_000)))
	check(env.Direct(ctx, Alice, "DailyBetCustody", "deposit", big.NewInt(100_000_000)))
	check(env.Direct(ctx, Governance, "AccessController", "resumeTrading"))
	check(env.RPC.Mine(ctx, 2))
	head, err := env.RPC.Head(ctx)
	check(err)
	anchor, err := env.RPC.Header(ctx, head-1)
	check(err)
	dm := dailyrelay.Manifest{ChainID: ChainID, Confirmations: 1, Anchor: contracts.Cursor{Number: anchor.Number, Hash: anchor.Hash}, Modules: map[string]dailyrelay.ModulePin{}}
	for name, module := range map[string]string{"AccessController": "AccessController", "DailyLPVault": "DailyLPVault", "DailyBetCustody": "DailyBetCustody", "USDC": "USDC", "RedemptionReserve": "DailyReserve"} {
		pin := env.Deployment.Modules[module]
		if name == "USDC" {
			pin = env.Deployment.USDC
		}
		code, err := env.RPC.Code(ctx, pin.Address)
		check(err)
		dm.Modules[name] = dailyrelay.ModulePin{Module: pin, RuntimeHash: crypto.Keccak256Hash(code)}
		artifact, _, err := contracts.PinnedArtifact(manifest, pin)
		check(err)
		check(os.MkdirAll(filepath.Join(output, "artifacts"), 0700))
		check(os.WriteFile(filepath.Join(output, "artifacts", filepath.Base(pin.Artifact)), artifact, 0600))
	}
	manifestPath := filepath.Join(output, "daily-deployment.json")
	raw, _ := json.MarshalIndent(dm, "", "  ")
	check(os.WriteFile(manifestPath, raw, 0600))
	reader, err := dailyrelay.NewReader(manifestPath, env.RPC)
	check(err)
	policyRaw, err := os.ReadFile("../../config/paper.json")
	check(err)
	var policy engine.Policy
	check(json.Unmarshal(policyRaw, &policy))
	policy.Version += "-daily-binding-e2e"
	policy.QuoteTTLMS = 5000 // Synthetic local execution fixture; not approved latency calibration.
	state, err := engine.NewState(policy)
	check(err)
	sourceDB, err := storage.OpenPostgres(ctx, database)
	check(err)
	sourceQ, err := engine.Open(ctx, policy, sourceDB)
	check(err)
	if sourceQ.Snapshot().Sequence != 0 {
		t.Fatal("daily rehearsal requires a fresh canonical journal")
	}
	defer func() { _ = sourceDB.Close(context.Background()) }()
	reader, err = dailyrelay.NewSigningReader(manifestPath, env.RPC, sourceQ)
	check(err)
	events := []engine.Event{}
	serial := 0
	apply := func(c engine.Command) engine.Event {
		t.Helper()
		serial++
		c.Key = fmt.Sprintf("daily-e2e/%d", serial)
		e, err := sourceQ.Execute(ctx, c)
		check(err)
		state = sourceQ.Snapshot()
		events = append(events, e)
		return e
	}
	now, err := env.RPC.Timestamp(ctx)
	check(err)
	at := int64(now) * 1000
	apply(engine.Command{Kind: "lp_fund", Amount: 3_000_000_000, At: at})
	apply(engine.Command{Kind: "deposit", Actor: Wallet(Alice).Hex(), ID: "customer", Amount: 100_000_000, At: at})
	apply(engine.Command{Kind: "ack_deposit", ID: "customer", At: at})
	price := func(asset, value string, at int64) {
		t.Helper()
		for _, source := range []string{"a", "b"} {
			apply(engine.Command{Kind: "oracle", At: at, Source: source, Raw: json.RawMessage(fmt.Sprintf(`{"channel":"activeAssetCtx","data":{"coin":%q,"ctx":{"oraclePx":%q}}}`, asset, value))})
		}
	}
	price("BTC", "100000", at)
	price("ETH", "3000", at)
	store, err := dailyrelay.OpenBindings(ctx, database)
	check(err)
	bindings := []dailyrelay.Binding{}
	acceptReceipts := []common.Hash{}
	originReceipts := []*types.Receipt{}
	accept := func(asset string, stake int64) engine.Stage {
		t.Helper()
		now, err := env.RPC.Timestamp(ctx)
		check(err)
		at := int64(now) * 1000
		price("BTC", "100000", at)
		price("ETH", "3000", at)
		e := apply(engine.Command{Kind: "quote", Actor: Wallet(Alice).Hex(), Asset: asset, Amount: stake, Multiplier: 2, At: at})
		var native engine.Quote
		check(json.Unmarshal(e.Result, &native))
		id := crypto.Keccak256Hash([]byte(native.ID))
		q, err := dailyrelay.QuoteForStage(engine.Stage{Terms: native}, id)
		check(err)
		generation, err := env.Uint(ctx, "AccessController", "signatureVersion", 0)
		check(err)
		v, err := env.Read(ctx, "DailyLPVault", "limitsHash", 0)
		check(err)
		digest, err := q.Digest(new(big.Int).SetUint64(ChainID), env.Address("DailyBetCustody"), common.Hash(v[0].([32]byte)), generation)
		check(err)
		remote, err := env.Read(ctx, "DailyBetCustody", "hashQuote", 0, q)
		check(err)
		check(checkedDigest(remote, digest))
		sig, err := sign(SettlementSigner, digest)
		check(err)
		risk, err := sign(RiskSigner, digest)
		check(err)
		data, err := env.Data("DailyBetCustody", "accept", q, sig, risk)
		check(err)
		to := env.Address("DailyBetCustody")
		receipt, err := env.RPC.Send(ctx, Alice, &to, data)
		check(err)
		var start uint64
		for _, l := range receipt.Logs {
			if l.Address == to && len(l.Topics) > 0 && l.Topics[0] == env.ABIs["DailyBetCustody"].Events["TicketAccepted"].ID {
				v, err := env.ABIs["DailyBetCustody"].Events["TicketAccepted"].Inputs.NonIndexed().Unpack(l.Data)
				check(err)
				start = v[1].(uint64)
			}
		}
		e = apply(engine.Command{Kind: "enter", Actor: Wallet(Alice).Hex(), ID: native.ID, At: int64(start)})
		var stage engine.Stage
		check(json.Unmarshal(e.Result, &stage))
		journal, err := dailyrelay.Replay(policy, events)
		check(err)
		if _, err = reader.Bind(ctx, journal, stage.ID, id, receipt.TxHash, generation.String()); !errors.Is(err, contracts.ErrAwaitFinality) {
			t.Fatalf("unconfirmed acceptance did not wait: %v", err)
		}
		check(env.RPC.Mine(ctx, 2))
		b, err := reader.Bind(ctx, journal, stage.ID, id, receipt.TxHash, generation.String())
		check(err)
		check(store.Put(ctx, b))
		check(store.Put(ctx, b))
		bindings = append(bindings, b)
		acceptReceipts = append(acceptReceipts, receipt.TxHash)
		originReceipts = append(originReceipts, receipt)
		return stage
	}
	win := accept("BTC", 1_000_000)
	loss := accept("ETH", 3_000_000)
	check(env.Direct(ctx, Governance, "DailyLPVault", "withdraw", big.NewInt(1), big.NewInt(100_000_000)))
	check(env.RPC.Advance(ctx, 1))
	now, err = env.RPC.Timestamp(ctx)
	check(err)
	price("ETH", "1", int64(now)*1000)
	for state.Stages[win.ID].Status != "survived" {
		check(env.RPC.Advance(ctx, 3))
		now, err = env.RPC.Timestamp(ctx)
		check(err)
		price("BTC", "100000", int64(now)*1000)
	}
	if state.Stages[loss.ID].Status != "exploded" {
		t.Fatal("shared reducer failed to resolve barrier loss")
	}
	check(env.RPC.Mine(ctx, 2))
	journal, err := dailyrelay.Replay(policy, events)
	check(err)
	staleReader := reader
	check(sourceDB.Close(ctx))
	sourceDB, err = storage.OpenPostgres(ctx, database)
	check(err)
	sourceQ, err = engine.Open(ctx, policy, sourceDB)
	check(err)
	reader, err = dailyrelay.NewSigningReader(manifestPath, env.RPC, sourceQ)
	check(err)
	// Restart the actual durable binding connection before planning/signing.
	check(store.Close(ctx))
	store, err = dailyrelay.OpenBindings(ctx, database)
	check(err)
	defer func() { _ = store.Close(context.Background()) }()
	for i, b := range bindings {
		stored, err := store.Get(ctx, b.ChainID, b.Custody, b.TicketID)
		check(err)
		if engine.Hash(stored) != engine.Hash(b) {
			t.Fatal("binding changed on restart")
		}
		bindings[i] = stored
	}
	bad := bindings[0]
	bad.StageID = bindings[1].StageID
	if store.Put(ctx, bad) == nil {
		t.Fatal("allowed binding replacement")
	}
	snap, err := reader.Snapshot(ctx)
	check(err)
	plan, err := reader.Plan(ctx, journal, bindings, snap.Time+300)
	check(err)
	if len(plan.Actions) != 1 || plan.Actions[0].Kind != "batch" {
		t.Fatalf("unexpected daily plan: %+v", plan.Actions)
	}
	signer := &dailyTestSigner{}
	if _, err = staleReader.Authorize(ctx, plan, 0, signer); err == nil || signer.calls != 0 {
		t.Fatal("disconnected canonical writer reached signer")
	}
	readOnly, err := dailyrelay.NewReader(manifestPath, env.RPC)
	check(err)
	if _, err = readOnly.Authorize(ctx, plan, 0, signer); err == nil || signer.calls != 0 {
		t.Fatal("keyless replay reader created financial signatures")
	}
	plan.Actions[0].Outcomes[0].CanonicalTime++
	if _, err = reader.Authorize(ctx, plan, 0, signer); err == nil || signer.calls != 0 {
		t.Fatal("modified plan reached signer")
	}
	plan.Actions[0].Outcomes[0].CanonicalTime--
	// A different but internally valid replay must not claim the accepted ticket.
	alternativeState, err := engine.NewState(policy)
	check(err)
	alternativeEvents := []engine.Event{}
	changed := false
	for _, event := range events {
		command := event.Command
		if !changed && command.Kind == "quote" {
			command.Amount++
			changed = true
		}
		next, e, err := engine.Apply(alternativeState, command)
		check(err)
		alternativeState = next
		alternativeEvents = append(alternativeEvents, e)
	}
	alternative, err := dailyrelay.Replay(policy, alternativeEvents)
	check(err)
	if _, err = reader.Bind(ctx, alternative, bindings[0].StageID, bindings[0].TicketID, bindings[0].TxHash, bindings[0].Generation); err == nil {
		t.Fatal("changed native terms bound to an original onchain ticket")
	}
	reorg := &dailyReorgRPC{base: env.RPC}
	reorgReader, err := dailyrelay.NewSigningReader(manifestPath, reorg, sourceQ)
	check(err)
	// A self-consistent branch with unchanged accepted terms is still not the
	// operator's authoritative journal; recomputing hashes cannot grant authority.
	forkState, err := engine.NewState(policy)
	check(err)
	forkEvents := []engine.Event{}
	for i, event := range events {
		command := event.Command
		if i == len(events)-1 {
			command.Key += "/forged-branch"
		}
		next, e, err := engine.Apply(forkState, command)
		check(err)
		forkState = next
		forkEvents = append(forkEvents, e)
	}
	forked, err := dailyrelay.Replay(policy, forkEvents)
	check(err)
	forkPlan, err := reader.Plan(ctx, forked, bindings, snap.Time+300)
	check(err)
	if _, err = reader.Authorize(ctx, forkPlan, 0, signer); err == nil || signer.calls != 0 {
		t.Fatal("self-consistent forged source branch reached signing")
	}
	reorgPlan, err := reorgReader.Plan(ctx, journal, bindings, snap.Time+300)
	check(err)
	reorg.block = reorgPlan.Block
	reorg.corrupt = true
	if _, err = reorgReader.Authorize(ctx, reorgPlan, 0, signer); !errors.Is(err, contracts.ErrFinalityReorg) || signer.calls != 0 {
		t.Fatalf("finalized block replacement reached signing: %v", err)
	}
	check(env.Direct(ctx, Governance, "AccessController", "setSigner", crypto.Keccak256Hash([]byte("RISK_SIGNER")), Wallet(RiskSigner)))
	check(env.RPC.Mine(ctx, 2))
	if _, err = reader.Authorize(ctx, plan, 0, signer); err == nil || signer.calls != 0 {
		t.Fatal("rotated authorization reached signer")
	}
	snap, err = reader.Snapshot(ctx)
	check(err)
	plan, err = reader.Plan(ctx, journal, bindings, snap.Time+300)
	check(err)
	before, err := env.Uint(ctx, "DailyLPVault", "accountedCash", 0)
	check(err)
	authorized, settled, proof := exerciseDailyOutbox(t, ctx, env, database, manifestPath, output, reader, journal, plan, bindings, signer)
	corruptReceipt := &dailyReorgRPC{base: env.RPC, corruptTransfer: settled.TxHash, usdc: usdc}
	corruptReader, err := dailyrelay.NewReader(manifestPath, corruptReceipt)
	check(err)
	if _, err = corruptReader.ReconcileBatch(ctx, journal, bindings, authorized, settled.TxHash); err == nil {
		t.Fatal("successful receipt with altered token movement passed reconciliation")
	}
	check(store.CommitSettlement(ctx, proof))
	check(store.CommitSettlement(ctx, proof))
	changedProof := proof
	changedProof.Transaction = crypto.Keccak256Hash([]byte("different settled transaction"))
	if store.CommitSettlement(ctx, changedProof) == nil {
		t.Fatal("paid ticket reassigned to another transaction")
	}
	check(store.Close(ctx))
	store, err = dailyrelay.OpenBindings(ctx, database)
	check(err)
	storedProof, err := store.Settlement(ctx, proof.ChainID, proof.Custody, proof.Transaction)
	check(err)
	if engine.Hash(storedProof) != engine.Hash(proof) {
		t.Fatal("receipt proof changed on restart")
	}
	changedAuth := authorized
	changedAuth.Action = authorized.Action
	changedAuth.Action.Tickets = append([]common.Hash{}, authorized.Action.Tickets...)
	changedAuth.Action.Tickets[0] = crypto.Keccak256Hash([]byte("wrong paid ticket"))
	if _, err = reader.ReconcileBatch(ctx, journal, bindings, changedAuth, settled.TxHash); err == nil {
		t.Fatal("paid ticket metadata was not tied to receipt outcomes")
	}
	after, err := env.Uint(ctx, "DailyLPVault", "accountedCash", 0)
	check(err)
	if new(big.Int).Sub(after, before).Int64() != 2_000_000 || signer.calls != 8 {
		t.Fatal("batch did not use shared outcomes, exact net cash and both signers")
	}
	plan, err = reader.Plan(ctx, journal, bindings, snap.Time+300)
	check(err)
	if plan.Actions[0].Kind != "reconcile" {
		t.Fatal("resolved flags must request receipt reconciliation")
	}
	if _, err = reader.Authorize(ctx, plan, 0, signer); err == nil {
		t.Fatal("signed a settled ticket again")
	}
	// A second zero-net batch exercises another relayer's successful execution
	// while our original signed transaction still owns an unresolved nonce.
	auxWin := accept("BTC", 10_000_000)
	auxLoss := accept("ETH", 10_000_000)
	now, err = env.RPC.Timestamp(ctx)
	check(err)
	price("ETH", "1", int64(now)*1000+123)
	if state.Stages[auxLoss.ID].Status != "exploded" {
		t.Fatal("auxiliary shared-engine loss did not resolve")
	}
	for state.Stages[auxWin.ID].Status != "survived" {
		check(env.RPC.Advance(ctx, 3))
		now, err = env.RPC.Timestamp(ctx)
		check(err)
		price("BTC", "100000", int64(now)*1000)
	}
	check(env.RPC.Mine(ctx, 2))
	auxJournal, err := dailyrelay.Replay(policy, events)
	check(err)
	externallySettleDailyBatch(t, ctx, env, database, manifestPath, output, reader, auxJournal, bindings[len(bindings)-2:], signer)
	// Rehearse a real late final void: expiry before midnight, final decision after.
	cutoff, err := env.Uint(ctx, "DailyLPVault", "cutoff", 0)
	check(err)
	advanceTo := func(target uint64) {
		t.Helper()
		for {
			now, err := env.RPC.Timestamp(ctx)
			check(err)
			if now >= target {
				return
			}
			step := target - now
			if step > 3600 {
				step = 3600
			}
			check(env.RPC.Advance(ctx, step))
		}
	}
	advanceTo(cutoff.Uint64() - 40)
	voidStage := accept("ETH", 10_000_000)
	advanceTo(cutoff.Uint64() + 20)
	now, err = env.RPC.Timestamp(ctx)
	check(err)
	apply(engine.Command{Kind: "tick", At: int64(now) * 1000})
	if state.Stages[voidStage.ID].Status != "voided" {
		t.Fatal("shared engine did not finalize outage void")
	}
	check(env.RPC.Mine(ctx, 2))
	journal, err = dailyrelay.Replay(policy, events)
	check(err)
	voidBindings := []dailyrelay.Binding{bindings[len(bindings)-1]}
	snap, err = reader.Snapshot(ctx)
	check(err)
	voidPlan, err := reader.Plan(ctx, journal, voidBindings, snap.Time+300)
	check(err)
	if voidPlan.Actions[0].Kind != "queue_void" {
		t.Fatal("future-day void was not separated from a cash batch")
	}
	queued, queuedReceipt, _ := queueDailyVoid(t, ctx, env, database, manifestPath, output, reader, journal, voidPlan, voidBindings, signer)
	// Reconciliation of the original queue must survive a later native prefix.
	now, err = env.RPC.Timestamp(ctx)
	check(err)
	apply(engine.Command{Kind: "tick", At: int64(now) * 1000})
	journal, err = dailyrelay.Replay(policy, events)
	check(err)
	snap, err = reader.Snapshot(ctx)
	check(err)
	waiting, err := reader.Plan(ctx, journal, voidBindings, snap.Time+300)
	check(err)
	if waiting.Actions[0].Kind != "await_close" {
		t.Fatal("queued stake released before its canonical day")
	}
	if _, err = reader.Authorize(ctx, waiting, 0, signer); err == nil {
		t.Fatal("signed an await-close action")
	}
	day, err := env.Uint(ctx, "DailyLPVault", "currentDay", 0)
	check(err)
	betSeq, err := env.Uint(ctx, "DailyLPVault", "betSequence", 0)
	check(err)
	now, err = env.RPC.Timestamp(ctx)
	check(err)
	close := dailyCloseABI{day.Uint64(), now * 1000, betSeq, zero, zero, zero, common.HexToHash(state.JournalHash), now + 300}
	value, err := env.Read(ctx, "DailyBetCustody", "hashClose", 0, close)
	check(err)
	digest := common.Hash(value[0].([32]byte))
	ss, err := sign(SettlementSigner, digest)
	check(err)
	rs, err := sign(RiskSigner, digest)
	check(err)
	check(env.Direct(ctx, Governance, "AccessController", "pauseTrading"))
	check(env.Direct(ctx, Governance, "DailyBetCustody", "closeDay", close, ss, rs))
	check(env.Direct(ctx, Governance, "AccessController", "setSigner", crypto.Keccak256Hash([]byte("RISK_SIGNER")), Wallet(RiskSigner)))
	check(env.RPC.Mine(ctx, 2))
	snap, err = reader.Snapshot(ctx)
	check(err)
	completePlan, err := reader.Plan(ctx, journal, voidBindings, snap.Time+300)
	check(err)
	if completePlan.Actions[0].Kind != "complete_void" {
		t.Fatal("queued void did not reach canonical-day completion")
	}
	callsBefore := signer.calls
	keyless, err := dailyrelay.NewReader(manifestPath, env.RPC)
	check(err)
	check(sourceDB.Close(ctx))
	_, completedReceipt, _ := completeDailyVoid(t, ctx, env, database, manifestPath, output, keyless, journal, completePlan, voidBindings, signer)
	if signer.calls != callsBefore {
		t.Fatal("previously authenticated void required new signatures")
	}
	exposure, err := env.Uint(ctx, "DailyLPVault", "openExposure", 0)
	check(err)
	if exposure.Sign() != 0 {
		t.Fatal("void did not release original risk")
	}
	fee, err := env.Uint(ctx, "DailyLPVault", "operatorDue", 0)
	check(err)
	if fee.Int64() != 100_000 {
		t.Fatal("daily fee did not equal 5% of actual 2-USDC eligible profit")
	}
	for id, owner := range []int{Governance, Bob} {
		free, err := env.Uint(ctx, "DailyLPVault", "maxWithdrawal", 0, big.NewInt(int64(id+1)))
		check(err)
		check(env.Direct(ctx, owner, "DailyLPVault", "withdraw", big.NewInt(int64(id+1)), free))
	}
	remaining, err := env.Uint(ctx, "DailyLPVault", "accountedCash", 0)
	check(err)
	if remaining.Cmp(fee) != 0 {
		t.Fatal("LP withdrawal consumed unpaid daily fee")
	}
	check(env.Direct(ctx, Governance, "DailyLPVault", "payFee", day.Uint64()))
	customer, err := env.Uint(ctx, "DailyBetCustody", "available", 0, Wallet(Alice))
	check(err)
	if customer.Int64() != 98_000_000 {
		t.Fatal("customer refund/win/loss accounting changed")
	}
	check(env.Direct(ctx, Alice, "DailyBetCustody", "withdraw", customer))
	reserveBalance, err := env.Uint(ctx, "USDC", "balanceOf", 0, env.Address("DailyReserve"))
	check(err)
	if reserveBalance.Int64() != 125_000_000 {
		t.Fatal("LP flows consumed segregated backing")
	}
	sourceDB, err = storage.OpenPostgres(ctx, database)
	check(err)
	sourceQ, err = engine.Open(ctx, policy, sourceDB)
	check(err)
	now, err = env.RPC.Timestamp(ctx)
	check(err)
	apply(engine.Command{Kind: "paper_settle", At: int64(now) * 1000})
	if state.LPProfit != 2_000_000 {
		t.Fatal("actual net settlement disagrees with shared paper settlement")
	}
	// Persist the independently replayable source and actual receipts for review.
	check(writeEvidence(output, "initial-policy.json", policy))
	check(writeEvidence(output, "journal.json", events))
	check(writeEvidence(output, "bindings.json", bindings))
	check(writeEvidence(output, "authorized-batch.json", authorized))
	check(writeEvidence(output, "settlement-receipt.json", settled))
	check(writeEvidence(output, "settlement-proof.json", proof))
	check(writeEvidence(output, "void-queue-authorization.json", queued))
	check(writeEvidence(output, "void-queue-receipt.json", queuedReceipt))
	check(writeEvidence(output, "void-complete-receipt.json", completedReceipt))
	check(writeEvidence(output, "acceptance-transactions.json", acceptReceipts))
	check(writeEvidence(output, "acceptance-receipts.json", originReceipts))
	check(writeEvidence(output, "result.json", map[string]any{"passed": true, "public_transactions": false, "chain_id": ChainID, "native_outcomes": []string{"survived", "exploded", "voided"}, "confirmed_bindings": len(bindings), "durable_restart": true, "two_roles_checked": true, "net_lp_credit_usdc_units": 2_000_000, "free_lp_withdrawal_usdc_units": 100_000_000, "daily_fee_usdc_units": 100_000, "late_void_after_midnight": true, "signature_free_completion_after_rotation": true, "paused_customer_and_lp_withdrawals": true, "segregated_test_backing_unchanged_usdc_units": 125_000_000, "rejected": []string{"unconfirmed acceptance", "changed native terms", "changed stored binding", "modified signed plan", "replaced finalized block", "stale signer generation", "already-settled signing", "early queued void release"}, "settlement_transaction": settled.TxHash, "production_approved": false}))
	t.Log("actual daily custody/LP binding, PostgreSQL restart, shared-engine batch and net USDC transfer passed")
}
