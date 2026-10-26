package engine

import (
	"context"
	"errors"
	"fmt"
	"sync"
)

// Store atomically persists journal, postings, snapshot and outbox (Notices).
// Append must fence writers and compare the expected journal head.
type Store interface {
	Load(context.Context) ([]Event, error)
	Append(context.Context, Event, State) error
	Close(context.Context) error
}
type Sequencer struct {
	mu       sync.RWMutex
	state    State
	store    Store
	events   []Event
	requests map[string]Event
	failed   bool
}

func Open(ctx context.Context, p Policy, store Store) (*Sequencer, error) {
	s, err := NewState(p)
	if err != nil {
		return nil, err
	}
	events, err := store.Load(ctx)
	if err != nil {
		return nil, err
	}
	q := &Sequencer{state: s, store: store, events: []Event{}, requests: map[string]Event{}}
	for _, e := range events {
		if _, ok := q.requests[e.Command.Key]; ok {
			return nil, errors.New("duplicate journal command")
		}
		next, got, err := Apply(q.state, e.Command)
		if err != nil || Hash(got) != Hash(e) {
			return nil, fmt.Errorf("replay divergence at sequence %d: %v", e.Sequence, err)
		}
		q.state = next
		q.events = append(q.events, e)
		q.requests[e.Command.Key] = e
	}
	return q, nil
}
func (q *Sequencer) Execute(ctx context.Context, c Command) (Event, error) {
	q.mu.Lock()
	defer q.mu.Unlock()
	return q.execute(ctx, c)
}
func (q *Sequencer) execute(ctx context.Context, c Command) (Event, error) {
	if q.failed {
		return Event{}, errors.New("sequencer fenced after storage failure; restart and replay")
	}
	if old, ok := q.requests[c.Key]; ok {
		if old.Command.Identity() != c.Identity() {
			return Event{}, reject("idempotency key reused for different command")
		}
		return clone(old), nil
	}
	next, e, err := Apply(q.state, c)
	if err != nil {
		return Event{}, err
	}
	if err = q.store.Append(ctx, e, next); err != nil {
		q.failed = true
		return Event{}, fmt.Errorf("durable commit unavailable: %w", err)
	}
	q.state = next
	q.events = append(q.events, e)
	q.requests[c.Key] = e
	return clone(e), nil
}
func (q *Sequencer) Snapshot() State { q.mu.RLock(); defer q.mu.RUnlock(); return clone(q.state) }
func (q *Sequencer) Ready() bool     { q.mu.RLock(); defer q.mu.RUnlock(); return !q.failed }
func (q *Sequencer) Events(after uint64, limit int) []Event {
	q.mu.RLock()
	defer q.mu.RUnlock()
	if after >= uint64(len(q.events)) {
		return []Event{}
	}
	end := int(after) + limit
	if end > len(q.events) {
		end = len(q.events)
	}
	return clone(q.events[int(after):end])
}

// Exclusive keeps a local capital-moving workflow consistent with trading. Its
// prepared transaction remains journaled if the callback fails or the process dies.
// Callbacks must use Writer methods, rather than reentering Sequencer methods.
type Writer struct{ q *Sequencer }

func (q *Sequencer) Exclusive(fn func(*Writer) error) error {
	q.mu.Lock()
	defer q.mu.Unlock()
	if q.failed {
		return errors.New("sequencer fenced")
	}
	return fn(&Writer{q})
}
func (w *Writer) Snapshot() State                                       { return clone(w.q.state) }
func (w *Writer) Execute(ctx context.Context, c Command) (Event, error) { return w.q.execute(ctx, c) }
func (w *Writer) Events() []Event                                       { return clone(w.q.events) }

// At reads the committed logical clock while the writer lock is held.
func (w *Writer) At() int64 { return w.q.state.At }
