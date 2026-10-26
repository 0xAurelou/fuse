package localdev

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"time"

	"fuse/engine/internal/api"
	"fuse/engine/internal/engine"
	"fuse/engine/internal/storage"
)

func Serve(ctx context.Context, endpoint, manifest, config, listen, database, token string) error {
	host, _, err := net.SplitHostPort(listen)
	ip := net.ParseIP(host)
	if err != nil || ip == nil || !ip.IsLoopback() {
		return fmt.Errorf("local backend must bind a literal loopback address")
	}
	if len(token) < 32 {
		return fmt.Errorf("FUSE_LOCAL_ADMIN_TOKEN requires at least 32 characters")
	}
	if database == "" {
		return fmt.Errorf("DATABASE_URL required for durable local execution")
	}
	env, err := Load(ctx, manifest, endpoint)
	if err != nil {
		return err
	}
	raw, err := os.ReadFile(config)
	if err != nil {
		return err
	}
	var policy engine.Policy
	if err = json.Unmarshal(raw, &policy); err != nil {
		return err
	}
	if policy.Mode != "local" {
		return fmt.Errorf("local policy required")
	}
	db, err := storage.OpenPostgres(ctx, database)
	if err != nil {
		return err
	}
	defer db.Close(context.Background())
	q, err := engine.Open(ctx, policy, db)
	if err != nil {
		return err
	}
	controller, err := NewController(ctx, env, q)
	if err != nil {
		return err
	}
	if err = controller.Sync(ctx); err != nil {
		return err
	}
	if err = controller.Heartbeat(ctx); err != nil {
		return err
	}
	origin := "http://" + listen
	base := &api.Server{Q: q, Auth: api.NewLocalAuth(origin), AdminToken: token, Origin: origin, Now: controller.Now}
	server := &http.Server{Addr: listen, Handler: controller.Handler(base), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
	workerCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	done := make(chan struct{})
	go func() {
		defer close(done)
		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-workerCtx.Done():
				return
			case <-ticker.C:
				operationCtx, stop := context.WithTimeout(workerCtx, 10*time.Second)
				err := controller.Sync(operationCtx)
				if err == nil {
					err = controller.Heartbeat(operationCtx)
				}
				stop()
				if err != nil && workerCtx.Err() == nil {
					slog.Error("local worker reconciliation failed", "error", err)
				}
			}
		}
	}()
	errorsCh := make(chan error, 1)
	go func() {
		slog.Info("local contract backend listening", "address", listen, "chain_id", ChainID)
		errorsCh <- server.ListenAndServe()
	}()
	select {
	case <-ctx.Done():
	case err = <-errorsCh:
	}
	cancel()
	shutdown, stop := context.WithTimeout(context.Background(), 10*time.Second)
	defer stop()
	_ = server.Shutdown(shutdown)
	<-done
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}
