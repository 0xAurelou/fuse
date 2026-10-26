package api

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"fuse/engine/internal/engine"
	"fuse/engine/internal/storage"
	"github.com/ethereum/go-ethereum/accounts"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/gorilla/websocket"
)

func setup(t *testing.T) (*Server, string, string) {
	t.Helper()
	raw, err := os.ReadFile("../../config/paper.json")
	if err != nil {
		t.Fatal(err)
	}
	var p engine.Policy
	_ = json.Unmarshal(raw, &p)
	q, err := engine.Open(context.Background(), p, &storage.Memory{})
	if err != nil {
		t.Fatal(err)
	}
	s := &Server{Q: q, Auth: NewAuth("https://paper.example"), AdminToken: strings.Repeat("a", 32), Origin: "https://paper.example"}
	key, err := crypto.GenerateKey()
	if err != nil {
		t.Fatal(err)
	}
	wallet := strings.ToLower(crypto.PubkeyToAddress(key.PublicKey).Hex())
	id, message, err := s.Auth.Challenge(wallet)
	if err != nil {
		t.Fatal(err)
	}
	sig, err := crypto.Sign(accounts.TextHash([]byte(message)), key)
	if err != nil {
		t.Fatal(err)
	}
	token, err := s.Auth.Verify(id, hex.EncodeToString(sig))
	if err != nil {
		t.Fatal(err)
	}
	return s, token, wallet
}
func request(s *Server, method, path, token, body string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	return w
}
func TestAuthAndAccountIsolation(t *testing.T) {
	s, token, wallet := setup(t)
	if got := request(s, "GET", "/v1/account", "", "").Code; got != 401 {
		t.Fatal(got)
	}
	if got := request(s, "GET", "/v1/account", token, "").Code; got != 200 {
		t.Fatal(got)
	}
	now := time.Now().UnixMilli()
	_, err := s.Q.Execute(context.Background(), engine.Command{Key: "private", Kind: "deposit", Actor: "another-wallet", ID: "private", At: now, Amount: 1_000_000})
	if err != nil {
		t.Fatal(err)
	}
	if got := request(s, "GET", "/v1/events", token, ""); strings.Contains(got.Body.String(), "another-wallet") {
		t.Fatal("private event leaked")
	}
	if got := request(s, "POST", "/v1/quotes", token, `{"actor":"`+wallet+`","amount":1}`); got.Code != 400 {
		t.Fatal("actor override allowed", got.Body.String())
	}
	request(s, "DELETE", "/v1/session", token, "")
	if got := request(s, "GET", "/v1/account", token, "").Code; got != 401 {
		t.Fatal("revoked session allowed")
	}
}
func TestWalletChallengeSingleUseAndWrongSignature(t *testing.T) {
	a := NewAuth("domain")
	key, _ := crypto.GenerateKey()
	wallet := crypto.PubkeyToAddress(key.PublicKey).Hex()
	id, message, _ := a.Challenge(wallet)
	sig, _ := crypto.Sign(accounts.TextHash([]byte(message)), key)
	token, err := a.Verify(id, hex.EncodeToString(sig))
	if err != nil || token == "" {
		t.Fatal(err)
	}
	if _, err = a.Verify(id, hex.EncodeToString(sig)); err == nil {
		t.Fatal("replayed challenge")
	}
	id, _, _ = a.Challenge(wallet)
	if _, err = a.Verify(id, hex.EncodeToString(sig)); err == nil {
		t.Fatal("old signature accepted")
	}
}
func TestWebsocketCatchupAndOrigin(t *testing.T) {
	s, token, wallet := setup(t)
	_, err := s.Q.Execute(context.Background(), engine.Command{Key: "mine", Kind: "deposit", Actor: wallet, ID: "mine", At: time.Now().UnixMilli(), Amount: 1_000_000})
	if err != nil {
		t.Fatal(err)
	}
	_, err = s.Q.Execute(context.Background(), engine.Command{Key: "ack", Kind: "ack_deposit", ID: "mine", At: time.Now().UnixMilli()})
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(s.Handler())
	defer srv.Close()
	headers := http.Header{"Authorization": []string{"Bearer " + token}, "Origin": []string{s.Origin}}
	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/v1/ws?after=0"
	conn, _, err := websocket.DefaultDialer.Dial(url, headers)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	var b batch
	if err = conn.ReadJSON(&b); err != nil {
		t.Fatal(err)
	}
	if b.Cursor != 2 || len(b.Events) != 2 {
		t.Fatal(b)
	}
	headers.Set("Origin", "https://evil.example")
	bad, resp, err := websocket.DefaultDialer.Dial(url, headers)
	if bad != nil {
		bad.Close()
	}
	if err == nil || resp.StatusCode != 403 {
		t.Fatal("cross-origin socket accepted")
	}
}

func TestHTTPPaperJourneyAndRetryReceipt(t *testing.T) {
	s, token, wallet := setup(t)
	n := 0
	admin := func(kind string, fields map[string]any) *httptest.ResponseRecorder {
		t.Helper()
		n++
		fields["kind"] = kind
		fields["key"] = fmt.Sprintf("admin/test/%d", n)
		raw, _ := json.Marshal(fields)
		return request(s, "POST", "/admin/commands", s.AdminToken, string(raw))
	}
	mustAdmin := func(kind string, fields map[string]any) {
		t.Helper()
		got := admin(kind, fields)
		if got.Code != 200 {
			t.Fatal(kind, got.Code, got.Body.String())
		}
	}
	post := func(path, key, payload string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", path, strings.NewReader(payload))
		r.Header.Set("Authorization", "Bearer "+token)
		r.Header.Set("Idempotency-Key", key)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		return w
	}
	mustAdmin("lp_fund", map[string]any{"amount": 1_000_000_000})
	mustAdmin("deposit", map[string]any{"actor": wallet, "id": "http-deposit", "amount": 100_000_000})
	mustAdmin("ack_deposit", map[string]any{"id": "http-deposit"})
	price := func(value string) {
		for _, source := range []string{"a", "b"} {
			mustAdmin("oracle", map[string]any{"source": source, "raw": map[string]any{"channel": "activeAssetCtx", "data": map[string]any{"coin": "BTC", "ctx": map[string]string{"oraclePx": value}}}})
		}
	}
	price("100000")
	quoteResponse := post("/v1/quotes", "quote", `{"amount":10000000,"multiplier":2}`)
	if quoteResponse.Code != 200 {
		t.Fatal(quoteResponse.Body.String())
	}
	var quote struct {
		Result engine.Quote `json:"result"`
	}
	_ = json.Unmarshal(quoteResponse.Body.Bytes(), &quote)
	payload := fmt.Sprintf(`{"id":%q}`, quote.Result.ID)
	first := post("/v1/stages", "enter", payload)
	if first.Code != 200 {
		t.Fatal(first.Body.String())
	}
	retry := post("/v1/stages", "enter", payload)
	if first.Body.String() != retry.Body.String() {
		t.Fatal("retry changed acceptance receipt")
	}
	price("1")
	stages := request(s, "GET", "/v1/stages", token, "")
	if !strings.Contains(stages.Body.String(), `"status":"exploded"`) {
		t.Fatal(stages.Body.String())
	}
	response := post("/v1/withdrawals", "withdraw", `{"amount":90000000}`)
	if response.Code != 200 {
		t.Fatal(response.Body.String())
	}
	var claim struct {
		Result engine.Withdrawal `json:"result"`
	}
	_ = json.Unmarshal(response.Body.Bytes(), &claim)
	if rejected := admin("paper_pay", map[string]any{"id": claim.Result.ID}); rejected.Code != 409 {
		t.Fatal("unfunded payment accepted")
	}
	mustAdmin("paper_settle", map[string]any{})
	mustAdmin("paper_pay", map[string]any{"id": claim.Result.ID})
	claims := request(s, "GET", "/v1/withdrawals", token, "")
	if !strings.Contains(claims.Body.String(), `"status":"paid"`) {
		t.Fatal(claims.Body.String())
	}
	if after := post("/v1/stages", "enter", payload); after.Body.String() != first.Body.String() {
		t.Fatal("later state changed old idempotent receipt")
	}
}

func TestIngressClockCannotRegressBehindCommittedOracle(t *testing.T) {
	s, _, _ := setup(t)
	// Model an oracle commit while an older HTTP receipt waits for serialization.
	_, err := s.Q.Execute(context.Background(), engine.Command{Key: "oracle-clock", Kind: "tick", At: 2000})
	if err != nil {
		t.Fatal(err)
	}
	s.Now = func() int64 { return 1000 }
	got := request(s, "POST", "/admin/commands", s.AdminToken, `{"key":"admin/stale-receipt","kind":"tick"}`)
	if got.Code != 200 {
		t.Fatal("stale wall-time rejected after preceding commit", got.Code, got.Body.String())
	}
	if s.Q.Snapshot().At != 2000 {
		t.Fatal("logical clock regressed")
	}
}

func TestHTTPSingleStage100xSelectionCreditAndIdempotency(t *testing.T) {
	s, token, wallet := setup(t)
	now := int64(1_000_000)
	s.Now = func() int64 { return now }
	serial := 0
	execute := func(c engine.Command) {
		t.Helper()
		serial++
		c.Key, c.At = fmt.Sprint("setup/", serial), now
		if _, err := s.Q.Execute(context.Background(), c); err != nil {
			t.Fatal(err)
		}
	}
	execute(engine.Command{Kind: "lp_fund", Amount: 11_000_000_000})
	execute(engine.Command{Kind: "deposit", ID: "d", Actor: wallet, Amount: 10_000_000})
	execute(engine.Command{Kind: "ack_deposit", ID: "d"})
	price := func() {
		for _, src := range []string{"a", "b"} {
			execute(engine.Command{Kind: "oracle", Source: src, Raw: json.RawMessage(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"100000"}}}`)})
		}
	}
	price()
	post := func(path, key, payload string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", path, strings.NewReader(payload))
		r.Header.Set("Authorization", "Bearer "+token)
		r.Header.Set("Idempotency-Key", key)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		return w
	}
	for _, payload := range []string{`{"amount":1000000}`, `{"amount":1000000,"multiplier":1}`, `{"amount":1000000,"multiplier":101}`, `{"amount":1000000,"multiplier":3}`, `{"amount":1000000,"multiplier":999}`, `{"amount":1000000,"multiplier":10001}`, `{"amount":1000000,"multiplier":100,"previous":"old"}`} {
		if got := post("/v1/quotes", "invalid", payload); got.Code != 409 {
			t.Fatal(got.Code, got.Body.String())
		}
	}
	for _, value := range []string{"2.5", "2.0", `"100"`, "1e2"} {
		if got := post("/v1/quotes", "invalid-json", `{"amount":1000000,"multiplier":`+value+`}`); got.Code != 400 {
			t.Fatal(got.Code, got.Body.String())
		}
	}
	for _, multiplier := range engine.PayoutOptions() {
		got := post("/v1/quotes", fmt.Sprint("preset/", multiplier), fmt.Sprintf(`{"amount":1000000,"multiplier":%d}`, multiplier))
		var selected struct{ Result engine.Quote }
		if err := json.Unmarshal(got.Body.Bytes(), &selected); err != nil || got.Code != 200 || selected.Result.Multiplier != multiplier || selected.Result.Payout != 1_000_000*multiplier {
			t.Fatal("preset quote failed", multiplier, got.Code, got.Body.String(), err)
		}
	}
	oracle := request(s, "GET", "/v1/oracle", token, "")
	var metadata struct{ Multipliers []int64 }
	if err := json.Unmarshal(oracle.Body.Bytes(), &metadata); err != nil || engine.Hash(metadata.Multipliers) != engine.Hash(engine.PayoutOptions()) {
		t.Fatal("oracle did not expose exact preset choices", oracle.Body.String(), err)
	}
	quote := post("/v1/quotes", "quote", `{"amount":1000000,"multiplier":100}`)
	if quote.Code != 200 {
		t.Fatal(quote.Body.String())
	}
	var q struct{ Result engine.Quote }
	json.Unmarshal(quote.Body.Bytes(), &q)
	if q.Result.Payout != 100_000_000 || q.Result.Multiplier != 100 {
		t.Fatal(q)
	}
	if changed := post("/v1/quotes", "quote", `{"amount":1000000,"multiplier":2}`); changed.Code != 409 {
		t.Fatal("changed multiplier reused an idempotency key")
	}
	payload := fmt.Sprintf(`{"id":%q}`, q.Result.ID)
	entered := post("/v1/stages", "enter", payload)
	if entered.Code != 200 {
		t.Fatal(entered.Body.String())
	}
	if retry := post("/v1/stages", "enter", payload); retry.Body.String() != entered.Body.String() {
		t.Fatal("entry retry changed receipt")
	}
	for i := 0; i < 6; i++ {
		now += 5000
		price()
	}
	a := s.Q.Snapshot().Accounts[wallet]
	if a.RunHead != "" || a.Available != 10_000_000 || a.Unfunded != 99_000_000 {
		t.Fatal("100x win was not credited automatically", a)
	}
	stages := request(s, "GET", "/v1/stages", token, "")
	if !strings.Contains(stages.Body.String(), `"multiplier":100`) || !strings.Contains(stages.Body.String(), `"status":"survived"`) {
		t.Fatal(stages.Body.String())
	}
}

func TestHTTPThreeMarketDeskUsesIndependentQuotesAndOneAccount(t *testing.T) {
	s, token, wallet := setup(t)
	now := int64(1_000_000)
	s.Now = func() int64 { return now }
	serial := 0
	execute := func(c engine.Command) {
		t.Helper()
		serial++
		c.At = now
		c.Key = fmt.Sprint("desk/setup/", serial)
		if _, err := s.Q.Execute(context.Background(), c); err != nil {
			t.Fatal(err)
		}
	}
	execute(engine.Command{Kind: "lp_fund", Amount: 1_000_000_000})
	execute(engine.Command{Kind: "deposit", Actor: wallet, ID: "desk", Amount: 100_000_000})
	execute(engine.Command{Kind: "ack_deposit", ID: "desk"})
	for asset, price := range map[string]string{"BTC": "100000", "ETH": "3000", "HYPE": "40"} {
		for _, source := range []string{"a", "b"} {
			execute(engine.Command{Kind: "oracle", Source: source, Raw: json.RawMessage(fmt.Sprintf(`{"channel":"activeAssetCtx","data":{"coin":%q,"ctx":{"oraclePx":%q}}}`, asset, price))})
		}
	}
	post := func(path, key string, payload any) *httptest.ResponseRecorder {
		raw, _ := json.Marshal(payload)
		req := httptest.NewRequest("POST", path, strings.NewReader(string(raw)))
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("Idempotency-Key", key)
		response := httptest.NewRecorder()
		s.Handler().ServeHTTP(response, req)
		return response
	}
	quotes := []engine.Quote{}
	for _, asset := range []string{"BTC", "HYPE", "ETH"} {
		response := post("/v1/quotes", "quote/"+asset, map[string]any{"asset": asset, "amount": 10_000_000, "multiplier": 10})
		if response.Code != 200 {
			t.Fatal(response.Body.String())
		}
		var quote struct{ Result engine.Quote }
		if err := json.Unmarshal(response.Body.Bytes(), &quote); err != nil {
			t.Fatal(err)
		}
		if quote.Result.Asset != asset {
			t.Fatal("incorrect market terms", quote)
		}
		quotes = append(quotes, quote.Result)
	}
	for _, quote := range quotes {
		if response := post("/v1/stages", "entry/"+quote.Asset, map[string]string{"id": quote.ID}); response.Code != 200 {
			t.Fatal(response.Body.String())
		}
	}
	if _, _, active := s.Q.Snapshot().Exposure(); active != 3 {
		t.Fatal("parallel market entries unavailable", active)
	}
	markets := request(s, "GET", "/v1/markets", "", "")
	var body struct {
		Markets []struct {
			Asset   string `json:"asset"`
			Healthy bool   `json:"healthy"`
		} `json:"markets"`
	}
	if markets.Code != 200 || json.Unmarshal(markets.Body.Bytes(), &body) != nil || len(body.Markets) != 3 {
		t.Fatal(markets.Body.String())
	}
	for _, market := range body.Markets {
		if !market.Healthy {
			t.Fatal("market should have paired feeds", market)
		}
	}
	if bad := request(s, "GET", "/v1/oracle?asset=SOL", "", ""); bad.Code != 400 {
		t.Fatal("unknown asset accepted")
	}
	stages := request(s, "GET", "/v1/stages", token, "")
	var accepted []engine.Stage
	if json.Unmarshal(stages.Body.Bytes(), &accepted) != nil || len(accepted) != 3 {
		t.Fatal(stages.Body.String())
	}
}
