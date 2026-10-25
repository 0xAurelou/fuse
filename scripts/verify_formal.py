#!/usr/bin/env python3
"""Run the pinned symbolic verifier and reject incomplete or vacuous results."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "formal-results" / "halmos.json"


def validate_report(report, registry, artifact):
    """Fail closed even if Halmos reports PASS after hitting its loop bound."""
    expected = [entry["function"] for entry in registry["properties"]]
    if not expected or len(expected) != len(set(expected)):
        raise ValueError("empty or duplicate proof registry")
    compiled = {
        "{}({})".format(item["name"], ",".join(arg["type"] for arg in item["inputs"]))
        for item in artifact["abi"]
        if item["type"] == "function" and item["name"].startswith("check_")
    }
    if set(expected) != compiled:
        raise ValueError("proof registry and compiled harness differ")
    results = report.get("test_results", {})
    if report.get("exitcode") != 0 or set(results) != {registry["contract"]}:
        raise ValueError("verifier failed or ran the wrong contracts")
    checks = results[registry["contract"]]
    if len(checks) != len(expected) or {check["name"] for check in checks} != set(expected):
        raise ValueError("missing, duplicate or unexpected proof results")
    for check in checks:
        paths = check.get("num_paths")
        if (
            check.get("exitcode") != 0
            or check.get("num_models") != 0
            or check.get("num_bounded_loops") != 0
            or not isinstance(paths, list)
            or len(paths) != 3
            or paths[0] <= 0
            or paths[1] <= 0
            or paths[2] != 0
        ):
            raise ValueError("failed, incomplete or vacuous proof: " + check["name"])
    return len(checks)


def validate_math_report(report, registry):
    expected = registry["math_lemmas"]
    lemmas = report.get("lemmas", [])
    if (report.get("solver") != "4.12.6" or not expected or len(expected) != len(set(expected))
            or len(lemmas) != len(expected) or {lemma["name"] for lemma in lemmas} != set(expected)):
        raise ValueError("missing, duplicate or unexpected integer lemmas")
    for lemma in lemmas:
        if lemma.get("result") != "unsat" or lemma.get("assumptions_satisfiable") is not True:
            raise ValueError("failed or vacuous integer lemma: " + lemma["name"])
    return len(lemmas)


def main():
    os.chdir(ROOT)
    halmos = shutil.which(os.environ.get("HALMOS_BIN", "halmos"))
    if not halmos:
        raise ValueError("Halmos is missing; install formal/requirements.txt in a Python 3.12 virtual environment")
    version = subprocess.check_output([halmos, "--version"], text=True).strip()
    if version != "halmos 0.2.6":
        raise ValueError("expected halmos 0.2.6, got " + version)
    # Prefer the solver installed alongside Halmos, rather than an unrelated system Z3.
    sibling = Path(halmos).resolve().parent / "z3"
    solver = os.environ.get("Z3_BIN") or (str(sibling) if sibling.is_file() else shutil.which("z3"))
    if not solver:
        raise ValueError("Z3 is missing; install formal/requirements.txt")
    solver = str(Path(solver).resolve())
    solver_version = subprocess.check_output([solver, "--version"], text=True).strip()
    if not solver_version.startswith("Z3 version 4.12.6 "):
        raise ValueError("expected Z3 4.12.6, got " + solver_version)
    REPORT.parent.mkdir(exist_ok=True)
    if REPORT.exists():
        REPORT.unlink()  # Never validate stale output from an earlier run.
    math_report = REPORT.with_name("math.json")
    if math_report.exists():
        math_report.unlink()
    env = dict(os.environ, FOUNDRY_PROFILE="formal")
    # Install the pinned solc on a clean CI runner before offline witness execution.
    subprocess.run(["forge", "build", "--quiet"], env=env, check=True)
    # At least one successful concrete execution is required for each symbolic harness.
    subprocess.run(["forge", "test", "--offline", "--match-contract", "FormalWitness"], env=env, check=True)
    registry = json.loads((ROOT / "formal/properties.json").read_text())
    witness = json.loads((ROOT / "out-formal/FUSEFormalWitness.t.sol/FormalWitness.json").read_text())
    expected_witnesses = {"test_" + entry["function"].split("(")[0] for entry in registry["properties"]}
    actual_witnesses = {item["name"] for item in witness["abi"]
                        if item["type"] == "function" and item["name"].startswith("test_check_")}
    if expected_witnesses != actual_witnesses:
        raise ValueError("missing or unexpected concrete witnesses")
    tool_python = Path(halmos).resolve().parent / "python"
    subprocess.run([str(tool_python) if tool_python.exists() else sys.executable,
                    str(ROOT / "formal/math_lemmas.py")], check=True)
    lemma_count = validate_math_report(json.loads(math_report.read_text()), registry)
    # Halmos 0.2.6 splits solver-command on whitespace. Alias the pinned executable
    # through a path without spaces, including on macOS with uv's Application Support path.
    with tempfile.TemporaryDirectory(prefix="fuse-formal-", dir="/tmp") as tool_dir:
        Path(tool_dir, "z3").symlink_to(solver)
        env["PATH"] = tool_dir + os.pathsep + env.get("PATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        result = subprocess.run([halmos, "--no-status"], env=env)
        if result.returncode:
            raise ValueError("Halmos returned exit code " + str(result.returncode))
    artifact = json.loads((ROOT / "out-formal/FUSEFormal.t.sol/FUSEFormal.json").read_text())
    count = validate_report(json.loads(REPORT.read_text()), registry, artifact)
    print("Verified {} registered properties; no blocked paths, loop truncation or vacuous results.".format(count))
    print("Verified {} registered integer lemmas.".format(lemma_count))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print("Formal verification failed: " + str(error), file=sys.stderr)
        sys.exit(1)
