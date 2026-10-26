package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"fuse/engine/internal/localdev"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	if len(os.Args) < 2 {
		return fmt.Errorf("usage: fuse-local deploy|serve|wallet|simulate")
	}
	flags := flag.NewFlagSet(os.Args[1], flag.ContinueOnError)
	rpcURL := flags.String("rpc", "http://127.0.0.1:8545", "loopback Anvil RPC")
	manifest := flags.String("manifest", ".local/deployment.json", "deployment manifest")
	artifacts := flags.String("artifacts", "../out", "compiled Foundry artifacts")
	config := flags.String("config", "config/local.json", "local engine policy")
	listen := flags.String("listen", "127.0.0.1:8080", "local HTTP address")
	wallet := flags.Int("wallet", localdev.Alice, "development trader index 5..304")
	action := flags.String("action", "balances", "wallet action")
	amount := flags.String("amount", "0", "integer token/USDC units, or deposit ID for refund")
	apiURL := flags.String("api", "http://127.0.0.1:8080", "local API URL for login")
	ticket := flags.String("ticket", "", "withdrawal authorization JSON")
	reward := flags.String("rewards", "", "account reward list JSON")
	initialLP := flags.Int64("lp", 1_000_000_000_000, "initial local LP in USDC atomic units")
	defaultTraders := 2
	if os.Args[1] == "simulate" {
		defaultTraders = 100
	}
	traders := flags.Int("traders", defaultTraders, "seeded local trader wallets (2..300)")
	capture := flags.Duration("capture", 0, "minimum real-time oracle capture after deposits (up to 1h)")
	cohortSize := flags.Int("cohort-size", 0, "wallets per entry cohort; zero puts all wallets in one cohort")
	cohortInterval := flags.Duration("cohort-interval", 0, "spacing between entry cohorts")
	controlEvery := flags.Int("control-every", 0, "every Nth wallet uses exact frozen fractional width; zero disables")
	output := flags.String("output", ".local/live-report", "simulation evidence directory")
	seed := flags.Int64("seed", 20261025, "reproducible strategy diversity seed")
	feed := flags.String("feed", "wss://api.hyperliquid.xyz/ws", "HyperCore WebSocket endpoint")
	epoch := flags.Uint64("epoch", 1, "reward/redemption epoch")
	if err := flags.Parse(os.Args[2:]); err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	switch os.Args[1] {
	case "simulate":
		liveCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer stop()
		return localdev.SimulateWithOptions(liveCtx, *rpcURL, *manifest, *config, os.Getenv("DATABASE_URL"), *feed, *output, *traders, *seed, localdev.SimulationOptions{CaptureDuration: *capture, CohortSize: *cohortSize, CohortInterval: *cohortInterval, ControlEvery: *controlEvery})
	case "serve":
		serviceCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer stop()
		return localdev.Serve(serviceCtx, *rpcURL, *manifest, *config, *listen, os.Getenv("DATABASE_URL"), os.Getenv("FUSE_LOCAL_ADMIN_TOKEN"))
	case "wallet":
		env, err := localdev.Load(ctx, *manifest, *rpcURL)
		if err != nil {
			return err
		}
		result, err := localdev.WalletAction(ctx, env, *wallet, *action, *amount, *apiURL, *ticket, *reward, *epoch)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(result)
	case "deploy":
		rpc, err := localdev.Connect(ctx, *rpcURL)
		if err != nil {
			return err
		}
		deployment, err := localdev.DeployWithOptions(ctx, rpc, *artifacts, *manifest, *initialLP, *traders)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"manifest": *manifest, "chain_id": deployment.ChainID, "alice": localdev.Wallet(localdev.Alice), "bob": localdev.Wallet(localdev.Bob)})
	}
	return fmt.Errorf("unknown local command")
}
