package dailyrelay

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"

	"github.com/ethereum/go-ethereum/common"
	"github.com/jackc/pgx/v5"
)

const voidSchema = `CREATE TABLE IF NOT EXISTS fuse_daily_void_proofs (
 chain_id numeric(20,0) NOT NULL, custody text NOT NULL, tx_hash text NOT NULL,
 proof_encoded bytea NOT NULL, PRIMARY KEY(chain_id,custody,tx_hash)
);
CREATE TABLE IF NOT EXISTS fuse_daily_void_rights (
 chain_id numeric(20,0) NOT NULL, custody text NOT NULL, ticket_id text NOT NULL,
 queue_tx text NOT NULL, queue_encoded bytea NOT NULL,
 completion_tx text, completion_encoded bytea,
 PRIMARY KEY(chain_id,custody,ticket_id),
 FOREIGN KEY(chain_id,custody,ticket_id) REFERENCES fuse_daily_bindings(chain_id,custody,ticket_id),
 FOREIGN KEY(chain_id,custody,queue_tx) REFERENCES fuse_daily_void_proofs(chain_id,custody,tx_hash),
 FOREIGN KEY(chain_id,custody,completion_tx) REFERENCES fuse_daily_void_proofs(chain_id,custody,tx_hash),
 CHECK((completion_tx IS NULL)=(completion_encoded IS NULL))
);`

func (s *BindingStore) CommitVoid(ctx context.Context, p VoidProof) error {
	if !p.validProof() {
		return fmt.Errorf("void receipt proof requires fresh verification")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	tx, err := s.conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(context.Background()) //nolint:errcheck
	if err = commitVoid(ctx, tx, p); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
func commitVoid(ctx context.Context, tx pgx.Tx, p VoidProof) error {
	stake, ok := new(big.Int).SetString(p.StakeUSDC, 10)
	if !p.validProof() || !ok || stake.Sign() <= 0 || stake.BitLen() > 255 || stake.String() != p.StakeUSDC || p.ChainID == 0 || p.Custody == (common.Address{}) || p.Account == (common.Address{}) || p.Ticket == (common.Hash{}) || p.Transaction == (common.Hash{}) || p.Block == 0 || p.BlockHash == (common.Hash{}) || p.CanonicalMS == 0 || p.BindingHash == (common.Hash{}) {
		return fmt.Errorf("incomplete void proof")
	}
	if (p.Kind == "queue_void" && (p.QueueTransaction != (common.Hash{}) || p.CreditUSDC != "0")) || (p.Kind == "complete_void" && (p.QueueTransaction == (common.Hash{}) || p.CreditUSDC != p.StakeUSDC)) || (p.Kind != "queue_void" && p.Kind != "complete_void") {
		return fmt.Errorf("void queue/credit identity mismatch")
	}
	raw, err := json.Marshal(p)
	if err != nil {
		return err
	}
	chain, custody, hash, ticket := fmt.Sprint(p.ChainID), p.Custody.Hex(), p.Transaction.Hex(), p.Ticket.Hex()
	if _, err = tx.Exec(ctx, `INSERT INTO fuse_daily_void_proofs VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING`, chain, custody, hash, raw); err != nil {
		return err
	}
	var stored []byte
	if err = tx.QueryRow(ctx, `SELECT proof_encoded FROM fuse_daily_void_proofs WHERE chain_id=$1 AND custody=$2 AND tx_hash=$3 FOR UPDATE`, chain, custody, hash).Scan(&stored); err != nil {
		return err
	}
	if string(stored) != string(raw) {
		return fmt.Errorf("void receipt proof cannot be replaced")
	}
	if p.Kind == "queue_void" {
		if _, err = tx.Exec(ctx, `INSERT INTO fuse_daily_void_rights(chain_id,custody,ticket_id,queue_tx,queue_encoded) VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING`, chain, custody, ticket, hash, raw); err != nil {
			return err
		}
		if err = tx.QueryRow(ctx, `SELECT queue_encoded FROM fuse_daily_void_rights WHERE chain_id=$1 AND custody=$2 AND ticket_id=$3 FOR UPDATE`, chain, custody, ticket).Scan(&stored); err != nil {
			return err
		}
		if string(stored) != string(raw) {
			return fmt.Errorf("original queued void right cannot be replaced")
		}
		return nil
	}
	var queueRaw, completeRaw []byte
	if err = tx.QueryRow(ctx, `SELECT queue_encoded,completion_encoded FROM fuse_daily_void_rights WHERE chain_id=$1 AND custody=$2 AND ticket_id=$3 FOR UPDATE`, chain, custody, ticket).Scan(&queueRaw, &completeRaw); err != nil {
		return fmt.Errorf("original queued right required before refund: %w", err)
	}
	var q VoidProof
	if err = json.Unmarshal(queueRaw, &q); err != nil {
		return err
	}
	if q.Transaction != p.QueueTransaction || q.BindingHash != p.BindingHash || q.Ticket != p.Ticket || q.Account != p.Account || q.StakeUSDC != p.StakeUSDC || q.CanonicalMS != p.CanonicalMS || !sameVoidDecision(q.Native, p.Native) {
		return fmt.Errorf("refund differs from original queued right")
	}
	if completeRaw != nil {
		if string(completeRaw) != string(raw) {
			return fmt.Errorf("void already refunded by another receipt")
		}
		return nil
	}
	_, err = tx.Exec(ctx, `UPDATE fuse_daily_void_rights SET completion_tx=$4,completion_encoded=$5 WHERE chain_id=$1 AND custody=$2 AND ticket_id=$3`, chain, custody, ticket, hash, raw)
	return err
}

func loadVoidRight(ctx context.Context, c *pgx.Conn, chain uint64, custody common.Address, ticket common.Hash) (VoidProof, *VoidProof, error) {
	var queueRaw, completeRaw []byte
	err := c.QueryRow(ctx, `SELECT queue_encoded,completion_encoded FROM fuse_daily_void_rights WHERE chain_id=$1 AND custody=$2 AND ticket_id=$3`, fmt.Sprint(chain), custody.Hex(), ticket.Hex()).Scan(&queueRaw, &completeRaw)
	var q VoidProof
	if err != nil {
		return q, nil, err
	}
	if err = json.Unmarshal(queueRaw, &q); err != nil {
		return q, nil, err
	}
	if completeRaw == nil {
		return q, nil, nil
	}
	var p VoidProof
	err = json.Unmarshal(completeRaw, &p)
	return q, &p, err
}

// VoidRight returns untrusted restored records; reverify their chain receipts
// before relying on them or committing again. Queue presence never means paid.
func (s *BindingStore) VoidRight(ctx context.Context, chain uint64, custody common.Address, ticket common.Hash) (VoidProof, *VoidProof, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return loadVoidRight(ctx, s.conn, chain, custody, ticket)
}
