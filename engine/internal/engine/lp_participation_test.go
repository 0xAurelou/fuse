package engine

import (
	"encoding/json"
	"os"
	"testing"
)

func lpState(t *testing.T) State {
	t.Helper()
	raw, err := os.ReadFile("../../config/paper.json")
	if err != nil {
		t.Fatal(err)
	}
	var p Policy
	if err = json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	s, err := NewState(p)
	if err != nil {
		t.Fatal(err)
	}
	s.LP = 1000_000_000
	s.Local = &LocalState{TokenSupply: "0", TokenBalances: map[string]string{}}
	return s
}

func TestLPReservedLiabilitiesCannotUnderwrite(t *testing.T) {
	s := lpState(t)
	for _, e := range []LocalEffect{
		{Module: "LPVault", Event: "ReserveFeeAccrued", Amount: 100_000_000, Value: "100000000"},
		{Module: "LPVault", Event: "LPExitReserved", Amount: 200_000_000},
	} {
		if err := s.localEffect(e); err != nil {
			t.Fatal(err)
		}
	}
	if s.LPAvailable() != 700_000_000 || s.LP != 1000_000_000 {
		t.Fatal("reserved capital counted as underwriting")
	}
	if err := s.Check(); err != nil {
		t.Fatal(err)
	}
	s.Policy.LPBuffer = 800_000_000
	if err := s.capacity(); err == nil {
		t.Fatal("reserved capital admitted new risk")
	}
	s.Policy.LPBuffer = 0
	if err := s.localEffect(LocalEffect{Module: "LPVault", Event: "LPExitPaid", Amount: 200_000_000}); err != nil {
		t.Fatal(err)
	}
	if s.LPAvailable() != 700_000_000 || s.LP != 800_000_000 {
		t.Fatal("exit payment changed remaining equity")
	}
	if err := s.localEffect(LocalEffect{Module: "LPVault", Event: "ReserveFunded", Amount: 100_000_000, Value: "285714286"}); err != nil {
		t.Fatal(err)
	}
	if s.LPAvailable() != 700_000_000 || s.Local.LPFeeAccrued != 0 || s.Reserve != 100_000_000 {
		t.Fatal("fee funding changed LP equity")
	}
	if err := s.Check(); err != nil {
		t.Fatal(err)
	}
}

func TestLPInvalidAccrualAndExitFailClosed(t *testing.T) {
	for _, e := range []LocalEffect{
		{Module: "LPVault", Event: "ReserveFeeAccrued", Amount: 1, Value: "2"},
		{Module: "LPVault", Event: "ReserveFeeAccrued", Amount: -1, Value: "1"},
		{Module: "LPVault", Event: "LPExitPaid", Amount: 1},
		{Module: "LPVault", Event: "LPExitReserved", Amount: 1000_000_001},
	} {
		s := lpState(t)
		if err := s.localEffect(e); err == nil {
			t.Fatalf("accepted invalid LP event: %+v", e)
		}
	}
}

func TestZeroLPReservationFieldsPreserveHistoricalJSON(t *testing.T) {
	raw, err := json.Marshal(LocalState{})
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]any
	if err = json.Unmarshal(raw, &fields); err != nil {
		t.Fatal(err)
	}
	if _, ok := fields["lp_fee_accrued"]; ok {
		t.Fatal("zero fee changes historical replay state")
	}
	if _, ok := fields["lp_exit_reserved"]; ok {
		t.Fatal("zero exits change historical replay state")
	}
}
