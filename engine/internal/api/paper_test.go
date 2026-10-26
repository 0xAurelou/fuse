package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"strings"
	"testing"

	"fuse/engine/internal/engine"
	"fuse/engine/internal/storage"
)

func TestPaperSessionGrantsOneVirtualBalanceAndCannotWithdraw(t *testing.T) {
	s, walletToken, _ := setup(t)
	secret := strings.Repeat("ab", 32)
	body := `{"secret":"` + secret + `"}`
	if got := request(s, "POST", "/v1/paper/session", "", body); got.Code != 404 {
		t.Fatal("paper faucet enabled by default", got.Body.String())
	}
	s.PaperDesk = true
	var session struct{ Token, Wallet string }
	first := request(s, "POST", "/v1/paper/session", "", body)
	if first.Code != 200 || json.Unmarshal(first.Body.Bytes(), &session) != nil {
		t.Fatal(first.Body.String())
	}
	sequence := s.Q.Snapshot().Sequence
	second := request(s, "POST", "/v1/paper/session", "", body)
	if !bytes.Equal(first.Body.Bytes(), second.Body.Bytes()) || s.Q.Snapshot().Sequence != sequence || s.Q.Snapshot().Accounts[session.Wallet].Available != PaperStartingBalance {
		t.Fatal("resume minted another balance")
	}
	if got := request(s, "POST", "/v1/withdrawals", session.Token, `{"amount":1000000}`); got.Code != 401 {
		t.Fatal("paper session acquired withdrawal rights")
	}
	if got := request(s, "POST", "/v1/paper/entries", walletToken, `{}`); got.Code != 401 {
		t.Fatal("wallet session gained paper entry rights")
	}
	if got := request(s, "POST", "/v1/paper/session", "", `{"secret":"x"}`); got.Code != 400 {
		t.Fatal("weak secret allowed")
	}
	if got := request(s, "POST", "/v1/paper/session", "", strings.TrimSuffix(body, "}")+`,"amount":999999999}`); got.Code != 400 {
		t.Fatal("custom faucet amount allowed")
	}
	policy := s.Q.Snapshot().Policy
	policy.Mode = "local"
	// The runtime gate remains closed even if an operator accidentally enables the UI.
	s.Q, _ = engine.Open(context.Background(), policy, &storage.Memory{})
	if got := request(s, "POST", "/v1/paper/session", "", body); got.Code != 404 {
		t.Fatal("local-contract mode allowed anonymous virtual funding")
	}
}

func TestPaperEntriesUseLivePerAssetOracleAndRetryTheSameReceipt(t *testing.T) {
	s, _, _ := setup(t)
	s.PaperDesk = true
	var session struct{ Token, Wallet string }
	got := request(s, "POST", "/v1/paper/session", "", `{"secret":"`+strings.Repeat("cd", 32)+`"}`)
	if got.Code != 200 || json.Unmarshal(got.Body.Bytes(), &session) != nil {
		t.Fatal(got.Body.String())
	}
	exec := func(c engine.Command) {
		t.Helper()
		if _, err := s.execute(context.Background(), c); err != nil {
			t.Fatal(err)
		}
	}
	exec(engine.Command{Key: "lp", Kind: "lp_fund", Amount: 1_000_000_000_000})
	for _, asset := range []string{"BTC", "HYPE", "ETH"} {
		price := map[string]string{"BTC": "100000", "ETH": "3000", "HYPE": "40"}[asset]
		for _, source := range []string{"a", "b"} {
			exec(engine.Command{Key: asset + source, Kind: "oracle", Source: source, Raw: json.RawMessage(fmt.Sprintf(`{"channel":"activeAssetCtx","data":{"coin":%q,"ctx":{"oraclePx":%q}}}`, asset, price))})
		}
		payload := fmt.Sprintf(`{"asset":%q,"amount":10000000,"multiplier":25}`, asset)
		entry := func(body string) *httptest.ResponseRecorder {
			r := httptest.NewRequest("POST", "/v1/paper/entries", strings.NewReader(body))
			r.Header.Set("Authorization", "Bearer "+session.Token)
			r.Header.Set("Idempotency-Key", asset+"/entry")
			w := httptest.NewRecorder()
			s.Handler().ServeHTTP(w, r)
			return w
		}
		first := entry(payload)
		if first.Code != 200 {
			t.Fatal(first.Body.String())
		}
		sequence := s.Q.Snapshot().Sequence
		if retry := entry(payload); retry.Code != 200 || !bytes.Equal(first.Body.Bytes(), retry.Body.Bytes()) || s.Q.Snapshot().Sequence != sequence {
			t.Fatal("entry retried with another debit", retry.Body.String())
		}
		if conflict := entry(strings.Replace(payload, "10000000", "20000000", 1)); conflict.Code != 409 {
			t.Fatal("retry changed amount")
		}
	}
	state := s.Q.Snapshot()
	_, _, active := state.Exposure()
	if active != 3 || state.Accounts[session.Wallet].Available != PaperStartingBalance-30_000_000 {
		t.Fatal("three shared-account paper stakes incorrect")
	}
}
