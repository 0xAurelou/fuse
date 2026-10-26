package contracts

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
)

func TestExactArtifactCachePreservesBindingAndRejectsTampering(t *testing.T) {
	directory := t.TempDir()
	original := filepath.Join(directory, "out", "Module.json")
	cache := filepath.Join(directory, "artifacts", "Module.json")
	if err := os.MkdirAll(filepath.Dir(original), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(cache), 0700); err != nil {
		t.Fatal(err)
	}
	good := []byte(`{"abi":[]}`)
	digest := sha256.Sum256(good)
	module := Module{Artifact: original, SHA256: hex.EncodeToString(digest[:])}
	_ = os.WriteFile(original, []byte(`{"abi":["changed build"]}`), 0600)
	_ = os.WriteFile(cache, good, 0600)
	raw, path, err := PinnedArtifact(filepath.Join(directory, "deployment.json"), module)
	if err != nil || string(raw) != string(good) || path != cache || module.Artifact != original {
		t.Fatal("exact cache fallback changed binding", path, err)
	}
	_ = os.WriteFile(cache, []byte(`{"abi":["tampered"]}`), 0600)
	if _, _, err = PinnedArtifact(filepath.Join(directory, "deployment.json"), module); err == nil {
		t.Fatal("cache digest bypass")
	}
}
