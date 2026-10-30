from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analyze_adaptive_capture import analyze
from prepare_adaptive_policy_compat import patched_source
import test_adaptive_capture as fixtures
from test_native_adaptive_data import receipts
from test_frozen_conditional_cdf import values


class AdaptivePolicyCompatibilityTests(unittest.TestCase):
    def test_semantically_identical_manifest_preserves_all_numbers_and_predictions(self):
        fixture=fixtures.AdaptiveCaptureTests();fixture.setUpClass()
        with tempfile.TemporaryDirectory() as temp:
            directory,spec=fixture.fixture(Path(temp));start=1001000;end=start+8*3600000
            raw=receipts()
            for r in raw:r.update(at=r['at']+start,hash='fixture-head')
            (directory/'receipts.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in raw))
            original=json.loads((directory/'frozen-policy.json').read_text())
            recorded=deepcopy(original)
            for model in (recorded['model'],*recorded.get('markets',{}).values()):
                for key in ('base_width_bps','control_width_bps','max_drift_bps','volatility_factor'):
                    model.setdefault(key,0)
            # Add omitted optional-market zeros to exercise the real discrepancy.
            original.setdefault('markets',{})['ETH']={'version':'fixture-eth'}
            recorded.setdefault('markets',{})['ETH']=dict(version='fixture-eth',base_width_bps=0,
                control_width_bps=0,max_drift_bps=0,volatility_factor=0)
            manifest=dict(frozen_at_ms=start,duration_ms=8*3600000,policy=recorded)
            (directory/'manifest.json').write_text(json.dumps(manifest))
            namespace=dict(__name__='supplemental_fixture',__file__=str(directory/'analyze.py'))
            exec(compile(patched_source((directory/'analyze.py').read_text()),'supplemental_fixture','exec'),namespace)
            def reference(rows,_):
                result=values(rows)
                for p in result:
                    if p['row']['adaptive_features'] is None:
                        p.update(width_ppm=None,shadow_survived=None,survived=None)
                    elif not p['row']['valid']:p.update(shadow_survived=None,survived=None)
                return [],result
            namespace['price']=reference
            for name,policy in (('original',original),('compatible',recorded)):
                verified=dict(manifest=dict(manifest,policy=policy),head=dict(hash='fixture-head'))
                # Model source bindings stay real; only the synthetic policy
                # fixture differs from the originally generated packet.
                with patch('analyze_adaptive_capture.verify_artifacts',return_value=spec), \
                        patch('prospective_capture_v2.verify_artifacts',return_value=spec), \
                        patch('analyze_adaptive_capture.price',side_effect=reference), \
                        patch('subprocess.check_output',return_value=json.dumps(verified)), \
                        patch('time.time_ns',return_value=(end+1)*1000000):
                    (directory/'frozen-policy.json').write_text(json.dumps(original))
                    if name=='original':result=analyze(directory,directory/'fuse-capture',directory/(name+'.json'))
                    else:
                        namespace['verify_artifacts']=lambda _:spec
                        result=namespace['analyze'](directory,directory/'fuse-capture',directory/(name+'.json'))
                if name=='original':baseline=result
                else:
                    self.assertEqual(result.pop('analysis_procedure'),'supplemental-policy-zero-compatibility-v1')
                    self.assertFalse(result.pop('unmodified_frozen_analyzer'))
                    # Compressed files embed creation metadata; compare records.
                    result.pop('predictions_sha256');baseline.pop('predictions_sha256')
                    self.assertEqual(result,baseline)
            with gzip.open(directory/'original-predictions.jsonl.gz','rt') as a, \
                    gzip.open(directory/'compatible-predictions.jsonl.gz','rt') as b:
                self.assertEqual(a.read(),b.read())

    def test_unexpected_analyzer_patch_is_rejected(self):
        with self.assertRaises(ValueError):patched_source('unknown analyzer')
