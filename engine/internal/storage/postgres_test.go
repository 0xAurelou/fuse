package storage_test

import (
	"context"
	"encoding/json"
	"os"
	"testing"

	"fuse/engine/internal/engine"
	"fuse/engine/internal/storage"
	"github.com/jackc/pgx/v5"
)

func TestPostgresAtomicRecoveryAndLeadership(t *testing.T) {
	url := os.Getenv("FUSE_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("set FUSE_TEST_DATABASE_URL to an isolated, empty database")
	}
	ctx := context.Background()
	db, err := storage.OpenPostgres(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close(ctx)
	if second, err := storage.OpenPostgres(ctx, url); err == nil {
		second.Close(ctx)
		t.Fatal("two writers acquired leadership")
	}
	raw, err := os.ReadFile("../../config/paper-recovery.json")
	if err != nil {
		t.Fatal(err)
	}
	var policy engine.Policy
	_ = json.Unmarshal(raw, &policy)
	q, err := engine.Open(ctx, policy, db)
	if err != nil {
		t.Fatal(err)
	}
	if q.Snapshot().Sequence != 0 {
		t.Fatal("test requires empty database")
	}
	c := engine.Command{Key: "pg/fund", Kind: "lp_fund", At: 1000, Amount: 1_000_000_000}
	e, err := q.Execute(ctx, c)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := pgx.Connect(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	var journal, postings, outbox int
	if err = conn.QueryRow(ctx, "SELECT (SELECT count(*) FROM fuse_journal),(SELECT count(*) FROM fuse_postings),(SELECT count(*) FROM fuse_outbox)").Scan(&journal, &postings, &outbox); err != nil {
		t.Fatal(err)
	}
	if journal != 1 || postings != 2 || outbox != 0 {
		t.Fatalf("partial persistence: %d/%d/%d", journal, postings, outbox)
	}
	if _, err = conn.Exec(ctx, "DELETE FROM fuse_journal"); err == nil {
		t.Fatal("journal mutation allowed")
	}
	if err = db.Close(ctx); err != nil {
		t.Fatal(err)
	}
	next, err := storage.OpenPostgres(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer next.Close(ctx)
	recovered, err := engine.Open(ctx, policy, next)
	if err != nil {
		t.Fatal(err)
	}
	retry, err := recovered.Execute(ctx, c)
	if err != nil || retry.Hash != e.Hash {
		t.Fatal("committed command not deduplicated on restart", err)
	}
	// Killing the lock-owning session permits a new generation, while the old
	// sequencer must fail closed rather than silently reconnect.
	var backendPID int
	if err = conn.QueryRow(ctx, "SELECT pid FROM pg_locks WHERE locktype='advisory' AND granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) AND pid<>pg_backend_pid()").Scan(&backendPID); err != nil {
		t.Fatal(err)
	}
	if _, err = conn.Exec(ctx, "SELECT pg_terminate_backend($1)", backendPID); err != nil {
		t.Fatal(err)
	}
	if _, err = recovered.Execute(ctx, engine.Command{Key: "pg/dead-session", Kind: "lp_fund", At: 1001, Amount: 1}); err == nil {
		t.Fatal("disconnected leader acknowledged a write")
	}
	takeover, err := storage.OpenPostgres(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer takeover.Close(ctx)
	recovered, err = engine.Open(ctx, policy, takeover)
	if err != nil {
		t.Fatal(err)
	}
	// Forced SQL failure must roll back journal AND snapshot, and fence the process.
	if _, err = conn.Exec(ctx, `CREATE FUNCTION fuse_test_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected failure'; END $$; CREATE TRIGGER fuse_test_failure BEFORE INSERT ON fuse_postings FOR EACH ROW EXECUTE FUNCTION fuse_test_failure();`); err != nil {
		t.Fatal(err)
	}
	defer conn.Exec(ctx, "DROP TRIGGER fuse_test_failure ON fuse_postings; DROP FUNCTION fuse_test_failure()")
	if _, err = recovered.Execute(ctx, engine.Command{Key: "pg/fail", Kind: "lp_fund", At: 1001, Amount: 1}); err == nil {
		t.Fatal("failed transaction acknowledged")
	}
	if recovered.Ready() {
		t.Fatal("uncertain writer not fenced")
	}
	var count int
	_ = conn.QueryRow(ctx, "SELECT count(*) FROM fuse_journal").Scan(&count)
	if count != 1 {
		t.Fatal("transaction partly persisted")
	}
	// PostgreSQL JSONB changes object key order. Authoritative encoded bytes must
	// preserve RawMessage evidence, request identities and replay commitments.
	if _, err = conn.Exec(ctx, "DROP TRIGGER fuse_test_failure ON fuse_postings; DROP FUNCTION fuse_test_failure()"); err != nil {
		t.Fatal(err)
	}
	if err = takeover.Close(ctx); err != nil {
		t.Fatal(err)
	}
	rawStore, err := storage.OpenPostgres(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	rawWriter, err := engine.Open(ctx, policy, rawStore)
	if err != nil {
		t.Fatal(err)
	}
	oracleCommand := engine.Command{Key: "pg/raw-oracle", Kind: "oracle", At: 1002, Source: "a", Raw: json.RawMessage(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"100000"}}}`)}
	if _, err = rawWriter.Execute(ctx, oracleCommand); err != nil {
		t.Fatal(err)
	}
	rawState := rawWriter.Snapshot()
	if err = rawStore.Close(ctx); err != nil {
		t.Fatal(err)
	}
	reloadedStore, err := storage.OpenPostgres(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer reloadedStore.Close(ctx)
	reloaded, err := engine.Open(ctx, policy, reloadedStore)
	if err != nil {
		t.Fatal(err)
	}
	if engine.Hash(reloaded.Snapshot()) != engine.Hash(rawState) {
		t.Fatal("raw JSON journal normalized during persistence")
	}
	if _, err = reloaded.Execute(ctx, oracleCommand); err != nil {
		t.Fatal("raw request identity changed after restart", err)
	}

	// Realized risk loss and its immutable policy must survive an actual SQL
	// snapshot/journal reload, not only an in-memory Store replay.
	execute := func(c engine.Command) engine.Event {
		t.Helper()
		if c.Key == "" {
			c.Key = "risk/" + engine.Hash(c)
		}
		e, err := reloaded.Execute(ctx, c)
		if err != nil {
			t.Fatal(err)
		}
		return e
	}
	rawPrice := oracleCommand.Raw
	execute(engine.Command{Kind: "oracle", At: 1002, Source: "b", Raw: rawPrice})
	execute(engine.Command{Kind: "deposit", At: 1002, Actor: "alice", ID: "risk-deposit", Amount: 100_000_000})
	execute(engine.Command{Kind: "ack_deposit", At: 1002, ID: "risk-deposit"})
	quoteEvent := execute(engine.Command{Kind: "quote", At: 1002, Actor: "alice", Amount: 10_000_000, Multiplier: 2})
	var quote engine.Quote
	json.Unmarshal(quoteEvent.Result, &quote)
	execute(engine.Command{Kind: "enter", At: 1002, Actor: "alice", ID: quote.ID})
	for at := int64(6002); at <= 31002; at += 5000 {
		for _, source := range []string{"a", "b"} {
			execute(engine.Command{Kind: "oracle", At: at, Source: source, Raw: rawPrice})
		}
	}
	beforeRecovery := reloaded.Snapshot()
	if len(beforeRecovery.Recovery.Losses) != 1 {
		t.Fatal("SQL recovery fixture did not realize loss")
	}
	if err = reloadedStore.Close(ctx); err != nil {
		t.Fatal(err)
	}
	riskStore, err := storage.OpenPostgres(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer riskStore.Close(ctx)
	riskWriter, err := engine.Open(ctx, policy, riskStore)
	if err != nil {
		t.Fatal(err)
	}
	if engine.Hash(beforeRecovery) != engine.Hash(riskWriter.Snapshot()) {
		t.Fatal("recovery limits changed across PostgreSQL restart")
	}

}
