"""User's 2026-10-29 cross-solver rule: strictly below 5%, no calibration."""
from __future__ import annotations

import math
from typing import Any


def assess_pair(etabs: float, opensees: float) -> dict[str, Any]:
    """ETABS is the relative-error denominator, not a declaration of truth.

    Exact zero/zero passes. Zero/nonzero exceeds the range. No near-zero
    response is silently discarded or replaced with a denominator floor.
    """
    if not math.isfinite(etabs) or not math.isfinite(opensees):
        raise ValueError('Finite, successfully solved responses required')
    difference = abs(opensees-etabs)
    relative = difference/abs(etabs) if etabs else (0. if difference == 0. else None)
    passed = relative is not None and relative < .05
    return {'absolute_difference':difference, 'relative_difference':relative,
        'within_tolerance':passed, 'status':'WITHIN_5_PERCENT' if passed else 'EXCEEDS_OR_EQUALS_5_PERCENT',
        'followup':'CLOSED_NO_CALIBRATION' if passed else 'REQUIRES_FOLLOWUP'}


def assess_comparison(comparison: dict[str, Any], story_height_m: float) -> dict[str, Any]:
    """All matched periods, every floor UX/UY/RZ, translational story drifts.

    Values use SI s, m, rad. Drift is (u_i-u_{i-1})/height, dimensionless.
    No mode, floor or small coupled response is excluded from the full result.
    """
    if not math.isfinite(story_height_m) or story_height_m <= 0.:
        raise ValueError('Positive finite story height required')
    metrics = []
    for mode in comparison['periods']:
        metrics.append({'category':'period', 'id':f"mode_{mode['etabs_mode']}",
            'etabs':mode['etabs_period_s'], 'opensees':mode['opensees_period_s'],
            **assess_pair(mode['etabs_period_s'], mode['opensees_period_s'])})
    for case, rows in comparison['static'].items():
        main = 'u1' if case == 'ROOF_X' else 'u2'
        for row in rows:
            metrics.append({'category':'primary_displacement' if row['component'] == main else 'coupled_response',
                'id':f"{case}_S{row['story']}_{row['component']}", 'etabs':row['etabs'], 'opensees':row['opensees'],
                **assess_pair(row['etabs'], row['opensees'])})
        for component in ('u1', 'u2'):
            levels = sorted((r for r in rows if r['component'] == component), key=lambda r:r['story'])
            if not levels or [r['story'] for r in levels] != list(range(1, len(levels)+1)):
                raise ValueError('Missing/duplicated floor responses')
            previous = (0., 0.)
            for row in levels:
                a, b = ((row[key]-previous[i])/story_height_m for i, key in enumerate(('etabs', 'opensees')))
                metrics.append({'category':'primary_drift' if component == main else 'coupled_drift',
                    'id':f"{case}_S{row['story']}_{component}_drift", 'etabs':a, 'opensees':b, **assess_pair(a, b)})
                previous = row['etabs'], row['opensees']
    if not metrics:
        raise ValueError('Missing structural comparison metrics')
    categories = {}
    for category in sorted({m['category'] for m in metrics}):
        group = [m for m in metrics if m['category'] == category]
        categories[category] = {'total':len(group), 'passed':sum(m['within_tolerance'] for m in group),
            'max_relative_difference':None if any(m['relative_difference'] is None for m in group)
                else max(m['relative_difference'] for m in group)}
    return {'rule':'abs(OpenSees-ETABS)/abs(ETABS) < 0.05', 'categories':categories,
        'metrics':metrics, 'passed':sum(m['within_tolerance'] for m in metrics), 'total':len(metrics),
        'status':'WITHIN_5_PERCENT' if all(m['within_tolerance'] for m in metrics) else 'PARTIAL_EXCEEDANCE',
        'engineering_feasibility':'NOT_EVALUATED'}
