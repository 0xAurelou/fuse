"""Unbounded integer lemmas for FUSE accounting formulas, separate from bytecode proofs.

These prove the mathematical model, not equivalence of arbitrary EVM states to that
model. Halmos and concrete witnesses separately check the deployed implementation.
"""

import json
from pathlib import Path

from z3 import And, Ints, Not, Solver, get_version_string, sat, unsat


def prove(name, assumptions, proposition):
    solver = Solver()
    solver.set(timeout=15000)
    solver.add(*assumptions)
    if solver.check() != sat:
        raise RuntimeError(name + ": assumptions are unsatisfiable or solver is unknown")
    solver.add(Not(proposition))
    result = solver.check()
    if result != unsat:
        raise RuntimeError(name + ": " + str(result) + (" " + str(solver.model()) if result == sat else ""))
    print("[PROVED] " + name, flush=True)
    return {"name": name, "result": "unsat", "assumptions_satisfiable": True}


def main():
    if get_version_string() != "4.12.6":
        raise RuntimeError("Expected pinned Z3 4.12.6")
    results = []
    profit, consumed, amount, bps = Ints("profit consumed amount bps")
    eligible = profit - consumed
    consumed_delta = (amount * 10000 + bps - 1) / bps
    results.append(prove("profit_consumption_within_eligible_for_all_configured_bps", [
        profit > consumed, consumed >= 0, amount > 0, bps >= 1, bps <= 5000,
        amount <= eligible * bps / 10000,
    ], And(consumed_delta > 0, consumed + consumed_delta <= profit)))

    first, second, numerator, denominator = Ints("first second numerator denominator")
    common = [first >= 0, second >= 0, numerator >= 0, denominator > 0]
    q1 = first * numerator / denominator
    q2 = second * numerator / denominator
    combined = (first + second) * numerator / denominator
    results.append(prove("cumulative_redemption_telescopes_and_never_decreases", common,
                         And(combined - q1 >= 0, q1 + (combined - q1) == combined)))
    results.append(prove("wallet_splitting_never_increases_payout_and_rounds_less_than_one_unit", common,
                         And(q1 + q2 <= combined, combined - q1 - q2 <= 1)))
    results.append(prove("single_floor_rounding_is_strictly_less_than_one_atomic_unit", common,
                         And(q1 * denominator <= first * numerator,
                             first * numerator < (q1 + 1) * denominator)))

    ceil1 = (first * 10000 + bps - 1) / bps
    ceil2 = (second * 10000 + bps - 1) / bps
    ceil_combined = ((first + second) * 10000 + bps - 1) / bps
    results.append(prove("splitting_reserve_distributions_cannot_save_consumed_profit",
                         [first >= 0, second >= 0, bps >= 1, bps <= 5000], ceil1 + ceil2 >= ceil_combined))

    supply, reserve, net_bps = Ints("supply reserve net_bps")
    payout1 = first * reserve * net_bps / (supply * 10000)
    payout2 = second * reserve * net_bps / (supply * 10000)
    results.append(prove("two_account_discounted_redemptions_remain_backed", [
        first >= 0, second >= 0, supply > 0, first + second <= supply,
        reserve >= 0, net_bps >= 0, net_bps <= 10000,
    ], And(payout1 >= 0, payout2 >= 0, payout1 + payout2 <= reserve)))

    balance, prior, new, paid = Ints("balance prior new paid")
    results.append(prove("deducting_prior_liabilities_preserves_backing_after_claims", [
        balance >= prior, prior >= 0, new >= 0, new <= balance - prior,
        paid >= 0, paid <= prior + new,
    ], And(prior + new - paid >= 0, prior + new - paid <= balance - paid)))

    output = Path(__file__).resolve().parents[1] / "formal-results/math.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({"solver": get_version_string(), "lemmas": results}, indent=2) + "\n")
    print("Proved {} integer lemmas.".format(len(results)))


if __name__ == "__main__":
    main()
