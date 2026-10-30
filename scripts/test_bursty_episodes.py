from copy import deepcopy
import unittest

from bursty_episodes import SPECS,coordinates,context,fit_model,reprice,similarity,spec,estimate
from test_bursty_pricing import references


def model():
    values=[]
    for day in range(3):
        for p in references(100,move=80):
            r=p['row'];r.update(period=str(day),start=r['start']+day*10_000_000,expiry=r['expiry']+day*10_000_000)
            values.append(p)
    m=fit_model(values)
    for s in m['states'].values():s['static_factor']=1
    for s in m['episode_contexts'].values():s['static_factor']=1
    return m


class BurstyEpisodeTests(unittest.TestCase):
    def test_only_bursty_quotes_change_without_input_mutation(self):
        v=references()
        for i,p in enumerate(v):p['row']['activity_state']=('active','sparse','frozen','bursty')[i%4]
        v[7].update(paused=True,survived=None);v[11]['row']['valid']=False;v[11].update(shadow_survived=None,survived=None)
        v[15].update(width_ppm=None,shadow_survived=None,survived=None)
        before=deepcopy(v)
        for c in SPECS:
            if c['comparator']:continue
            for a,b in zip(reprice(v,model(),c),v):
                self.assertEqual((a['paused'],a['width_ppm'] is None,a['shadow_survived'] is None),(b['paused'],b['width_ppm'] is None,b['shadow_survived'] is None))
                if b['row']['activity_state']!='bursty':self.assertEqual((a['width_ppm'],a['shadow_survived']),(b['width_ppm'],b['shadow_survived']))
                if a['width_ppm'] is not None:self.assertTrue(1<=a['width_ppm']<=50000)
        self.assertEqual(v,before)

    def test_future_outcomes_wait_until_expiry_plus_delay(self):
        v=references();changed=deepcopy(v)
        for p in changed[40:]:p['row'].update(move=10000,valid=False)
        for c in SPECS:
            if c['comparator']:continue
            a,b=reprice(v,model(),c),reprice(changed,model(),c)
            self.assertEqual([p['width_ppm'] for p in a[:42]],[p['width_ppm'] for p in b[:42]])
            self.assertEqual([p['episode'] for p in a],[p['episode'] for p in b])

    def test_boundaries_use_past_features_and_exact_gap(self):
        v=references(3)
        v[1]['row'].update(start=299999,expiry=329999)
        v[2]['row'].update(start=599999,expiry=629999)
        out=reprice(v,model(),spec('episodes',episodes=True,reset='full'))
        self.assertEqual([p['episode'] for p in out],[1,1,2])
        v=references(2);v[1]['row']['adaptive_features']['vol_300_ppm']=200
        self.assertEqual(reprice(v,model(),spec('episodes',episodes=True,reset='full'))[-1]['episode'],2)

    def test_pending_old_episode_cannot_enter_new_leaf(self):
        v=references(3)
        v[1]['row']['adaptive_features']['vol_300_ppm']=200
        v[2]['row']['adaptive_features']['vol_300_ppm']=200
        out=reprice(v,model(),spec('episodes',episodes=True,reset='full'))
        self.assertEqual(out[2]['episode'],2)
        self.assertEqual(out[2]['episode_mature'],0)

    def test_kernel_weights_reduce_dissimilar_transfer_mass(self):
        c=spec('kernel',kernel=True);m=model()['states']['bursty']
        same=(0.,0.,0.,0.);far=(20.,20.,20.,20.)
        parent=[dict(expiry=0,ratio=.01,floor=False,point=same) for _ in range(20)]
        _,ess,mass=estimate(parent,[],m,100,same,0,c,.48)
        _,_,far_mass=estimate(parent,[],m,100,far,0,c,.48)
        self.assertEqual(ess,20);self.assertEqual(mass,12)
        self.assertLess(far_mass,1e-20)
        self.assertEqual(similarity(same,same,c),1)

    def test_low_effective_sample_limits_transfer(self):
        c=spec('kernel',kernel=True);m=model()['states']['bursty'];point=(0.,0.,0.,0.)
        parent=[dict(expiry=0,ratio=1,floor=False,point=point)]
        parent += [dict(expiry=0,ratio=.1,floor=False,point=(20.,)*4) for _ in range(19)]
        _,ess,mass=estimate(parent,[],m,100,point,0,c,.48)
        self.assertAlmostEqual(ess,1);self.assertLess(mass,1)

    def test_paused_learning_age_memory_and_period_reset(self):
        v=references(100)
        for p in v:p.update(paused=True,survived=None)
        c=spec('episode',episodes=True,reset='full')
        out=reprice(v,model(),c)
        self.assertGreater(out[20]['episode_mature'],0)
        self.assertTrue(all(p['survived'] is None for p in out))
        self.assertTrue(all(p['episode_mature']<=30 for p in out))
        v += references(1)
        v[-1]['row'].update(start=20_000_000,expiry=20_030_000,period='next')
        out=reprice(v,model(),c)
        self.assertEqual(out[-1]['episode'],1);self.assertEqual(out[-1]['episode_mature'],0)

    def test_rate_limit_within_episode_and_explicit_reset(self):
        v=references(40);c=spec('episode',episodes=True,reset='full')
        out=reprice(v,model(),c)
        for a,b in zip(out,out[1:]):
            if not b['episode_boundary']:
                self.assertGreaterEqual(b['episode_correction'],.95*a['episode_correction']-1e-12)
                self.assertLessEqual(b['episode_correction'],1.05*a['episode_correction']+1e-12)
        v.append(deepcopy(v[-1]));v[-1]['row'].update(start=20_000_000,expiry=20_030_000)
        last=reprice(v,model(),c)[-1]
        self.assertTrue(last['episode_boundary']);self.assertTrue(.95<=last['episode_correction']<=1.05)

    def test_guard_and_context_fallback(self):
        v=references()
        for i,p in enumerate(v):p['row']['market_regime']=('mixed','pump','dump')[i%3]
        out=reprice(v,model(),spec('guard',episodes=True,kernel=True,reset='full',guard=True))
        self.assertTrue(all(p['width_ppm']==100 for p in out if p['row']['market_regime'] in ('pump','dump')))
        m=fit_model(references(100));self.assertTrue(all(s['used_state_parent'] for s in m['episode_contexts'].values()))
        r=references(1)[0]['row'];r['activity_features']['idle_ms']=4999
        self.assertTrue(context(r).endswith(':recent'));r['activity_features']['idle_ms']=5000
        self.assertTrue(context(r).endswith(':idle'));self.assertEqual(len(coordinates(r)),4)


if __name__=='__main__':unittest.main()
