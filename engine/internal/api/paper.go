package api

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/crypto"
)

const PaperStartingBalance int64 = 1_000_000_000

// A browser-generated secret resumes the same virtual account. Neither the
// secret nor its bearer token is journaled. These sessions cannot withdraw.
func (a *Auth) paperSession(secret string) (string, string, error) {
	decoded, err := hex.DecodeString(secret)
	if err != nil || len(decoded) != 32 || secret != strings.ToLower(secret) || a.mode != "paper" {
		return "", "", fmt.Errorf("a 32-byte paper account secret is required")
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	a.prune(time.Now())
	token := crypto.Keccak256Hash([]byte("fuse/paper/session/" + a.domain + secret)).Hex()
	account := strings.ToLower(crypto.Keccak256Hash([]byte("fuse/paper/account/" + a.domain + secret)).Hex()[26:])
	account = "0x" + account
	if _, exists := a.sessions[token]; !exists && len(a.sessions) >= 10_000 {
		return "", "", fmt.Errorf("paper session capacity reached")
	}
	a.sessions[token] = session{account, time.Now().Add(24 * time.Hour), map[string]bool{"read": true, "quote": true, "trade": true, "paper": true}}
	return token, account, nil
}

func (s *Server) paperEnabled(w http.ResponseWriter) bool {
	if !s.PaperDesk || s.Q.Snapshot().Policy.Mode != "paper" {
		fail(w, 404, fmt.Errorf("paper desk is disabled"))
		return false
	}
	return true
}

func (s *Server) paperSession(w http.ResponseWriter, r *http.Request) {
	if !s.paperEnabled(w) {
		return
	}
	var input struct {
		Secret string `json:"secret"`
	}
	if err := body(w, r, &input); err != nil {
		fail(w, 400, err)
		return
	}
	token, account, err := s.Auth.paperSession(input.Secret)
	if err != nil {
		fail(w, 400, err)
		return
	}
	err = s.Q.Exclusive(func(writer *engine.Writer) error {
		id := "paper/faucet/" + account
		for _, command := range []engine.Command{
			{Key: id, Kind: "deposit", ID: id, Actor: account, Amount: PaperStartingBalance},
			{Key: id + "/ack", Kind: "ack_deposit", ID: id},
		} {
			command.At = max(s.now(), writer.At())
			if _, err := writer.Execute(r.Context(), command); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		fail(w, 503, err)
		return
	}
	write(w, 200, map[string]any{"token": token, "wallet": account, "starting_balance": PaperStartingBalance, "expires_in": 86400, "mode": "paper"})
}

// Quote and acceptance share one sequencer lock. Price updates cannot slip
// between them. Retries reuse both journal keys and the original receipt.
func (s *Server) paperEntry(w http.ResponseWriter, r *http.Request) {
	if !s.paperEnabled(w) {
		return
	}
	account, ok := s.authenticated(w, r, "paper")
	if !ok {
		return
	}
	var input struct {
		Asset      string `json:"asset"`
		Amount     int64  `json:"amount"`
		Multiplier int64  `json:"multiplier"`
	}
	if err := body(w, r, &input); err != nil {
		fail(w, 400, err)
		return
	}
	key := r.Header.Get("Idempotency-Key")
	if key == "" || len(key) > 100 {
		fail(w, 400, fmt.Errorf("Idempotency-Key required (max 100 bytes)"))
		return
	}
	var receipt engine.Event
	err := s.Q.Exclusive(func(writer *engine.Writer) error {
		quoted, err := writer.Execute(r.Context(), engine.Command{Key: account + "/paper/" + key + "/quote", Kind: "quote", Actor: account, Asset: input.Asset, Amount: input.Amount, Multiplier: input.Multiplier, At: max(s.now(), writer.At())})
		if err != nil {
			return err
		}
		var quote engine.Quote
		if err := json.Unmarshal(quoted.Result, &quote); err != nil {
			return err
		}
		receipt, err = writer.Execute(r.Context(), engine.Command{Key: account + "/paper/" + key + "/enter", Kind: "enter", Actor: account, ID: quote.ID, At: max(s.now(), writer.At())})
		return err
	})
	if err != nil {
		status := 503
		if errors.Is(err, engine.ErrRejected) {
			status = 409
		}
		fail(w, status, err)
		return
	}
	write(w, 200, map[string]any{"sequence": receipt.Sequence, "state_version": receipt.Sequence, "journal_hash": receipt.Hash, "result": receipt.Result})
}
