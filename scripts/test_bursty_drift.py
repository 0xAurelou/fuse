from copy import deepcopy
import unittest

from bursty_drift import SPECS,spec,reprice,mixture_quantile
from research_bursty_drift import choose,phases,paired_cells
from test_bursty_pricing import references,model
from test_flat_pause import prediction
from test_oracle_activity import training


class BurstyDriftTests(unittest.TestCase):
    def test_masks_eligibility_other_states_and_inputs_are_preserved(self):
        v=references()
        for i,p in enumerate(v):p['row']['activity_state']=('active','sparse','frozen','bursty')[i%4]
        v[7].update(paused=True,survived=None)
        v[11]['row']['valid']=False;v[11].update(shadow_survived=None,survived=None)
        v[15].update(width_ppm=None,shadow_survived=None,survived=None)
        original=deepcopy(v)
        for c in SPECS:
            if c['family']=='comparator':continue
            out=reprice(v,model(),c)
            for a,b in zip(out,v):
                self.assertEqual((a['paused'],a['width_ppm'] is None,a['shadow_survived'] is None),
                                 (b['paused'],b['width_ppm'] is None,b['shadow_survived'] is None))
                if b['row']['activity_state']!='bursty':self.assertEqual((a['width_ppm'],a['shadow_survived']),(b['width_ppm'],b['shadow_survived']))
                if a['width_ppm'] is not None:self.assertTrue(1<=a['width_ppm']<=50000)
        self.assertEqual(v,original)

    def test_future_validity_and_movement_wait_for_maturity(self):
        v=references();changed=deepcopy(v)
        for p in changed[40:]:p['row'].update(valid=False,move=10000)
        for c in SPECS:
            if c['family']=='comparator':continue
            a,b=reprice(v,model(),c),reprice(changed,model(),c)
            self.assertEqual([p['width_ppm'] for p in a[:42]],[p['width_ppm'] for p in b[:42]])

    def test_clock_adapts_before_next_bursty_quote(self):
        v=references(30)
        for p in v[1:-1]:p['row']['activity_state']='active'
        c=spec('clock',family='clock',memory=120,age_hours=4,half_life=0)
        out=reprice(v,model(),c)
        self.assertLess(out[-1]['drift_correction'],.95)
        self.assertTrue(all(p['width_ppm']==100 for p in out[1:-1]))

    def test_cdf_blends_distributions_instead_of_quantiles(self):
        m=model()['states']['bursty'];m.update(minimum_width_floor=.25,positive_ratios=[2,4],static_factor=1)
        c=spec('cdf',prior=4,parent_mass=0,half_life=0)
        leaf=[dict(expiry=0,ratio=.01,floor=True)]
        self.assertEqual(mixture_quantile([],leaf,m,100,0,c,.48),2)
        c['prior_mass']=1
        self.assertEqual(mixture_quantile([],leaf,m,100,0,c,.48),.01)

    def test_parent_does_not_double_count_bursty_and_frozen_never_enters(self):
        v=references(20)
        out=reprice(v,model(),spec('cdf'))
        self.assertEqual(out[-1]['drift_parent_mature'],0)
        for p in v[:-1]:p['row']['activity_state']='active'
        out=reprice(v,model(),spec('cdf'))
        self.assertEqual(out[-1]['drift_parent_mature'],18)
        self.assertEqual(out[-1]['drift_leaf_mature'],0)
        for p in v[:-1]:p['row']['activity_state']='frozen'
        self.assertEqual(reprice(v,model(),spec('cdf'))[-1]['drift_parent_mature'],0)

    def test_recency_weights_reverse_old_evidence_when_new_distribution_changes(self):
        m=model()['states']['bursty'];m.update(minimum_width_floor=0,positive_ratios=[1],static_factor=1)
        leaf=[dict(expiry=0,ratio=.1,floor=False) for _ in range(10)]
        leaf += [dict(expiry=3_600_000,ratio=2,floor=False) for _ in range(4)]
        c=spec('cdf',prior=1,parent_mass=0,half_life=0)
        self.assertEqual(mixture_quantile([],leaf,m,100,3_600_000,c,.48),.1)
        c['half_life_ms']=15*60_000
        self.assertEqual(mixture_quantile([],leaf,m,100,3_600_000,c,.48),2)

    def test_paused_references_learn_and_rate_memory_age_period_bounds(self):
        v=references(100)
        for p in v:p.update(paused=True,survived=None)
        c=spec('cdf',memory=20)
        out=reprice(v,model(),c)
        self.assertTrue(all(p['survived'] is None for p in out))
        self.assertTrue(all(p['drift_leaf_mature']<=10 for p in out))
        for a,b in zip(out,out[1:]):
            self.assertGreaterEqual(b['drift_correction'],.95*a['drift_correction']-1e-12)
            self.assertLessEqual(b['drift_correction'],1.05*a['drift_correction']+1e-12)
        v += [prediction(10_000_000),prediction(10_030_000,period='next')]
        for p in v[-2:]:p['row']['activity_state']='bursty'
        out=reprice(v,model(),c)
        self.assertEqual(out[-2]['drift_leaf_mature'],0)
        self.assertEqual(out[-1]['drift_leaf_mature'],0)

    def test_feedback_uses_own_width_and_decays_between_bursts(self):
        v=references(10,move=75);m=model();m['states']['bursty']['static_factor']=.5
        c=spec('feedback',family='feedback')
        out=reprice(v,m,c)
        self.assertGreater(out[2]['drift_correction'],1)
        altered=deepcopy(v)
        for p in altered:p['shadow_survived']=False
        self.assertEqual([p['width_ppm'] for p in out],[p['width_ppm'] for p in reprice(altered,m,c)])
        # At a long gap all recent outcome pools expire and the leaky target returns toward one.
        v.append(prediction(20_000_000));v[-1]['row']['activity_state']='bursty'
        out=reprice(v,m,c)
        self.assertAlmostEqual(out[-1]['drift_requested'],1,places=3)

    def test_guard_keeps_directional_base_widths(self):
        v=references()
        for i,p in enumerate(v):p['row']['market_regime']=('mixed','pump','dump')[i%3]
        out=reprice(v,model(),spec('guard',guard=True))
        self.assertTrue(all(p['width_ppm']==100 for p in out if p['row']['market_regime'] in ('pump','dump')))

    def test_phase_membership_is_chosen_before_later_censoring(self):
        v=references(30);v[0]['row']['valid']=False;v[0].update(survived=None,shadow_survived=None)
        s=dict(id='case',source='raw',period='day',split='test',mode='restart',intervals=[dict(start=0,end=900000,hour=0)])
        rows=phases(s,v,'candidate');first=next(r for r in rows if r['phase']=='first12')
        self.assertEqual(first['grid_windows'],12);self.assertEqual(first['windows'],11)
        self.assertEqual(next(r for r in rows if r['phase']=='later')['windows'],18)

    def test_pairing_scores_identical_underlying_eligible_paths_only(self):
        v=references(4);w=deepcopy(v);w[0].update(shadow_survived=None,survived=None)
        w[1]['width_ppm']=50
        sessions=[dict(id=mode,source='raw',period='day',mode=mode,intervals=[dict(start=0,end=120000)]) for mode in ('restart','continuous')]
        rows=paired_cells(sessions,{'restart':v,'continuous':w},'candidate')
        self.assertEqual(rows[0]['common_paths'],3);self.assertEqual(rows[0]['restart_eligible'],4)
        self.assertEqual(rows[0]['width_disagreements'],1)
        w[2]['row']['move']=999
        with self.assertRaises(ValueError):paired_cells(sessions,{'restart':v,'continuous':w},'candidate')

    def test_later_dates_do_not_enter_both_mode_selection(self):
        dates=[f'day-{i:02}' for i in range(24)]
        rows=[dict(r,period=dates[d],start=d*10_000_000+r['start'],expiry=d*10_000_000+r['expiry']) for d in range(24) for r in training()[:60]]
        sessions=[]
        for d in range(24):
            for mode in ('restart','continuous'):
                v=references(60,move=30+d*5)
                for p in v:p['row']['period']=dates[d]
                sessions.append(dict(id=f'{d}:{mode}',period=dates[d],source='normalized',split='train',mode=mode,intervals=[dict(start=0,end=1800000,hour=0)],values=v))
        from research_frozen_pricing import SPECS as FROZEN
        overlay=next(c for c in FROZEN if c['name']=='hurdle_all_120')
        before=choose(rows,dates,sessions,overlay)[:3]
        altered_rows,altered_sessions=deepcopy(rows),deepcopy(sessions)
        for r in altered_rows:
            if r['period'] in dates[14:]:r.update(valid=False,move=99999)
        for s in altered_sessions:
            if s['period'] in dates[14:]:
                for p in s['values']:p['row'].update(valid=False,move=99999)
        self.assertEqual(before,choose(altered_rows,dates,altered_sessions,overlay)[:3])


if __name__=='__main__':unittest.main()
