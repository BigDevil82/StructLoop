"""Observable optimization state sent to policies, never geometry or credentials."""
from __future__ import annotations

from typing import Literal
from pydantic import Field, model_validator
from .base import Contract
from .state import Action, Decision


class LocalAdjustmentConfig(Contract):
    """Operator authorization for bounded trials, not engineering approval."""
    steps_m: tuple[float, ...] = (.1,.2)
    target_utilization: float = Field(default=1.,gt=0.,le=1.)
    max_candidates: int = Field(default=4,ge=1,le=32)
    max_trials: int = Field(default=4,ge=1,le=32)
    protected_member_ids: tuple[str, ...] = ()

    @model_validator(mode='after')
    def whole_mm(self) -> LocalAdjustmentConfig:
        if not self.steps_m or any(s<=0 or abs(s*1000-round(s*1000))>1e-7 for s in self.steps_m):
            raise ValueError('Local adjustment steps must be positive whole millimetres')
        return self


class LocalLayoutChoice(Contract):
    candidate_id: str
    control_member_id: str
    control_story: int = Field(ge=1)
    metric: Literal['beam_shear','wall_shear','wall_reinforcement']
    control_utilization: float = Field(ge=0.)
    operation: Literal['retract_wall_tip','extend_wall_tip']
    displacement_m: float = Field(gt=0.)
    reason: str
    evidence_ref: str


class LocalAdjustmentOutcome(Contract):
    parent_layout_id: str
    candidate_id: str
    accepted: bool
    solver_status: Literal['SUCCESS','MODEL_ERROR','SOLVER_ERROR','INVALID_RESULT']
    feasible: bool | None
    control_member_id: str
    control_utilization_before: float = Field(ge=0.)
    control_utilization_after: float | None = Field(default=None,ge=0.)
    material_cost_before: float = Field(ge=0.)
    material_cost_after: float | None = Field(default=None,ge=0.)
    max_beam_utilization_before: float = Field(ge=0.)
    max_beam_utilization_after: float | None = Field(default=None,ge=0.)
    evidence_ref: str


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
    local_adjustment_enabled: bool = False
    local_trials_used: int = Field(default=0,ge=0)
    local_trials_remaining: int = Field(default=0,ge=0)
    local_target_utilization: float | None = Field(default=None,gt=0.,le=1.)
    current_response: dict[str,float] = Field(default_factory=dict)
    local_layout_choices: tuple[LocalLayoutChoice,...] = ()
    local_adjustment_history: tuple[LocalAdjustmentOutcome,...] = ()

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
        if 'ADJUST_LOCAL_LAYOUT' in self.allowed_actions and (not self.local_adjustment_enabled
                or not self.local_layout_choices or not self.local_trials_remaining or not self.fea_budget_remaining):
            raise ValueError('Local adjustment requires operator authorization, candidates and budget')
        if len({c.candidate_id for c in self.local_layout_choices})!=len(self.local_layout_choices):
            raise ValueError('Duplicate local candidate IDs')
        return self


def validate_decision(decision: Decision, state: OptimizationState) -> Decision:
    if decision.action not in state.allowed_actions:
        raise ValueError("Action is not allowed in the current state")
    if decision.evidence_refs != state.evidence_refs:
        raise ValueError("Decision must cite exactly the supplied current evidence references")
    if decision.action == "SWITCH_LAYOUT" and decision.target_layout_id not in state.available_layouts:
        raise ValueError("Target must be an available unvisited layout")
    if decision.action=='ADJUST_LOCAL_LAYOUT' and decision.target_layout_id not in {c.candidate_id for c in state.local_layout_choices}:
        raise ValueError('Target must be a supplied local candidate')
    return decision
