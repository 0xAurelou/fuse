package localdev

import (
	"context"
	"encoding/json"
	"errors"
	"math/big"
	"testing"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/dailyrelay"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/jackc/pgx/v5"
)

type dailyExternalFaultRPC struct {
	base dailyrelay.RPC
	hash common.Hash
	mode string
}

func (r *dailyExternalFaultRPC) ReadRPC(ctx context.Context, method string, params any, out any) error {
	var raw json.RawMessage
	if err := r.base.ReadRPC(ctx, method, params, &raw); err != nil {
		return err
	}
	if method == "eth_getTransactionReceipt" && r.mode == "block-index" {
		var p *types.Receipt
		if err := json.Unmarshal(raw, &p); err != nil {
			return err
		}
		if p != nil && p.TxHash == r.hash {
			p.TransactionIndex++
			raw, _ = json.Marshal(p)
		}
	}
	if method == "eth_getTransactionByHash" && r.mode == "raw-payload" {
		var p map[string]any
		if err := json.Unmarshal(raw, &p); err != nil {
			return err
		}
		if p["hash"] == r.hash.Hex() {
			p["input"] = "0x1234"
			raw, _ = json.Marshal(p)
		}
	}
	return json.Unmarshal(raw, out)
}

type dailyLostUntracked struct {
	rpc   *RPC
	calls int
}

func (s *dailyLostUntracked) Broadcast(ctx context.Context, raw []byte) (common.Hash, error) {
	s.calls++
	if _, err := s.rpc.Broadcast(ctx, raw); err != nil {
		return common.Hash{}, err
	}
	return common.Hash{}, errors.New("injected lost reply from independently submitted transaction")
}

func recoverDailyUntrackedNonce(t *testing.T, ctx context.Context, env *Environment, db *pgx.Conn, database, manifest, output string, r *dailyrelay.Reader, j *dailyrelay.Journal, bindings []dailyrelay.Binding, roles *dailyDurableRole, payer *dailyPayerSigner, wrongHash common.Hash) dailyrelay.Outbound {
	t.Helper()
	check := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	o, err := dailyrelay.OpenOutbox(ctx, database, ChainID, Wallet(7))
	check(err)
	defer func() { _ = o.Close(context.Background()) }()
	restart := func() {
		t.Helper()
		check(o.Close(ctx))
		o, err = dailyrelay.OpenOutbox(ctx, database, ChainID, Wallet(7))
		check(err)
	}
	s, err := r.Snapshot(ctx)
	check(err)
	p, err := r.Plan(ctx, j, bindings, s.Time+20)
	check(err)
	terms := dailyrelay.TransactionTerms{Gas: 15_000_000, FeeCap: big.NewInt(3_000_000_000), TipCap: big.NewInt(1_000_000_000)}
	payer.fail = true
	b, err := o.Prepare(ctx, r, p, 0, roles, payer, terms)
	if err == nil || b.State != "reserved" || len(b.Raw) != 0 {
		t.Fatal("reserved-only crash was not retained")
	}
	restart()
	// Another instance consumed the dedicated payer's nonce while this process
	// was down. Its exact signed self-transfer was never in the outbox.
	to := Wallet(7)
	receipt, err := env.RPC.Send(ctx, 7, &to, nil)
	check(err)
	keyless, err := dailyrelay.NewReader(manifest, env.RPC)
	check(err)
	reason := "Audit independently submitted self-transfer after reservation crash"
	if _, err = o.AdoptNonce(ctx, keyless, b.ID, receipt.TxHash, reason); !errors.Is(err, contracts.ErrAwaitFinality) {
		t.Fatal("unconfirmed nonce recovery accepted", err)
	}
	check(env.RPC.Mine(ctx, 2))
	for _, mode := range []string{"block-index", "raw-payload"} {
		bad, err := dailyrelay.NewReader(manifest, &dailyExternalFaultRPC{base: env.RPC, hash: receipt.TxHash, mode: mode})
		check(err)
		if _, err = bad.ObserveTransaction(ctx, receipt.TxHash); err == nil {
			t.Fatal("false transaction block membership/raw payload accepted", mode)
		}
	}
	if _, err = o.AdoptNonce(ctx, keyless, b.ID, wrongHash, reason); err == nil {
		t.Fatal("wrong historical nonce adopted")
	}
	found, err := keyless.FindNonce(ctx, Wallet(7), *b.Nonce, b.Authorization.VerifiedBlock, receipt.BlockNumber.Uint64())
	check(err)
	if found == nil || found.Transaction != receipt.TxHash || found.Sender != Wallet(7) {
		t.Fatal("bounded scan did not find the actual nonce consumer")
	}
	before, err := env.Uint(ctx, "DailyLPVault", "openExposure", 0)
	check(err)
	_, err = db.Exec(ctx, `CREATE FUNCTION pg_temp.fuse_reject_superseded() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF (convert_from(NEW.record_encoded,'UTF8')::jsonb->>'state')='superseded' THEN RAISE EXCEPTION 'injected nonce recovery terminal failure'; END IF; RETURN NEW; END $$;
CREATE TRIGGER fuse_test_superseded BEFORE UPDATE ON fuse_daily_outbound FOR EACH ROW EXECUTE FUNCTION pg_temp.fuse_reject_superseded()`)
	check(err)
	if _, err = o.AdoptNonce(ctx, keyless, b.ID, receipt.TxHash, reason); err == nil {
		t.Fatal("nonce terminal failure injection passed")
	}
	if _, active, err := o.Active(ctx); err != nil || !active {
		t.Fatal("failed nonce audit released active lane", err)
	}
	_, err = db.Exec(ctx, `DROP TRIGGER fuse_test_superseded ON fuse_daily_outbound`)
	check(err)
	restart()
	adopted, err := o.AdoptNonce(ctx, keyless, b.ID, receipt.TxHash, reason)
	check(err)
	if adopted.State != "superseded" || adopted.WinningAttempt == nil || *adopted.WinningAttempt != -2 || adopted.NonceRecovery == nil || adopted.NonceRecovery.Class != "unrelated" || len(adopted.Raw) != 0 {
		t.Fatal("nonce recovery fabricated a financial execution")
	}
	after, err := env.Uint(ctx, "DailyLPVault", "openExposure", 0)
	check(err)
	if after.Cmp(before) != 0 {
		t.Fatal("unrelated nonce consumption released accepted risk")
	}
	var paid int
	check(db.QueryRow(ctx, `SELECT count(*) FROM fuse_daily_settled_tickets`).Scan(&paid))
	if paid != 0 {
		t.Fatal("unrelated nonce consumption recorded payouts")
	}
	if _, active, err := o.Active(ctx); err != nil || active {
		t.Fatal("audited nonce did not release its payer lane", err)
	}
	if retry, err := o.AdoptNonce(ctx, keyless, b.ID, receipt.TxHash, reason); err != nil || retry.State != "superseded" {
		t.Fatal("terminal nonce adoption retry was not idempotent", err)
	}
	check(writeEvidence(output, "outbound-superseded.json", adopted))
	return adopted
}

func externallySettleDailyBatch(t *testing.T, ctx context.Context, env *Environment, database, manifest, output string, r *dailyrelay.Reader, j *dailyrelay.Journal, bindings []dailyrelay.Binding, signer *dailyTestSigner) {
	t.Helper()
	check := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
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
	s, err := r.Snapshot(ctx)
	check(err)
	p, err := r.Plan(ctx, j, bindings, s.Time+300)
	check(err)
	roles := &dailyDurableRole{conn: db, base: signer}
	payer := &dailyPayerSigner{rpc: env.RPC, conn: db}
	terms := dailyrelay.TransactionTerms{Gas: 15_000_000, FeeCap: big.NewInt(3_000_000_000), TipCap: big.NewInt(1_000_000_000)}
	beforeCalls := signer.calls
	b, err := o.Prepare(ctx, r, p, 0, roles, payer, terms)
	check(err)
	check(env.RPC.FundGas(ctx, Wallet(8)))
	to := env.Address("DailyBetCustody")
	receipt, err := env.RPC.Send(ctx, 8, &to, b.Authorization.Data)
	check(err)
	keyless, err := dailyrelay.NewReader(manifest, env.RPC)
	check(err)
	reason := "Reconcile exact authorized batch submitted by a different relay"
	if _, err = o.AdoptExternalExecution(ctx, keyless, j, b.ID, receipt.TxHash, reason); !errors.Is(err, contracts.ErrAwaitFinality) {
		t.Fatal("unconfirmed external payment accepted", err)
	}
	check(env.RPC.Mine(ctx, 2))
	if _, err = o.AdoptNonce(ctx, keyless, b.ID, receipt.TxHash, reason); err == nil {
		t.Fatal("different payer's execution consumed our reserved nonce")
	}
	// Reject the association after proof writes: payment proof and external
	// evidence must commit together, while the owned nonce stays untouched.
	_, err = db.Exec(ctx, `CREATE FUNCTION pg_temp.fuse_reject_external_association() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF (convert_from(NEW.record_encoded,'UTF8')::jsonb->>'state')='external_executed' THEN RAISE EXCEPTION 'injected external association failure'; END IF; RETURN NEW; END $$;
CREATE TRIGGER fuse_test_external BEFORE UPDATE ON fuse_daily_outbound FOR EACH ROW EXECUTE FUNCTION pg_temp.fuse_reject_external_association()`)
	check(err)
	if _, err = o.AdoptExternalExecution(ctx, keyless, j, b.ID, receipt.TxHash, reason); err == nil {
		t.Fatal("external association injection passed")
	}
	var premature int
	check(db.QueryRow(ctx, `SELECT count(*) FROM fuse_daily_settlements WHERE tx_hash=$1`, receipt.TxHash.Hex()).Scan(&premature))
	if premature != 0 {
		t.Fatal("failed external association left a payment proof")
	}
	_, err = db.Exec(ctx, `DROP TRIGGER fuse_test_external ON fuse_daily_outbound`)
	check(err)
	restart()
	executed, err := o.AdoptExternalExecution(ctx, keyless, j, b.ID, receipt.TxHash, reason)
	check(err)
	if executed.State != "external_executed" || executed.Receipt != nil || executed.ExternalExecution == nil || executed.ExternalExecution.Settlement.LPNetUSDC != "0" || *executed.Nonce != *b.Nonce {
		t.Fatal("external payment overwrote payer nonce state")
	}
	if _, active, err := o.Active(ctx); err != nil || !active {
		t.Fatal("external payment released unresolved payer lane", err)
	}
	if _, err = o.Deliver(ctx, keyless, j, b.ID, env.RPC); err == nil {
		t.Fatal("already proven external payment sent again")
	}
	if _, _, err = o.PrepareReplacement(ctx, r, j, b.ID, terms, "Do not resend already paid batch", &dailyAttemptPayerSigner{rpc: env.RPC, conn: db}); err == nil {
		t.Fatal("externally executed settlement admitted a fee replacement")
	}
	proof, err := o.CommitBatch(ctx, keyless, j, b.ID)
	check(err)
	if proof.Transaction != receipt.TxHash {
		t.Fatal("external financial proof points at owned unexecuted raw")
	}
	fees := dailyrelay.TransactionTerms{Gas: 21000, FeeCap: big.NewInt(6_000_000_000), TipCap: big.NewInt(2_000_000_000)}
	armed, index, err := o.PrepareCancellation(ctx, keyless, b.ID, fees, "Clean payer nonce after proven external settlement", &dailyAttemptPayerSigner{rpc: env.RPC, conn: db})
	check(err)
	lost := &dailyLostReply{rpc: env.RPC, conn: db}
	if _, err = o.DeliverAttempt(ctx, keyless, nil, b.ID, index, lost); err == nil || lost.calls != 1 {
		t.Fatal("external-paid cleanup lost reply not retained")
	}
	restart()
	check(env.RPC.Mine(ctx, 2))
	closed, err := o.Observe(ctx, keyless, b.ID)
	check(err)
	if closed.State != "external_reconciled" || closed.ExternalExecution.Observation.Transaction != receipt.TxHash || closed.Receipt.TxHash != armed.Attempts[index].Transaction || closed.Receipt.TxHash == proof.Transaction {
		t.Fatal("external payment and nonce cleanup were conflated")
	}
	if _, active, err := o.Active(ctx); err != nil || active {
		t.Fatal("confirmed cleanup retained payer lane", err)
	}
	proofRetry, err := o.CommitBatch(ctx, keyless, j, b.ID)
	check(err)
	if proofRetry.Transaction != proof.Transaction || signer.calls != beforeCalls+2 {
		t.Fatal("external cleanup recharged or resigned settlement")
	}
	if retry, err := o.AdoptExternalExecution(ctx, keyless, j, b.ID, receipt.TxHash, reason); err != nil || retry.State != "external_reconciled" {
		t.Fatal("terminal external adoption retry was not idempotent", err)
	}
	var paid int
	check(db.QueryRow(ctx, `SELECT count(*) FROM fuse_daily_settled_tickets WHERE tx_hash=$1`, receipt.TxHash.Hex()).Scan(&paid))
	if paid != 2 {
		t.Fatal("external zero-net batch did not record both obligations exactly once")
	}
	check(writeEvidence(output, "external-batch-proof.json", proof))
	check(writeEvidence(output, "outbound-external-reconciled.json", closed))
	check(writeEvidence(output, "external-recovery.json", map[string]any{"passed": true, "reserved_only_nonce_consumer_audited": true, "unrelated_nonce_consumption_not_counted_as_payment": true, "bounded_scan_found_actual_nonce_consumer": true, "external_payment_did_not_release_owned_nonce": true, "different_payer_cannot_consume_owned_nonce": true, "external_semantic_proof_and_association_atomic": true, "owned_nonce_cleanup_kept_separate_from_payment": true, "external_payment_not_sent_or_charged_again": true, "keyless_external_receipt_reconciliation": true, "external_zero_net_lp_usdc": proof.LPNetUSDC, "synthetic_chain_id": ChainID, "public_transactions": false, "production_approved": false}))
}
