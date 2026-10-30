package capture

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"
)

func awaitCancellation(t *testing.T, ctx context.Context, cause error) {
	t.Helper()
	select {
	case <-ctx.Done():
		if !errors.Is(context.Cause(ctx), cause) {
			t.Fatalf("cause: %v; want %v", context.Cause(ctx), cause)
		}
	case <-time.After(time.Second):
		t.Fatal("wall-clock cancellation did not wake collector")
	}
}

func TestWallDeadlineChecksResumeClockInsteadOfTickTimestamp(t *testing.T) {
	start := time.Now()
	deadline := start.Add(8 * time.Hour)
	var clock atomic.Int64
	clock.Store(start.UnixMilli())
	checks := make(chan time.Time)
	ctx, cancel := withWallDeadline(context.Background(), deadline,
		func() time.Time { return time.UnixMilli(clock.Load()) }, checks)
	defer cancel(nil)
	select {
	case <-ctx.Done():
		t.Fatal("cancelled before original deadline")
	default:
	}
	// Simulate sleep: wall time moves beyond the eight-hour horizon, while a
	// delayed ticker delivers a timestamp from before suspension.
	clock.Store(deadline.Add(time.Hour).UnixMilli())
	checks <- start.Add(time.Second)
	awaitCancellation(t, ctx, context.DeadlineExceeded)
}

func TestWallDeadlineAlreadyElapsedAndParentCancellation(t *testing.T) {
	now := time.UnixMilli(1000)
	for _, deadline := range []time.Time{now, now.Add(-time.Millisecond)} {
		ctx, cancel := withWallDeadline(context.Background(), deadline, func() time.Time { return now }, nil)
		awaitCancellation(t, ctx, context.DeadlineExceeded)
		cancel(nil)
	}
	parent, stop := context.WithCancel(context.Background())
	ctx, cancel := withWallDeadline(parent, now.Add(time.Hour), func() time.Time { return now }, nil)
	defer cancel(nil)
	stop()
	awaitCancellation(t, ctx, context.Canceled)
}

func TestDeadlineCrossingAtAppendPreservesOriginalChain(t *testing.T) {
	dir := t.TempDir()
	r, _ := openTest(t, dir)
	if err := r.Append("a", price); err != nil {
		t.Fatal(err)
	}
	head := r.Head()
	deadline := r.Deadline()
	for _, at := range []time.Time{deadline, deadline.Add(16 * time.Hour)} {
		r.now = func() time.Time { return at }
		if err := r.Append("b", price); !errors.Is(err, ErrDeadlineElapsed) {
			t.Fatalf("deadline crossing was not a normal horizon stop: %v", err)
		}
		if r.Head().Hash != head.Hash || r.Head().Sequence != head.Sequence {
			t.Fatal("late receipt changed evidence")
		}
	}
	r.Close()
	m, verified, err := Verify(dir)
	if err != nil || verified.Hash != head.Hash || m.FrozenAt+m.DurationMS != deadline.UnixMilli() {
		t.Fatalf("original horizon or retained chain changed: %v", err)
	}
}
