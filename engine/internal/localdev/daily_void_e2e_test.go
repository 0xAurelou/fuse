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
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/jackc/pgx/v5"
)

type dailyVoidFaultRPC struct {
	base                 dailyrelay.RPC
	hash                 common.Hash
	mode                 string
	vault, custody, usdc common.Address
}

func (r *dailyVoidFaultRPC) ReadRPC(ctx context.Context, method string, params any, out any) error {
	var raw json.RawMessage
	if err := r.base.ReadRPC(ctx, method, params, &raw); err != nil {
		return err
	}
	if method == "eth_getTransactionReceipt" {
		var receipt *types.Receipt
		if err := json.Unmarshal(raw, &receipt); err != nil {
			return err
		}
		if receipt != nil && receipt.TxHash == r.hash {
			switch r.mode {
			case "queue-time":
				for _, log := range receipt.Logs {
					if log.Address == r.vault && len(log.Topics) > 0 && log.Topics[0] == crypto.Keccak256Hash([]byte("FinalVoidQueued(bytes32,uint64)")) {
						log.Data[len(log.Data)-1] ^= 1
					}
				}
			case "refund-outcome":
				for _, log := range receipt.Logs {
					if log.Address == r.custody && len(log.Topics) > 0 && log.Topics[0] == crypto.Keccak256Hash([]byte("TicketResolved(bytes32,uint8,uint64,bytes32)")) {
						log.Data[31] = 3
					}
				}
			case "token-move":
				data := make([]byte, 32)
				data[31] = 1
				receipt.Logs = append(receipt.Logs, &types.Log{Address: r.usdc, Topics: []common.Hash{crypto.Keccak256Hash([]byte("Transfer(address,address,uint256)")), common.BytesToHash(r.custody.Bytes()), common.BytesToHash(r.vault.Bytes())}, Data: data, BlockNumber: receipt.BlockNumber.Uint64(), BlockHash: receipt.BlockHash, TxHash: receipt.TxHash, TxIndex: receipt.TransactionIndex, Index: receipt.Logs[len(receipt.Logs)-1].Index + 1})
			}
			raw, _ = json.Marshal(receipt)
		}
	}
	return json.Unmarshal(raw, out)
}

func queueDailyVoid(t *testing.T, ctx context.Context, env *Environment, database, manifest, output string, r *dailyrelay.Reader, j *dailyrelay.Journal, p *dailyrelay.Plan, bindings []dailyrelay.Binding, signer *dailyTestSigner) (dailyrelay.Authorized, *types.Receipt, dailyrelay.VoidProof) {
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
	roles := &dailyDurableRole{conn: db, base: signer}
	payer := &dailyPayerSigner{rpc: env.RPC, conn: db}
	terms := dailyrelay.TransactionTerms{Gas: 15_000_000, FeeCap: big.NewInt(3_000_000_000), TipCap: big.NewInt(1_000_000_000)}
	creditBefore, err := env.Uint(ctx, "DailyBetCustody", "available", 0, Wallet(Alice))
	check(err)
	exposureBefore, err := env.Uint(ctx, "DailyLPVault", "openExposure", 0)
	check(err)
	b, err := o.Prepare(ctx, r, p, 0, roles, payer, terms)
	check(err)
	restart()
	lost := &dailyLostReply{rpc: env.RPC, conn: db}
	check(env.RPC.write(ctx, "anvil_setAutomine", []any{false}, nil))
	defer func() { _ = env.RPC.write(context.Background(), "anvil_setAutomine", []any{true}, nil) }()
	if _, err = o.Deliver(ctx, r, j, b.ID, lost); err == nil || lost.calls != 1 {
		t.Fatal("queue lost reply was not retained")
	}
	restart()
	attemptSigner := &dailyAttemptPayerSigner{rpc: env.RPC, conn: db}
	fees := dailyrelay.TransactionTerms{Gas: 21000, FeeCap: big.NewInt(6_000_000_000), TipCap: big.NewInt(2_000_000_000)}
	armed, index, err := o.PrepareCancellation(ctx, r, b.ID, fees, "Exercise original queue inclusion racing a prepared cancellation", attemptSigner)
	check(err)
	// The original was already pending before cancellation was prepared. Mine
	// it without broadcasting cancellation: reconciliation must credit its true
	// queue receipt rather than assuming the newest attempt won.
	check(env.RPC.Mine(ctx, 1))
	if _, err = o.Observe(ctx, r, b.ID); !errors.Is(err, contracts.ErrAwaitFinality) {
		t.Fatal("unconfirmed queue did not await finality", err)
	}
	check(env.RPC.write(ctx, "anvil_setAutomine", []any{true}, nil))
	check(env.RPC.Mine(ctx, 2))
	included, err := o.Observe(ctx, r, b.ID)
	check(err)
	if included.State != "included" {
		t.Fatal("queue skipped semantic reconciliation")
	}
	if included.IncludedTransaction != b.Transaction || included.WinningAttempt == nil || *included.WinningAttempt != -1 || len(armed.Attempts) != 1 {
		t.Fatal("original queue winner lost to prepared cancellation metadata")
	}
	if _, err = o.CommitBatch(ctx, r, j, b.ID); err == nil {
		t.Fatal("queue receipt counted as cash-batch payment")
	}
	for _, mode := range []string{"queue-time", "token-move"} {
		fault := &dailyVoidFaultRPC{base: env.RPC, hash: b.Transaction, mode: mode, vault: env.Address("DailyLPVault"), custody: env.Address("DailyBetCustody"), usdc: env.Address("USDC")}
		badReader, err := dailyrelay.NewReader(manifest, fault)
		check(err)
		if _, err = badReader.ReconcileVoidQueue(ctx, j, bindings[0], *b.Authorization, b.Transaction); err == nil {
			t.Fatal("altered queue receipt accepted", mode)
		}
	}
	// A valid receipt is not evidence for different asserted signature calldata.
	changed := *b.Authorization
	changed.SettlementSignature = append([]byte{}, changed.SettlementSignature...)
	changed.SettlementSignature[0] ^= 1
	changed.Data, err = env.Data("DailyBetCustody", "resolve", changed.Action.Outcomes[0], changed.SettlementSignature, changed.RiskSignature)
	check(err)
	if _, err = r.ReconcileVoidQueue(ctx, j, bindings[0], changed, b.Transaction); err == nil {
		t.Fatal("queue actual transaction input was not checked")
	}
	proof, err := o.CommitVoid(ctx, r, j, b.ID)
	check(err)
	if proof.Kind != "queue_void" || proof.CreditUSDC != "0" {
		t.Fatal("queue recorded a paid refund")
	}
	restart()
	store, err := dailyrelay.OpenBindings(ctx, database)
	check(err)
	defer store.Close(context.Background()) //nolint:errcheck
	q, completed, err := store.VoidRight(ctx, ChainID, proof.Custody, proof.Ticket)
	check(err)
	if completed != nil {
		t.Fatal("queued right already recorded as paid")
	}
	if store.CommitVoid(ctx, q) == nil {
		t.Fatal("restored queue proof bypassed receipt verification")
	}
	q, err = r.VerifyVoidQueue(ctx, j, bindings[0], q)
	check(err)
	wrongGeneration := q
	wrongGeneration.Authorization = q.Authorization
	gen, ok := new(big.Int).SetString(q.Authorization.Generation, 10)
	if !ok || gen.Cmp(big.NewInt(1)) <= 0 {
		t.Fatal("fixture signer version unavailable")
	}
	gen.Sub(gen, big.NewInt(1))
	wrongGeneration.Authorization.Generation = gen.String()
	digest, err := wrongGeneration.Authorization.Action.Outcomes[0].Digest(new(big.Int).SetUint64(ChainID), q.Custody, gen)
	check(err)
	wrongGeneration.Authorization.Action.Digest = digest
	wrongGeneration.Authorization.Action.OnchainDigest = digest
	if _, err = r.VerifyVoidQueue(ctx, j, bindings[0], wrongGeneration); err == nil {
		t.Fatal("self-consistent false historical generation accepted")
	}
	check(store.CommitVoid(ctx, q))
	creditAfter, err := env.Uint(ctx, "DailyBetCustody", "available", 0, Wallet(Alice))
	check(err)
	exposureAfter, err := env.Uint(ctx, "DailyLPVault", "openExposure", 0)
	check(err)
	if creditAfter.Cmp(creditBefore) != 0 || exposureAfter.Cmp(exposureBefore) != 0 {
		t.Fatal("queue released stake or original underwriting")
	}
	if _, active, err := o.Active(ctx); err != nil || active {
		t.Fatal("confirmed queued obligation did not release its transport lane", err)
	}
	if _, err = o.CommitVoid(ctx, r, j, b.ID); err != nil {
		t.Fatal("queue commit retry failed", err)
	}
	if _, err = o.Deliver(ctx, r, j, b.ID, lost); err != nil || lost.calls != 1 {
		t.Fatal("queued retry sent again", err)
	}
	if _, err = o.DeliverAttempt(ctx, r, j, b.ID, index, lost); err != nil || lost.calls != 1 {
		t.Fatal("losing cancellation sent after original inclusion", err)
	}
	terminal, err := o.Get(ctx, b.ID)
	check(err)
	if terminal.State != "queued" {
		t.Fatal("durable queue transport state missing")
	}
	check(writeEvidence(output, "outbound-void-queued.json", terminal))
	check(writeEvidence(output, "void-queue-proof.json", proof))
	check(writeEvidence(output, "replacement-original-won.json", map[string]any{"passed": true, "original_queue_transaction": b.Transaction, "losing_prepared_cancellation": armed.Attempts[index].Transaction, "original_won_after_cancellation_prepared": true, "actual_original_receipt_reconciled": true, "losing_cancellation_not_broadcast_after_original_inclusion": true, "public_transactions": false, "production_approved": false}))
	return *b.Authorization, included.Receipt, proof
}

func completeDailyVoid(t *testing.T, ctx context.Context, env *Environment, database, manifest, output string, r *dailyrelay.Reader, j *dailyrelay.Journal, p *dailyrelay.Plan, bindings []dailyrelay.Binding, signer *dailyTestSigner) (dailyrelay.Authorized, *types.Receipt, dailyrelay.VoidProof) {
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
	store, err := dailyrelay.OpenBindings(ctx, database)
	check(err)
	defer store.Close(context.Background()) //nolint:errcheck
	q, oldCompletion, err := store.VoidRight(ctx, ChainID, env.Address("DailyBetCustody"), bindings[0].TicketID)
	check(err)
	if oldCompletion != nil {
		t.Fatal("refund was already completed")
	}
	creditBefore, err := env.Uint(ctx, "DailyBetCustody", "available", 0, Wallet(Alice))
	check(err)
	equityBefore, err := env.Uint(ctx, "DailyLPVault", "totalEquity", 0)
	check(err)
	callsBefore := signer.calls
	payer := &dailyPayerSigner{rpc: env.RPC, conn: db}
	terms := dailyrelay.TransactionTerms{Gas: 15_000_000, FeeCap: big.NewInt(3_000_000_000), TipCap: big.NewInt(1_000_000_000)}
	// This reader has no canonical writer or financial signer. Its original
	// queued receipt and unchanged onchain right supply completion authority.
	b, err := o.Prepare(ctx, r, p, 0, nil, payer, terms)
	check(err)
	restart()
	check(env.Direct(ctx, Governance, "AccessController", "setSigner", crypto.Keccak256Hash([]byte("RISK_SIGNER")), Wallet(RiskSigner)))
	check(env.RPC.Advance(ctx, 601))
	check(env.RPC.Mine(ctx, 2))
	if _, err = r.Authorize(ctx, p, 0, nil); err != nil {
		t.Fatal("recorded right expired with old plan deadline or signer generation", err)
	}
	if _, err = o.Prepare(ctx, r, p, 0, nil, payer, terms); err != nil {
		t.Fatal("prepared refund did not survive signer rotation", err)
	}
	lost := &dailyLostReply{rpc: env.RPC, conn: db}
	to := env.Address("DailyBetCustody")
	untrackedTx, untrackedRaw, err := env.RPC.Prepare(ctx, 7, &to, b.Authorization.Data)
	check(err)
	untracked := &dailyLostUntracked{rpc: env.RPC}
	if _, err = untracked.Broadcast(ctx, untrackedRaw); err == nil || untracked.calls != 1 {
		t.Fatal("independent refund lost reply not injected")
	}
	restart()
	check(env.RPC.Mine(ctx, 2))
	if _, err = o.Observe(ctx, r, b.ID); !errors.Is(err, dailyrelay.ErrNonceConflict) {
		t.Fatal("untracked refund nonce did not stop normal processing", err)
	}
	actual, err := env.RPC.Receipt(ctx, untrackedTx.Hash())
	check(err)
	found, err := r.FindNonce(ctx, Wallet(7), *b.Nonce, b.Authorization.VerifiedBlock, actual.BlockNumber.Uint64())
	check(err)
	if found == nil || found.Transaction != untrackedTx.Hash() {
		t.Fatal("untracked matching refund not discovered")
	}
	included, err := o.AdoptNonce(ctx, r, b.ID, found.Transaction, "Recover matching refund submitted independently while the writer is disconnected")
	check(err)
	if included.NonceRecovery == nil || included.NonceRecovery.Class != "matching" || included.WinningAttempt == nil || *included.WinningAttempt != -2 {
		t.Fatal("matching unknown transaction was classified as unrelated")
	}
	for _, mode := range []string{"refund-outcome", "token-move"} {
		fault := &dailyVoidFaultRPC{base: env.RPC, hash: included.Receipt.TxHash, mode: mode, vault: env.Address("DailyLPVault"), custody: env.Address("DailyBetCustody"), usdc: env.Address("USDC")}
		badReader, err := dailyrelay.NewReader(manifest, fault)
		check(err)
		if _, err = badReader.ReconcileVoidCompletion(ctx, j, bindings[0], q, *b.Authorization, included.Receipt.TxHash); err == nil {
			t.Fatal("altered refund receipt accepted", mode)
		}
	}
	if _, err = r.ReconcileVoidCompletion(ctx, j, bindings[0], q, *b.Authorization, q.Transaction); err == nil {
		t.Fatal("queued obligation counted as completed refund")
	}
	wrong := q
	wrong.Account = Wallet(Bob)
	if _, err = r.ReconcileVoidCompletion(ctx, j, bindings[0], wrong, *b.Authorization, included.Receipt.TxHash); err == nil {
		t.Fatal("original void refund owner changed")
	}
	_, err = db.Exec(ctx, `CREATE FUNCTION pg_temp.fuse_reject_void_terminal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF (convert_from(NEW.record_encoded,'UTF8')::jsonb->>'state')='refunded' THEN RAISE EXCEPTION 'injected refund terminal persistence failure'; END IF; RETURN NEW; END $$;
CREATE TRIGGER fuse_test_void_failure BEFORE UPDATE ON fuse_daily_outbound FOR EACH ROW EXECUTE FUNCTION pg_temp.fuse_reject_void_terminal()`)
	check(err)
	if _, err = o.CommitVoid(ctx, r, j, b.ID); err == nil {
		t.Fatal("refund terminal persistence injection passed")
	}
	_, notCompleted, err := store.VoidRight(ctx, ChainID, q.Custody, q.Ticket)
	check(err)
	if notCompleted != nil {
		t.Fatal("failed terminal commit left a paid refund right")
	}
	var premature int
	check(db.QueryRow(ctx, `SELECT count(*) FROM fuse_daily_void_proofs WHERE tx_hash=$1`, included.Receipt.TxHash.Hex()).Scan(&premature))
	if premature != 0 {
		t.Fatal("failed terminal commit left a completion proof")
	}
	_, err = db.Exec(ctx, `DROP TRIGGER fuse_test_void_failure ON fuse_daily_outbound`)
	check(err)
	restart()
	proof, err := o.CommitVoid(ctx, r, j, b.ID)
	check(err)
	restart()
	queued, completed, err := store.VoidRight(ctx, ChainID, q.Custody, q.Ticket)
	check(err)
	if completed == nil || queued.Transaction != q.Transaction || completed.Transaction != proof.Transaction || proof.QueueTransaction != q.Transaction || proof.CreditUSDC != q.StakeUSDC {
		t.Fatal("refund lost original right or exact custody credit")
	}
	if store.CommitVoid(ctx, *completed) == nil {
		t.Fatal("unverified restored completion proof committed")
	}
	if _, err = o.CommitVoid(ctx, r, j, b.ID); err != nil {
		t.Fatal("refund proof retry failed", err)
	}
	if _, err = o.Deliver(ctx, r, j, b.ID, lost); err != nil || lost.calls != 0 {
		t.Fatal("completed refund sent again", err)
	}
	creditAfter, err := env.Uint(ctx, "DailyBetCustody", "available", 0, Wallet(Alice))
	check(err)
	equityAfter, err := env.Uint(ctx, "DailyLPVault", "totalEquity", 0)
	check(err)
	if new(big.Int).Sub(creditAfter, creditBefore).String() != q.StakeUSDC || equityAfter.Cmp(equityBefore) != 0 || signer.calls != callsBefore {
		t.Fatal("refund duplicated, changed LP equity or required fresh financial signatures")
	}
	if _, active, err := o.Active(ctx); err != nil || active {
		t.Fatal("refunded right kept nonce lane active", err)
	}
	if _, err = o.Prepare(ctx, r, p, 0, nil, payer, terms); err == nil {
		t.Fatal("completed right admitted again")
	}
	terminal, err := o.Get(ctx, b.ID)
	check(err)
	if terminal.State != "refunded" {
		t.Fatal("durable refund transport state missing")
	}
	check(writeEvidence(output, "outbound-void-refunded.json", terminal))
	check(writeEvidence(output, "void-completion-proof.json", proof))
	check(writeEvidence(output, "void-recovery.json", map[string]any{"passed": true, "queued_stake_and_exposure_remain_reserved": true, "queue_and_refund_have_separate_proofs": true, "queue_actual_transaction_input_verified": true, "queue_lost_reply_restart": true, "refund_lost_reply_restart": true, "refund_without_live_canonical_writer": true, "refund_after_pause_and_additional_signer_rotation": true, "refund_after_old_plan_deadline": true, "exact_original_owner_stake_credited_once": true, "queue_not_counted_as_paid": true, "completion_proof_and_outbox_commit_atomic": true, "terminal_failure_rolled_back_paid_right": true, "changed_receipt_owner_calldata_or_transfer_rejected": true, "refund_does_not_change_lp_equity": true, "no_fresh_financial_signatures_for_refund": true, "newer_journal_preserves_original_queue_proof": true, "synthetic_chain_id": ChainID, "public_transactions": false, "production_approved": false}))
	return *b.Authorization, included.Receipt, proof
}
