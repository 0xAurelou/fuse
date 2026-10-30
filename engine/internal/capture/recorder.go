// Package capture retains prospective oracle receipts without signing, trading,
// or claiming independent upstream truth. Every successful Append is fsynced.
package capture

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"fuse/engine/internal/engine"
)

// ErrDeadlineElapsed is a normal fixed-horizon stop, including when the clock
// crosses the deadline between the caller's check and the serialized append.
var ErrDeadlineElapsed = errors.New("capture deadline elapsed")

type Manifest struct {
	DurationMS         int64         `json:"duration_ms"`
	Version            int           `json:"version"`
	FrozenAt           int64         `json:"frozen_at_ms"`
	Policy             engine.Policy `json:"policy"`
	PolicyHash         string        `json:"policy_hash"`
	Endpoint           string        `json:"endpoint"`
	ProductionApproved bool          `json:"production_approved"`
}
type Receipt struct {
	Sequence uint64          `json:"sequence"`
	Previous string          `json:"previous_hash"`
	Hash     string          `json:"hash"`
	At       int64           `json:"at"`
	Source   string          `json:"source"`
	Raw      json.RawMessage `json:"raw"`
}

func (r Receipt) digest() string { r.Hash = ""; return engine.Hash(r) }

type Recorder struct {
	now        func() time.Time
	mu         sync.Mutex
	manifest   Manifest
	file, lock *os.File
	head       Receipt
	failed     bool
}

func Open(directory, endpoint string, policy engine.Policy, duration time.Duration) (_ *Recorder, err error) {
	if err = policy.Validate(); err != nil {
		return nil, err
	}
	if duration < time.Millisecond || duration > 7*24*time.Hour {
		return nil, fmt.Errorf("invalid capture duration")
	}
	if endpoint == "" {
		return nil, fmt.Errorf("oracle endpoint required")
	}
	if err = os.MkdirAll(directory, 0700); err != nil {
		return nil, err
	}
	lock, err := os.OpenFile(filepath.Join(directory, "capture.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		lock.Close()
		return nil, fmt.Errorf("capture already owned: %w", err)
	}
	r := &Recorder{lock: lock, now: time.Now}
	defer func() {
		if err != nil {
			r.Close()
		}
	}()
	manifestPath := filepath.Join(directory, "manifest.json")
	raw, err := os.ReadFile(manifestPath)
	if os.IsNotExist(err) {
		// An existing journal must never be assigned a new prospective freeze.
		if _, statErr := os.Stat(filepath.Join(directory, "receipts.jsonl")); !os.IsNotExist(statErr) {
			return nil, fmt.Errorf("unbound existing receipts")
		}
		r.manifest = Manifest{Version: 1, DurationMS: duration.Milliseconds(), FrozenAt: time.Now().UnixMilli(), Policy: policy, PolicyHash: engine.Hash(policy), Endpoint: endpoint}
		if r.Deadline().UnixMilli() >= policy.Model.ValidUntil {
			return nil, fmt.Errorf("frozen policy expires during capture")
		}
		raw, err = json.MarshalIndent(r.manifest, "", "  ")
		if err != nil {
			return nil, err
		}
		f, e := os.OpenFile(manifestPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if e != nil {
			return nil, e
		}
		_, err = f.Write(append(raw, '\n'))
		if err == nil {
			err = f.Sync()
		}
		closeErr := f.Close()
		if err != nil {
			return nil, err
		}
		if closeErr != nil {
			return nil, closeErr
		}
	} else if err != nil {
		return nil, err
	} else {
		if err = json.Unmarshal(raw, &r.manifest); err != nil {
			return nil, err
		}
		if r.manifest.DurationMS != duration.Milliseconds() || r.manifest.Version != 1 || r.manifest.FrozenAt <= 0 || r.manifest.ProductionApproved || r.manifest.Endpoint != endpoint || r.manifest.PolicyHash != engine.Hash(policy) || engine.Hash(r.manifest.Policy) != engine.Hash(policy) {
			return nil, fmt.Errorf("capture freeze or endpoint changed")
		}
	}
	if r.manifest.FrozenAt+r.manifest.DurationMS >= policy.Model.ValidUntil {
		return nil, fmt.Errorf("frozen policy expires during capture")
	}
	r.head.Hash = engine.Hash(r.manifest)
	r.file, err = os.OpenFile(filepath.Join(directory, "receipts.jsonl"), os.O_CREATE|os.O_RDWR|os.O_APPEND, 0600)
	if err != nil {
		return nil, err
	}
	// Network frames are bounded to 1 MiB. Allow JSON escaping overhead while
	// refusing an unbounded/corrupt retained line during recovery.
	reader := bufio.NewReaderSize(r.file, 8<<20)
	for {
		line, e := reader.ReadSlice('\n')
		if e == io.EOF && len(line) == 0 {
			break
		}
		if e != nil {
			return nil, fmt.Errorf("incomplete receipt tail; preserve evidence: %w", e)
		}
		var receipt Receipt
		if err = json.Unmarshal(line, &receipt); err != nil {
			return nil, err
		}
		if err = r.validate(receipt); err != nil {
			return nil, err
		}
		r.head = receipt
	}
	// Retain directory entries as well as contents before acknowledging receipts.
	dir, e := os.Open(directory)
	if e != nil {
		return nil, e
	}
	err = dir.Sync()
	dir.Close()
	if err != nil {
		return nil, err
	}
	return r, nil
}
func (r *Recorder) validate(v Receipt) error {
	if v.Sequence != r.head.Sequence+1 || v.Previous != r.head.Hash || v.Hash != v.digest() || v.At < r.head.At || v.At <= r.manifest.FrozenAt || v.At >= r.Deadline().UnixMilli() || v.At >= r.manifest.Policy.Model.ValidUntil || (v.Source != "a" && v.Source != "b") {
		return fmt.Errorf("receipt chain, time or source invalid at %d", v.Sequence)
	}
	_, err := engine.ParseOracle(v.Raw)
	return err
}
func (r *Recorder) Append(source string, raw json.RawMessage) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.failed || r.file == nil {
		return fmt.Errorf("capture fenced or closed")
	}
	if len(raw) > 1<<20 {
		return fmt.Errorf("oracle frame exceeds 1 MiB")
	}
	v := Receipt{Sequence: r.head.Sequence + 1, Previous: r.head.Hash, At: r.now().UnixMilli(), Source: source, Raw: append(json.RawMessage{}, raw...)}
	if v.At >= r.Deadline().UnixMilli() {
		return ErrDeadlineElapsed
	}
	v.Hash = v.digest()
	if err := r.validate(v); err != nil {
		return err
	}
	encoded, err := json.Marshal(v)
	if err != nil {
		return err
	}
	if _, err = r.file.Write(append(encoded, '\n')); err == nil {
		err = r.file.Sync()
	}
	if err != nil {
		r.failed = true
		return err
	}
	r.head = v
	return nil
}
func (r *Recorder) Head() Receipt {
	r.mu.Lock()
	defer r.mu.Unlock()
	h := r.head
	h.Raw = append(json.RawMessage{}, h.Raw...)
	return h
}
func (r *Recorder) Close() error {
	r.mu.Lock()
	defer r.mu.Unlock()
	var err error
	if r.file != nil {
		err = r.file.Close()
		r.file = nil
	}
	if r.lock != nil {
		syscall.Flock(int(r.lock.Fd()), syscall.LOCK_UN)
		r.lock.Close()
		r.lock = nil
	}
	return err
}

func (r *Recorder) Deadline() time.Time {
	return time.UnixMilli(r.manifest.FrozenAt + r.manifest.DurationMS)
}

// Verify takes the writer lock and checks the entire retained chain against its
// original freeze. An expired recording can still be verified offline.
func Verify(directory string) (Manifest, Receipt, error) {
	raw, err := os.ReadFile(filepath.Join(directory, "manifest.json"))
	if err != nil {
		return Manifest{}, Receipt{}, err
	}
	var m Manifest
	if err = json.Unmarshal(raw, &m); err != nil {
		return m, Receipt{}, err
	}
	r, err := Open(directory, m.Endpoint, m.Policy, time.Duration(m.DurationMS)*time.Millisecond)
	if err != nil {
		return m, Receipt{}, err
	}
	defer r.Close()
	return m, r.Head(), nil
}
