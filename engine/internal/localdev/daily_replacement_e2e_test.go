package localdev

import (
	"bytes"
	"context"
	"errors"
	"math/big"
	"testing"

	"fuse/engine/internal/contracts"
	"fuse/engine/internal/dailyrelay"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/jackc/pgx/v5"
)

type dailyAttemptPayerSigner struct {
	rpc         *RPC
	conn        *pgx.Conn
	fail, wrong bool
	calls       int
}

func (s *dailyAttemptPayerSigner) SignTransaction(ctx context.Context, tx *types.Transaction) (*types.Transaction, error) {
	if err := s.rpc.guard(ctx); err != nil {
		return nil, err
	}
	b, err := dailyActiveOutbound(ctx, s.conn, Wallet(7))
	if err != nil {
		return nil, err
	}
	if (b.State != "prepared" && b.State != "external_executed") || b.Nonce == nil || *b.Nonce != tx.Nonce() || len(b.Attempts) == 0 {
		return nil, errors.New("attempt signer reached before durable parent nonce")
	}
	a := b.Attempts[len(b.Attempts)-1]
	encoded, err := tx.MarshalBinary()
	if err != nil {
		return nil, err
	}
	if a.State != "staged" || len(a.Raw) != 0 || !bytes.Equal(a.Unsigned, encoded) {
		return nil, errors.New("attempt signer reached before exact durable decision/unsigned payload")
	}
	s.calls++
	if s.fail {
		s.fail = false
		return nil, errors.New("injected crash after replacement decision persistence")
	}
	if s.wrong {
		tx = types.NewTx(&types.DynamicFeeTx{ChainID: tx.ChainId(), Nonce: tx.Nonce(), Gas: tx.Gas(), GasFeeCap: tx.GasFeeCap(), GasTipCap: tx.GasTipCap(), To: tx.To(), Data: tx.Data(), Value: big.NewInt(1)})
	}
	key, err := DevKey(7)
	if err != nil {
		return nil, err
	}
	return types.SignTx(tx, types.LatestSignerForChainID(new(big.Int).SetUint64(ChainID)), key)
}

func cancelDailyPrepared(t *testing.T, ctx context.Context, env *Environment, db *pgx.Conn, database, manifest, output string, r *dailyrelay.Reader, j *dailyrelay.Journal, bindings []dailyrelay.Binding, roles *dailyDurableRole, payer *dailyPayerSigner) dailyrelay.Outbound {
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
	p, err := r.Plan(ctx, j, bindings, s.Time+2)
	check(err)
	terms := dailyrelay.TransactionTerms{Gas: 15_000_000, FeeCap: big.NewInt(3_000_000_000), TipCap: big.NewInt(1_000_000_000)}
	b, err := o.Prepare(ctx, r, p, 0, roles, payer, terms)
	check(err)
	before, err := env.Uint(ctx, "DailyLPVault", "accountedCash", 0)
	check(err)
	creditBefore, err := env.Uint(ctx, "DailyBetCustody", "available", 0, Wallet(Alice))
	check(err)
	exposureBefore, err := env.Uint(ctx, "DailyLPVault", "openExposure", 0)
	check(err)
	check(env.RPC.Advance(ctx, 3))
	check(env.RPC.Mine(ctx, 2))
	if _, err = o.Deliver(ctx, r, j, b.ID, env.RPC); err == nil {
		t.Fatal("expired prepared settlement broadcast again")
	}
	if o.RetireUnprepared(ctx, r, b.ID) == nil {
		t.Fatal("expired signed transaction discarded without consuming its nonce")
	}
	keyless, err := dailyrelay.NewReader(manifest, env.RPC)
	check(err)
	fees := dailyrelay.TransactionTerms{Gas: 21000, FeeCap: big.NewInt(6_000_000_000), TipCap: big.NewInt(2_000_000_000)}
	attemptSigner := &dailyAttemptPayerSigner{rpc: env.RPC, conn: db, fail: true}
	staged, index, err := o.PrepareCancellation(ctx, keyless, b.ID, fees, "Expired settlement authorization; preserve obligations and reclaim nonce", attemptSigner)
	if err == nil || index != 0 || len(staged.Attempts) != 1 || staged.Attempts[0].State != "staged" {
		t.Fatal("crash did not retain unsigned cancellation decision")
	}
	restart()
	attemptSigner.wrong = true
	if _, _, err = o.PrepareCancellation(ctx, keyless, b.ID, fees, staged.Attempts[0].Reason, attemptSigner); err == nil {
		t.Fatal("cancellation payer added native value")
	}
	retained, err := o.Get(ctx, b.ID)
	check(err)
	if len(retained.Attempts[0].Raw) != 0 {
		t.Fatal("invalid cancellation signature persisted")
	}
	attemptSigner.wrong = false
	armed, index, err := o.PrepareCancellation(ctx, keyless, b.ID, fees, staged.Attempts[0].Reason, attemptSigner)
	check(err)
	if *armed.Nonce != *b.Nonce || !bytes.Equal(armed.Raw, b.Raw) || armed.Transaction != b.Transaction {
		t.Fatal("cancellation replaced original evidence or nonce")
	}
	if o.AbandonUnsignedAttempt(ctx, keyless, b.ID, index) == nil {
		t.Fatal("signed cancellation abandoned")
	}
	if _, _, err = o.PrepareReplacement(ctx, r, j, b.ID, terms, "Do not resurrect settlement", attemptSigner); err == nil {
		t.Fatal("settlement replacement admitted after cancellation armed")
	}
	if _, err = o.Deliver(ctx, r, j, b.ID, env.RPC); err == nil {
		t.Fatal("original send resumed after cancellation armed")
	}
	restart()
	lost := &dailyLostReply{rpc: env.RPC, conn: db}
	if _, err = o.DeliverAttempt(ctx, keyless, nil, b.ID, index, lost); err == nil || lost.calls != 1 {
		t.Fatal("lost cancellation send reply not retained")
	}
	restart()
	if _, err = o.Observe(ctx, keyless, b.ID); !errors.Is(err, contracts.ErrAwaitFinality) {
		t.Fatal("unconfirmed cancellation released nonce", err)
	}
	var claims int
	check(db.QueryRow(ctx, `SELECT count(*) FROM fuse_daily_outbound_claims WHERE intent_id=$1`, b.ID.Hex()).Scan(&claims))
	if claims != len(bindings) {
		t.Fatal("unconfirmed cancellation released ticket claims")
	}
	check(env.RPC.Mine(ctx, 2))
	_, err = db.Exec(ctx, `CREATE FUNCTION pg_temp.fuse_reject_cancel_terminal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF (convert_from(NEW.record_encoded,'UTF8')::jsonb->>'state')='cancelled' THEN RAISE EXCEPTION 'injected cancellation terminal failure'; END IF; RETURN NEW; END $$;
CREATE TRIGGER fuse_test_cancel_failure BEFORE UPDATE ON fuse_daily_outbound FOR EACH ROW EXECUTE FUNCTION pg_temp.fuse_reject_cancel_terminal()`)
	check(err)
	if _, err = o.Observe(ctx, keyless, b.ID); err == nil {
		t.Fatal("cancellation terminal failure injection passed")
	}
	check(db.QueryRow(ctx, `SELECT count(*) FROM fuse_daily_outbound_claims WHERE intent_id=$1`, b.ID.Hex()).Scan(&claims))
	if claims != len(bindings) {
		t.Fatal("failed cancellation commit released claims")
	}
	if _, active, err := o.Active(ctx); err != nil || !active {
		t.Fatal("failed cancellation commit released payer lane", err)
	}
	_, err = db.Exec(ctx, `DROP TRIGGER fuse_test_cancel_failure ON fuse_daily_outbound`)
	check(err)
	restart()
	cancelled, err := o.Observe(ctx, keyless, b.ID)
	check(err)
	if cancelled.State != "cancelled" || cancelled.Receipt == nil || cancelled.Receipt.TxHash != armed.Attempts[index].Transaction || cancelled.IncludedTransaction == b.Transaction || cancelled.WinningAttempt == nil || *cancelled.WinningAttempt != index {
		t.Fatal("confirmed cancellation winner was not identified")
	}
	if _, err = o.CommitBatch(ctx, r, j, b.ID); err == nil {
		t.Fatal("cancellation receipt counted as payout")
	}
	if _, active, err := o.Active(ctx); err != nil || active {
		t.Fatal("confirmed cancellation did not release payer lane", err)
	}
	check(db.QueryRow(ctx, `SELECT count(*) FROM fuse_daily_settled_tickets WHERE chain_id=$1`, "31337").Scan(&claims))
	if claims != 0 {
		t.Fatal("cancellation recorded paid tickets")
	}
	after, err := env.Uint(ctx, "DailyLPVault", "accountedCash", 0)
	check(err)
	creditAfter, err := env.Uint(ctx, "DailyBetCustody", "available", 0, Wallet(Alice))
	check(err)
	exposureAfter, err := env.Uint(ctx, "DailyLPVault", "openExposure", 0)
	check(err)
	if after.Cmp(before) != 0 || creditAfter.Cmp(creditBefore) != 0 || exposureAfter.Cmp(exposureBefore) != 0 {
		t.Fatal("cancellation changed settlement obligations or balances")
	}
	if _, err = env.RPC.Broadcast(ctx, b.Raw); err == nil {
		t.Fatal("original transaction executed after cancellation consumed nonce")
	}
	if _, err = o.DeliverAttempt(ctx, keyless, nil, b.ID, index, lost); err != nil || lost.calls != 1 {
		t.Fatal("cancelled retry sent again", err)
	}
	check(writeEvidence(output, "outbound-cancelled.json", cancelled))
	return cancelled
}

// Compile-time check: the injected signer supports only transaction signing.
var _ dailyrelay.TransactionSigner = (*dailyAttemptPayerSigner)(nil)
