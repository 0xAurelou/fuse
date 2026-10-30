package dailyrelay

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"sync"

	"fuse/engine/internal/contracts"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/jackc/pgx/v5"
)

var (
	ErrOutboundBusy  = errors.New("outbound payer or ticket already has unresolved work")
	ErrNonceConflict = errors.New("payer nonce changed without the recorded transaction receipt; reconciliation required")
)

// TransactionSigner signs only the supplied transaction; it must never broadcast.
// There are no keys or public-network senders in this package.
type TransactionSigner interface {
	SignTransaction(context.Context, *types.Transaction) (*types.Transaction, error)
}
type RawBroadcaster interface {
	Broadcast(context.Context, []byte) (common.Hash, error)
}

// TransactionTerms are explicit, immutable operator inputs. No fee/gas estimate
// or chain-specific limit is inferred or promoted to a production default.
type TransactionTerms struct {
	Gas    uint64   `json:"gas"`
	FeeCap *big.Int `json:"fee_cap"`
	TipCap *big.Int `json:"tip_cap"`
}

type OutboundIntent struct {
	ChainID        uint64           `json:"chain_id"`
	Payer          common.Address   `json:"payer"`
	Custody        common.Address   `json:"custody"`
	JournalHash    common.Hash      `json:"journal_hash"`
	SourceSequence uint64           `json:"source_sequence"`
	SourceState    string           `json:"source_state"`
	Generation     string           `json:"generation"`
	Action         Action           `json:"action"`
	Bindings       []Binding        `json:"bindings"`
	Terms          TransactionTerms `json:"transaction_terms"`
	Queue          *VoidProof       `json:"queued_void_proof,omitempty"`
}

func (i OutboundIntent) id() common.Hash { raw, _ := json.Marshal(i); return crypto.Keccak256Hash(raw) }

type Outbound struct {
	ID                  common.Hash        `json:"id"`
	Intent              OutboundIntent     `json:"intent"`
	State               string             `json:"state"` // planned, authorized, reserved, prepared, included, settled, queued, refunded, cancelled, reverted, abandoned
	Authorization       *Authorized        `json:"authorization,omitempty"`
	Nonce               *uint64            `json:"nonce,omitempty"`
	Unsigned            []byte             `json:"unsigned_transaction,omitempty"`
	Raw                 []byte             `json:"raw_transaction,omitempty"`
	Transaction         common.Hash        `json:"transaction,omitempty"`
	Receipt             *types.Receipt     `json:"receipt,omitempty"`
	Attempts            []OutboundAttempt  `json:"attempts,omitempty"`
	IncludedTransaction common.Hash        `json:"included_transaction,omitempty"`
	WinningAttempt      *int               `json:"winning_attempt,omitempty"` // -1 is the original transaction.
	NonceRecovery       *NonceRecovery     `json:"nonce_recovery,omitempty"`
	ExternalExecution   *ExternalExecution `json:"external_execution,omitempty"`
}

const outboundSchema = `CREATE TABLE IF NOT EXISTS fuse_daily_outbound_lanes (
 chain_id numeric(20,0) NOT NULL, payer text NOT NULL, active_id text,
 nonce_floor numeric(20,0), anchor_block bigint NOT NULL DEFAULT 0,
 anchor_hash text NOT NULL DEFAULT '', PRIMARY KEY(chain_id,payer)
);
CREATE TABLE IF NOT EXISTS fuse_daily_outbound (
 chain_id numeric(20,0) NOT NULL, payer text NOT NULL, id text NOT NULL,
 record_encoded bytea NOT NULL, PRIMARY KEY(chain_id,payer,id)
);
CREATE TABLE IF NOT EXISTS fuse_daily_outbound_claims (
 chain_id numeric(20,0) NOT NULL, custody text NOT NULL, ticket_id text NOT NULL,
 payer text NOT NULL, intent_id text NOT NULL,
 PRIMARY KEY(chain_id,custody,ticket_id)
);`

// Outbox owns a non-reconnecting PostgreSQL advisory-lock session for a dedicated
// (chain,payer) lane. One unresolved transaction blocks all later nonces. Ticket
// claims additionally prevent overlapping batches across different payers.
type Outbox struct {
	mu    sync.Mutex
	conn  *pgx.Conn
	chain uint64
	payer common.Address
}

type outboundRoleSigner struct {
	o     *Outbox
	r     *Reader
	id    common.Hash
	inner contracts.Signer
}

func (s outboundRoleSigner) SignDigest(ctx context.Context, role string, digest common.Hash) ([]byte, error) {
	l, err := s.o.guard(ctx, s.r)
	if err != nil {
		return nil, err
	}
	if l.active != s.id.Hex() || s.inner == nil {
		return nil, ErrOutboundBusy
	}
	return s.inner.SignDigest(ctx, role, digest)
}

func OpenOutbox(ctx context.Context, url string, chain uint64, payer common.Address) (*Outbox, error) {
	if chain == 0 || payer == (common.Address{}) {
		return nil, fmt.Errorf("explicit outbound chain and dedicated payer required")
	}
	c, err := pgx.Connect(ctx, url)
	if err != nil {
		return nil, err
	}
	closeOnError := func(err error) (*Outbox, error) { _ = c.Close(context.Background()); return nil, err }
	var locked bool
	if err = c.QueryRow(ctx, `SELECT pg_try_advisory_lock(hashtextextended($1,0))`, fmt.Sprintf("fuse/daily/outbound/%d/%s", chain, payer.Hex())).Scan(&locked); err != nil {
		return closeOnError(err)
	}
	if !locked {
		return closeOnError(ErrOutboundBusy)
	}
	if _, err = c.Exec(ctx, bindingSchema+voidSchema+outboundSchema); err != nil {
		return closeOnError(err)
	}
	if _, err = c.Exec(ctx, `INSERT INTO fuse_daily_outbound_lanes(chain_id,payer) VALUES($1,$2) ON CONFLICT DO NOTHING`, fmt.Sprint(chain), payer.Hex()); err != nil {
		return closeOnError(err)
	}
	return &Outbox{conn: c, chain: chain, payer: payer}, nil
}
func (o *Outbox) Close(ctx context.Context) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	return o.conn.Close(ctx)
}

type outboundLane struct {
	active, floor string
	block         uint64
	hash          string
}

func (o *Outbox) lane(ctx context.Context) (outboundLane, error) {
	var l outboundLane
	err := o.conn.QueryRow(ctx, `SELECT COALESCE(active_id,''),COALESCE(nonce_floor::text,''),anchor_block,anchor_hash FROM fuse_daily_outbound_lanes WHERE chain_id=$1 AND payer=$2`, fmt.Sprint(o.chain), o.payer.Hex()).Scan(&l.active, &l.floor, &l.block, &l.hash)
	return l, err
}
func (o *Outbox) guard(ctx context.Context, r *Reader) (outboundLane, error) {
	if r == nil || r.manifest.ChainID != o.chain {
		return outboundLane{}, fmt.Errorf("outbound reader chain mismatch")
	}
	l, err := o.lane(ctx) // Same leadership session, never an implicit reconnect.
	if err != nil {
		return l, err
	}
	if l.block != 0 {
		err = r.stable(ctx, Snapshot{Number: l.block, Hash: common.HexToHash(l.hash)})
	}
	return l, err
}
func (o *Outbox) get(ctx context.Context, id common.Hash) (Outbound, error) {
	var raw []byte
	err := o.conn.QueryRow(ctx, `SELECT record_encoded FROM fuse_daily_outbound WHERE chain_id=$1 AND payer=$2 AND id=$3`, fmt.Sprint(o.chain), o.payer.Hex(), id.Hex()).Scan(&raw)
	if err != nil {
		return Outbound{}, err
	}
	var b Outbound
	if err = json.Unmarshal(raw, &b); err != nil {
		return b, err
	}
	if b.ID != id || b.Intent.id() != id || b.Intent.ChainID != o.chain || b.Intent.Payer != o.payer {
		return b, fmt.Errorf("outbound identity changed")
	}
	return b, nil
}
func (o *Outbox) Get(ctx context.Context, id common.Hash) (Outbound, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	return o.get(ctx, id)
}

// Active discovers crash-interrupted work without an in-memory ID or nonce.
func (o *Outbox) Active(ctx context.Context) (Outbound, bool, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	l, err := o.lane(ctx)
	if err != nil || l.active == "" {
		return Outbound{}, false, err
	}
	b, err := o.get(ctx, common.HexToHash(l.active))
	return b, err == nil, err
}
func (o *Outbox) save(ctx context.Context, b Outbound) error {
	if b.ID != b.Intent.id() {
		return fmt.Errorf("outbound intent mutated")
	}
	raw, err := json.Marshal(b)
	if err != nil {
		return err
	}
	res, err := o.conn.Exec(ctx, `UPDATE fuse_daily_outbound SET record_encoded=$4 WHERE chain_id=$1 AND payer=$2 AND id=$3 AND EXISTS(SELECT 1 FROM fuse_daily_outbound_lanes WHERE chain_id=$1 AND payer=$2 AND active_id=$3)`, fmt.Sprint(o.chain), o.payer.Hex(), b.ID.Hex(), raw)
	if err == nil && res.RowsAffected() != 1 {
		return ErrOutboundBusy
	}
	return err
}
func validTerms(t TransactionTerms) bool {
	return t.Gas >= 21000 && t.FeeCap != nil && t.TipCap != nil && t.FeeCap.Sign() > 0 && t.FeeCap.BitLen() <= 256 && t.TipCap.Sign() >= 0 && t.TipCap.Cmp(t.FeeCap) <= 0
}
func makeIntent(o *Outbox, p *Plan, index int, t TransactionTerms) (OutboundIntent, error) {
	if p == nil || p.source == nil || p.seal == (common.Hash{}) || p.hash() != p.seal || index < 0 || index >= len(p.Actions) || p.ChainID != o.chain || !validTerms(t) {
		return OutboundIntent{}, fmt.Errorf("invalid outbound plan or explicit transaction terms")
	}
	a := p.Actions[index]
	if a.Kind != "batch" && a.Kind != "queue_void" && a.Kind != "complete_void" {
		return OutboundIntent{}, fmt.Errorf("outbox needs an executable settlement action")
	}
	byID := map[common.Hash]Binding{}
	for _, b := range p.bindings {
		byID[b.TicketID] = b
	}
	bindings := []Binding{}
	for _, id := range a.Tickets {
		b, ok := byID[id]
		if !ok {
			return OutboundIntent{}, fmt.Errorf("outbound binding missing")
		}
		bindings = append(bindings, b)
	}
	i := OutboundIntent{ChainID: o.chain, Payer: o.payer, Custody: p.Custody, JournalHash: p.JournalHash, SourceSequence: p.source.state.Sequence, SourceState: p.source.state.Digest(), Generation: p.Generation, Action: a, Bindings: bindings, Terms: t}
	if a.Kind == "complete_void" {
		i.Generation = "0"
	} // No financial authorization generation applies to this recorded right.
	// Caller-owned slices and big integers must not alias durable intent data.
	raw, err := json.Marshal(i)
	if err != nil {
		return i, err
	}
	var copy OutboundIntent
	err = json.Unmarshal(raw, &copy)
	return copy, err
}
func (o *Outbox) recordIntent(ctx context.Context, i OutboundIntent) (Outbound, error) {
	id := i.id()
	l, err := o.lane(ctx)
	if err != nil {
		return Outbound{}, err
	}
	if l.active != "" {
		if l.active != id.Hex() {
			return Outbound{}, ErrOutboundBusy
		}
		return o.get(ctx, id)
	}
	if prior, err := o.get(ctx, id); err == nil {
		return prior, nil
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return Outbound{}, err
	}
	b := Outbound{ID: id, Intent: i, State: "planned"}
	raw, _ := json.Marshal(b)
	tx, err := o.conn.Begin(ctx)
	if err != nil {
		return b, err
	}
	defer tx.Rollback(context.Background()) //nolint:errcheck
	if _, err = tx.Exec(ctx, `INSERT INTO fuse_daily_outbound VALUES($1,$2,$3,$4)`, fmt.Sprint(o.chain), o.payer.Hex(), id.Hex(), raw); err != nil {
		return b, err
	}
	for _, ticket := range i.Action.Tickets {
		res, err := tx.Exec(ctx, `INSERT INTO fuse_daily_outbound_claims VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING`, fmt.Sprint(o.chain), i.Custody.Hex(), ticket.Hex(), o.payer.Hex(), id.Hex())
		if err != nil {
			return b, err
		}
		if res.RowsAffected() != 1 {
			return b, ErrOutboundBusy
		}
	}
	res, err := tx.Exec(ctx, `UPDATE fuse_daily_outbound_lanes SET active_id=$3 WHERE chain_id=$1 AND payer=$2 AND active_id IS NULL`, fmt.Sprint(o.chain), o.payer.Hex(), id.Hex())
	if err != nil {
		return b, err
	}
	if res.RowsAffected() != 1 {
		return b, ErrOutboundBusy
	}
	return b, tx.Commit(ctx)
}

// Prepare records intent BEFORE requesting either financial signature. It
// reserves the payer nonce before transaction signing, validates every signed
// field and stores the exact raw bytes BEFORE any broadcaster may receive them.
// Retry the same plan after a crash; once raw bytes exist, use Deliver/Observe.
func (o *Outbox) Prepare(ctx context.Context, r *Reader, p *Plan, index int, roles contracts.Signer, payer TransactionSigner, terms TransactionTerms) (Outbound, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	i, err := makeIntent(o, p, index, terms)
	if err != nil {
		return Outbound{}, err
	}
	if _, err = o.guard(ctx, r); err != nil {
		return Outbound{}, err
	}
	if i.Action.Kind != "complete_void" {
		if err = r.sourceFence(ctx, p.source); err != nil {
			return Outbound{}, err
		}
	} else {
		if len(i.Bindings) != 1 || len(i.Action.Tickets) != 1 {
			return Outbound{}, fmt.Errorf("one original queued right required")
		}
		q, completed, err := loadVoidRight(ctx, o.conn, i.ChainID, i.Custody, i.Action.Tickets[0])
		if err != nil {
			return Outbound{}, err
		}
		if completed != nil {
			return Outbound{}, fmt.Errorf("queued right already refunded")
		}
		q, err = r.VerifyVoidQueue(ctx, p.source, i.Bindings[0], q)
		if err != nil {
			return Outbound{}, err
		}
		i.Queue = &q
	}
	b, err := o.recordIntent(ctx, i)
	if err != nil {
		return b, err
	}
	if b.State == "settled" || b.State == "queued" || b.State == "refunded" || b.State == "cancelled" || b.State == "superseded" || b.State == "external_reconciled" || b.State == "reverted" || b.State == "abandoned" {
		return b, fmt.Errorf("outbound intent is terminal")
	}
	if len(b.Raw) > 0 {
		if err = checkRaw(b); err != nil {
			return b, err
		}
		return b, checkAttempts(b)
	}
	if b.Authorization == nil {
		a, err := r.Authorize(ctx, p, index, outboundRoleSigner{o: o, r: r, id: b.ID, inner: roles})
		if err != nil {
			return b, err
		}
		b.Authorization = &a
		b.State = "authorized"
		if err = o.save(ctx, b); err != nil {
			return b, err
		}
	}
	if err = r.validateOutboundAuthorization(ctx, p.source, b); err != nil {
		return b, err
	}
	latest, pending, err := o.nonces(ctx, r)
	if err != nil {
		return b, err
	}
	l, err := o.guard(ctx, r)
	if err != nil {
		return b, err
	}
	if l.active != b.ID.Hex() {
		return b, ErrOutboundBusy
	}
	if latest != pending || (l.floor != "" && l.floor != fmt.Sprint(latest)) {
		return b, ErrNonceConflict
	}
	if b.Nonce == nil {
		if latest == ^uint64(0) {
			return b, fmt.Errorf("payer nonce exhausted")
		}
		b.Nonce = &latest
		unsigned := unsignedTransaction(b)
		b.Unsigned, err = unsigned.MarshalBinary()
		if err != nil {
			return b, err
		}
		b.State = "reserved"
		if err = o.save(ctx, b); err != nil {
			return b, err
		}
	} else if *b.Nonce != latest {
		return b, ErrNonceConflict
	}
	if payer == nil {
		return b, fmt.Errorf("controlled transaction signer required")
	}
	// Fail before invoking the payer signer if this PostgreSQL session died.
	if _, err = o.guard(ctx, r); err != nil {
		return b, err
	}
	if i.Action.Kind != "complete_void" {
		if err = r.sourceFence(ctx, p.source); err != nil {
			return b, err
		}
	}
	tx, err := payer.SignTransaction(ctx, unsignedTransaction(b))
	if err != nil {
		return b, err
	}
	if tx == nil {
		return b, fmt.Errorf("transaction signer returned no transaction")
	}
	b.Raw, err = tx.MarshalBinary()
	if err != nil {
		return b, err
	}
	b.Transaction = tx.Hash()
	if err = checkRaw(b); err != nil {
		return b, err
	}
	if err = r.validateOutboundAuthorization(ctx, p.source, b); err != nil {
		return b, err
	}
	b.State = "prepared"
	if err = o.save(ctx, b); err != nil {
		return b, err
	}
	return b, nil
}
func unsignedTransaction(b Outbound) *types.Transaction {
	t := b.Intent.Terms
	return types.NewTx(&types.DynamicFeeTx{ChainID: new(big.Int).SetUint64(b.Intent.ChainID), Nonce: *b.Nonce, Gas: t.Gas, GasFeeCap: t.FeeCap, GasTipCap: t.TipCap, To: &b.Intent.Custody, Value: new(big.Int), Data: b.Authorization.Data})
}
func checkRaw(b Outbound) error {
	if b.Authorization == nil || b.Nonce == nil || len(b.Raw) == 0 || !validTerms(b.Intent.Terms) {
		return fmt.Errorf("outbound signed transaction incomplete")
	}
	var tx types.Transaction
	if err := tx.UnmarshalBinary(b.Raw); err != nil {
		return err
	}
	unsigned := unsignedTransaction(b)
	encoded, err := unsigned.MarshalBinary()
	if err != nil {
		return err
	}
	signer := types.LatestSignerForChainID(new(big.Int).SetUint64(b.Intent.ChainID))
	from, err := types.Sender(signer, &tx)
	if err != nil {
		return err
	}
	if !bytes.Equal(encoded, b.Unsigned) || tx.Type() != types.DynamicFeeTxType || !tx.Protected() || tx.ChainId().Cmp(unsigned.ChainId()) != 0 || signer.Hash(&tx) != signer.Hash(unsigned) || from != b.Intent.Payer || tx.Hash() != b.Transaction {
		return fmt.Errorf("outbound signer/transaction fields changed")
	}
	canonical, err := tx.MarshalBinary()
	if err != nil || !bytes.Equal(canonical, b.Raw) {
		return fmt.Errorf("noncanonical outbound transaction bytes")
	}
	return nil
}
func (r *Reader) validateOutboundAuthorization(ctx context.Context, j *Journal, b Outbound) error {
	if j == nil || b.Intent.SourceSequence != j.state.Sequence || b.Intent.SourceState != j.state.Digest() || b.Intent.JournalHash != common.HexToHash(j.state.JournalHash) || b.Authorization == nil {
		return fmt.Errorf("outbound canonical source mismatch")
	}
	a := b.Authorization
	if a.ChainID != b.Intent.ChainID || a.Custody != b.Intent.Custody || a.JournalHash != b.Intent.JournalHash || (a.Action.Kind != "complete_void" && a.Generation != b.Intent.Generation) || !equalAction(a.Action, b.Intent.Action) {
		return fmt.Errorf("outbound authorization identity changed")
	}
	completion := a.Action.Kind == "complete_void"
	if !completion {
		if err := r.sourceFence(ctx, j); err != nil {
			return err
		}
	} else {
		if b.Intent.Queue == nil || len(b.Intent.Bindings) != 1 {
			return fmt.Errorf("recorded queue proof required")
		}
		if _, err := r.VerifyVoidQueue(ctx, j, b.Intent.Bindings[0], *b.Intent.Queue); err != nil {
			return err
		}
	}
	if err := r.stable(ctx, Snapshot{Number: a.VerifiedBlock, Hash: a.VerifiedHash}); err != nil {
		return err
	}
	deadline := a.Action.Deadline
	if completion {
		s, err := r.Snapshot(ctx)
		if err != nil {
			return err
		}
		deadline = s.Time + 300
	}
	fresh, err := r.Plan(ctx, j, b.Intent.Bindings, deadline)
	if err != nil {
		return err
	}
	if (!completion && fresh.Generation != a.Generation) || len(fresh.Actions) != 1 || !equalAction(fresh.Actions[0], a.Action) {
		return fmt.Errorf("outbound authorization no longer executable")
	}
	var data []byte
	switch a.Action.Kind {
	case "batch":
		data, err = r.abis["DailyBetCustody"].Pack("settleBatch", a.Action.Outcomes, a.JournalHash, a.Action.Deadline, a.SettlementSignature, a.RiskSignature)
	case "queue_void":
		if len(a.Action.Outcomes) != 1 {
			return fmt.Errorf("one queued void outcome required")
		}
		data, err = r.abis["DailyBetCustody"].Pack("resolve", a.Action.Outcomes[0], a.SettlementSignature, a.RiskSignature)
	case "complete_void":
		if len(a.Action.Tickets) != 1 || len(a.SettlementSignature) != 0 || len(a.RiskSignature) != 0 {
			return fmt.Errorf("void completion must remain signature-free")
		}
		data, err = r.abis["DailyBetCustody"].Pack("completeVoid", a.Action.Tickets[0])
	default:
		return fmt.Errorf("unsupported outbound authorization")
	}
	if err != nil {
		return err
	}
	if !bytes.Equal(data, a.Data) {
		return fmt.Errorf("outbound authorized calldata changed")
	}
	s := Snapshot{Number: fresh.Block, Hash: fresh.BlockHash}
	if completion {
		return r.stable(ctx, s)
	}
	for _, role := range []struct {
		name string
		sig  []byte
	}{{"SETTLEMENT_SIGNER", a.SettlementSignature}, {"RISK_SIGNER", a.RiskSignature}} {
		if _, err = r.read(ctx, s, "AccessController", "verify", crypto.Keccak256Hash([]byte(role.name)), a.Action.Digest, role.sig); err != nil {
			return err
		}
	}
	return r.stable(ctx, s)
}
func (o *Outbox) nonces(ctx context.Context, r *Reader) (uint64, uint64, error) {
	var latest, pending hexutil.Uint64
	if err := r.rpc.ReadRPC(ctx, "eth_getTransactionCount", []any{o.payer, "latest"}, &latest); err != nil {
		return 0, 0, err
	}
	err := r.rpc.ReadRPC(ctx, "eth_getTransactionCount", []any{o.payer, "pending"}, &pending)
	return uint64(latest), uint64(pending), err
}

// Observe never broadcasts. Receipt absence is pending; RPC failure is an error.
// Confirmed reverts release claims, but success requires CommitBatch's monetary
// proof. Canonical receipt anchors are retained for all later lane operations.
func (o *Outbox) Observe(ctx context.Context, r *Reader, id common.Hash) (Outbound, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	return o.observe(ctx, r, id)
}
func (o *Outbox) observe(ctx context.Context, r *Reader, id common.Hash) (Outbound, error) {
	if _, err := o.guard(ctx, r); err != nil {
		return Outbound{}, err
	}
	b, err := o.get(ctx, id)
	if err != nil {
		return b, err
	}
	if len(b.Raw) == 0 && b.NonceRecovery == nil {
		return b, fmt.Errorf("outbound raw transaction not durably prepared")
	}
	if err = checkRecoverableParent(b); err != nil {
		return b, err
	}
	if err = checkAttempts(b); err != nil {
		return b, err
	}
	if b.NonceRecovery != nil {
		p := b.NonceRecovery
		if !validRecoveryReason(p.Reason) {
			return b, fmt.Errorf("nonce recovery reason missing")
		}
		if err = r.verifyObservation(ctx, p.Observation); err != nil {
			return b, err
		}
		class, err := r.nonceClass(b, p.Observation)
		if err != nil {
			return b, err
		}
		if class != p.Class {
			return b, fmt.Errorf("nonce recovery classification changed")
		}
	}
	if err = o.verifyExternal(ctx, r, b); err != nil {
		return b, err
	}
	receipt, winner, err := r.outboundReceipt(ctx, b)
	if err != nil {
		return b, err
	}
	if receipt == nil {
		if b.Receipt != nil {
			return b, contracts.ErrFinalityReorg
		}
		latest, _, err := o.nonces(ctx, r)
		if err != nil {
			return b, err
		}
		if latest != *b.Nonce {
			return b, ErrNonceConflict
		}
		return b, nil
	}
	if receipt.BlockNumber == nil || !receipt.BlockNumber.IsUint64() || receipt.Status > 1 {
		return b, fmt.Errorf("outbound receipt identity invalid")
	}
	s, err := r.Snapshot(ctx)
	if err != nil {
		return b, err
	}
	if receipt.BlockNumber.Uint64() > s.Number {
		return b, contracts.ErrAwaitFinality
	}
	h, err := r.header(ctx, receipt.BlockNumber.Uint64())
	if err != nil {
		return b, err
	}
	if h.Hash != receipt.BlockHash {
		return b, contracts.ErrFinalityReorg
	}
	if b.Receipt != nil && (b.Receipt.TxHash != receipt.TxHash || b.Receipt.BlockHash != receipt.BlockHash || b.Receipt.Status != receipt.Status) {
		return b, contracts.ErrFinalityReorg
	}
	if err = r.stable(ctx, s); err != nil {
		return b, err
	}
	b.Receipt = receipt
	b.IncludedTransaction = receipt.TxHash
	b.WinningAttempt = &winner
	if b.State == "settled" || b.State == "queued" || b.State == "refunded" || b.State == "cancelled" || b.State == "superseded" || b.State == "external_reconciled" || b.State == "reverted" {
		return b, nil
	}
	if b.ExternalExecution != nil {
		// The payment proof was committed separately. This receipt only closes
		// our payer nonce; it must not record or charge the payment again.
		b.State = "external_reconciled"
		return b, o.finish(ctx, b, nil, nil)
	}
	if winner == -2 && b.NonceRecovery.Class == "unrelated" {
		b.State = "superseded"
		return b, o.finish(ctx, b, nil, nil)
	}
	if winner >= 0 && b.Attempts[winner].Kind == "cancel" {
		// The only cancellable transaction is a zero-value, empty-data self
		// transfer with exactly intrinsic gas. It cannot discharge any bet.
		if len(receipt.Logs) != 0 || receipt.GasUsed != 21000 {
			return b, fmt.Errorf("cancellation receipt contains unexpected execution")
		}
		b.State = "cancelled"
		return b, o.finish(ctx, b, nil, nil)
	}
	if receipt.Status == 0 {
		b.State = "reverted"
		return b, o.finish(ctx, b, nil, nil)
	}
	b.State = "included"
	return b, o.save(ctx, b)
}

// Deliver may only expose already committed raw bytes. An uncertain response
// leaves the same hash and nonce recoverable; it never allocates a replacement.
func (o *Outbox) Deliver(ctx context.Context, r *Reader, j *Journal, id common.Hash, sender RawBroadcaster) (Outbound, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	return o.deliver(ctx, r, j, id, -1, sender)
}

func (o *Outbox) deliver(ctx context.Context, r *Reader, j *Journal, id common.Hash, index int, sender RawBroadcaster) (Outbound, error) {
	b, err := o.observe(ctx, r, id)
	if err != nil {
		return b, err
	}
	if b.Receipt != nil {
		return b, nil
	}
	if (b.State != "prepared" && b.State != "external_executed") || sender == nil {
		return b, fmt.Errorf("prepared outbound transaction and explicit broadcaster required")
	}
	raw, hash, kind := b.Raw, b.Transaction, "replace"
	if index >= 0 {
		if index >= len(b.Attempts) || b.Attempts[index].State != "prepared" {
			return b, fmt.Errorf("attempt raw bytes not durably prepared")
		}
		a := b.Attempts[index]
		raw, hash, kind = a.Raw, a.Transaction, a.Kind
	} else if index != -1 {
		return b, fmt.Errorf("invalid attempt index")
	}
	if kind != "cancel" && hasCancellation(b) {
		return b, fmt.Errorf("cancellation is armed; only cancellation attempts may be sent")
	}
	if kind != "cancel" && b.ExternalExecution != nil {
		return b, fmt.Errorf("external financial execution is already proven; only nonce cleanup may be sent")
	}
	if kind != "cancel" {
		if err = r.validateOutboundAuthorization(ctx, j, b); err != nil {
			return b, fmt.Errorf("outbound authorization verification failed; retain recorded nonce: %w", err)
		}
	} else if _, err = r.Snapshot(ctx); err != nil {
		return b, err
	}
	if _, err = o.guard(ctx, r); err != nil {
		return b, err
	}
	ack, err := sender.Broadcast(ctx, append([]byte{}, raw...))
	if err != nil {
		return b, fmt.Errorf("outbound broadcast uncertain; recover %s: %w", hash, err)
	}
	if ack != hash {
		return b, fmt.Errorf("outbound RPC acknowledgement hash mismatch; recover recorded hash")
	}
	return b, nil
}

func (o *Outbox) CommitBatch(ctx context.Context, r *Reader, j *Journal, id common.Hash) (SettlementProof, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	b, err := o.observe(ctx, r, id)
	if err != nil {
		return SettlementProof{}, err
	}
	if b.ExternalExecution != nil && b.ExternalExecution.Kind == "batch" {
		return r.ReconcileBatch(ctx, j, b.Intent.Bindings, *b.Authorization, b.ExternalExecution.Observation.Transaction)
	}
	if b.Receipt == nil || b.Receipt.Status != 1 || b.State == "cancelled" || b.State == "superseded" {
		return SettlementProof{}, fmt.Errorf("confirmed successful outbound receipt required")
	}
	p, err := r.ReconcileBatch(ctx, j, b.Intent.Bindings, *b.Authorization, b.Receipt.TxHash)
	if err != nil {
		return p, err
	}
	if b.State == "settled" {
		return p, nil
	}
	b.State = "settled"
	return p, o.finish(ctx, b, &p, nil)
}

func (o *Outbox) CommitVoid(ctx context.Context, r *Reader, j *Journal, id common.Hash) (VoidProof, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	b, err := o.observe(ctx, r, id)
	if err != nil {
		return VoidProof{}, err
	}
	if b.ExternalExecution != nil && b.ExternalExecution.Void != nil {
		if b.ExternalExecution.Kind == "queue_void" {
			return r.ReconcileVoidQueue(ctx, j, b.Intent.Bindings[0], *b.Authorization, b.ExternalExecution.Observation.Transaction)
		}
		if b.Intent.Queue == nil {
			return VoidProof{}, fmt.Errorf("original queue required")
		}
		return r.ReconcileVoidCompletion(ctx, j, b.Intent.Bindings[0], *b.Intent.Queue, *b.Authorization, b.ExternalExecution.Observation.Transaction)
	}
	if b.Receipt == nil || b.Receipt.Status != 1 || b.State == "cancelled" || b.State == "superseded" || b.Authorization == nil || len(b.Intent.Bindings) != 1 {
		return VoidProof{}, fmt.Errorf("confirmed void delivery required")
	}
	var p VoidProof
	switch b.Intent.Action.Kind {
	case "queue_void":
		p, err = r.ReconcileVoidQueue(ctx, j, b.Intent.Bindings[0], *b.Authorization, b.Receipt.TxHash)
	case "complete_void":
		if b.Intent.Queue == nil {
			return p, fmt.Errorf("original queued proof required")
		}
		p, err = r.ReconcileVoidCompletion(ctx, j, b.Intent.Bindings[0], *b.Intent.Queue, *b.Authorization, b.Receipt.TxHash)
	default:
		return p, fmt.Errorf("cash batches require CommitBatch")
	}
	if err != nil {
		return p, err
	}
	if b.State == "queued" || b.State == "refunded" {
		return p, nil
	}
	if p.Kind == "queue_void" {
		b.State = "queued"
	} else {
		b.State = "refunded"
	}
	return p, o.finish(ctx, b, nil, &p)
}

func (o *Outbox) finish(ctx context.Context, b Outbound, p *SettlementProof, v *VoidProof) error {
	if b.Receipt == nil || b.Nonce == nil || *b.Nonce == ^uint64(0) {
		return fmt.Errorf("outbound terminal evidence missing")
	}
	raw, err := json.Marshal(b)
	if err != nil {
		return err
	}
	tx, err := o.conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(context.Background()) //nolint:errcheck
	if p != nil {
		if err = commitSettlement(ctx, tx, *p); err != nil {
			return err
		}
	}
	if v != nil {
		if err = commitVoid(ctx, tx, *v); err != nil {
			return err
		}
	}
	if b.State == "reverted" || b.State == "queued" || b.State == "cancelled" || b.State == "superseded" || (b.State == "external_reconciled" && b.ExternalExecution.Kind == "queue_void") {
		if _, err = tx.Exec(ctx, `DELETE FROM fuse_daily_outbound_claims WHERE chain_id=$1 AND payer=$2 AND intent_id=$3`, fmt.Sprint(o.chain), o.payer.Hex(), b.ID.Hex()); err != nil {
			return err
		}
	}
	if _, err = tx.Exec(ctx, `UPDATE fuse_daily_outbound SET record_encoded=$4 WHERE chain_id=$1 AND payer=$2 AND id=$3`, fmt.Sprint(o.chain), o.payer.Hex(), b.ID.Hex(), raw); err != nil {
		return err
	}
	anchor := b.Receipt
	if b.ExternalExecution != nil && b.ExternalExecution.Observation.Receipt.BlockNumber.Cmp(anchor.BlockNumber) > 0 {
		anchor = b.ExternalExecution.Observation.Receipt
	}
	res, err := tx.Exec(ctx, `UPDATE fuse_daily_outbound_lanes SET active_id=NULL,nonce_floor=$4,anchor_block=$5,anchor_hash=$6 WHERE chain_id=$1 AND payer=$2 AND active_id=$3`, fmt.Sprint(o.chain), o.payer.Hex(), b.ID.Hex(), fmt.Sprint(*b.Nonce+1), anchor.BlockNumber.Uint64(), anchor.BlockHash.Hex())
	if err != nil {
		return err
	}
	if res.RowsAffected() != 1 {
		return ErrOutboundBusy
	}
	return tx.Commit(ctx)
}

// RetireUnprepared can release a never-broadcast attempt only after confirmed
// expiry/rotation and unchanged payer nonce. Prepared raw transactions are
// deliberately excluded: they require receipt or explicit nonce reconciliation.
func (o *Outbox) RetireUnprepared(ctx context.Context, r *Reader, id common.Hash) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	l, err := o.guard(ctx, r)
	if err != nil {
		return err
	}
	if l.active != id.Hex() {
		return ErrOutboundBusy
	}
	b, err := o.get(ctx, id)
	if err != nil {
		return err
	}
	if len(b.Raw) != 0 {
		return fmt.Errorf("prepared transaction cannot be abandoned")
	}
	if b.Intent.Action.Kind == "complete_void" {
		return fmt.Errorf("recorded void rights do not expire or rotate; resume their preparation")
	}
	s, err := r.Snapshot(ctx)
	if err != nil {
		return err
	}
	if s.Time <= b.Intent.Action.Deadline && s.Generation.String() == b.Intent.Generation {
		return fmt.Errorf("authorization is still executable")
	}
	latest, pending, err := o.nonces(ctx, r)
	if err != nil {
		return err
	}
	if latest != pending || (b.Nonce != nil && latest != *b.Nonce) || (l.floor != "" && l.floor != fmt.Sprint(latest)) {
		return ErrNonceConflict
	}
	if err = r.stable(ctx, s); err != nil {
		return err
	}
	b.State = "abandoned"
	raw, _ := json.Marshal(b)
	tx, err := o.conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(context.Background()) //nolint:errcheck
	if _, err = tx.Exec(ctx, `DELETE FROM fuse_daily_outbound_claims WHERE chain_id=$1 AND payer=$2 AND intent_id=$3`, fmt.Sprint(o.chain), o.payer.Hex(), id.Hex()); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `UPDATE fuse_daily_outbound SET record_encoded=$4 WHERE chain_id=$1 AND payer=$2 AND id=$3`, fmt.Sprint(o.chain), o.payer.Hex(), id.Hex(), raw); err != nil {
		return err
	}
	res, err := tx.Exec(ctx, `UPDATE fuse_daily_outbound_lanes SET active_id=NULL WHERE chain_id=$1 AND payer=$2 AND active_id=$3`, fmt.Sprint(o.chain), o.payer.Hex(), id.Hex())
	if err != nil {
		return err
	}
	if res.RowsAffected() != 1 {
		return ErrOutboundBusy
	}
	return tx.Commit(ctx)
}
