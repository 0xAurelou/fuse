package api

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/ethereum/go-ethereum/accounts"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
)

type challenge struct {
	Account string
	Message string
	Expiry  time.Time
}
type session struct {
	Account string
	Expiry  time.Time
	Scopes  map[string]bool
}
type Auth struct {
	mu         sync.Mutex
	domain     string
	mode       string
	challenges map[string]challenge
	sessions   map[string]session
}

func NewAuth(domain string) *Auth {
	return &Auth{domain: domain, mode: "paper", challenges: map[string]challenge{}, sessions: map[string]session{}}
}
func NewLocalAuth(domain string) *Auth { a := NewAuth(domain); a.mode = "local Anvil"; return a }

func randomID() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}
func address(v string) (string, error) {
	if !common.IsHexAddress(v) || common.HexToAddress(v) == (common.Address{}) {
		return "", fmt.Errorf("invalid wallet address")
	}
	return strings.ToLower(common.HexToAddress(v).Hex()), nil
}
func (a *Auth) prune(now time.Time) {
	for k, c := range a.challenges {
		if !now.Before(c.Expiry) {
			delete(a.challenges, k)
		}
	}
	for k, s := range a.sessions {
		if !now.Before(s.Expiry) {
			delete(a.sessions, k)
		}
	}
}
func (a *Auth) Challenge(account string) (string, string, error) {
	account, err := address(account)
	if err != nil {
		return "", "", err
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	a.prune(time.Now())
	if len(a.challenges) >= 10_000 {
		return "", "", fmt.Errorf("challenge capacity reached")
	}
	id := randomID()
	expiry := time.Now().Add(time.Minute)
	message := fmt.Sprintf("FUSE %s engine session\nDomain: %s\nAccount: %s\nNonce: %s\nExpires: %s\nScopes: read quote trade withdraw\nThis session authorizes %s trading only.", a.mode, a.domain, account, id, expiry.UTC().Format(time.RFC3339), a.mode)
	a.challenges[id] = challenge{account, message, expiry}
	return id, message, nil
}
func (a *Auth) Verify(id, sigHex string) (string, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	c, ok := a.challenges[id]
	delete(a.challenges, id)
	if !ok || !time.Now().Before(c.Expiry) {
		return "", fmt.Errorf("challenge expired or used")
	}
	sig, err := hex.DecodeString(strings.TrimPrefix(sigHex, "0x"))
	if err != nil || len(sig) != 65 {
		return "", fmt.Errorf("invalid signature")
	}
	if sig[64] >= 27 {
		sig[64] -= 27
	}
	if sig[64] > 1 {
		return "", fmt.Errorf("invalid recovery id")
	}
	pub, err := crypto.SigToPub(accounts.TextHash([]byte(c.Message)), sig)
	if err != nil || strings.ToLower(crypto.PubkeyToAddress(*pub).Hex()) != c.Account {
		return "", fmt.Errorf("wallet signature mismatch")
	}
	a.prune(time.Now())
	if len(a.sessions) >= 10_000 {
		return "", fmt.Errorf("session capacity reached")
	}
	token := randomID()
	a.sessions[token] = session{c.Account, time.Now().Add(30 * time.Minute), map[string]bool{"read": true, "quote": true, "trade": true, "withdraw": true}}
	return token, nil
}
func (a *Auth) Session(r *http.Request, scope string) (string, bool) {
	token := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	a.mu.Lock()
	defer a.mu.Unlock()
	s, ok := a.sessions[token]
	if !ok || !time.Now().Before(s.Expiry) || !s.Scopes[scope] {
		return "", false
	}
	return s.Account, true
}
func (a *Auth) Revoke(r *http.Request) {
	a.mu.Lock()
	defer a.mu.Unlock()
	delete(a.sessions, strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "))
}
func equalSecret(a, b string) bool {
	return len(a) > 0 && len(a) == len(b) && subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}
