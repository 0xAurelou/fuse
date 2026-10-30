"""Bounded symbolic quantile regression with chronological structure selection.

Expressions are data trees, never executable Python strings. This local NumPy
search uses a small grammar and beam mutations; it is not the PySR package.
"""
from collections import Counter, deque
from datetime import datetime, timezone
import json
import math

import numpy as np

from adaptive_corridor import required_width, weighted_quantile


FEATURES = ('vol_ratio', 'signed_drift', 'mark_gap', 'concentration', 'idle', 'activity', 'efficiency')
SPEC = dict(target=.48, source='gap', seed=20261028, max_terms=3, max_depth=2,
            max_nodes=17, beam=6, rounds=4, proposals_per_round=64,
            ridge=.03, irls_steps=40, huber=.05, complexity_charge=.002,
            worst_date_weight=.25, worst_regime_weight=.25, regime_balance=.4,
            minimum_regime_paths=8, minimum_fit_dates=3, minimum_validation_dates=1,
            minimum_fit_paths=80, minimum_validation_paths=20,
            log_bound=math.log(4), maturity_delay_ms=30000, memory=120,
            online_half_life_ms=3600000, online_max_age_ms=14400000,
            online_prior_mass=3., online_step=.05, online_bound=math.log(2),
            maximum_width=50000)


def features(row):
    """Only explicitly permitted pre-entry fields enter the formula."""
    a, f = row['activity_features'], row['adaptive_features']
    slow = max(.001, f['vol_300_ppm'])
    return [max(-1., min(1., math.log(max(.001, f['vol_60_ppm']) / slow) / 2)),
            math.tanh(f['net_300_bps'] * 100 / (math.sqrt(10) * slow)),
            math.tanh(row['oracle_gap']['values'][0]),
            2 * a['largest_variance_share_300'] - 1,
            math.tanh(a['idle_ms'] / 10000),
            math.tanh(math.log1p(a['changes_60']) / 3),
            min(1., f['directional_strength'] / math.sqrt(max(1, a['changes_300'])))]


def tree_key(tree):
    return json.dumps(tree, separators=(',', ':'))


def size(tree):
    return 1 if tree[0] == 'x' else 1 + sum(size(t) for t in tree[1:])


def depth(tree):
    return 0 if tree[0] == 'x' else 1 + max(depth(t) for t in tree[1:])


def check_tree(tree):
    if not isinstance(tree, (list, tuple)) or not tree:
        raise ValueError('expression tree required')
    op = tree[0]
    if op == 'x':
        if len(tree) != 2 or type(tree[1]) is not int or not 0 <= tree[1] < len(FEATURES):
            raise ValueError('feature outside allowlist')
    elif op in ('abs', 'tanh', 'mul', 'add', 'div'):
        if len(tree) != (2 if op in ('abs', 'tanh') else 3):
            raise ValueError('operator arity differs')
        for child in tree[1:]:
            check_tree(child)
    else:
        raise ValueError('operator outside grammar')
    if depth(tree) > SPEC['max_depth']:
        raise ValueError('expression too deep')


def term_value(tree, x):
    op = tree[0]
    if op == 'x':
        return x[:, tree[1]]
    a = term_value(tree[1], x)
    if op == 'abs': return np.abs(a)
    if op == 'tanh': return np.tanh(a)
    b = term_value(tree[2], x)
    if op == 'mul': return a * b
    if op == 'add': return a + b
    if op == 'div': return a / (1 + np.abs(b))
    raise ValueError('operator outside grammar')


def term_text(tree):
    op = tree[0]
    if op == 'x': return FEATURES[tree[1]]
    a = term_text(tree[1])
    if op in ('abs', 'tanh'): return f'{op}({a})'
    b = term_text(tree[2])
    if op == 'div': return f'({a}/(1+abs({b})))'
    return f'({a}{"*" if op == "mul" else "+"}{b})'


def expression_text(model):
    return ' + '.join([f'{model["coefficients"][0]:.8g}'] +
                     [f'({c:.8g})*{term_text(t)}' for c, t in zip(model['coefficients'][1:], model['terms'])])


def weights(records):
    days = Counter(r['row']['period'] for r in records)
    groups = Counter((r['row']['period'], r['regime']) for r in records)
    group_count = Counter(day for day, regime in groups)
    # A convex mixture retains ordinary path weighting while balancing regimes
    # within each equally weighted date. All grouping is confined to fit data.
    w = [(1-SPEC['regime_balance'])/days[r['row']['period']] + SPEC['regime_balance']/
         (group_count[r['row']['period']] * groups[(r['row']['period'], r['regime'])]) for r in records]
    w = np.asarray(w); return w / w.sum()


def fit_coefficients(design, target, w):
    if design.shape[1] == 1:
        return np.asarray([weighted_quantile(list(zip(target, w)), SPEC['target'])])
    penalty = np.diag([1e-8] + [SPEC['ridge']] * (design.shape[1]-1))
    coef = np.zeros(design.shape[1]); coef[0] = weighted_quantile(list(zip(target, w)), SPEC['target'])
    for _ in range(SPEC['irls_steps']):
        residual = target - design @ coef
        irls = w * np.where(residual >= 0, SPEC['target'], 1-SPEC['target']) / np.maximum(np.abs(residual), SPEC['huber'])
        updated = np.linalg.solve(design.T @ (irls[:, None] * design) + penalty, design.T @ (irls * target))
        if np.max(np.abs(updated-coef)) < 1e-7:
            coef = updated; break
        coef = updated
    return coef


def canonical(terms):
    found = {tree_key(t): t for t in terms}
    return [found[k] for k in sorted(found)]


def robust_loss(target, predicted, records, complexity):
    residual = target - np.clip(predicted, -SPEC['log_bound'], SPEC['log_bound'])
    loss = np.maximum(SPEC['target']*residual, (SPEC['target']-1)*residual)
    dates = sorted({r['row']['period'] for r in records})
    date_loss = [float(np.mean(loss[[r['row']['period']==d for r in records]])) for d in dates]
    regime_loss = []
    for regime in sorted({r['regime'] for r in records}):
        ids = [i for i,r in enumerate(records) if r['regime']==regime]
        if len(ids) >= SPEC['minimum_regime_paths']:
            regime_loss.append(float(loss[ids].mean()))
    return (float(weights(records) @ loss) + SPEC['worst_date_weight'] * max(date_loss)
            + SPEC['worst_regime_weight'] * max(regime_loss, default=0.) + SPEC['complexity_charge']*complexity)


def fit(records, periods, cutoff):
    if len(set(periods)) != len(periods) or any(d >= cutoff for d in periods):
        raise ValueError('unique dates strictly before cutoff required')
    boundary = int(datetime.fromisoformat(cutoff).replace(tzinfo=timezone.utc).timestamp()*1000)
    part = [r for r in records if r['source']==SPEC['source'] and r['row']['period'] in periods
            and r['row']['activity_state']=='bursty']
    if len({(r['row']['period'],r['row']['start']) for r in part}) != len(part):
        raise ValueError('duplicate calibration reference')
    for r in part:
        day = r['row']['period']
        if r['model_cutoff'] > day or any(d >= day for d in r['training_periods']) or r['row']['expiry']+SPEC['maturity_delay_ms'] >= boundary:
            raise ValueError('forecast or label crosses chronological boundary')
        if not math.isfinite(r['ratio']) or r['ratio'] <= 0 or len(r['features']) != len(FEATURES) or not all(math.isfinite(v) for v in r['features']):
            raise ValueError('finite allowed features and positive residual required')
    days = sorted({r['row']['period'] for r in part})
    model = dict(training_periods=periods, cutoff=cutoff, windows=len(part), observed_dates=days,
                 regime_counts=dict(Counter(r['regime'] for r in part)), feature_names=FEATURES,
                 terms=[], coefficients=[0.], constant_coefficients=[0.],
                 neutral_fallback=not part, candidates=[], fitting_dates=[], validation_dates=[])
    if not part: return model
    x = np.asarray([r['features'] for r in part]); y = np.clip(np.log([r['ratio'] for r in part]), -SPEC['log_bound'], SPEC['log_bound'])
    model['constant_coefficients'] = fit_coefficients(np.ones((len(part),1)), y, weights(part)).tolist()
    if len(days) < SPEC['minimum_fit_dates'] + SPEC['minimum_validation_dates']:
        model['coefficients'] = model['constant_coefficients']; model['fallback_reason']='Too few dates for chronological structure selection'
        return model
    count = max(1, math.ceil(len(days)*.25)); split = max(SPEC['minimum_fit_dates'],len(days)-count)
    model['fitting_dates'], model['validation_dates'] = days[:split], days[split:]
    fitting = np.asarray([r['row']['period'] in days[:split] for r in part]); validation = ~fitting
    fit_rows = [r for r,keep in zip(part,fitting) if keep]; val_rows = [r for r,keep in zip(part,validation) if keep]
    if len(fit_rows)<SPEC['minimum_fit_paths'] or len(val_rows)<SPEC['minimum_validation_paths']:
        model['coefficients']=model['constant_coefficients']; model['fallback_reason']='Too few paths for chronological structure selection'
        return model
    w = weights(fit_rows); cache = {}; evaluated = {}
    def design(terms):
        columns = [np.ones(len(part))]
        for term in terms:
            key = tree_key(term)
            if key not in cache: cache[key] = term_value(term,x)
            columns.append(cache[key])
        return np.column_stack(columns)
    def consider(terms):
        terms = canonical(terms); key = tree_key(terms)
        complexity = len(terms)+sum(size(t) for t in terms)
        if key in evaluated or len(terms)>SPEC['max_terms'] or complexity>SPEC['max_nodes']: return
        for term in terms: check_tree(term)
        z = design(terms); coef = fit_coefficients(z[fitting],y[fitting],w)
        score = robust_loss(y[validation],z[validation]@coef,val_rows,complexity)
        evaluated[key] = dict(terms=terms,complexity=complexity,score=score)
    rng = np.random.default_rng(SPEC['seed'])
    leaves = [('x',i) for i in range(len(FEATURES))]
    def random_term(level=0):
        if level >= SPEC['max_depth'] or rng.random()<.45: return leaves[int(rng.integers(len(leaves)))]
        op = ('abs','tanh','mul','add','div')[int(rng.integers(5))]
        a = random_term(level+1)
        if op in ('abs','tanh'): return (op,a)
        b = random_term(level+1)
        if op in ('mul','add') and tree_key(a)>tree_key(b): a,b = b,a
        return (op,a,b)
    consider([])
    for leaf in leaves:
        consider([leaf]); consider([('abs',leaf)])
    for round_index in range(SPEC['rounds']):
        beam = sorted(evaluated.values(),key=lambda r:(r['score'],r['complexity'],tree_key(r['terms'])))[:SPEC['beam']]
        for _ in range(SPEC['proposals_per_round']):
            terms = list(beam[int(rng.integers(len(beam)))]['terms'])
            operation = int(rng.integers(3))
            if terms and operation==0: terms.pop(int(rng.integers(len(terms))))
            elif terms and (operation==1 or len(terms)>=SPEC['max_terms']): terms[int(rng.integers(len(terms)))] = random_term()
            else: terms.append(random_term())
            consider(terms)
    ranking = sorted(evaluated.values(),key=lambda r:(r['score'],r['complexity'],tree_key(r['terms'])))
    chosen = ranking[0]; coef = fit_coefficients(design(chosen['terms']),y,weights(part))
    model.update(terms=chosen['terms'],coefficients=coef.tolist(),complexity=chosen['complexity'],
                 validation_score=chosen['score'],candidates=ranking)
    model['expression'] = expression_text(model)
    return model


def formula_log(row, model, constant=False):
    coef = model['constant_coefficients'] if constant else model['coefficients']
    terms = [] if constant else model['terms']
    x = np.asarray([features(row)])
    value = coef[0] + sum(c*float(term_value(t,x)[0]) for c,t in zip(coef[1:],terms))
    return max(-SPEC['log_bound'],min(SPEC['log_bound'],value))


def series(values, cached, model, adaptive=False, constant=False):
    if len(values)!=len(cached): raise ValueError('forecast alignment differs')
    for term in model['terms']: check_tree(term)
    if (len(model['terms'])>SPEC['max_terms'] or len(model['terms'])+sum(size(t) for t in model['terms'])>SPEC['max_nodes']
            or len(model['coefficients'])!=len(model['terms'])+1 or len(model['constant_coefficients'])!=1
            or not all(math.isfinite(c) for c in model['coefficients']+model['constant_coefficients'])):
        raise ValueError('invalid bounded formula model')
    output = []; pending = deque(); pool = deque(); correction = 1.; period = previous = None
    for p, prediction in zip(values,cached):
        row = p['row']; at = row['start']
        if previous is not None and at<previous: raise ValueError('chronological references required')
        previous = at
        if period!=row['period']:
            period=row['period']; pending.clear(); pool.clear(); correction=1.
        while pending and pending[0][0]<=at:
            _, old, q = pending.popleft()
            if old['valid'] and at-old['expiry']<=SPEC['online_max_age_ms']:
                pool.append((old['expiry'],required_width(old)/q))
        while pool and (len(pool)>SPEC['memory'] or at-pool[0][0]>SPEC['online_max_age_ms']): pool.popleft()
        result = p
        if prediction is not None:
            if p['width_ppm'] is None or row['activity_state']!='bursty' or row.get('oracle_gap') is None:
                raise ValueError('forecast cache support differs')
            q, _ = prediction; log_static = formula_log(row,model,constant); static = q*math.exp(log_static)
            if adaptive:
                evidence = [(v,2**(-(at-expiry)/SPEC['online_half_life_ms'])) for expiry,v in pool]
                wanted = weighted_quantile([(1.,SPEC['online_prior_mass'])]+evidence,SPEC['target'])
                wanted = max(math.exp(-SPEC['online_bound']),min(math.exp(SPEC['online_bound']),wanted))
                if not pool: correction=1.
                correction=min(correction*(1+SPEC['online_step']),max(correction*(1-SPEC['online_step']),wanted))
            log_total = max(-SPEC['log_bound'],min(SPEC['log_bound'],log_static+math.log(correction)))
            raw = q if log_total==0 else math.ceil(q*math.exp(log_total)); width = max(1,min(SPEC['maximum_width'],raw))
            hit = row['move']<row['entry']*width//1000000 if row['valid'] else None
            result = dict(p,width_ppm=width,shadow_survived=hit,survived=None if p['paused'] else hit,
                          capped=raw>SPEC['maximum_width'],symbolic_static=log_static,
                          symbolic_total=log_total,symbolic_online=math.log(correction),symbolic_mature=len(pool))
            if adaptive: pending.append((row['expiry']+SPEC['maturity_delay_ms'],row,static))
        output.append(result)
    return output
