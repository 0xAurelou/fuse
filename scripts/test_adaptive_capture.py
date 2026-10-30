from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analyze_adaptive_capture import analyze,replay
from freeze_adaptive_capture import freeze,ROOT
from frozen_context_cdf import fit
from prospective_capture_v2 import verify_artifacts
from test_frozen_context_cdf import market_rows
from test_frozen_conditional_cdf import values
from test_native_adaptive_data import receipts


class AdaptiveCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=market_rows(400)
        cls.models=dict(fixed={},frozen={f:dict(model=fit(cls.data,f)) for f in ('timing','market')})

    def fixture(self,root):
        research=root/'research';research.mkdir()
        result=dict(selected='market:priceable_open')
        for name in ('research.json','audit.json','selection.json'):
            (research/name).write_text(json.dumps(result))
        policy=root/'policy.json';p=json.loads((ROOT/'engine/config/paper.json').read_text())
        p.update(duration_ms=30000,max_gap_ms=8000,disagreement_ms=1500);policy.write_text(json.dumps(p))
        recorder=root/'recorder';recorder.write_bytes(b'fixture recorder')
        directory=root/'trial'
        with patch('freeze_adaptive_capture.bindings',return_value=(result,{},self.models,1)), \
                patch('freeze_adaptive_capture.wall_ms',return_value=1000000):
            spec=freeze(directory,research,policy,recorder)
        return directory,spec

    def test_freeze_pins_models_sources_inputs_and_observation_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,spec=self.fixture(Path(tmp));verified=verify_artifacts(directory)
            self.assertEqual(spec,verified);self.assertEqual(spec['duration_hours'],8)
            self.assertEqual(spec['primary_candidate'],'market:priceable_open')
            self.assertFalse(spec['production_approved']);self.assertFalse(spec['economics_validated'])
            self.assertIn('native_adaptive_data.py',spec['files_sha256'])
            self.assertIn('adaptive-models.json',spec['files_sha256'])
            self.assertEqual((directory/'analyze.py').read_bytes(),(ROOT/'scripts/analyze_adaptive_capture.py').read_bytes())
            policy=json.loads((directory/'frozen-policy.json').read_text())
            self.assertIn('transport only',policy['model']['dataset'])
            self.assertFalse((directory/'manifest.json').exists())
            (directory/'adaptive-models.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'artifact changed'):verify_artifacts(directory)

    def test_replay_has_private_restart_state_and_keeps_all_quote_denominators(self):
        data=[dict(r,entry_healthy=True,market_regime='range') for r in deepcopy(self.data[:80])]
        models=deepcopy(self.models)
        for family in models['frozen'].values():
            family['model']['floor_coefficients']=[30]+[0]*len(family['model']['center'])
        # Forced high predicted floor learns downward on moving paths, but the
        # quote-time priceability restriction keeps the coverage level fixed.
        for r in data:r['move']=50
        with patch('analyze_adaptive_capture.price',side_effect=lambda rows,_:([],values(rows))):
            summaries,saved,pairs=replay(data,models,['retained_open','market:priceable_open'],data[0]['start'],data[-1]['expiry'])
        continuous=saved['continuous']['market:priceable_open'];restart=saved['restart_half']['market:priceable_open']
        self.assertLess(continuous[40]['frozen_logit_delta'],0)
        self.assertEqual(restart[40]['frozen_logit_delta'],0)
        self.assertTrue(all(p['frozen_level']==.48 for p in continuous))
        full=next(r for r in summaries if r['candidate']=='market:priceable_open' and r['mode']=='continuous'
                  and r['interval']=='full' and r['axis']=='all')
        self.assertEqual(full['grid_windows'],80);self.assertEqual(full['offered_pre_entry_decisions'],80)
        self.assertEqual(full['eligible_quote_fraction'],1.);self.assertEqual(len(pairs),4)

    def test_completed_horizon_with_outage_cannot_pass_collection_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,spec=self.fixture(Path(tmp));start=1001000;end=start+8*3600000
            raw=receipts()
            for p in raw:p.update(at=p['at']+start,hash='fixture-head')
            (directory/'receipts.jsonl').write_text(''.join(json.dumps(p)+'\n' for p in raw))
            manifest=dict(frozen_at_ms=start,duration_ms=8*3600000,
                          policy=json.loads((directory/'frozen-policy.json').read_text()))
            (directory/'manifest.json').write_text(json.dumps(manifest))
            verified=dict(manifest=manifest,head=dict(hash='fixture-head',at=raw[-1]['at']))
            def reference(rows,_):
                ref=values(rows)
                for p in ref:
                    if p['row']['adaptive_features'] is None:p.update(width_ppm=None,shadow_survived=None,survived=None)
                    elif not p['row']['valid']:p.update(shadow_survived=None,survived=None)
                return [],ref
            with patch('analyze_adaptive_capture.subprocess.check_output',return_value=json.dumps(verified)), \
                    patch('analyze_adaptive_capture.time.time_ns',return_value=(end+1)*1000000), \
                    patch('analyze_adaptive_capture.price',side_effect=reference):
                result=analyze(directory,directory/'fuse-capture',directory/'analysis.json')
            self.assertEqual(result['grid_windows'],960)
            self.assertFalse(result['collection_quality_met']);self.assertTrue(result['collection_deadline_elapsed'])
            self.assertTrue(result['prospectively_frozen']);self.assertFalse(result['economics_validated'])
            self.assertLess(result['full_horizon_healthy_fraction'],.1)
            self.assertTrue((directory/'analysis-predictions.jsonl.gz').exists())
            with self.assertRaisesRegex(ValueError,'preserve existing'):analyze(directory,directory/'fuse-capture',directory/'analysis.json')

    def test_early_horizon_and_changed_policy_never_reach_pricing(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,spec=self.fixture(Path(tmp));start=1001000
            manifest=dict(frozen_at_ms=start,duration_ms=8*3600000,
                          policy=json.loads((directory/'frozen-policy.json').read_text()))
            with patch('analyze_adaptive_capture.subprocess.check_output',return_value=json.dumps(dict(manifest=manifest,head={}))), \
                    patch('analyze_adaptive_capture.time.time_ns',return_value=start*1000000), \
                    patch('analyze_adaptive_capture.replay') as prices:
                with self.assertRaisesRegex(ValueError,'not elapsed'):analyze(directory,directory/'fuse-capture',directory/'analysis.json')
                prices.assert_not_called()
            manifest['policy']['max_gap_ms']=16000
            with patch('analyze_adaptive_capture.subprocess.check_output',return_value=json.dumps(dict(manifest=manifest,head={}))):
                with self.assertRaisesRegex(ValueError,'does not match'):analyze(directory,directory/'fuse-capture',directory/'analysis.json')
            self.assertFalse((directory/'analysis.json').exists())
