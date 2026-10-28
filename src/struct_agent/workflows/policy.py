"""Deterministic fixture policies; no LLM and no claim of CASINO continuation."""
from __future__ import annotations

from struct_agent.schemas.state import Decision
from .environment import MockDesignEnv


def choose_decision(env: MockDesignEnv, *, allow_switch: bool) -> Decision:
    state = env.state
    evidence = (state.latest_analysis_ref,) if state.latest_analysis_ref else ()
    if state.solver_status not in ("SUCCESS", "NOT_EVALUATED"):
        action, reason = "REQUEST_HUMAN_REVIEW", "Evaluation failed; feasibility remains unknown"
    elif state.feasible is True:
        action, reason = "FINALIZE", "Synthetic feasibility reached; no engineering conclusion"
    elif state.fea_budget_remaining == 0:
        action, reason = "FINALIZE", "Shared evaluation budget exhausted"
    elif env.has_candidate():
        action, reason = "CONTINUE_OPTIMIZATION", "Evaluate next predefined candidate in current layout"
    elif allow_switch and env.unvisited_layouts():
        return Decision(action="SWITCH_LAYOUT", reason="Current fixture queue exhausted while mock-infeasible",
                        evidence_refs=evidence, target_layout_id=env.unvisited_layouts()[0])
    else:
        action, reason = "FINALIZE", "No more candidates under this policy"
    return Decision(action=action, reason=reason, evidence_refs=evidence)
