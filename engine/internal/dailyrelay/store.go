package dailyrelay

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/ethereum/go-ethereum/common"
	"math/big"
	"sync"

	"github.com/jackc/pgx/v5"
)

// Bindings live alongside the existing PostgreSQL journal. Both ticket and
// accepted-stage identities are unique within a deployment. Retry cannot
// replace any original acceptance fields, including its canonical block hash.
// Readers must revalidate stored records before signing, including after restart.
const bindingSchema = `CREATE TABLE IF NOT EXISTS fuse_daily_bindings (
 chain_id numeric(20,0) NOT NULL,
 custody text NOT NULL,
 ticket_id text NOT NULL,
 stage_id text NOT NULL,
 binding_encoded bytea NOT NULL,
 PRIMARY KEY(chain_id,custody,ticket_id),
 UNIQUE(chain_id,custody,stage_id)
);
CREATE TABLE IF NOT EXISTS fuse_daily_settlements (
 chain_id numeric(20,0) NOT NULL, custody text NOT NULL, tx_hash text NOT NULL,
 proof_encoded bytea NOT NULL, PRIMARY KEY(chain_id,custody,tx_hash)
);
CREATE TABLE IF NOT EXISTS fuse_daily_settled_tickets (
 chain_id numeric(20,0) NOT NULL, custody text NOT NULL, ticket_id text NOT NULL,
 tx_hash text NOT NULL, PRIMARY KEY(chain_id,custody,ticket_id),
 FOREIGN KEY(chain_id,custody,ticket_id) REFERENCES fuse_daily_bindings(chain_id,custody,ticket_id),
 FOREIGN KEY(chain_id,custody,tx_hash) REFERENCES fuse_daily_settlements(chain_id,custody,tx_hash)
);`

type BindingStore struct {
	mu   sync.Mutex
	conn *pgx.Conn
}

func OpenBindings(ctx context.Context, url string) (*BindingStore, error) {
	c, err := pgx.Connect(ctx, url)
	if err != nil {
		return nil, err
	}
	if _, err = c.Exec(ctx, bindingSchema+voidSchema); err != nil {
		_ = c.Close(context.Background())
		return nil, err
	}
	return &BindingStore{conn: c}, nil
}
func (s *BindingStore) Close(ctx context.Context) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.conn.Close(ctx)
}

// Put stores Reader-produced identity data. PostgreSQL enforces global
// deployment uniqueness even across concurrent controllers/connections.
func (s *BindingStore) Put(ctx context.Context, b Binding) error {
	if !b.validProof() || b.ChainID == 0 || b.Custody == ([20]byte{}) || b.TicketID == ([32]byte{}) || b.StageID == "" || b.StageCommitment == ([32]byte{}) || b.TxHash == ([32]byte{}) || b.BlockHash == ([32]byte{}) || b.Generation == "" || b.ExpiryMS-b.StartMS != 30_000 {
		return fmt.Errorf("incomplete daily binding")
	}
	raw, err := json.Marshal(b)
	if err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	tx, err := s.conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(context.Background()) //nolint:errcheck
	_, err = tx.Exec(ctx, `INSERT INTO fuse_daily_bindings(chain_id,custody,ticket_id,stage_id,binding_encoded)
 VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING`, fmt.Sprint(b.ChainID), b.Custody.Hex(), b.TicketID.Hex(), b.StageID, raw)
	if err != nil {
		return err
	}
	var stored []byte
	err = tx.QueryRow(ctx, `SELECT binding_encoded FROM fuse_daily_bindings WHERE chain_id=$1 AND custody=$2 AND ticket_id=$3 FOR UPDATE`, fmt.Sprint(b.ChainID), b.Custody.Hex(), b.TicketID.Hex()).Scan(&stored)
	if err != nil {
		return fmt.Errorf("daily ticket/stage already bound to another acceptance: %w", err)
	}
	var old Binding
	if err = json.Unmarshal(stored, &old); err != nil {
		return err
	}
	if old.identityHash() != b.identityHash() {
		return fmt.Errorf("daily binding cannot be replaced")
	}
	return tx.Commit(ctx)
}
func (s *BindingStore) Get(ctx context.Context, chain uint64, custody common.Address, ticket common.Hash) (Binding, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var raw []byte
	err := s.conn.QueryRow(ctx, `SELECT binding_encoded FROM fuse_daily_bindings WHERE chain_id=$1 AND custody=$2 AND ticket_id=$3`, fmt.Sprint(chain), custody.Hex(), ticket.Hex()).Scan(&raw)
	if err != nil {
		return Binding{}, err
	}
	var b Binding
	err = json.Unmarshal(raw, &b)
	return b, err
}

// CommitSettlement is the atomic terminal transition for a receipt-verified
// batch: all ticket associations and the exact proof commit together. A retry
// is idempotent; a different receipt cannot overwrite a paid ticket.
func (s *BindingStore) CommitSettlement(ctx context.Context, p SettlementProof) error {
	if !p.validProof() {
		return fmt.Errorf("incomplete daily settlement proof")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	tx, err := s.conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(context.Background()) //nolint:errcheck
	if err = commitSettlement(ctx, tx, p); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// Shared by the binding store and outbound coordinator so payment proof and
// transport completion can commit in the same PostgreSQL transaction.
func commitSettlement(ctx context.Context, tx pgx.Tx, p SettlementProof) error {
	net, ok := new(big.Int).SetString(p.LPNetUSDC, 10)
	if !p.validProof() || !ok || net.String() != p.LPNetUSDC || net.BitLen() > 255 || p.ChainID == 0 || p.Block == 0 || p.Custody == (common.Address{}) || p.Transaction == (common.Hash{}) || p.BlockHash == (common.Hash{}) || p.Digest == (common.Hash{}) || p.JournalHash == (common.Hash{}) || len(p.Tickets) == 0 || len(p.Tickets) > 16 {
		return fmt.Errorf("incomplete daily settlement proof")
	}
	seen := map[common.Hash]bool{}
	for _, id := range p.Tickets {
		if id == (common.Hash{}) || seen[id] {
			return fmt.Errorf("duplicate daily proof ticket")
		}
		seen[id] = true
	}
	raw, err := json.Marshal(p)
	if err != nil {
		return err
	}
	chain, custody, hash := fmt.Sprint(p.ChainID), p.Custody.Hex(), p.Transaction.Hex()
	_, err = tx.Exec(ctx, `INSERT INTO fuse_daily_settlements VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING`, chain, custody, hash, raw)
	if err != nil {
		return err
	}
	var stored []byte
	if err = tx.QueryRow(ctx, `SELECT proof_encoded FROM fuse_daily_settlements WHERE chain_id=$1 AND custody=$2 AND tx_hash=$3 FOR UPDATE`, chain, custody, hash).Scan(&stored); err != nil {
		return err
	}
	if string(stored) != string(raw) {
		return fmt.Errorf("daily settlement proof cannot be replaced")
	}
	for _, id := range p.Tickets {
		_, err = tx.Exec(ctx, `INSERT INTO fuse_daily_settled_tickets VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING`, chain, custody, id.Hex(), hash)
		if err != nil {
			return err
		}
		var previous string
		if err = tx.QueryRow(ctx, `SELECT tx_hash FROM fuse_daily_settled_tickets WHERE chain_id=$1 AND custody=$2 AND ticket_id=$3 FOR UPDATE`, chain, custody, id.Hex()).Scan(&previous); err != nil {
			return err
		}
		if previous != hash {
			return fmt.Errorf("daily ticket already has another settled receipt")
		}
	}
	return nil
}

func (s *BindingStore) Settlement(ctx context.Context, chain uint64, custody common.Address, hash common.Hash) (SettlementProof, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var raw []byte
	err := s.conn.QueryRow(ctx, `SELECT proof_encoded FROM fuse_daily_settlements WHERE chain_id=$1 AND custody=$2 AND tx_hash=$3`, fmt.Sprint(chain), custody.Hex(), hash.Hex()).Scan(&raw)
	if err != nil {
		return SettlementProof{}, err
	}
	var p SettlementProof
	err = json.Unmarshal(raw, &p)
	return p, err
}
