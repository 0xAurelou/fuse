// Package oracle collects redundant HyperCore BTC oraclePx messages. It never
// adjudicates outcomes or writes balances; the sequencer does both atomically.
package oracle

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"fuse/engine/internal/engine"
	"github.com/gorilla/websocket"
)

type Collector struct {
	Assets    []string
	URL       string
	Sequencer *engine.Sequencer
	Log       *slog.Logger
	// Observe records validated market evidence; BBO never enters settlement.
	Observe func(source, channel string, raw json.RawMessage)
	Submit  func(context.Context, string, json.RawMessage) error
}

func (c Collector) Run(ctx context.Context) {
	done := make(chan struct{}, 2)
	for _, source := range []string{"a", "b"} {
		go func(source string) { defer func() { done <- struct{}{} }(); c.receiver(ctx, source) }(source)
	}
	<-done
	<-done
}
func (c Collector) receiver(ctx context.Context, source string) {
	backoff := time.Second
	for ctx.Err() == nil {
		err := c.connect(ctx, source)
		if ctx.Err() != nil {
			return
		}
		c.Log.Warn("oracle receiver reconnecting", "source", source, "error", err)
		timer := time.NewTimer(backoff)
		select {
		case <-ctx.Done():
			timer.Stop()
			return
		case <-timer.C:
		}
		if backoff < 16*time.Second {
			backoff *= 2
		}
	}
}
func (c Collector) connect(ctx context.Context, source string) error {
	dialer := *websocket.DefaultDialer
	dialer.HandshakeTimeout = 10 * time.Second
	conn, _, err := dialer.DialContext(ctx, c.URL, nil)
	if err != nil {
		return err
	}
	defer conn.Close()
	conn.SetReadLimit(1 << 20)
	assets := c.Assets
	if len(assets) == 0 {
		assets = []string{"BTC"}
	}
	enabled := map[string]bool{}
	for _, asset := range assets {
		if !engine.SupportedAsset(asset) || enabled[asset] {
			return fmt.Errorf("invalid or duplicate oracle asset")
		}
		enabled[asset] = true
		if err = conn.WriteJSON(map[string]any{"method": "subscribe", "subscription": map[string]string{"type": "activeAssetCtx", "coin": asset}}); err != nil {
			return err
		}
	}

	if c.Observe != nil && source == "a" {
		if err = conn.WriteJSON(map[string]any{"method": "subscribe", "subscription": map[string]string{"type": "bbo", "coin": "BTC"}}); err != nil {
			return err
		}
	}
	child, cancel := context.WithCancel(ctx)
	defer cancel()
	go func() {
		ticker := time.NewTicker(20 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-child.Done():
				_ = conn.Close()
				return
			case <-ticker.C:
				_ = conn.SetWriteDeadline(time.Now().Add(5 * time.Second))
				if err := conn.WriteJSON(map[string]string{"method": "ping"}); err != nil {
					_ = conn.Close()
					return
				}
			}
		}
	}()
	for {
		_ = conn.SetReadDeadline(time.Now().Add(45 * time.Second))
		_, raw, err := conn.ReadMessage()
		if err != nil {
			return err
		}
		var envelope struct {
			Channel string `json:"channel"`
		}
		if json.Unmarshal(raw, &envelope) != nil {
			return fmt.Errorf("invalid oracle message")
		}
		if envelope.Channel == "bbo" && c.Observe != nil {
			if _, err := ParseBBO(raw); err != nil {
				return err
			}
			c.Observe(source, envelope.Channel, raw)
		}
		if envelope.Channel != "activeAssetCtx" {
			continue
		}
		asset, _, parseErr := engine.ParseAssetOracle(raw)
		if parseErr != nil {
			return parseErr
		}
		if !enabled[asset] {
			return fmt.Errorf("unsubscribed oracle asset")
		}
		if c.Observe != nil {
			c.Observe(source, envelope.Channel, raw)
		}
		if c.Submit != nil {
			if err := c.Submit(ctx, source, raw); err != nil {
				return err
			}
			continue
		}
		// Millisecond receipt ordering is serialized by the sequencer. A competing
		// command may have advanced the clock; retry with its current logical time.
		for tries := 0; tries < 3; tries++ {
			now := time.Now().UnixMilli()
			if latest := c.Sequencer.Snapshot().At; now < latest {
				now = latest
			}
			cmd := engine.Command{Key: fmt.Sprintf("oracle/%s/%d/%s", source, time.Now().UnixNano(), engine.Hash(json.RawMessage(raw))), Kind: "oracle", Source: source, At: now, Raw: json.RawMessage(raw)}
			_, err = c.Sequencer.Execute(ctx, cmd)
			if err == nil {
				break
			}
			if !c.Sequencer.Ready() {
				return err
			}
		}
		if err != nil {
			return err
		}
	}
}
