from copy import deepcopy
import unittest

from capture_policy_equivalence import compare_policy,ZERO_FIELDS


class CapturePolicyComparisonTests(unittest.TestCase):
    def fixture(self):
        frozen=dict(max_gap_ms=8000,model=dict(version='fixed',base_width_ppm=314),
                    markets=dict(ETH=dict(version='fixed-eth')))
        recorded=deepcopy(frozen)
        for model in (recorded['model'],recorded['markets']['ETH']):
            model.update({field:0 for field in ZERO_FIELDS})
        return recorded,frozen

    def test_only_struct_zero_expansion_is_equivalent(self):
        recorded,frozen=self.fixture();original=deepcopy(frozen)
        result=compare_policy(recorded,frozen)
        self.assertTrue(result['semantic_policy_match']);self.assertFalse(result['exact_json_object_match'])
        self.assertEqual(len(result['explicit_zero_fields_added']),8)
        self.assertEqual(frozen,original)
        self.assertTrue(compare_policy(recorded,recorded)['exact_json_object_match'])

    def test_changed_values_missing_fields_and_unknown_additions_reject(self):
        recorded,frozen=self.fixture()
        for field,value in (('max_gap_ms',16000),('extra',0)):
            changed=deepcopy(recorded);changed[field]=value
            with self.assertRaises(ValueError):compare_policy(changed,frozen)
        for value in (1,False,0.0,None):
            changed=deepcopy(recorded);changed['markets']['ETH']['max_drift_bps']=value
            with self.assertRaises(ValueError):compare_policy(changed,frozen)
        changed=deepcopy(recorded);del changed['model']['control_width_bps']
        with self.assertRaises(ValueError):compare_policy(changed,frozen)
        changed=deepcopy(recorded);changed['markets']['ETH']['base_width_ppm']=0
        with self.assertRaises(ValueError):compare_policy(changed,frozen)
