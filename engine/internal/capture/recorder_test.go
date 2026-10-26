package capture

import (
	"encoding/json"
	"fuse/engine/internal/engine"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

var price = json.RawMessage(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":"100000"}}}`)

func openTest(t *testing.T, dir string) (*Recorder, engine.Policy) {
	t.Helper()
	raw, err := os.ReadFile("../../config/paper.json")
	if err != nil {
		t.Fatal(err)
	}
	var p engine.Policy
	json.Unmarshal(raw, &p)
	r, err := Open(dir, "ws://fixture", p, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	r.now = func() time.Time { return time.UnixMilli(r.manifest.FrozenAt + 1) }
	return r, p
}
func TestDurableResumeAndFreeze(t *testing.T) {
	dir := t.TempDir()
	r, p := openTest(t, dir)
	if _, err := Open(dir, "ws://fixture", p, time.Hour); err == nil {
		t.Fatal("second writer acquired lock")
	}
	if err := r.Append("a", price); err != nil {
		t.Fatal(err)
	}
	old := r.Head()
	r.Close()
	r, err := Open(dir, "ws://fixture", p, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if r.Head().Hash != old.Hash || r.Head().Sequence != 1 {
		t.Fatal("durable head differs")
	}
	r.now = func() time.Time { return time.UnixMilli(old.At + 1) }
	if err = r.Append("b", price); err != nil {
		t.Fatal(err)
	}
	if r.Head().Sequence != 2 {
		t.Fatal("resume reset sequence")
	}
	r.Close()
	p.Model.Version = "retuned"
	if _, err = Open(dir, "ws://fixture", p, time.Hour); err == nil {
		t.Fatal("changed policy accepted")
	}
}
func TestTamperAndInterruptedTailFailClosed(t *testing.T) {
	for _, tail := range []bool{false, true} {
		t.Run(map[bool]string{true: "tail", false: "tamper"}[tail], func(t *testing.T) {
			dir := t.TempDir()
			r, p := openTest(t, dir)
			if err := r.Append("a", price); err != nil {
				t.Fatal(err)
			}
			r.Close()
			path := filepath.Join(dir, "receipts.jsonl")
			raw, _ := os.ReadFile(path)
			if tail {
				raw = append(raw, []byte(`{"sequence":2`)...)
			} else {
				raw = []byte(strings.Replace(string(raw), "100000", "100001", 1))
			}
			os.WriteFile(path, raw, 0600)
			if _, err := Open(dir, "ws://fixture", p, time.Hour); err == nil {
				t.Fatal("corrupt evidence accepted")
			}
		})
	}
}
func TestReceiptBoundariesAndClock(t *testing.T) {
	r, _ := openTest(t, t.TempDir())
	defer r.Close()
	if err := r.Append("x", price); err == nil {
		t.Fatal("unknown source")
	}
	if err := r.Append("a", json.RawMessage(`{}`)); err == nil {
		t.Fatal("invalid price")
	}
	r.now = func() time.Time { return time.UnixMilli(r.manifest.FrozenAt) }
	if err := r.Append("a", price); err == nil {
		t.Fatal("receipt before freeze")
	}
	r.now = func() time.Time { return r.Deadline() }
	if err := r.Append("a", price); err == nil {
		t.Fatal("receipt at deadline")
	}
	r.now = func() time.Time { return time.UnixMilli(r.manifest.FrozenAt + 100) }
	if err := r.Append("a", price); err != nil {
		t.Fatal(err)
	}
	r.now = func() time.Time { return time.UnixMilli(r.manifest.FrozenAt + 99) }
	if err := r.Append("b", price); err == nil {
		t.Fatal("clock regression")
	}
}
func TestManifestBoundToReceipts(t *testing.T) {
	dir := t.TempDir()
	r, p := openTest(t, dir)
	r.Append("a", price)
	r.Close()
	path := filepath.Join(dir, "manifest.json")
	raw, _ := os.ReadFile(path)
	var m Manifest
	json.Unmarshal(raw, &m)
	m.FrozenAt--
	raw, _ = json.Marshal(m)
	os.WriteFile(path, raw, 0600)
	if _, err := Open(dir, "ws://fixture", p, time.Hour); err == nil {
		t.Fatal("changed manifest accepted")
	}
}

func TestWriteFailureFencesRecorder(t *testing.T) {
	r, _ := openTest(t, t.TempDir())
	defer r.Close()
	r.file.Close()
	if err := r.Append("a", price); err == nil || !r.failed {
		t.Fatal("write failure did not fence")
	}
	if r.Head().Sequence != 0 {
		t.Fatal("failed receipt acknowledged")
	}
	if err := r.Append("b", price); err == nil {
		t.Fatal("fenced writer continued")
	}
}
