package capture

import (
	"context"
	"time"
)

// WithWallDeadline checks the original UTC deadline on every wakeup. A single
// context timer can run late on systems whose monotonic clock pauses in sleep.
// No goroutine can run while the host is suspended; the next check cancels even
// if the monotonic duration has not elapsed. Callers must still gate each append.
func WithWallDeadline(parent context.Context, deadline time.Time) (context.Context, context.CancelCauseFunc) {
	ticker := time.NewTicker(time.Second)
	ctx, cancel := withWallDeadline(parent, deadline, time.Now, ticker.C)
	go func() {
		<-ctx.Done()
		ticker.Stop()
	}()
	return ctx, cancel
}

func withWallDeadline(parent context.Context, deadline time.Time, now func() time.Time, checks <-chan time.Time) (context.Context, context.CancelCauseFunc) {
	ctx, cancel := context.WithCancelCause(parent)
	// Strip monotonic readings on both sides, including in injected clocks.
	elapsed := func() bool { return !now().Round(0).Before(deadline.Round(0)) }
	if elapsed() {
		cancel(context.DeadlineExceeded)
		return ctx, cancel
	}
	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case <-checks:
				if elapsed() {
					cancel(context.DeadlineExceeded)
					return
				}
			}
		}
	}()
	return ctx, cancel
}
