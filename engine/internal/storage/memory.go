package storage

import (
	"context"
	"encoding/json"
	"errors"
	"sync"

	"fuse/engine/internal/engine"
)

// Memory is explicitly ephemeral and used only for paper demos and tests.
type Memory struct {
	mu     sync.Mutex
	events []engine.Event
	Fail   bool
}

func (m *Memory) Load(context.Context) ([]engine.Event, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	b, _ := json.Marshal(m.events)
	var out []engine.Event
	_ = json.Unmarshal(b, &out)
	return out, nil
}
func (m *Memory) Append(_ context.Context, e engine.Event, _ engine.State) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.Fail {
		return errors.New("injected storage failure")
	}
	if e.Sequence != uint64(len(m.events)+1) {
		return errors.New("journal head mismatch")
	}
	m.events = append(m.events, e)
	return nil
}
func (*Memory) Close(context.Context) error { return nil }
