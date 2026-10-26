package localdev

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/accounts"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/crypto"
)

func Login(ctx context.Context, apiURL string, wallet int) (string, error) {
	u, err := url.Parse(apiURL)
	if err != nil || u.Scheme != "http" || u.User != nil {
		return "", fmt.Errorf("local API URL required")
	}
	ip := net.ParseIP(u.Hostname())
	if ip == nil || !ip.IsLoopback() {
		return "", fmt.Errorf("API must be a literal loopback address")
	}
	client := &http.Client{Timeout: 10 * time.Second, Transport: &http.Transport{Proxy: nil}, CheckRedirect: func(*http.Request, []*http.Request) error { return fmt.Errorf("redirect refused") }}
	post := func(path string, payload, out any) error {
		raw, _ := json.Marshal(payload)
		req, err := http.NewRequestWithContext(ctx, "POST", strings.TrimSuffix(apiURL, "/")+path, bytes.NewReader(raw))
		if err != nil {
			return err
		}
		req.Header.Set("Content-Type", "application/json")
		res, err := client.Do(req)
		if err != nil {
			return err
		}
		defer res.Body.Close()
		if res.StatusCode != 200 {
			b, _ := io.ReadAll(io.LimitReader(res.Body, 4096))
			return fmt.Errorf("API status %d: %s", res.StatusCode, b)
		}
		return json.NewDecoder(res.Body).Decode(out)
	}
	var challenge struct{ ID, Message string }
	if err = post("/v1/auth/challenge", map[string]any{"account": Wallet(wallet)}, &challenge); err != nil {
		return "", err
	}
	key, err := DevKey(wallet)
	if err != nil {
		return "", err
	}
	sig, err := crypto.Sign(accounts.TextHash([]byte(challenge.Message)), key)
	if err != nil {
		return "", err
	}
	var session struct{ Token string }
	if err = post("/v1/auth/verify", map[string]string{"id": challenge.ID, "signature": hexutil.Encode(sig)}, &session); err != nil {
		return "", err
	}
	return session.Token, nil
}
func WalletAction(ctx context.Context, env *Environment, wallet int, action, amountText, apiURL, ticketPath, rewardPath string, epoch uint64) (any, error) {
	if wallet < Alice || wallet >= Alice+MaxLocalTraders {
		return nil, fmt.Errorf("wallet actions use local traders 5 through 104")
	}
	amount, ok := new(big.Int).SetString(amountText, 10)
	if !ok || amount.Sign() < 0 || amount.BitLen() > 256 {
		return nil, fmt.Errorf("invalid integer amount")
	}
	switch action {
	case "login":
		token, err := Login(ctx, apiURL, wallet)
		return map[string]string{"token": token}, err
	case "balances":
		usdc, err := env.Uint(ctx, "USDC", "balanceOf", 0, Wallet(wallet))
		if err != nil {
			return nil, err
		}
		fuse, err := env.Uint(ctx, "FUSEToken", "balanceOf", 0, Wallet(wallet))
		return map[string]any{"account": Wallet(wallet), "usdc": usdc.String(), "fuse": fuse.String()}, err
	case "deposit":
		if amount.Sign() == 0 {
			return nil, fmt.Errorf("positive USDC base units required")
		}
		if err := env.Direct(ctx, wallet, "CustomerCustodyVault", "deposit", amount, Wallet(wallet)); err != nil {
			return nil, err
		}
	case "refund":
		if amount.Sign() == 0 {
			return nil, fmt.Errorf("deposit ID required in -amount")
		}
		if err := env.Direct(ctx, wallet, "CustomerCustodyVault", "refundUncreditedDeposit", amount); err != nil {
			return nil, err
		}
	case "claim-withdrawal":
		raw, err := os.ReadFile(ticketPath)
		if err != nil {
			return nil, err
		}
		var ticket engine.LocalTicket
		if err = json.Unmarshal(raw, &ticket); err != nil {
			return nil, err
		}
		if ticket.Account != strings.ToLower(Wallet(wallet).Hex()) {
			return nil, fmt.Errorf("ticket belongs to another account")
		}
		if err = env.ClaimWithdrawal(ctx, wallet, ticket); err != nil {
			return nil, err
		}
	case "claim-reward":
		raw, err := os.ReadFile(rewardPath)
		if err != nil {
			return nil, err
		}
		var records []engine.LocalReward
		if err = json.Unmarshal(raw, &records); err != nil {
			return nil, err
		}
		found := false
		for _, record := range records {
			if record.Epoch != epoch {
				continue
			}
			for _, allocation := range record.Allocations {
				if allocation.Account != strings.ToLower(Wallet(wallet).Hex()) {
					continue
				}
				n, ok := new(big.Int).SetString(allocation.Amount, 10)
				if !ok {
					return nil, fmt.Errorf("invalid allocation")
				}
				proof := []common.Hash{}
				for _, hash := range allocation.Proof {
					proof = append(proof, common.HexToHash(hash))
				}
				if err = env.Direct(ctx, wallet, "RewardDistributor", "claim", epoch, new(big.Int).SetUint64(allocation.Index), Wallet(wallet), n, proof); err != nil {
					return nil, err
				}
				found = true
			}
		}
		if !found {
			return nil, fmt.Errorf("allocation not found")
		}
	case "redeem":
		if amount.Sign() == 0 {
			return nil, fmt.Errorf("positive FUSE base units required")
		}
		if err := env.Direct(ctx, wallet, "FUSEToken", "approve", env.Address("RedemptionReserve"), amount); err != nil {
			return nil, err
		}
		if err := env.Direct(ctx, wallet, "RedemptionReserve", "requestRedeem", amount); err != nil {
			return nil, err
		}
	case "claim-redemption":
		if err := env.Direct(ctx, wallet, "RedemptionReserve", "claimRedeemedUSDC", epoch); err != nil {
			return nil, err
		}
	default:
		return nil, fmt.Errorf("unknown wallet action")
	}
	if err := env.RPC.Mine(ctx, env.Deployment.Confirmations); err != nil {
		return nil, err
	}
	return map[string]any{"account": Wallet(wallet), "action": action, "confirmed": true}, nil
}
