"""Shared symbolic quantile model plus shrunk bursty intercept calibration."""
from collections import Counter
from datetime import datetime, timezone
import math

import numpy as np

from adaptive_corridor import weighted_quantile
from symbolic_corridor import (FEATURES, SPEC as GRAMMAR, canonical, check_tree,
    expression_text, fit_coefficients, size, term_value, tree_key, weights)

SPEC = dict(child_prior=200., child_log_bound=math.log(2), maximum_fit_paths_per_date=400,
            population='All supported non-frozen OOF references; only bursty quotes are repriced',
            child='Period-balanced bursty quantile intercept, shrunk n/(n+200), after parent refit',
            child_calibration='Earlier allowed data; in-sample relative to expression fit, not independent calibration')


def fit(records,periods,cutoff):
    if len(set(periods))!=len(periods) or any(d>=cutoff for d in periods): raise ValueError('unique earlier training dates required')
    boundary=int(datetime.fromisoformat(cutoff).replace(tzinfo=timezone.utc).timestamp()*1000)
    part=[r for r in records if r['source']=='gap' and r['row']['period'] in periods and r['row']['activity_state'] in ('active','sparse','bursty')]
    if len({(r['row']['period'],r['row']['start']) for r in part})!=len(part): raise ValueError('duplicate OOF reference')
    for r in part:
        if (r['model_cutoff']>r['row']['period'] or any(d>=r['row']['period'] for d in r['training_periods'])
                or r['row']['expiry']+GRAMMAR['maturity_delay_ms']>=boundary): raise ValueError('forecast or label crosses boundary')
        if not math.isfinite(r['ratio']) or r['ratio']<=0 or len(r['features'])!=len(FEATURES) or not all(math.isfinite(v) for v in r['features']):
            raise ValueError('finite features and positive residual required')
    days=sorted({r['row']['period'] for r in part})
    model=dict(training_periods=periods,cutoff=cutoff,windows=len(part),observed_dates=days,
               regime_counts=dict(Counter(r['regime'] for r in part)),state_counts=dict(Counter(r['row']['activity_state'] for r in part)),
               feature_names=FEATURES,terms=[],coefficients=[0.],constant_coefficients=[0.],neutral_fallback=not part,
               candidates=[],fitting_dates=[],validation_dates=[],child_prior=SPEC['child_prior'])
    if not part: return model
    x=np.asarray([r['features'] for r in part]); y=np.clip(np.log([r['ratio'] for r in part]),-GRAMMAR['log_bound'],GRAMMAR['log_bound'])
    rng=np.random.default_rng(GRAMMAR['seed'])
    # Date-stratified uniform samples bound coefficient-fit cost. Validation uses
    # every path; the sampler never sees labels, regimes, or entry features.
    def sampled(indices):
        result=[]
        for day in days:
            ids=[i for i in indices if part[i]['row']['period']==day]
            if len(ids)>SPEC['maximum_fit_paths_per_date']:
                ids=sorted(rng.choice(ids,SPEC['maximum_fit_paths_per_date'],replace=False).tolist())
            result.extend(ids)
        return np.asarray(result,dtype=int)
    all_ids=np.arange(len(part)); final_ids=sampled(all_ids)
    final_w=weights([part[i] for i in final_ids])
    constant=fit_coefficients(np.ones((len(final_ids),1)),y[final_ids],final_w)
    cache={}
    def design(terms):
        columns=[np.ones(len(part))]
        for term in terms:
            key=tree_key(term)
            if key not in cache: cache[key]=term_value(term,x)
            columns.append(cache[key])
        return np.column_stack(columns)
    chosen=dict(terms=[],complexity=0); parent=constant
    if len(days)>=GRAMMAR['minimum_fit_dates']+GRAMMAR['minimum_validation_dates']:
        split=max(GRAMMAR['minimum_fit_dates'],len(days)-max(1,math.ceil(len(days)*.25)))
        model['fitting_dates'],model['validation_dates']=days[:split],days[split:]
        fit_ids=sampled([i for i,r in enumerate(part) if r['row']['period'] in days[:split]])
        val_ids=np.asarray([i for i,r in enumerate(part) if r['row']['period'] in days[split:]],dtype=int)
        if len(fit_ids)>=GRAMMAR['minimum_fit_paths'] and len(val_ids)>=GRAMMAR['minimum_validation_paths']:
            fw=weights([part[i] for i in fit_ids]); val_rows=[part[i] for i in val_ids]; vw=weights(val_rows)
            di=[np.asarray([i for i,r in enumerate(val_rows) if r['row']['period']==day],dtype=int) for day in days[split:]]
            ri=[np.asarray([i for i,r in enumerate(val_rows) if r['regime']==regime],dtype=int) for regime in sorted({r['regime'] for r in val_rows})]
            ri=[ids for ids in ri if len(ids)>=GRAMMAR['minimum_regime_paths']]
            evaluated={}
            def consider(terms):
                terms=canonical(terms); key=tree_key(terms); complexity=len(terms)+sum(size(t) for t in terms)
                if key in evaluated or len(terms)>GRAMMAR['max_terms'] or complexity>GRAMMAR['max_nodes']: return
                for term in terms: check_tree(term)
                z=design(terms); coef=fit_coefficients(z[fit_ids],y[fit_ids],fw)
                residual=y[val_ids]-np.clip(z[val_ids]@coef,-GRAMMAR['log_bound'],GRAMMAR['log_bound'])
                loss=np.maximum(GRAMMAR['target']*residual,(GRAMMAR['target']-1)*residual)
                score=float(vw@loss)+GRAMMAR['worst_date_weight']*max(float(loss[ids].mean()) for ids in di)
                score+=GRAMMAR['worst_regime_weight']*max((float(loss[ids].mean()) for ids in ri),default=0.)+GRAMMAR['complexity_charge']*complexity
                evaluated[key]=dict(terms=terms,complexity=complexity,score=score)
            leaves=[('x',i) for i in range(len(FEATURES))]
            def random_term(level=0):
                if level>=GRAMMAR['max_depth'] or rng.random()<.45: return leaves[int(rng.integers(len(leaves)))]
                op=('abs','tanh','mul','add','div')[int(rng.integers(5))]; a=random_term(level+1)
                if op in ('abs','tanh'): return (op,a)
                b=random_term(level+1)
                if op in ('mul','add') and tree_key(a)>tree_key(b): a,b=b,a
                return (op,a,b)
            consider([])
            for leaf in leaves: consider([leaf]); consider([('abs',leaf)])
            for _ in range(GRAMMAR['rounds']):
                beam=sorted(evaluated.values(),key=lambda r:(r['score'],r['complexity'],tree_key(r['terms'])))[:GRAMMAR['beam']]
                for _ in range(GRAMMAR['proposals_per_round']):
                    terms=list(beam[int(rng.integers(len(beam)))]['terms']); operation=int(rng.integers(3))
                    if terms and operation==0: terms.pop(int(rng.integers(len(terms))))
                    elif terms and (operation==1 or len(terms)>=GRAMMAR['max_terms']): terms[int(rng.integers(len(terms)))]=random_term()
                    else: terms.append(random_term())
                    consider(terms)
            ranking=sorted(evaluated.values(),key=lambda r:(r['score'],r['complexity'],tree_key(r['terms'])))
            chosen=ranking[0]; model['candidates']=ranking; model['validation_score']=chosen['score']
            parent=fit_coefficients(design(chosen['terms'])[final_ids],y[final_ids],final_w)
    burst_ids=np.asarray([i for i,r in enumerate(part) if r['row']['activity_state']=='bursty'],dtype=int)
    n=len(burst_ids); child_weight=n/(n+SPEC['child_prior'])
    model.update(parent_fit_paths=len(final_ids),terms=chosen['terms'],complexity=chosen['complexity'],
                 parent_coefficients=parent.tolist(),parent_constant_coefficients=constant.tolist(),
                 child_windows=n,child_weight=child_weight)
    adjustments=[]
    for coef,terms in ((parent,chosen['terms']),(constant,[])):
        if n:
            residual=y[burst_ids]-np.clip(design(terms)[burst_ids]@coef,-GRAMMAR['log_bound'],GRAMMAR['log_bound'])
            bw=weights([part[i] for i in burst_ids]); shift=weighted_quantile(list(zip(residual,bw)),GRAMMAR['target'])
            shift=max(-SPEC['child_log_bound'],min(SPEC['child_log_bound'],shift))*child_weight
        else: shift=0.
        adjusted=coef.copy(); adjusted[0]+=shift; adjustments.append((adjusted.tolist(),shift))
    model.update(coefficients=adjustments[0][0],constant_coefficients=adjustments[1][0],
                 child_shift=adjustments[0][1],constant_child_shift=adjustments[1][1])
    model['expression']=expression_text(model)
    return model
