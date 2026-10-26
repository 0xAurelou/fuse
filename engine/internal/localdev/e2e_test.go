package localdev

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math/big"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"fuse/engine/internal/api"
	"fuse/engine/internal/engine"
	"fuse/engine/internal/storage"
	"github.com/ethereum/go-ethereum/accounts"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
)

// This test uses actual Anvil transactions, deployed compiled contracts, a real
// PostgreSQL journal, and the HTTP backend. The runner supplies isolated services.
func TestLocalContractBackendE2E(t *testing.T) {
	endpoint, manifest, database := os.Getenv("FUSE_LOCAL_E2E_RPC"), os.Getenv("FUSE_LOCAL_E2E_MANIFEST"), os.Getenv("FUSE_LOCAL_E2E_DATABASE")
	if endpoint == "" || manifest == "" || database == "" {
		t.Skip("run scripts/local-e2e.sh for isolated Anvil + PostgreSQL E2E")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	env, err := Load(ctx, manifest, endpoint)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("../../config/local.json")
	if err != nil {
		t.Fatal(err)
	}
	var policy engine.Policy
	if err = json.Unmarshal(raw, &policy); err != nil {
		t.Fatal(err)
	}
	// Synthetic local risk profile exercises enforcement without approving
	// production limits or changing the live observation-only experiment.
	policy.Recovery = &engine.RecoveryPolicy{Version: "local-e2e-recovery-v1", DailyLoss: 100_000_000,
		RollingLoss: 200_000_000, RollingMS: 7 * 86_400_000, PauseDrawdown: 15_000_000,
		HardDrawdown: 100_000_000, ResumeDrawdown: 5_000_000, CooldownMS: 2 * 86_400_000, ProbeLoss: 2_000_000}
	db, err := storage.OpenPostgres(ctx, database)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close(context.Background())
	q, err := engine.Open(ctx, policy, db)
	if err != nil {
		t.Fatal(err)
	}
	if q.Snapshot().Sequence != 0 {
		t.Fatal("E2E requires a fresh isolated database")
	}
	evidenceQ := q
	if output := os.Getenv("FUSE_LOCAL_E2E_EVIDENCE"); output != "" {
		defer func() {
			if err := os.MkdirAll(output, 0700); err != nil {
				t.Error(err)
				return
			}
			for name, value := range map[string]any{"initial-policy.json": policy, "final-state.json": evidenceQ.Snapshot(), "deployment.json": env.Deployment} {
				if err := writeEvidence(output, name, value); err != nil {
					t.Error(err)
				}
			}
			f, err := os.OpenFile(output+"/journal.jsonl", os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
			if err != nil {
				t.Error(err)
				return
			}
			defer f.Close()
			for after := uint64(0); ; {
				batch := evidenceQ.Events(after, 256)
				if len(batch) == 0 {
					break
				}
				for _, event := range batch {
					if err = json.NewEncoder(f).Encode(event); err != nil {
						t.Error(err)
						return
					}
					after = event.Sequence
				}
			}
			if err = f.Sync(); err != nil {
				t.Error(err)
			}
		}()
	}
	controller, err := NewController(ctx, env, q)
	if err != nil {
		t.Fatal(err)
	}
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	must(controller.Sync(ctx))
	must(controller.Heartbeat(ctx))
	operator := strings.Repeat("local-e2e", 8)
	base := &api.Server{Q: q, Auth: api.NewLocalAuth("http://localhost.local-e2e"), AdminToken: operator, Origin: "http://localhost.local-e2e", Now: controller.Now}
	server := httptest.NewServer(controller.Handler(base))
	defer server.Close()
	request := func(method, path, token, key string, payload any, status int) []byte {
		t.Helper()
		var body bytes.Buffer
		if payload != nil {
			must(json.NewEncoder(&body).Encode(payload))
		}
		r, err := http.NewRequestWithContext(ctx, method, server.URL+path, &body)
		must(err)
		if token != "" {
			r.Header.Set("Authorization", "Bearer "+token)
		}
		if key != "" {
			r.Header.Set("Idempotency-Key", key)
		}
		r.Header.Set("Content-Type", "application/json")
		response, err := http.DefaultClient.Do(r)
		must(err)
		defer response.Body.Close()
		var result bytes.Buffer
		_, err = result.ReadFrom(response.Body)
		must(err)
		if response.StatusCode != status {
			t.Fatalf("%s %s: got %d want %d: %s", method, path, response.StatusCode, status, result.String())
		}
		return result.Bytes()
	}
	var challenge struct{ ID, Message string }
	must(json.Unmarshal(request("POST", "/v1/auth/challenge", "", "", map[string]any{"account": Wallet(Alice)}, 200), &challenge))
	key, _ := DevKey(Alice)
	signature, err := crypto.Sign(accounts.TextHash([]byte(challenge.Message)), key)
	must(err)
	var session struct{ Token string }
	must(json.Unmarshal(request("POST", "/v1/auth/verify", "", "", map[string]string{"id": challenge.ID, "signature": "0x" + hex.EncodeToString(signature)}, 200), &session))
	account := strings.ToLower(Wallet(Alice).Hex())
	t.Log("refund safety: refundable deposits never become trading funds")
	must(env.Direct(ctx, Bob, "CustomerCustodyVault", "deposit", big.NewInt(5_000_000), Wallet(Bob)))
	must(controller.Sync(ctx))
	if q.Snapshot().Accounts[strings.ToLower(Wallet(Bob).Hex())].Available != 0 {
		t.Fatal("pending deposit credited")
	}
	must(controller.Advance(ctx, 11, "100000"))
	must(env.Direct(ctx, Bob, "CustomerCustodyVault", "refundUncreditedDeposit", big.NewInt(1)))
	must(controller.Sync(ctx))
	if q.Snapshot().Deposits["1"].Status != "refunded" {
		t.Fatal("refund not projected")
	}
	t.Log("deposit -> confirmed event -> signed acknowledgement checkpoint")
	must(env.Direct(ctx, Alice, "CustomerCustodyVault", "deposit", big.NewInt(100_000_000), Wallet(Alice)))
	must(controller.Sync(ctx))
	if q.Snapshot().Accounts[account].Available != 0 {
		t.Fatal("deposit tradable before onchain acknowledgement")
	}
	request("POST", "/v1/quotes", session.Token, "uncredited", map[string]any{"amount": 10_000_000}, 409)
	request("POST", "/local/checkpoints", operator, "deposit-checkpoint", map[string]any{}, 200)
	if q.Snapshot().Accounts[account].Available != 100_000_000 {
		t.Fatal("acknowledged funds missing")
	}
	checkpoint := q.Snapshot().Epochs[0]
	if checkpoint.Status != "onchain-confirmed" {
		t.Fatal(checkpoint)
	}
	enterMarket := func(stake int64, key, asset string) engine.Stage {
		t.Helper()
		var quoted struct{ Result engine.Quote }
		must(json.Unmarshal(request("POST", "/v1/quotes", session.Token, key+"/quote", map[string]any{"amount": stake, "multiplier": 2, "asset": asset}, 200), &quoted))
		var accepted struct{ Result engine.Stage }
		payload := map[string]string{"id": quoted.Result.ID}
		first := request("POST", "/v1/stages", session.Token, key+"/enter", payload, 200)
		must(json.Unmarshal(first, &accepted))
		retry := request("POST", "/v1/stages", session.Token, key+"/enter", payload, 200)
		if !bytes.Equal(first, retry) {
			t.Fatal("acceptance retry changed receipt")
		}
		return accepted.Result
	}
	enter := func(stake int64, key string) engine.Stage { return enterMarket(stake, key, "BTC") }
	t.Log("survival -> earned LP-backed entitlement -> funded cumulative withdrawal")
	winner := enter(10_000_000, "winner")
	request("POST", "/local/advance", operator, "", map[string]any{"seconds": 31, "price": "100000"}, 200)
	if q.Snapshot().Stages[winner.ID].Status != "survived" {
		t.Fatal(q.Snapshot().Stages[winner.ID])
	}
	request("POST", "/v1/cashout", session.Token, "winner/cashout", map[string]string{"id": winner.ID}, 409)
	var claim struct{ Result engine.Withdrawal }
	must(json.Unmarshal(request("POST", "/v1/withdrawals", session.Token, "withdraw", map[string]any{"amount": 20_000_000}, 200), &claim))
	request("POST", "/v1/withdrawals", session.Token, "overlap", map[string]any{"amount": 1}, 409)
	var ticket engine.LocalTicket
	must(json.Unmarshal(request("POST", "/v1/withdrawals/"+claim.Result.ID+"/authorization", session.Token, "", map[string]any{}, 200), &ticket))
	balanceBefore, err := env.Uint(ctx, "USDC", "balanceOf", 0, Wallet(Alice))
	must(err)
	must(env.ClaimWithdrawal(ctx, Alice, ticket))
	must(controller.Sync(ctx))
	balanceAfter, err := env.Uint(ctx, "USDC", "balanceOf", 0, Wallet(Alice))
	must(err)
	if new(big.Int).Sub(balanceAfter, balanceBefore).Int64() != 20_000_000 || q.Snapshot().Withdrawals[claim.Result.ID].Status != "paid" {
		t.Fatal("onchain payment not reconciled")
	}
	if err = env.ClaimWithdrawal(ctx, Alice, ticket); err == nil {
		t.Fatal("withdrawal paid twice")
	}
	t.Log("barrier loss -> customer-to-LP settlement -> bounded reward root and claim")
	loser := enter(20_000_000, "loser")
	request("POST", "/local/oracle", operator, "", map[string]string{"price": "101000"}, 200)
	if q.Snapshot().Stages[loser.ID].Status != "exploded" {
		t.Fatal("barrier breach missed")
	}
	request("POST", "/local/checkpoints", operator, "loss-checkpoint", map[string]any{}, 200)
	if q.Snapshot().LPProfit <= 0 {
		t.Fatal("realized LP profit missing")
	}
	rewardBudget := new(big.Int).Mul(big.NewInt(1000), big.NewInt(1e18))
	request("POST", "/local/rewards", operator, "reward-1", map[string]string{"budget": rewardBudget.String()}, 200)
	var rewardList []engine.LocalReward
	must(json.Unmarshal(request("GET", "/v1/rewards", session.Token, "", nil, 200), &rewardList))
	if len(rewardList) != 1 || len(rewardList[0].Allocations) != 1 {
		t.Fatal(rewardList)
	}
	allocation := rewardList[0].Allocations[0]
	amount, _ := new(big.Int).SetString(allocation.Amount, 10)
	proof := []common.Hash{}
	for _, hash := range allocation.Proof {
		proof = append(proof, common.HexToHash(hash))
	}
	must(env.Direct(ctx, Alice, "RewardDistributor", "claim", uint64(1), new(big.Int).SetUint64(allocation.Index), Wallet(Alice), amount, proof))
	must(controller.Sync(ctx))
	if !q.Snapshot().Local.Rewards["1"].Allocations[0].Claimed {
		t.Fatal("reward claim not indexed")
	}
	t.Log("dual-signed reserve funding -> snapshot redemption -> token burn -> USDC claim")
	request("POST", "/local/reserve", operator, "reserve-1", map[string]any{"amount": 2_000_000}, 200)
	if q.Snapshot().Reserve != 2_000_000 {
		t.Fatal("reserve transfer not projected")
	}
	request("POST", "/local/redemptions", operator, "redemption-1", map[string]any{"duration": 5, "penalty_bps": 1000}, 200)
	must(controller.Advance(ctx, 3, "100000"))
	must(env.Direct(ctx, Alice, "FUSEToken", "approve", env.Address("RedemptionReserve"), amount))
	must(env.Direct(ctx, Alice, "RedemptionReserve", "requestRedeem", amount))
	must(controller.Sync(ctx))
	record := q.Snapshot().Local.Redemptions["1/"+account]
	if record == nil || record.Accrued <= 0 {
		t.Fatal("redemption did not accrue")
	}
	must(controller.Advance(ctx, 10, "100000"))
	must(env.Direct(ctx, Alice, "RedemptionReserve", "claimRedeemedUSDC", uint64(1)))
	must(controller.Sync(ctx))
	record = q.Snapshot().Local.Redemptions["1/"+account]
	if record.Paid != record.Accrued {
		t.Fatal("redemption not reconciled")
	}
	t.Log("three simultaneous markets -> independent outcomes -> combined contract settlement")
	must(controller.Heartbeat(ctx))
	btcStage := enterMarket(1_000_000, "degen/btc", "BTC")
	ethStage := enterMarket(1_000_000, "degen/eth", "ETH")
	hypeStage := enterMarket(1_000_000, "degen/hype", "HYPE")
	request("POST", "/local/oracle", operator, "", map[string]string{"asset": "BTC", "price": "102000"}, 200)
	if q.Snapshot().Stages[btcStage.ID].Status != "exploded" || q.Snapshot().Stages[ethStage.ID].Status != "active" || q.Snapshot().Stages[hypeStage.ID].Status != "active" {
		t.Fatal("market outcomes were coupled")
	}
	must(controller.Advance(ctx, 31, "102000"))
	if q.Snapshot().Stages[ethStage.ID].Status != "survived" || q.Snapshot().Stages[hypeStage.ID].Status != "survived" {
		t.Fatal("independent market fixtures did not stay healthy")
	}
	request("POST", "/local/checkpoints", operator, "degen/checkpoint", map[string]any{}, 200)
	t.Log("confirmed tokenomics disclosures preserve full-supply backing denominator")
	var view map[string]any
	must(json.Unmarshal(request("GET", "/v1/tokenomics", "", "", nil, 200), &view))
	supplyView, err := env.Uint(ctx, "FUSEToken", "totalSupply", 0)
	must(err)
	if view["supply_fuse_units"] != supplyView.String() || view["secondary_market_bid"] != nil {
		t.Fatal("incorrect backing or invented market bid", view)
	}
	if view["free_reserve_usdc_units"].(float64) < 0 {
		t.Fatal("negative free backing")
	}

	total := new(big.Int)
	for _, address := range []common.Address{Wallet(Governance), Wallet(Alice), Wallet(Bob), env.Address("CustomerCustodyVault"), env.Address("LPVault"), env.Address("RedemptionReserve")} {
		value, err := env.Uint(ctx, "USDC", "balanceOf", 0, address)
		must(err)
		total.Add(total, value)
	}
	supply, err := env.Uint(ctx, "USDC", "totalSupply", 0)
	must(err)
	if total.Cmp(supply) != 0 {
		t.Fatal("USDC conservation mismatch", total, supply)
	}

	t.Log("signer rotation and expired tickets preserve one cumulative entitlement lock")
	var secondClaim struct{ Result engine.Withdrawal }
	must(json.Unmarshal(request("POST", "/v1/withdrawals", session.Token, "rotation/withdraw", map[string]any{"amount": 1_000_000}, 200), &secondClaim))
	var firstAuthorization engine.LocalTicket
	must(json.Unmarshal(request("POST", "/v1/withdrawals/"+secondClaim.Result.ID+"/authorization", session.Token, "", map[string]any{}, 200), &firstAuthorization))
	must(env.Direct(ctx, Governance, "AccessController", "setSigner", crypto.Keccak256Hash([]byte("WITHDRAWAL_SIGNER")), Wallet(WithdrawalSigner)))
	must(controller.Sync(ctx))
	if err = env.ClaimWithdrawal(ctx, Alice, firstAuthorization); err == nil {
		t.Fatal("rotated signature executed")
	}
	var rotatedAuthorization engine.LocalTicket
	must(json.Unmarshal(request("POST", "/v1/withdrawals/"+secondClaim.Result.ID+"/authorization", session.Token, "", map[string]any{}, 200), &rotatedAuthorization))
	if rotatedAuthorization.Cumulative != firstAuthorization.Cumulative || rotatedAuthorization.ID == firstAuthorization.ID {
		t.Fatal("rotation changed cumulative entitlement or reused authorization ID")
	}
	must(controller.Advance(ctx, 601, "100000"))
	if err = env.ClaimWithdrawal(ctx, Alice, rotatedAuthorization); err == nil {
		t.Fatal("expired signature executed")
	}
	var renewedAuthorization engine.LocalTicket
	must(json.Unmarshal(request("POST", "/v1/withdrawals/"+secondClaim.Result.ID+"/authorization", session.Token, "", map[string]any{}, 200), &renewedAuthorization))
	if renewedAuthorization.Cumulative != firstAuthorization.Cumulative || renewedAuthorization.ID == rotatedAuthorization.ID {
		t.Fatal("expiry replacement changed entitlement")
	}
	must(env.ClaimWithdrawal(ctx, Alice, renewedAuthorization))
	must(controller.Sync(ctx))
	if q.Snapshot().Accounts[account].Withdrawn != 21_000_000 {
		t.Fatal("cumulative withdrawal accounting diverged")
	}
	request("POST", "/local/reserve", operator, "reserve-1", map[string]any{"amount": 3_000_000}, 409)
	t.Log("durable prepared transaction survives restart and is broadcast once")
	controller.AfterPrepare = func() error { return errors.New("simulated crash after durable preparation") }
	_, err = controller.Settle(ctx, "crash-recovery")
	if err == nil {
		t.Fatal("crash injection failed")
	}
	before := q.Snapshot()
	pending := *before.Local.Operations["crash-recovery"]
	if pending.Status != "prepared" || before.Local.Pending != "crash-recovery" {
		t.Fatal("transaction not durably prepared")
	}
	must(db.Close(ctx))
	recoveredDB, err := storage.OpenPostgres(ctx, database)
	must(err)
	defer recoveredDB.Close(context.Background())
	recovered, err := engine.Open(ctx, policy, recoveredDB)
	must(err)
	if engine.Hash(recovered.Snapshot()) != engine.Hash(before) {
		t.Fatal("restart replay differs")
	}
	evidenceQ = recovered
	resumed, err := NewController(ctx, env, recovered)
	must(err)
	must(resumed.Sync(ctx))
	after := recovered.Snapshot()
	if after.Local.Pending != "" || after.Local.Operations["crash-recovery"].TxHash != pending.TxHash || len(after.Epochs) != len(before.Epochs)+1 {
		t.Fatal("pending settlement not recovered exactly once")
	}
	if after.LP != before.LP || after.Custody != before.Custody || after.Reserve != before.Reserve {
		t.Fatal("recovery moved value twice")
	}
	must(resumed.Sync(ctx))
	if len(recovered.Snapshot().Epochs) != len(after.Epochs) {
		t.Fatal("checkpoint replayed")
	}
	t.Log("temporary RPC interruption fences admission and recovers without permanent halt")
	previousTransport := env.RPC.client.Transport
	var injected atomic.Bool
	env.RPC.client.Transport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
		raw, err := io.ReadAll(request.Body)
		if err != nil {
			return nil, err
		}
		request.Body = io.NopCloser(bytes.NewReader(raw))
		if bytes.Contains(raw, []byte(`"method":"eth_getLogs"`)) && injected.CompareAndSwap(false, true) {
			return nil, io.EOF
		}
		return previousTransport.RoundTrip(request)
	})
	must(env.Direct(ctx, Bob, "CustomerCustodyVault", "deposit", big.NewInt(1_000_000), Wallet(Bob)))
	if err = resumed.Sync(ctx); err == nil || !transientRPC(err) || recovered.Snapshot().Local.Halted != "" || !resumed.unavailable.Load() {
		t.Fatal("temporary RPC outage permanently halted or failed to fence", err)
	}
	gate := httptest.NewRecorder()
	resumed.Handler(&api.Server{Q: recovered}).ServeHTTP(gate, httptest.NewRequest("POST", "/v1/quotes", strings.NewReader(`{}`)))
	if gate.Code != http.StatusServiceUnavailable {
		t.Fatal("offline admission remained open", gate.Code)
	}
	env.RPC.client.Transport = previousTransport
	must(resumed.Sync(ctx))
	if resumed.unavailable.Load() || recovered.Snapshot().Local.Halted != "" {
		t.Fatal("RPC recovery did not reopen reconciliation")
	}
	idleSequence := recovered.Snapshot().Sequence
	must(resumed.Sync(ctx))
	if recovered.Snapshot().Sequence != idleSequence {
		t.Fatal("idle sync generated unnecessary chain history")
	}
	after = recovered.Snapshot()

	if _, supported := env.Deployment.Modules["LPShareVault"]; supported {
		t.Log("LP shares, signed demand cap, atomic liquidity windows and reserved exit reconciliation")
		_, err = resumed.OpenLPLiquidityWindow(ctx, "lp/window/entry")
		must(err)
		must(env.Direct(ctx, Governance, "AccessController", "grantRole", crypto.Keccak256Hash([]byte("LP_PROVIDER")), Wallet(Alice)))
		must(env.Direct(ctx, Governance, "LPShareVault", "setPhase", uint8(1)))
		_, err = resumed.PublishLPCapacity(ctx, "lp/capacity", 1_000_000_000_000)
		must(err)
		_, err = resumed.PublishLPCapacity(ctx, "lp/capacity", 1_000_000_000_000)
		must(err)
		if _, err = resumed.PublishLPCapacity(ctx, "lp/capacity", 1); err == nil {
			t.Fatal("capacity idempotency key accepted different demand")
		}
		must(env.Direct(ctx, Governance, "USDC", "mint", Wallet(Alice), big.NewInt(100_000_000)))
		must(env.Direct(ctx, Alice, "USDC", "approve", env.Address("LPShareVault"), big.NewInt(100_000_000)))
		must(env.Direct(ctx, Alice, "LPShareVault", "deposit", big.NewInt(100_000_000), Wallet(Alice)))
		must(resumed.Sync(ctx))
		t.Log("external-LP profits accrue reserve fees without changing NAV when funded")
		must(env.Direct(ctx, Governance, "AccessController", "resumeTrading"))
		must(resumed.Sync(ctx))
		must(resumed.ObservePrice(ctx, "100000"))
		quoted, quoteErr := recovered.Execute(ctx, engine.Command{Kind: "quote", Key: "lp/profit/quote", Actor: account, At: resumed.Now(), Amount: 20_000_000, Multiplier: 2})
		must(quoteErr)
		var lpQuote engine.Quote
		must(json.Unmarshal(quoted.Result, &lpQuote))
		_, err = recovered.Execute(ctx, engine.Command{Kind: "enter", Key: "lp/profit/enter", Actor: account, At: resumed.Now(), ID: lpQuote.ID})
		must(err)
		must(resumed.ObservePrice(ctx, "101000"))
		_, err = resumed.Settle(ctx, "lp/profit/checkpoint")
		must(err)
		fee := recovered.Snapshot().Local.LPFeeAccrued
		if fee <= 0 {
			t.Fatal("external-LP reserve fee not reconciled")
		}
		// A future allocation pause must not erase fees already earned. The legacy
		// gross-profit estimator would incorrectly report zero available here.
		must(env.Direct(ctx, Governance, "LPVault", "setReserveAllocationBps", uint16(0)))
		equity := recovered.Snapshot().LPAvailable()
		_, err = resumed.FundReserve(ctx, "lp/profit/reserve", fee)
		must(err)
		if recovered.Snapshot().Local.LPFeeAccrued != 0 || recovered.Snapshot().LPAvailable() != equity {
			t.Fatal("fee funding changed LP equity or left a liability")
		}
		must(env.Direct(ctx, Governance, "LPVault", "setReserveAllocationBps", uint16(3500)))
		_, err = resumed.OpenLPLiquidityWindow(ctx, "lp/window/request")
		must(err)
		minted, readErr := env.Uint(ctx, "LPShareVault", "balanceOf", 0, Wallet(Alice))
		must(readErr)
		id, readErr := env.Uint(ctx, "LPShareVault", "nextRequestId", 0)
		must(readErr)
		must(env.Direct(ctx, Alice, "LPShareVault", "requestRedeem", minted, Wallet(Alice), Wallet(Alice)))
		if err = env.Direct(ctx, Governance, "LPShareVault", "fulfillRedeem", id); err == nil {
			t.Fatal("LP exit skipped 48-hour delay")
		}
		for hour := 0; hour < 48; hour++ {
			must(env.RPC.Advance(ctx, 3600))
		}
		must(env.RPC.Advance(ctx, 1))
		if err = env.Direct(ctx, Governance, "LPShareVault", "fulfillRedeem", id); err == nil {
			t.Fatal("LP exit used stale NAV")
		}
		must(env.Direct(ctx, Governance, "AccessController", "resumeTrading"))
		must(resumed.Sync(ctx))
		_, err = resumed.OpenLPLiquidityWindow(ctx, "lp/window/exit")
		must(err)
		must(env.Direct(ctx, Governance, "LPShareVault", "fulfillRedeem", id))
		must(resumed.Sync(ctx))
		if recovered.Snapshot().Local.LPExitReserved <= 0 {
			t.Fatal("backend did not reserve claimable LP capital")
		}
		if recovered.Snapshot().LPAvailable() >= recovered.Snapshot().LP {
			t.Fatal("LP claims counted as underwriting capital")
		}
		must(env.Direct(ctx, Alice, "LPShareVault", "redeem", minted, Wallet(Alice), Wallet(Alice)))
		must(resumed.Sync(ctx))
		if recovered.Snapshot().Local.LPExitReserved != 0 {
			t.Fatal("LP claim liability not cleared")
		}
		must(env.Direct(ctx, Governance, "AccessController", "resumeTrading"))
		must(resumed.Sync(ctx))
		if err = recovered.Snapshot().Check(); err != nil {
			t.Fatal(err)
		}
		after = recovered.Snapshot()
	}

	t.Log("recovery pause rejects new risk while accepted winnings remain payable")
	must(resumed.ObservePrice(ctx, "100000"))
	riskCommand := func(kind, id string, amount int64) engine.Event {
		t.Helper()
		multiplier := int64(0)
		if kind == "quote" {
			multiplier = 2
		}
		e, eerr := recovered.Execute(ctx, engine.Command{Key: "recovery/" + kind, Kind: kind, ID: id, Actor: account, Amount: amount, Multiplier: multiplier, At: max(resumed.Now(), recovered.Snapshot().At)})
		must(eerr)
		return e
	}
	var riskQuote engine.Quote
	must(json.Unmarshal(riskCommand("quote", "", 20_000_000).Result, &riskQuote))
	var riskStage engine.Stage
	must(json.Unmarshal(riskCommand("enter", riskQuote.ID, 0).Result, &riskStage))
	must(resumed.Advance(ctx, 31, "100000"))
	if recovered.Snapshot().Recovery.Mode != "paused" || recovered.Snapshot().Stages[riskStage.ID].Status != "survived" {
		t.Fatal("recovery pause missing")
	}
	if recovered.Snapshot().Accounts[account].RunHead != "" {
		t.Fatal("single-stage win was not automatically credited")
	}
	consumed := engine.Hash(recovered.Snapshot().Recovery)
	must(env.Direct(ctx, Governance, "AccessController", "resumeTrading"))
	must(resumed.Sync(ctx))
	must(env.Direct(ctx, Alice, "CustomerCustodyVault", "deposit", big.NewInt(5_000_000), Wallet(Alice)))
	must(resumed.Sync(ctx))
	_, err = resumed.Settle(ctx, "recovery/deposit")
	must(err)
	if engine.Hash(recovered.Snapshot().Recovery) != consumed {
		t.Fatal("resume or deposit reset recovery loss")
	}
	_, err = recovered.Execute(ctx, engine.Command{Key: "recovery/rejected-quote", Kind: "quote", Actor: account, Amount: 1_000_000, Multiplier: 2, At: max(resumed.Now(), recovered.Snapshot().At)})
	if err == nil || !strings.Contains(err.Error(), "recovery cooldown") {
		t.Fatal("risk pause bypassed", err)
	}
	var riskWithdrawal engine.Withdrawal
	must(json.Unmarshal(riskCommand("withdraw", "", 10_000_000).Result, &riskWithdrawal))
	riskTicket, ticketErr := resumed.Ticket(ctx, account, riskWithdrawal.ID)
	must(ticketErr)
	must(env.ClaimWithdrawal(ctx, Alice, riskTicket))
	must(resumed.Sync(ctx))
	if recovered.Snapshot().Withdrawals[riskWithdrawal.ID].Status != "paid" || recovered.Snapshot().Recovery.Mode != "paused" {
		t.Fatal("paused accepted claim did not pay")
	}
	after = recovered.Snapshot()

	t.Log("canonical receipts retain exact native execution fees for coordinated operations")
	gasDirectory := t.TempDir()
	must(writeGasEvidence(ctx, env, after, gasDirectory))
	gasJSON, gasErr := os.ReadFile(gasDirectory + "/gas-receipts.json")
	must(gasErr)
	var gas struct {
		Entries []gasReceiptEvidence `json:"entries"`
		Total   string               `json:"total_execution_fee_wei"`
	}
	must(json.Unmarshal(gasJSON, &gas))
	if len(gas.Entries) != len(after.Local.Operations) || gas.Total == "0" {
		t.Fatal("missing measured operation fees")
	}

	t.Log("finalized chain reorganization halts exposure creation without deleting claims")
	var snapshotID string
	must(env.RPC.write(ctx, "evm_snapshot", []any{}, &snapshotID))
	must(env.Direct(ctx, Bob, "CustomerCustodyVault", "deposit", big.NewInt(1_000_000), Wallet(Bob)))
	must(resumed.Sync(ctx))
	var reverted bool
	must(env.RPC.write(ctx, "evm_revert", []any{snapshotID}, &reverted))
	if !reverted {
		t.Fatal("Anvil snapshot revert failed")
	}
	if err = resumed.Sync(ctx); err == nil || recovered.Snapshot().Local.Halted == "" || !recovered.Snapshot().Paused {
		t.Fatal("finalized reorg did not halt the backend")
	}
	if _, err = recovered.Execute(ctx, engine.Command{Key: "unsafe-resume", Kind: "resume", At: resumed.Now()}); err == nil {
		t.Fatal("halt bypassed with offchain resume")
	}
	t.Logf("E2E passed: %d journal events, %d canonical chain events, %d checkpoints", after.Sequence, after.Local.ChainEvents, len(after.Epochs))
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return f(request) }
