from copy import deepcopy
import math
import unittest

from bursty_pricing import SPECS, fit_model, reprice, shape, spec
from research_bursty_pricing import choose, startup_cells
from test_flat_pause import prediction
from test_nonfrozen_pricing import prior
from test_oracle_activity import training


def references(n=80,move=0,state='bursty'):
    values=[prediction(i*30_000) for i in range(n)]
    for p in values:
        p['row'].update(activity_state=state,move=move)
    return values


def model():
    values=[]
    for day in range(3):
        for i,p in enumerate(references(100,move=80)):
            p['row'].update(period=str(day),start=day*10_000_000+i*30_000,expiry=day*10_000_000+i*30_000+30_000)
            values.append(p)
    m=fit_model(values)
    for state in m['states']:
        m['states'][state]['static_factor']=1
    for leaf in m['shape_leaves'].values():
        leaf['factor']=1
    return m


class BurstyPricingTests(unittest.TestCase):
    def test_only_bursty_changes_and_masks_eligibility_survive(self):
        values=references()
        for i,p in enumerate(values):
            p['row']['activity_state']=('active','sparse','frozen','bursty')[i%4]
        values[7].update(paused=True,survived=None)
        values[11]['row']['valid']=False
        values[11].update(shadow_survived=None,survived=None)
        values[15].update(width_ppm=None,shadow_survived=None,survived=None)
        original=deepcopy(values)
        for candidate in SPECS:
            output=reprice(values,model(),candidate)
            for a,b in zip(output,values):
                self.assertEqual((a['paused'],a['width_ppm'] is None,a['shadow_survived'] is None),
                                 (b['paused'],b['width_ppm'] is None,b['shadow_survived'] is None))
                if b['row']['activity_state']!='bursty':
                    self.assertEqual((a['width_ppm'],a['shadow_survived']),(b['width_ppm'],b['shadow_survived']))
                if a['width_ppm'] is not None:self.assertTrue(1<=a['width_ppm']<=50000)
        self.assertEqual(values,original)

    def test_future_outcomes_cannot_reprice_current_or_next_quote(self):
        values=references()
        changed=deepcopy(values)
        for p in changed[40:]:p['row'].update(move=100000,valid=False)
        for candidate in SPECS:
            a,b=reprice(values,model(),candidate),reprice(changed,model(),candidate)
            self.assertEqual([p['width_ppm'] for p in a[:42]],[p['width_ppm'] for p in b[:42]])
            self.assertTrue(all(p['width_ppm'] is not None for p in b[40:]))

    def test_parent_transfers_only_mature_nonfrozen_references(self):
        values=references(20,state='active')
        values[-1]['row']['activity_state']='bursty'
        candidate=spec('hierarchy')
        output=reprice(values,model(),candidate)
        self.assertEqual(output[-1]['burst_mature'],0)
        self.assertEqual(output[-1]['burst_parent_mature'],18)
        self.assertLess(output[-1]['width_ppm'],100)
        for p in values[:-1]:p['row']['activity_state']='frozen'
        output=reprice(values,model(),candidate)
        self.assertEqual(output[-1]['burst_parent_mature'],0)
        self.assertEqual(output[-1]['width_ppm'],100)

    def test_earlier_bursty_minimum_and_paused_learning(self):
        values=references()
        for p in values:p.update(paused=True,survived=None)
        output=reprice(values,model(),spec('feedback',family='feedback'))
        self.assertEqual(output[4]['burst_mature'],3)
        self.assertEqual(output[4]['width_ppm'],100)
        self.assertEqual(output[5]['burst_mature'],4)
        self.assertLess(output[5]['width_ppm'],100)
        self.assertTrue(all(p['survived'] is None for p in output))

    def test_feedback_uses_candidate_width(self):
        values=references(10,move=75)
        m=model();m['states']['bursty']['static_factor']=.5
        candidate=spec('feedback',family='feedback',minimum=1)
        output=reprice(values,m,candidate)
        self.assertEqual(output[0]['width_ppm'],50)
        self.assertAlmostEqual(output[2]['burst_correction'],math.exp(.048))
        altered=deepcopy(values)
        for p in altered:p['shadow_survived']=False
        self.assertEqual([p['width_ppm'] for p in output],[p['width_ppm'] for p in reprice(altered,m,candidate)])

    def test_directional_guard_preserves_base_terms(self):
        values=references()
        for i,p in enumerate(values):p['row']['market_regime']=('pump','dump','mixed')[i%3]
        candidate=spec('guard',conditional=True,guard=True)
        output=reprice(values,model(),candidate)
        for a,b in zip(output,values):
            if b['row']['market_regime'] in ('pump','dump'):
                self.assertEqual((a['width_ppm'],a['shadow_survived']),(b['width_ppm'],b['shadow_survived']))
        self.assertTrue(any(p['width_ppm']<100 for p in output if p['row']['market_regime']=='mixed'))

    def test_pool_age_period_reset_and_memory(self):
        candidate=spec('small',memory=20,age_hours=1)
        values=references(100)
        values += [prediction(10_000_000),prediction(10_030_000,period='next')]
        for p in values[-2:]:p['row']['activity_state']='bursty'
        output=reprice(values,model(),candidate)
        self.assertTrue(all(p['burst_parent_mature']<=20 and p['burst_mature']<=10 for p in output))
        self.assertEqual(output[-2]['burst_parent_mature'],0)
        self.assertEqual(output[-2]['burst_mature'],0)
        self.assertEqual(output[-1]['burst_correction'],1)

    def test_rate_bounds_and_no_stale_feedback_after_long_gap(self):
        values=references(100)
        output=reprice(values,model(),spec('feedback',family='feedback'))
        for a,b in zip(output,output[1:]):
            self.assertGreaterEqual(b['burst_correction'],.95*a['burst_correction']-1e-12)
            self.assertLessEqual(b['burst_correction'],1.05*a['burst_correction']+1e-12)
            self.assertTrue(.05<=b['burst_correction']<=2)
        # Pending paths aged out during a gap cannot seed the feedback later.
        a=references(1);a.append(prediction(10_000_000));a[-1]['row']['activity_state']='bursty'
        b=deepcopy(a);b[0]['row']['move']=10000
        candidate=spec('feedback',family='feedback',minimum=1)
        self.assertEqual(reprice(a,model(),candidate)[-1]['width_ppm'],reprice(b,model(),candidate)[-1]['width_ppm'])

    def test_shape_boundaries_and_prior_fallback(self):
        r=references(1)[0]['row']
        for ratio,label in ((.749,'cooling'),(.75,'balanced'),(1.499,'balanced'),(1.5,'fresh')):
            r['adaptive_features']['vol_60_ppm']=100*ratio
            self.assertEqual(shape(r),label)
        m=fit_model(references(100,move=99))
        self.assertTrue(m['shape_leaves']['bursty:balanced']['used_state_parent'])
        self.assertEqual(m['shape_leaves']['bursty:balanced']['factor'],m['states']['bursty']['static_factor'])
        self.assertFalse(fit_model([dict(p,row=dict(p['row'],period=str(day),start=day*10_000_000+p['row']['start'],expiry=day*10_000_000+p['row']['expiry'])) for day in range(3) for p in references(100,move=99)])['shape_leaves']['bursty:balanced']['used_state_parent'])

    def test_startup_uses_prediction_rank_not_later_health(self):
        values=references(20)
        values[0]['row']['valid']=False;values[0]['survived']=None;values[0]['shadow_survived']=None
        session=dict(id='x',source='raw',period='day',split='test',mode='restart',intervals=[dict(start=0,end=600000,hour=0)])
        cells=startup_cells(session,values,'candidate')
        self.assertEqual(cells[0]['pre_entry_decisions'],12)
        self.assertEqual(cells[0]['windows'],11)
        self.assertEqual(cells[1]['windows'],8)

    def test_later_periods_never_choose_candidate(self):
        dates=[f'day-{i:02}' for i in range(24)]
        rows=[dict(r,period=dates[d],start=d*10_000_000+r['start'],expiry=d*10_000_000+r['expiry']) for d in range(24) for r in training()[:60]]
        sessions=[]
        for d in range(24):
            v=references(60,move=30+d*5)
            for p in v:p['row']['period']=dates[d]
            sessions.append(dict(id=dates[d],period=dates[d],source='normalized',split='train',mode='restart',intervals=[dict(start=0,end=1_800_000,hour=0)],values=v))
        from research_frozen_pricing import SPECS as FROZEN
        overlay=next(c for c in FROZEN if c['name']=='hurdle_all_120')
        before=choose(rows,dates,sessions,overlay)[:3]
        altered_rows,altered_sessions=deepcopy(rows),deepcopy(sessions)
        for r in altered_rows:
            if r['period'] in dates[14:]:r.update(valid=False,move=999999)
        for s in altered_sessions[14:]:
            for p in s['values']:p['row'].update(valid=False,move=999999)
        self.assertEqual(before,choose(altered_rows,dates,altered_sessions,overlay)[:3])


if __name__=='__main__':unittest.main()
