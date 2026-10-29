"""Bounded discrete proposals; improvements are accepted only after evaluation.

Dimensions here are native integer mm, concrete is a grade string. Increasing
sections need not improve all constraints because stiffness redistributes loads.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from struct_agent._vendor.shearwall_optimization.core.contracts import EvaluationResult, VariableSpec


def ordered_domain(variable: VariableSpec) -> list[Any]:
    return sorted(variable.domain, key=lambda v: int(v[1:]) if variable.name == "conc_bot" else v)


def feedback_candidates(x: dict[str, Any], result: EvaluationResult, variables: list[VariableSpec],
                        repair: Callable[[dict[str, Any]], dict[str, Any]],
                        evaluated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Try reduced cost after feasibility, targeted capacity changes before it.

    Proposed values never alter engineering conditions or bypass failed checks.
    Exhausting these moves is not a proof that the layout is infeasible.
    """
    domains = {v.name: ordered_domain(v) for v in variables}
    violations = result.metrics.get("normalized_violations", {})
    active = {k for k, v in violations.items() if v > 0}
    if result.feasible:
        groups = [(v.name,) for v in variables]
        direction = -1
    else:
        names = []
        if any("wall" in k or k in ("max_drift_ratio", "torsion_ratio", "period_ratio", "min_stiffness_ratio") for k in active):
            names.extend(("tw_bot", "tw_mid", "tw_top"))
        if any("beam" in k for k in active):
            names.extend(("bb_main", "bb_sec"))
        names.append("conc_bot")
        groups = [tuple(names)] + [(name,) for name in names]
        # Depth changes are evaluated separately: deeper short beams may attract
        # greater shear and should not be treated as monotonic capacity repair.
        groups += [("hb_main",), ("hb_sec",)]
        direction = 1
    proposals = []
    for group in groups:
        candidate = dict(x)
        for name in group:
            values = domains[name]
            index = values.index(candidate[name])
            candidate[name] = values[min(len(values)-1, max(0, index+direction))]
        candidate = repair(candidate)
        if candidate != x and candidate not in evaluated and candidate not in proposals:
            proposals.append(candidate)
    return proposals
