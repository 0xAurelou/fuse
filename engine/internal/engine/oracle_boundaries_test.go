package engine

import "testing"

func TestOracleHealthAndGapEqualityBoundaries(t *testing.T) {
	s := lpState(t)
	s.Oracle.Price = 100
	s.Oracle.Sources = map[string]Feed{"a": {Price: 100, At: 10000}, "b": {Price: 100, At: 10000}}
	if !s.Healthy(10000+s.Policy.MaxGapMS) || s.gap(10000+s.Policy.MaxGapMS) {
		t.Fatal("freshness equality must be healthy")
	}
	if s.Healthy(10001+s.Policy.MaxGapMS) || !s.gap(10001+s.Policy.MaxGapMS) {
		t.Fatal("stale receipt admitted")
	}
	if s.Healthy(9999) {
		t.Fatal("future receipt admitted")
	}
	s.Oracle.Sources["b"] = Feed{Price: 101, At: 10000}
	s.Oracle.MismatchSince = 10000
	if s.Healthy(10000) || s.gap(10000+s.Policy.DisagreementMS-1) {
		t.Fatal("short disagreement handling")
	}
	if !s.gap(10000 + s.Policy.DisagreementMS) {
		t.Fatal("disagreement equality must make pending")
	}
	delete(s.Oracle.Sources, "b")
	if !s.gap(10000) || s.Healthy(10000) {
		t.Fatal("missing receiver admitted")
	}
}
