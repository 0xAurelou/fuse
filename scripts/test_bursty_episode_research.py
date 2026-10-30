from copy import deepcopy
import unittest

from bursty_episodes import SPECS,reprice,spec
from research_bursty_episodes import choose,episode_cells
from test_bursty_episodes import model
from test_bursty_pricing import references
from test_oracle_activity import training


class EpisodeResearchTests(unittest.TestCase):
    def test_episode_phases_use_entry_time_and_do_not_drop_censored_decisions(self):
        v=references(5);v[0]['row']['valid']=False;v[0].update(survived=None,shadow_survived=None)
        meta=reprice(v,model(),spec('episodes',episodes=True,reset='full'))
        session=dict(id='case',source='raw',period='day',split='test',mode='restart',intervals=[dict(start=0,end=150000,hour=0)])
        cells=episode_cells(session,v,meta,'candidate')
        self.assertEqual(cells[0]['grid_windows'],2)
        self.assertEqual(cells[0]['windows'],1)
        self.assertEqual(cells[1]['windows'],3)

    def test_later_and_raw_outputs_cannot_select_episode_parameters(self):
        dates=[f'day-{i:02}' for i in range(24)]
        rows=[dict(r,period=dates[d],start=d*10000000+r['start'],expiry=d*10000000+r['expiry']) for d in range(24) for r in training()[:60]]
        sessions=[]
        for d in range(24):
            for mode in ('restart','continuous'):
                v=references(60,move=30+d*5)
                for p in v:p['row']['period']=dates[d]
                sessions.append(dict(id=f'{d}:{mode}',source='normalized',period=dates[d],split='train',mode=mode,intervals=[dict(start=0,end=1800000,hour=0)],values=v))
        raw=deepcopy(sessions[10]);raw.update(id='raw-extension',source='raw_extended')
        sessions.append(raw)
        from research_frozen_pricing import SPECS as FROZEN
        overlay=next(c for c in FROZEN if c['name']=='hurdle_all_120')
        before=choose(rows,dates,sessions,overlay)[:3]
        changed_rows,changed=deepcopy(rows),deepcopy(sessions)
        for r in changed_rows:
            if r['period'] in dates[14:]:r.update(valid=False,move=999999)
        for s in changed:
            if s['period'] in dates[14:] or s['source']=='raw_extended':
                for p in s['values']:p['row'].update(valid=False,move=999999)
        self.assertEqual(before,choose(changed_rows,dates,changed,overlay)[:3])


if __name__=='__main__':unittest.main()
