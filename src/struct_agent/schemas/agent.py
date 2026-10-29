"""Observable optimization state sent to policies, never geometry or credentials."""
from __future__ import annotations

from typing import Literal
from pydantic import Field, model_validator
from .base import Contract
from .state import Action, Decision


class OptimizationState(Contract):
    case_id: str
    fidelity: Literal["full", "mock"]
    layout_id: str
    session_status: Literal["ready", "paused", "completed", "budget_exhausted", "analysis_failed", "optimizer_failed"]
    solver_status: Literal["NOT_EVALUATED", "SUCCESS", "MODEL_ERROR", "SOLVER_ERROR", "INVALID_RESULT"]
    latest_feasible: bool | None = None
    fea_budget: int = Field(ge=1)
    fea_calls_used: int = Field(ge=0)
    fea_budget_remaining: int = Field(ge=0)
    completed_generations: int = Field(ge=0)
    best_feasible_cost: float | None = Field(default=None, ge=0.)
    current_best_objective: float | None = None
    current_best_violation: float | None = Field(default=None, ge=0.)
    current_best_feasible: bool | None = None
    normalized_violations: dict[str, float] = Field(default_factory=dict)
    stagnation_steps: int = Field(ge=0)
    calibration_samples: int = Field(ge=0)
    available_layouts: tuple[str, ...] = ()
    allowed_actions: tuple[Action, ...]
    evidence_refs: tuple[str, ...] = ()
    action_history: tuple[Action, ...] = ()
    engineering_review: Literal["PENDING"] = "PENDING"

    @model_validator(mode="after")
    def consistent(self) -> OptimizationState:
        if self.fea_budget != self.fea_calls_used + self.fea_budget_remaining:
            raise ValueError("Inconsistent evaluation budget")
        if self.solver_status != "SUCCESS" and self.latest_feasible is not None:
            raise ValueError("Failed or absent analysis cannot declare feasibility")
        if not self.allowed_actions:
            raise ValueError("Policy state requires at least one allowed action")
        if "REQUEST_HUMAN_REVIEW" not in self.allowed_actions:
            raise ValueError("Human review must remain available for API/execution failures")
        if "SWITCH_LAYOUT" in self.allowed_actions and not self.available_layouts:
            raise ValueError("Switch requires an explicit available candidate")
        return self


def validate_decision(decision: Decision, state: OptimizationState) -> Decision:
    if decision.action not in state.allowed_actions:
        raise ValueError("Action is not allowed in the current state")
    if decision.evidence_refs != state.evidence_refs:
        raise ValueError("Decision must cite exactly the supplied current evidence references")
    if decision.action == "SWITCH_LAYOUT" and decision.target_layout_id not in state.available_layouts:
        raise ValueError("Target must be an available unvisited layout")
    return decision
