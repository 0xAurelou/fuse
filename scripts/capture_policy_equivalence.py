"""Strict policy comparison allowing Go Model's four explicit integer zeros.

The original JSON input can omit these fields. The frozen Go Model struct
declares int64 fields without omitempty, so its manifest emits each as zero.
No other missing field, value, model, or policy difference is allowed.
This is a semantic comparison, not native hash-chain verification.
"""
from copy import deepcopy
import json


ZERO_FIELDS=('base_width_bps','control_width_bps','max_drift_bps','volatility_factor')


def compare_policy(recorded,frozen):
    normalized=deepcopy(frozen);added=[]
    paths=[('model',)]
    if 'markets' in normalized:
        paths.extend(('markets',asset) for asset in sorted(normalized['markets']))
    for path in paths:
        expected=normalized;actual=recorded
        for key in path:
            expected=expected[key];actual=actual[key]
        for field in ZERO_FIELDS:
            if field not in actual or type(actual[field]) is not int:
                raise ValueError('recorded Go model lacks explicit integer field: '+'.'.join((*path,field)))
            if field not in expected:
                expected[field]=0
                added.append('.'.join((*path,field)))
    encode=lambda obj:json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False)
    if encode(recorded)!=encode(normalized):
        raise ValueError('recorded policy differs from frozen policy beyond omitted Go integer zeros')
    return dict(semantic_policy_match=True,exact_json_object_match=encode(recorded)==encode(frozen),
                explicit_zero_fields_added=added,
                rule='Only four non-omitempty int64 Model fields may expand from absent input to explicit zero; every other field and value must match exactly.')
