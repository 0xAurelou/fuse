"""Negative tests for the proof gate: incomplete symbolic runs must never pass CI."""

from copy import deepcopy
import unittest

from verify_formal import validate_math_report, validate_report


class ProofGateTest(unittest.TestCase):
    def setUp(self):
        self.registry = {"contract": "Proof", "properties": [{"function": "check_value(uint64)"}]}
        self.artifact = {"abi": [{"type": "function", "name": "check_value", "inputs": [{"type": "uint64"}]}]}
        self.report = {
            "exitcode": 0,
            "test_results": {"Proof": [{
                "name": "check_value(uint64)", "exitcode": 0, "num_models": 0,
                "num_paths": [3, 1, 0], "num_bounded_loops": 0,
            }]},
        }

    def test_accept_complete_proof(self):
        self.assertEqual(validate_report(self.report, self.registry, self.artifact), 1)

    def test_reject_incomplete_and_vacuous_proofs(self):
        for field, value in [("exitcode", 2), ("num_models", 1), ("num_bounded_loops", 1),
                             ("num_paths", [3, 0, 0]), ("num_paths", [3, 1, 1]), ("num_paths", None)]:
            with self.subTest(field=field, value=value):
                report = deepcopy(self.report)
                report["test_results"]["Proof"][0][field] = value
                with self.assertRaises(ValueError):
                    validate_report(report, self.registry, self.artifact)

    def test_reject_missing_duplicate_and_wrong_proofs(self):
        for checks in [[], self.report["test_results"]["Proof"] * 2,
                       [dict(self.report["test_results"]["Proof"][0], name="check_other(uint64)")]]:
            with self.subTest(checks=checks):
                report = deepcopy(self.report)
                report["test_results"]["Proof"] = checks
                with self.assertRaises(ValueError):
                    validate_report(report, self.registry, self.artifact)

    def test_reject_registry_drift(self):
        artifact = deepcopy(self.artifact)
        artifact["abi"][0]["name"] = "check_renamed"
        with self.assertRaises(ValueError):
            validate_report(self.report, self.registry, artifact)

    def test_reject_wrong_contract_or_failed_run(self):
        for report in [dict(self.report, exitcode=1), dict(self.report, test_results={"Other": []})]:
            with self.assertRaises(ValueError):
                validate_report(report, self.registry, self.artifact)

    def test_integer_lemma_gate(self):
        registry = {"math_lemmas": ["rounding"]}
        report = {"solver": "4.12.6", "lemmas": [
            {"name": "rounding", "result": "unsat", "assumptions_satisfiable": True}
        ]}
        self.assertEqual(validate_math_report(report, registry), 1)
        for field, value in [("result", "unknown"), ("result", "sat"), ("assumptions_satisfiable", False)]:
            modified = deepcopy(report)
            modified["lemmas"][0][field] = value
            with self.assertRaises(ValueError):
                validate_math_report(modified, registry)
        for lemmas in [[], report["lemmas"] * 2]:
            with self.assertRaises(ValueError):
                validate_math_report(dict(report, lemmas=lemmas), registry)


if __name__ == "__main__":
    unittest.main()
