package dailyrelay

import (
	"encoding/json"
	"fmt"
	"os"
	"testing"

	"fuse/engine/internal/engine"
	"github.com/ethereum/go-ethereum/common"
)

func sourceJournal(t *testing.T) (engine.Policy, []engine.Event, engine.Stage) {
	t.Helper()
	raw, err := os.ReadFile("../../config/paper.json")
	if err != nil {
		t.Fatal(err)
	}
	var policy engine.Policy
	if err = json.Unmarshal(raw, &policy); err != nil {
		t.Fatal(err)
	}
	s, err := engine.NewState(policy)
	if err != nil {
		t.Fatal(err)
	}
	events := []engine.Event{}
	actor := common.HexToAddress("0x1234").Hex()
	now := int64(1_000_000)
	apply := func(c engine.Command) engine.Event {
		t.Helper()
		c.Key = fmt.Sprint(len(events) + 1)
		if c.At == 0 {
			c.At = now
		}
		next, e, err := engine.Apply(s, c)
		if err != nil {
			t.Fatal(err)
		}
		s = next
		events = append(events, e)
		return e
	}
	apply(engine.Command{Kind: "lp_fund", Amount: 1_000_000_000})
	apply(engine.Command{Kind: "deposit", Actor: actor, ID: "fund", Amount: 100_000_000})
	apply(engine.Command{Kind: "ack_deposit", ID: "fund"})
	price := func(value string) {
		for _, source := range []string{"a", "b"} {
			apply(engine.Command{Kind: "oracle", Source: source, Raw: json.RawMessage(fmt.Sprintf(`{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{"oraclePx":%q}}}`, value))})
		}
	}
	price("100000")
	e := apply(engine.Command{Kind: "quote", Actor: actor, Amount: 1_000_000, Multiplier: 2})
	var q engine.Quote
	if err = json.Unmarshal(e.Result, &q); err != nil {
		t.Fatal(err)
	}
	e = apply(engine.Command{Kind: "enter", Actor: actor, ID: q.ID})
	var p engine.Stage
	if err = json.Unmarshal(e.Result, &p); err != nil {
		t.Fatal(err)
	}
	now += 123
	price("1")
	return policy, events, p
}

func TestReplayBindsSharedDecisionsAndRejectsTamperedOrTruncatedHistory(t *testing.T) {
	policy, events, p := sourceJournal(t)
	j, err := Replay(policy, events)
	if err != nil {
		t.Fatal(err)
	}
	out, err := j.Outcome(p.ID)
	if err != nil || out.Outcome != 3 || out.CanonicalMS != 1_000_123 {
		t.Fatalf("%+v %v", out, err)
	}
	for _, change := range []func([]engine.Event){
		func(e []engine.Event) { e[0].Command.Amount++ },
		func(e []engine.Event) { e[len(e)-1].Result = json.RawMessage(`{"fake":true}`) },
		func(e []engine.Event) { e[len(e)-1].Hash = "forged" },
		func(e []engine.Event) { e[len(e)-1].Command.Key = e[0].Command.Key },
	} {
		copyEvents := append([]engine.Event{}, events...)
		change(copyEvents)
		if _, err = Replay(policy, copyEvents); err == nil {
			t.Fatal("accepted changed source history")
		}
	}
	if _, err = Replay(policy, events[1:]); err == nil {
		t.Fatal("accepted missing source prefix")
	}
	policy.Version += "-different"
	if _, err = Replay(policy, events); err == nil {
		t.Fatal("accepted different initial policy")
	}
}

func TestNativeQuoteTTLUsesOnlySecondsInsideItsHalfOpenValidity(t *testing.T) {
	_, _, p := sourceJournal(t)
	ticket := common.HexToHash("0x1234")
	for _, times := range [][2]int64{{1_000_000, 1_002_000}, {1_000_123, 1_002_123}, {1_000_999, 1_001_999}} {
		p.Terms.Issued, p.Terms.ValidUntil = times[0], times[1]
		q, err := QuoteForStage(p, ticket)
		if err != nil {
			t.Fatal(err)
		}
		if int64(q.QuotedAt)*1000 < p.Terms.Issued || int64(q.ValidUntil)*1000 >= p.Terms.ValidUntil {
			t.Fatal("extended native quote validity")
		}
		for second := q.QuotedAt; second <= q.ValidUntil; second++ {
			if int64(second)*1000 < p.Terms.Issued || int64(second)*1000 >= p.Terms.ValidUntil {
				t.Fatal("contract could admit an engine-expired quote")
			}
		}
	}
	p.Terms.Issued, p.Terms.ValidUntil = 1_000_001, 1_000_999
	if _, err := QuoteForStage(p, ticket); err == nil {
		t.Fatal("accepted quote with no valid chain second")
	}
}

func TestExportedStageCopyCannotMutateVerifiedJournal(t *testing.T) {
	policy, events, p := sourceJournal(t)
	j, err := Replay(policy, events)
	if err != nil {
		t.Fatal(err)
	}
	copy, err := j.Stage(p.ID)
	if err != nil {
		t.Fatal(err)
	}
	copy.Terms.Stake++
	copy.Expiry++
	original, err := j.Stage(p.ID)
	if err != nil {
		t.Fatal(err)
	}
	if original.Terms.Stake != p.Terms.Stake || original.Expiry != p.Expiry {
		t.Fatal("journal state aliased caller copy")
	}
	if _, err = (&Journal{}).Stage(p.ID); err == nil {
		t.Fatal("empty journal supplied a stage")
	}
}
