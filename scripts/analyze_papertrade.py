#!/usr/bin/env python3
"""Inspect retained local/paper run data; independently check paired-oracle barriers."""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCALE = Decimal(1_000_000)


def money(value):
    return f"{Decimal(value) / SCALE:,.6f}"


def analyze(directory):
    summary = json.loads((directory / "summary.json").read_text())
    state = json.loads((directory / "final-state.json").read_text())
    sources, paired, last_price = {}, [], None
    sequence, previous_hash, commands = 0, "", Counter()
    ledger_lp, ledger_peak_exposure, ledger_min_lp, ledger_min_buffer = 0, 0, None, None
    account_debt, stage_risk = {}, {}
    lp_buffer = state['policy']['lp_buffer']
    gap_ms = next(iter(state["policy_history"].values()))["max_gap_ms"]
    with (directory / "journal.jsonl").open() as stream:
        for line in stream:
            event = json.loads(line)
            if event["sequence"] != sequence + 1 or event["previous_hash"] != previous_hash:
                raise ValueError(f"journal continuity failure: {directory}")
            sequence, previous_hash = event["sequence"], event["hash"]
            command = event["command"]
            commands[command["kind"]] += 1
            if command['kind'] == 'policy_update':
                lp_buffer = command['raw']['lp_buffer']
            for posting in event.get('postings', []):
                if posting['asset'] == 'USDC' and posting['account'] == 'asset/lp':
                    ledger_lp += posting['delta']
            for account, notice in event.get('notices', {}).items():
                balances = notice['account']['balances']
                account_debt[account] = sum(balances.get(key, 0) for key in ('unfunded', 'earned_unfunded', 'withdrawal_unfunded'))
                for stage in notice['stages']:
                    stage_risk[stage['id']] = stage['terms']['payout']-stage['funded'] if stage['status'] in ('active', 'pending') else 0
            exposure = sum(account_debt.values())+sum(stage_risk.values())
            if ledger_lp:
                ledger_peak_exposure = max(ledger_peak_exposure, exposure)
                ledger_min_lp = min(ledger_min_lp if ledger_min_lp is not None else ledger_lp, ledger_lp)
                buffer = ledger_lp-exposure-lp_buffer
                ledger_min_buffer = min(ledger_min_buffer if ledger_min_buffer is not None else buffer, buffer)
            if command["kind"] != "oracle":
                continue
            price = int(Decimal(command["raw"]["data"]["ctx"]["oraclePx"]) * SCALE)
            sources[command["source"]] = (price, command["at"])
            if len(sources) < 2 or sources["a"][0] != sources["b"][0]:
                continue
            if any(command["at"] - receipt > gap_ms for _, receipt in sources.values()):
                continue
            last_price = price
            paired.append((command["at"], last_price))
    if sequence != summary["journal_events"] or previous_hash != state["journal_hash"]:
        raise ValueError(f"journal head differs from final state: {directory}")
    if ledger_lp != summary['final_lp_usdc_units'] or exposure != summary['exposure_usdc_units']:
        raise ValueError(f'journal LP/exposure reconstruction mismatch: {directory}')
    stages = list(state["stages"].values())
    checked, mismatches = 0, []
    width_outcomes = defaultdict(Counter)
    for stage in stages:
        terms = stage["terms"]
        width = (terms["entry_price"] - terms["lower"]) * 10000 // terms["entry_price"]
        # Integer price rounding can put the derived width one unit below its
        # configured value, so use the immutable accepted policy for grouping.
        model=state["policy_history"][terms["policy_version"]]["model"]
        width = model.get("base_width_ppm",0)/100 if model.get("base_width_ppm",0) else model["base_width_bps"]
        width_outcomes[width][stage["status"]] += 1
        touches = [(at, px) for at, px in paired if stage["start"] <= at < stage["expiry"] and
                   (px <= terms["lower"] or px >= terms["upper"])]
        if stage["status"] == "survived" and touches:
            mismatches.append(stage["id"])
        if stage["status"] == "exploded" and not touches:
            mismatches.append(stage["id"])
        checked += 1
    if mismatches:
        raise ValueError(f"oracle barrier mismatches in {directory}: {mismatches}")
    traders = summary["traders"]
    pnl = sum(t["pnl_usdc_units"] for t in traders)
    if pnl != -summary["lp_realized_pnl_usdc_units"]:
        raise ValueError(f"customer/LP trading PnL mismatch: {directory}")
    if summary["usdc_total_supply_units"] != summary["usdc_sum_balances_units"]:
        raise ValueError(f"USDC conservation mismatch: {directory}")
    book_count, spreads, prices = 0, [], set()
    peak_active, peak_exposure, peak_utilization_bps = 0, 0, 0
    with (directory / "events.jsonl").open() as stream:
        for line in stream:
            event = json.loads(line)
            if event["kind"] == "risk_snapshot":
                risk = event["data"]
                peak_active = max(peak_active, risk["active"])
                peak_exposure = max(peak_exposure, risk["exposure_usdc_units"])
                if risk["lp_usdc_units"]:
                    peak_utilization_bps = max(peak_utilization_bps, risk["exposure_usdc_units"] * 10000 // risk["lp_usdc_units"])
            if event["kind"] == "market_activeAssetCtx":
                prices.add(event["data"]["raw"]["data"]["ctx"]["oraclePx"])
            if event["kind"] == "market_bbo":
                book_count += 1
                bid, ask = event["data"]["raw"]["data"]["bbo"]
                if bid and ask:
                    spreads.append(Decimal(ask["px"]) - Decimal(bid["px"]))
    strategy_pnl = defaultdict(int)
    for trader in traders:
        strategy_pnl[trader.get("strategy", "legacy ladder")] += trader["pnl_usdc_units"]
    return {"ledger_peak_exposure_usdc_units": ledger_peak_exposure, "ledger_min_lp_usdc_units": ledger_min_lp,
            "ledger_min_capital_buffer_usdc_units": ledger_min_buffer,
            "strategy_customer_pnl_usdc_units": dict(strategy_pnl), "sampled_peak_active_positions": peak_active,
            "sampled_peak_exposure_usdc_units": peak_exposure, "sampled_peak_exposure_utilization_bps": peak_utilization_bps,
            "run": directory.parent.name, "traders": len(traders), "outcomes": dict(Counter(s["status"] for s in stages)),
            "stage_barriers_independently_checked": checked, "barrier_mismatches": mismatches,
            "lp_pnl_usdc_units": summary["lp_realized_pnl_usdc_units"], "final_lp_usdc_units": summary["final_lp_usdc_units"],
            "customer_pnl_usdc_units": pnl, "checkpoint_count": summary["checkpoints"],
            "oracle_messages": commands["oracle"], "distinct_oracle_prices": len(prices), "bbo_messages": book_count,
            "bbo_spread_min_usd": str(min(spreads)) if spreads else None,
            "bbo_spread_max_usd": str(max(spreads)) if spreads else None,
            "unique_stakes": len({t["initial_stake_usdc_units"] for t in traders}),
            "widths_bps": sorted(width_outcomes), "outcomes_by_width": dict(sorted(width_outcomes.items())),
            "strategies": dict(Counter(t.get("strategy", "legacy ladder") for t in traders)),
            "max_stage_reached": max(s["terms"]["index"] for s in stages),
            "runs_completed": sum(t.get("runs_completed", 1) for t in traders),
            "execution_network": summary.get("execution_network", "local Anvil, chain 31337"),
            "postgres_replay_verified": summary["postgres_replay_verified"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=ROOT / ".local/live-runs")
    parser.add_argument("--output", type=Path, default=ROOT / ".local/papertrade-analysis")
    args = parser.parse_args()
    fixture = [json.loads(line) for line in (ROOT / "engine/testdata/paper-commands.jsonl").read_text().splitlines() if line]
    runs = [analyze(path.parent) for path in sorted(args.runs.glob("*/evidence/summary.json"))]
    failed = [str(path.parent.parent) for path in sorted(args.runs.glob("*/evidence/events.jsonl"))
              if any(json.loads(line)["kind"] == "run_failed" for line in path.open())]
    result = {"fixture_commands": len(fixture), "fixture_accounts": len({c["actor"] for c in fixture if c.get("actor")}),
              "runs": runs, "failed_runs_retained": failed,
              "limits": "Short correlated live experiments and synthetic paper fixture; no calibrated pricing or public HyperEVM settlement evidence."}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Repository paper-trading data", "", f"The deterministic paper fixture has {len(fixture)} commands and one account. It is a regression fixture, not a historical trading dataset.", "",
             "Each completed live run was independently checked against paired oraclePx receipt observations: every surviving stage had no barrier touch; every exploded stage had a valid touch in [start, expiry). Journal continuity, customer/LP PnL and USDC conservation were checked. Exact reducer replay is verified by the Go runner.", "",
             "| Run | Users | Stages | Outcomes | LP PnL USDC | Checkpoints | Stake sizes | Max stage |", "|---|---:|---:|---|---:|---:|---:|---:|"]
    for r in runs:
        lines.append(f"| {r['run']} | {r['traders']} | {r['stage_barriers_independently_checked']} | {r['outcomes']} | {money(r['lp_pnl_usdc_units'])} | {r['checkpoint_count']} | {r['unique_stakes']} | {r['max_stage_reached']} |")
    if runs:
        latest = runs[-1]
        lines += ["", f"Latest run: {latest['traders']} wallets, {latest['runs_completed']} completed games, {latest['unique_stakes']} stake sizes, {len(latest['widths_bps'])} widths, and stages through {latest['max_stage_reached']}.",
                  f"Sampled peak concurrent open positions: {latest['sampled_peak_active_positions']}; sampled peak exposure: {money(latest['sampled_peak_exposure_usdc_units'])} USDC. Samples occur approximately every five seconds, so peaks are lower bounds.", "",
                  "| Half-width bps | Survived | Breached | Voided |", "|---:|---:|---:|---:|"]
        for width, outcomes in latest["outcomes_by_width"].items():
            lines.append(f"| {width} | {outcomes.get('survived', 0)} | {outcomes.get('exploded', 0)} | {outcomes.get('voided', 0)} |")
        lines += ["", "| Strategy | Wallets | Customer trading PnL USDC |", "|---|---:|---:|"]
        for strategy, count in latest["strategies"].items():
            lines.append(f"| {strategy} | {count} | {money(latest['strategy_customer_pnl_usdc_units'][strategy])} |")
    lines += ["", "These runs deliberately use untrained widths. Observed survival rates and LP losses do not establish fair pricing: traders share the same short BTC path, widths vary, and stages/rollovers are correlated. A long historical out-of-sample dataset and calibration remain necessary.", "",
              f"Failed attempts retained for diagnosis: {len(failed)}. These are excluded from completed-run statistics.", "", "Public HyperEVM inclusion/finality has not been tested. The separate fork report records local compatibility against pinned HyperEVM testnet state."]
    (args.output / "report.md").write_text("\n".join(lines) + "\n")
    print(args.output / "report.md")
    print(json.dumps({"completed_runs": len(runs), "independently_checked_stages": sum(r['stage_barriers_independently_checked'] for r in runs), "barrier_mismatches": 0}))


if __name__ == "__main__":
    main()
