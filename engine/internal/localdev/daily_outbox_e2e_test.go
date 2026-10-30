package localdev

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"testing"

	"fuse/engine/internal/dailyrelay"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/jackc/pgx/v5"
)

type dailyDurableRole struct {
	conn *pgx.Conn
	base *dailyTestSigner
	fail bool
}

func (s *dailyDurableRole) SignDigest(ctx context.Context, role string, digest common.Hash) ([]byte, error) {
	b, err := dailyActiveOutbound(ctx, s.conn, Wallet(7))
	if err != nil {
		return nil, err
	}
	if b.State != "planned" || b.Authorization != nil || len(b.Raw) != 0 {
		return nil, fmt.Errorf("financial signer reached before durable intent")
	}
	if s.fail {
		s.fail = false
		return nil, errors.New("injected crash before financial signatures")
	}
	return s.base.SignDigest(ctx, role, digest)
}

type dailyPayerSigner struct {
	rpc         *RPC
	conn        *pgx.Conn
	fail, wrong bool
	calls       int
}

func (s *dailyPayerSigner) SignTransaction(ctx context.Context, tx *types.Transaction) (*types.Transaction, error) {
	if err := s.rpc.guard(ctx); err != nil {
		return nil, err
	}
	b, err := dailyActiveOutbound(ctx, s.conn, Wallet(7))
	if err != nil {
		return nil, err
	}
	if b.State != "reserved" || b.Nonce == nil || *b.Nonce != tx.Nonce() || len(b.Unsigned) == 0 || len(b.Raw) != 0 {
		return nil, fmt.Errorf("payer signer reached before durable nonce/unsigned bytes")
	}
	s.calls++
	if s.fail {
		s.fail = false
		return nil, errors.New("injected crash after nonce reservation")
	}
	if s.wrong {
		tx = types.NewTx(&types.DynamicFeeTx{ChainID: tx.ChainId(), Nonce: tx.Nonce() + 1, Gas: tx.Gas(), GasFeeCap: tx.GasFeeCap(), GasTipCap: tx.GasTipCap(), To: tx.To(), Data: tx.Data(), Value: new(big.Int)})
	}
	key, err := DevKey(7)
	if err != nil {
		return nil, err
	}
	return types.SignTx(tx, types.LatestSignerForChainID(new(big.Int).SetUint64(ChainID)), key)
}
func dailyActiveOutbound(ctx context.Context, c *pgx.Conn, payer common.Address) (dailyrelay.Outbound, error) {
	var raw []byte
	err := c.QueryRow(ctx, `SELECT o.record_encoded FROM fuse_daily_outbound o JOIN fuse_daily_outbound_lanes l ON o.chain_id=l.chain_id AND o.payer=l.payer AND o.id=l.active_id WHERE l.chain_id=$1 AND l.payer=$2`, fmt.Sprint(ChainID), payer.Hex()).Scan(&raw)
	var b dailyrelay.Outbound
	if err != nil {
		return b, err
	}
	err = json.Unmarshal(raw, &b)
	return b, err
}

type dailyLostReply struct {
	rpc   *RPC
	conn  *pgx.Conn
	calls int
}

func (s *dailyLostReply) Broadcast(ctx context.Context, raw []byte) (common.Hash, error) {
	b, err := dailyActiveOutbound(ctx, s.conn, Wallet(7))
	if err != nil {
		return common.Hash{}, err
	}
	committed := bytes.Equal(b.Raw, raw)
	for _, a := range b.Attempts {
		if a.State == "prepared" && bytes.Equal(a.Raw, raw) {
			committed = true
		}
	}
	if (b.State != "prepared" && b.State != "external_executed") || !committed {
		return common.Hash{}, fmt.Errorf("broadcast received uncommitted raw bytes")
	}
	s.calls++
	_, err = s.rpc.Broadcast(ctx, raw)
	if err != nil {
		return common.Hash{}, err
	}
	return common.Hash{}, errors.New("injected lost broadcast reply")
}

type dailyOutboundFaultRPC struct {
	base                         dailyrelay.RPC
	receiptOutage, nonceConflict bool
}

func (r *dailyOutboundFaultRPC) ReadRPC(ctx context.Context, method string, params any, out any) error {
	if r.receiptOutage && method == "eth_getTransactionReceipt" {
		return errors.New("injected receipt RPC outage")
	}
	var raw json.RawMessage
	if err := r.base.ReadRPC(ctx, method, params, &raw); err != nil {
		return err
	}
	if r.nonceConflict && method == "eth_getTransactionCount" {
		var nonce hexutil.Uint64
		if err := json.Unmarshal(raw, &nonce); err != nil {
			return err
		}
		raw, _ = json.Marshal(nonce + 1)
	}
	return json.Unmarshal(raw, out)
}

func exerciseDailyOutbox(t *testing.T, ctx context.Context, env *Environment, database, manifest, output string, reader *dailyrelay.Reader, journal *dailyrelay.Journal, plan *dailyrelay.Plan, bindings []dailyrelay.Binding, signer *dailyTestSigner) (dailyrelay.Authorized, *types.Receipt, dailyrelay.SettlementProof) {
	t.Helper()
	check := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	check(env.RPC.FundGas(ctx, Wallet(7)))
	db, err := pgx.Connect(ctx, database)
	check(err)
	defer db.Close(context.Background()) //nolint:errcheck
	o, err := dailyrelay.OpenOutbox(ctx, database, ChainID, Wallet(7))
	check(err)
	defer func() { _ = o.Close(context.Background()) }()
	restart := func() {
		t.Helper()
		check(o.Close(ctx))
		o, err = dailyrelay.OpenOutbox(ctx, database, ChainID, Wallet(7))
		check(err)
	}
	roles := &dailyDurableRole{conn: db, base: signer, fail: true}
	payer := &dailyPayerSigner{rpc: env.RPC, conn: db, fail: true}
	// Deliberately insufficient execution gas forces an actual mined revert.
	terms := dailyrelay.TransactionTerms{Gas: 100_000, FeeCap: big.NewInt(3_000_000_000), TipCap: big.NewInt(1_000_000_000)}
	snapshot, err := reader.Snapshot(ctx)
	check(err)
	shortPlan, err := reader.Plan(ctx, journal, bindings, snapshot.Time+2)
	check(err)
	abandoned, err := o.Prepare(ctx, reader, shortPlan, 0, roles, payer, terms)
	if err == nil || abandoned.State != "planned" {
		t.Fatal("short-lived intent did not stop before signing")
	}
	if o.RetireUnprepared(ctx, reader, abandoned.ID) == nil {
		t.Fatal("unexpired intent abandoned")
	}
	check(env.RPC.Advance(ctx, 3))
	check(env.RPC.Mine(ctx, 2))
	check(o.RetireUnprepared(ctx, reader, abandoned.ID))
	if _, active, err := o.Active(ctx); err != nil || active {
		t.Fatal("expired never-broadcast intent retained payer lane", err)
	}
	abandoned, err = o.Get(ctx, abandoned.ID)
	check(err)
	if abandoned.State != "abandoned" {
		t.Fatal("expired intent did not preserve terminal audit record")
	}
	check(writeEvidence(output, "outbound-abandoned.json", abandoned))
	roles.fail = true
	planned, err := o.Prepare(ctx, reader, plan, 0, roles, payer, terms)
	if err == nil || planned.State != "planned" || signer.calls != 0 {
		t.Fatal("crash before financial signatures did not retain planned intent")
	}
	restart()
	discovered, active, err := o.Active(ctx)
	check(err)
	if !active || discovered.ID != planned.ID {
		t.Fatal("restart could not discover durable work without caller ID")
	}
	reserved, err := o.Prepare(ctx, reader, plan, 0, roles, payer, terms)
	if err == nil || reserved.State != "reserved" || len(reserved.Raw) != 0 || signer.calls != 2 {
		t.Fatal("nonce reservation was not durable before payer signer failure")
	}
	restart()
	prepared, err := o.Prepare(ctx, reader, plan, 0, roles, payer, terms)
	check(err)
	if prepared.ID != planned.ID || prepared.State != "prepared" || signer.calls != 2 {
		t.Fatal("restart changed intent or repeated financial signing")
	}
	if duplicate, err := dailyrelay.OpenOutbox(ctx, database, ChainID, Wallet(7)); !errors.Is(err, dailyrelay.ErrOutboundBusy) {
		if duplicate != nil {
			_ = duplicate.Close(ctx)
		}
		t.Fatal("two controllers acquired the same payer lane", err)
	}
	other, err := dailyrelay.OpenOutbox(ctx, database, ChainID, Wallet(8))
	check(err)
	if _, err = other.Prepare(ctx, reader, plan, 0, roles, payer, terms); !errors.Is(err, dailyrelay.ErrOutboundBusy) {
		t.Fatal("different payer claimed overlapping tickets", err)
	}
	check(other.Close(ctx))
	if err = o.RetireUnprepared(ctx, reader, prepared.ID); err == nil {
		t.Fatal("prepared transaction abandoned without nonce evidence")
	}
	restart()
	_, err = o.Deliver(ctx, reader, journal, prepared.ID, env.RPC)
	check(err)
	check(env.RPC.Mine(ctx, 2))
	reverted, err := o.Observe(ctx, reader, prepared.ID)
	check(err)
	if reverted.State != "reverted" || reverted.Receipt == nil || reverted.Receipt.Status != 0 {
		t.Fatal("actual reverted receipt did not release the payer lane")
	}
	if _, err = o.CommitBatch(ctx, reader, journal, reverted.ID); err == nil {
		t.Fatal("reverted transaction became a payment proof")
	}
	check(writeEvidence(output, "outbound-reverted.json", reverted))
	check(o.Close(ctx))
	cancelled := cancelDailyPrepared(t, ctx, env, db, database, manifest, output, reader, journal, bindings, roles, payer)
	superseded := recoverDailyUntrackedNonce(t, ctx, env, db, database, manifest, output, reader, journal, bindings, roles, payer, cancelled.Receipt.TxHash)
	o, err = dailyrelay.OpenOutbox(ctx, database, ChainID, Wallet(7))
	check(err)
	// Same obligations, next consumed nonce, explicit new immutable gas terms.
	terms.Gas = 15_000_000
	payer.wrong = true
	bad, err := o.Prepare(ctx, reader, plan, 0, roles, payer, terms)
	if err == nil {
		t.Fatal("payer signer changed reserved nonce")
	}
	durable, err := o.Get(ctx, bad.ID)
	check(err)
	if durable.State != "reserved" || len(durable.Raw) != 0 {
		t.Fatal("invalid payer signature became prepared raw transaction")
	}
	payer.wrong = false
	good, err := o.Prepare(ctx, reader, plan, 0, roles, payer, terms)
	check(err)
	if *good.Nonce != *superseded.Nonce+1 || signer.calls != 8 {
		t.Fatal("reverted nonce reused or financial signatures repeated")
	}
	restart()
	stored, err := o.Get(ctx, good.ID)
	check(err)
	if !bytes.Equal(stored.Raw, good.Raw) || stored.Transaction != good.Transaction {
		t.Fatal("raw bytes/hash changed after PostgreSQL reconnect")
	}
	check(env.RPC.write(ctx, "anvil_setAutomine", []any{false}, nil))
	defer func() { _ = env.RPC.write(context.Background(), "anvil_setAutomine", []any{true}, nil) }()
	lost := &dailyLostReply{rpc: env.RPC, conn: db}
	if _, err = o.Deliver(ctx, reader, journal, good.ID, lost); err == nil || lost.calls != 1 {
		t.Fatal("lost RPC reply did not preserve uncertain send")
	}
	restart()
	pending, err := o.Observe(ctx, reader, good.ID)
	check(err)
	if pending.Receipt != nil || !bytes.Equal(pending.Raw, good.Raw) {
		t.Fatal("pending transaction was replaced after restart")
	}
	if _, err = o.Prepare(ctx, reader, plan, 0, roles, payer, terms); err != nil {
		t.Fatal("prepared retry was not idempotent", err)
	}
	if signer.calls != 8 {
		t.Fatal("uncertain send requested new financial signatures")
	}
	for _, fault := range []*dailyOutboundFaultRPC{{base: env.RPC, receiptOutage: true}, {base: env.RPC, nonceConflict: true}} {
		faultReader, err := dailyrelay.NewReader(manifest, fault)
		check(err)
		if _, err = o.Observe(ctx, faultReader, good.ID); err == nil {
			t.Fatal("RPC outage or unknown nonce consumption treated as successful/pending evidence")
		}
	}
	if _, err = o.CommitBatch(ctx, reader, journal, good.ID); err == nil {
		t.Fatal("pending transaction counted as paid")
	}
	attemptSigner := &dailyAttemptPayerSigner{rpc: env.RPC, conn: db}
	fees := dailyrelay.TransactionTerms{Gas: terms.Gas, FeeCap: big.NewInt(6_000_000_000), TipCap: big.NewInt(2_000_000_000)}
	replaced, index, err := o.PrepareReplacement(ctx, reader, journal, good.ID, fees, "Replace pending settlement with explicit higher fees", attemptSigner)
	check(err)
	if len(replaced.Attempts) != 1 || signer.calls != 8 || !bytes.Equal(replaced.Raw, good.Raw) {
		t.Fatal("fee replacement changed financial authorization or removed original raw")
	}
	restart()
	if _, err = o.DeliverAttempt(ctx, reader, journal, good.ID, index, lost); err == nil || lost.calls != 2 {
		t.Fatal("replacement lost reply not retained")
	}
	restart()
	check(env.RPC.write(ctx, "anvil_setAutomine", []any{true}, nil))
	check(env.RPC.Mine(ctx, 2))
	included, err := o.Observe(ctx, reader, good.ID)
	check(err)
	if included.State != "included" || included.Receipt == nil || included.Receipt.Status != 1 {
		t.Fatal("confirmed successful receipt skipped monetary reconciliation")
	}
	if included.Receipt.TxHash != replaced.Attempts[index].Transaction || included.IncludedTransaction == good.Transaction || included.WinningAttempt == nil || *included.WinningAttempt != index {
		t.Fatal("receipt winner did not identify fee replacement")
	}
	restart() // Crash after inclusion, before the atomic payment-proof commit.
	// Force the terminal outbox update to fail after proof/ticket inserts. The
	// transaction must roll back every financial row and remain recoverable.
	_, err = db.Exec(ctx, `CREATE FUNCTION pg_temp.fuse_reject_terminal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF (convert_from(NEW.record_encoded,'UTF8')::jsonb->>'state')='settled' THEN RAISE EXCEPTION 'injected terminal persistence failure'; END IF; RETURN NEW; END $$;
CREATE TRIGGER fuse_test_terminal_failure BEFORE UPDATE ON fuse_daily_outbound FOR EACH ROW EXECUTE FUNCTION pg_temp.fuse_reject_terminal()`)
	check(err)
	if _, err = o.CommitBatch(ctx, reader, journal, good.ID); err == nil {
		t.Fatal("injected atomic terminal failure passed")
	}
	var premature int
	check(db.QueryRow(ctx, `SELECT count(*) FROM fuse_daily_settled_tickets WHERE tx_hash=$1`, good.Transaction.Hex()).Scan(&premature))
	if premature != 0 {
		t.Fatal("failed terminal commit left paid-ticket rows")
	}
	check(db.QueryRow(ctx, `SELECT count(*) FROM fuse_daily_settlements WHERE tx_hash=$1`, good.Transaction.Hex()).Scan(&premature))
	if premature != 0 {
		t.Fatal("failed terminal commit left a settlement proof")
	}
	unfinished, err := o.Get(ctx, good.ID)
	check(err)
	if unfinished.State != "included" {
		t.Fatal("failed terminal commit lost recoverable inclusion state")
	}
	_, err = db.Exec(ctx, `DROP TRIGGER fuse_test_terminal_failure ON fuse_daily_outbound`)
	check(err)
	proof, err := o.CommitBatch(ctx, reader, journal, good.ID)
	check(err)
	restart()
	settled, err := o.Get(ctx, good.ID)
	check(err)
	if settled.State != "settled" {
		t.Fatal("payment proof and terminal transport state did not commit together")
	}
	proofRetry, err := o.CommitBatch(ctx, reader, journal, good.ID)
	check(err)
	if proofRetry.Transaction != proof.Transaction {
		t.Fatal("proof retry changed transaction")
	}
	if _, err = o.Deliver(ctx, reader, journal, good.ID, lost); err != nil || lost.calls != 2 {
		t.Fatal("settled retry broadcast again", err)
	}
	var paid int
	check(db.QueryRow(ctx, `SELECT count(*) FROM fuse_daily_settled_tickets WHERE chain_id=$1 AND custody=$2 AND tx_hash=$3`, fmt.Sprint(ChainID), proof.Custody.Hex(), proof.Transaction.Hex()).Scan(&paid))
	if paid != 2 {
		t.Fatal("atomic proof omitted or duplicated paid tickets")
	}
	check(writeEvidence(output, "outbound-settled.json", settled))
	check(writeEvidence(output, "replacement-recovery.json", map[string]any{"passed": true, "expired_prepared_cancellation_confirmed": true, "cancellation_preserves_payout_obligations": true, "cancellation_raw_staged_before_payer_signing": true, "cancellation_terminal_failure_rolls_back_lane_and_claims": true, "cancellation_not_counted_as_payment": true, "original_raw_and_all_signed_hashes_retained": true, "signed_cancel_prevents_resuming_original_send": true, "replacement_preserves_authorization_calldata_gas_and_nonce": true, "actual_pending_fee_replacement_won": true, "replacement_lost_reply_restart": true, "winner_receipt_used_for_payment_proof": true, "no_new_financial_signature_for_replacement": true, "public_transactions": false, "production_approved": false}))
	check(writeEvidence(output, "outbound-recovery.json", map[string]any{"passed": true, "dedicated_payer": Wallet(7), "durable_intent_before_financial_signing": true, "durable_nonce_before_payer_signing": true, "durable_raw_before_broadcast": true, "prepared_raw_restart": true, "same_payer_lock_enforced": true, "cross_payer_overlap_rejected": true, "altered_payer_nonce_rejected": true, "actual_mined_revert_recovered": true, "reverted_nonce_not_reused": true, "lost_broadcast_reply_recovered": true, "pending_restart_no_resign": true, "receipt_rpc_outage_rejected": true, "unknown_nonce_consumption_rejected": true, "included_before_payment_proof_restart": true, "atomic_proof_and_outbox_completion": true, "settled_retry_no_broadcast": true, "financial_signatures": signer.calls, "public_transactions": false, "production_approved": false}))
	return *settled.Authorization, settled.Receipt, proof
}
