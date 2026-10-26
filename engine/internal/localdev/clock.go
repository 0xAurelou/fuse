package localdev

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"fuse/engine/internal/engine"
)

// ObservePrice feeds a deterministic local fixture through the same canonical
// oracle reducer. It is explicit test data, never a HyperCore price assertion.
func (c *Controller) ObservePrice(ctx context.Context, price string) error {
	return c.ObserveAssetPrice(ctx, "BTC", price)
}
func (c *Controller) ObserveAssetPrice(ctx context.Context, asset, price string) error {
	asset = engine.AssetName(asset)
	return c.Q.Exclusive(func(w *engine.Writer) error { return c.observeAsset(ctx, w, asset, price) })
}
func (c *Controller) observeAsset(ctx context.Context, w *engine.Writer, asset, price string) error {
	if !w.Snapshot().Policy.HasAsset(asset) {
		return fmt.Errorf("market is not enabled: %s", asset)
	}
	if _, err := engine.ParsePrice(price); err != nil {
		return err
	}
	for _, source := range []string{"a", "b"} {
		s := w.Snapshot()
		now := max(c.Now(), s.At)
		raw, _ := json.Marshal(map[string]any{"channel": "activeAssetCtx", "data": map[string]any{"coin": asset, "ctx": map[string]string{"oraclePx": price}}})
		if _, err := w.Execute(ctx, engine.Command{Key: fmt.Sprintf("local/oracle/%s/%d", source, s.Sequence+1), Kind: "oracle", At: now, Source: source, Raw: raw}); err != nil {
			return err
		}
	}
	if asset == "BTC" {
		c.price.Store(price)
	}
	return nil
}

// Keep each enabled local fixture alive independently. These constants are
// explicit test prices; the live collector never calls this helper.
func (c *Controller) observeMarkets(ctx context.Context, w *engine.Writer, btc string) error {
	for _, asset := range w.Snapshot().Policy.Assets() {
		price := btc
		if asset != "BTC" {
			price = map[string]string{"ETH": "3000", "HYPE": "40"}[asset]
			if p := w.Snapshot().AssetOracle(asset).Price; p > 0 {
				price = fmt.Sprintf("%d.%06d", p/1_000_000, p%1_000_000)
			}
		}
		if err := c.observeAsset(ctx, w, asset, price); err != nil {
			return err
		}
	}
	return nil
}

func (c *Controller) Heartbeat(ctx context.Context) error {
	return c.Q.Exclusive(func(w *engine.Writer) error { return c.observeMarkets(ctx, w, c.price.Load().(string)) })
}

// Advance explicitly simulates paired observations at bounded intervals while
// advancing both the local chain and the persisted engine clock. Real stage
// duration stays 30 seconds; tests simply control their local clock.
func (c *Controller) Advance(ctx context.Context, seconds uint64, price string) error {
	if seconds == 0 || seconds > 3600 {
		return fmt.Errorf("advance must be 1..3600 seconds")
	}
	if _, err := engine.ParsePrice(price); err != nil {
		return err
	}
	requested := seconds
	return c.Q.Exclusive(func(w *engine.Writer) error {
		if err := c.sync(ctx, w); err != nil {
			return err
		}
		for seconds > 0 {
			step := min(seconds, uint64(5))
			s := w.Snapshot()
			offset := s.Local.ClockOffsetMS + int64(step)*1000
			now := time.Now().UnixMilli() + offset
			if _, err := w.Execute(ctx, engine.Command{Key: fmt.Sprintf("local/clock/%d", s.Sequence+1), Kind: "local_clock", At: max(now, s.At), Amount: offset}); err != nil {
				return err
			}
			c.offset.Store(offset)
			if err := c.observeMarkets(ctx, w, price); err != nil {
				return err
			}
			seconds -= step
		}
		return c.Env.RPC.Advance(ctx, requested)
	})
}
