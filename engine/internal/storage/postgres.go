package storage

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"sync"

	"fuse/engine/internal/engine"
	"github.com/jackc/pgx/v5"
)

//go:embed schema.sql
var schema string

// Postgres owns a dedicated session advisory lock. Every append runs on that
// same connection, locks the durable fence row, and compares generation/head.
// A disconnected writer cannot reconnect/reacquire implicitly.
type Postgres struct {
	mu         sync.Mutex
	conn       *pgx.Conn
	generation int64
}

const lockID int64 = 0x46555345313030

func OpenPostgres(ctx context.Context, url string) (*Postgres, error) {
	c, err := pgx.Connect(ctx, url)
	if err != nil {
		return nil, err
	}
	ok := false
	defer func() {
		if !ok {
			_ = c.Close(context.Background())
		}
	}()
	var held bool
	if err = c.QueryRow(ctx, "SELECT pg_try_advisory_lock($1)", lockID).Scan(&held); err != nil {
		return nil, err
	}
	if !held {
		return nil, errors.New("another trading writer holds leadership")
	}
	if _, err = c.Exec(ctx, schema); err != nil {
		return nil, err
	}
	p := &Postgres{conn: c}
	err = c.QueryRow(ctx, "UPDATE fuse_leadership SET generation=generation+1 WHERE id RETURNING generation").Scan(&p.generation)
	if err != nil {
		return nil, err
	}
	ok = true
	return p, nil
}
func (p *Postgres) Load(ctx context.Context) ([]engine.Event, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	rows, err := p.conn.Query(ctx, "SELECT COALESCE(event_encoded,convert_to(event::text,'UTF8')) FROM fuse_journal ORDER BY sequence")
	if err != nil {
		return nil, err
	}
	events := []engine.Event{}
	for rows.Next() {
		var raw []byte
		if err = rows.Scan(&raw); err != nil {
			rows.Close()
			return nil, err
		}
		var e engine.Event
		if err = json.Unmarshal(raw, &e); err != nil {
			rows.Close()
			return nil, err
		}
		events = append(events, e)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	var seq uint64
	var head string
	if err = p.conn.QueryRow(ctx, "SELECT sequence,journal_hash FROM fuse_leadership WHERE id").Scan(&seq, &head); err != nil {
		return nil, err
	}
	if seq != uint64(len(events)) || (seq > 0 && head != events[len(events)-1].Hash) {
		return nil, errors.New("durable journal head mismatch")
	}
	if seq > 0 {
		var raw []byte
		var snapSeq uint64
		if err = p.conn.QueryRow(ctx, "SELECT sequence,COALESCE(state_encoded,convert_to(state::text,'UTF8')) FROM fuse_snapshot WHERE id").Scan(&snapSeq, &raw); err != nil {
			return nil, err
		}
		var s engine.State
		if err = json.Unmarshal(raw, &s); err != nil {
			return nil, err
		}
		if snapSeq != seq || s.Sequence != seq || s.JournalHash != head || s.Digest() != events[len(events)-1].StateHash {
			return nil, errors.New("snapshot/journal mismatch")
		}
	}
	return events, nil
}
func (p *Postgres) Append(ctx context.Context, e engine.Event, s engine.State) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	tx, err := p.conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(context.Background()) //nolint:errcheck
	var gen int64
	var seq uint64
	var hash string
	if err = tx.QueryRow(ctx, "SELECT generation,sequence,journal_hash FROM fuse_leadership WHERE id FOR UPDATE").Scan(&gen, &seq, &hash); err != nil {
		return err
	}
	if gen != p.generation || seq+1 != e.Sequence || hash != e.PreviousHash {
		return errors.New("leadership fence or journal head changed")
	}
	raw, err := json.Marshal(e)
	if err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, "INSERT INTO fuse_journal(sequence,command_key,event,event_encoded) VALUES($1,$2,$3,$4)", e.Sequence, e.Command.Key, raw, raw); err != nil {
		return err
	}
	sums := map[string]int64{}
	for i, v := range e.Postings {
		sums[v.Asset] += v.Delta
		if _, err = tx.Exec(ctx, "INSERT INTO fuse_postings VALUES($1,$2,$3,$4,$5)", e.Sequence, i, v.Account, v.Asset, v.Delta); err != nil {
			return err
		}
	}
	for asset, sum := range sums {
		if sum != 0 {
			return fmt.Errorf("unbalanced %s postings", asset)
		}
	}
	for account, v := range e.Notices {
		if _, err = tx.Exec(ctx, "INSERT INTO fuse_outbox VALUES($1,$2,$3)", e.Sequence, account, []byte(v)); err != nil {
			return err
		}
	}
	snap, err := json.Marshal(s)
	if err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, "INSERT INTO fuse_snapshot(id,sequence,state,state_encoded) VALUES(true,$1,$2,$3) ON CONFLICT(id) DO UPDATE SET sequence=excluded.sequence,state=excluded.state,state_encoded=excluded.state_encoded", e.Sequence, snap, snap); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, "UPDATE fuse_leadership SET sequence=$1,journal_hash=$2 WHERE id AND generation=$3", e.Sequence, e.Hash, p.generation); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
func (p *Postgres) Close(ctx context.Context) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.conn.Close(ctx)
}

// AssertHead uses the same non-reconnecting leadership session as Append.
// A restarted, disconnected or superseded writer cannot authorize payments.
func (p *Postgres) AssertHead(ctx context.Context, sequence uint64, journalHash string) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	var generation int64
	var seq uint64
	var head string
	if err := p.conn.QueryRow(ctx, "SELECT generation,sequence,journal_hash FROM fuse_leadership WHERE id").Scan(&generation, &seq, &head); err != nil {
		return err
	}
	if generation != p.generation || seq != sequence || head != journalHash {
		return errors.New("canonical financial source leadership/head changed")
	}
	return nil
}
