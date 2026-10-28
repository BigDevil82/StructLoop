"""State and decisions for the explicit mock workflow; no engineering claims."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import Contract
from .layout import LayoutCandidate
from .project import DesignCandidate, ProjectSpec

Action = Literal["CONTINUE_OPTIMIZATION", "SWITCH_LAYOUT", "REQUEST_HUMAN_REVIEW", "FINALIZE"]


class MockCase(Contract):
    case_id: str = Field(min_length=1)
    fidelity: Literal["mock"]
    scenario: Literal["directional_capacity_v1"]
    spec: ProjectSpec
    layouts: tuple[LayoutCandidate, ...] = Field(min_length=1)
    designs: tuple[DesignCandidate, ...] = Field(min_length=1)
    initial_layout_id: str
    failure_design_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def references(self) -> MockCase:
        layout_ids = [layout.layout_id for layout in self.layouts]
        design_ids = [design.design_id for design in self.designs]
        if len(set(layout_ids)) != len(layout_ids) or len(set(design_ids)) != len(design_ids):
            raise ValueError("Duplicate layout/design IDs")
        if self.initial_layout_id not in layout_ids:
            raise ValueError("Unknown initial layout")
        if not set(self.failure_design_ids) <= set(design_ids):
            raise ValueError("Unknown failure-injection design")
        for design in self.designs:
            if design.layout_id not in layout_ids:
                raise ValueError("Design references unknown layout")
            design.validate_against(self.spec)
        if set(layout_ids) != {design.layout_id for design in self.designs}:
            raise ValueError("Every layout requires at least one candidate")
        return self


class DesignState(Contract):
    case_id: str
    fidelity: Literal["mock"]
    current_layout_id: str
    current_design_id: str | None = None
    status: Literal["RUNNING", "WAITING_APPROVAL", "AWAITING_REVIEW", "COMPLETED",
                    "BUDGET_EXHAUSTED", "NO_MORE_CANDIDATES"] = "RUNNING"
    solver_status: Literal["NOT_EVALUATED", "SUCCESS", "MODEL_ERROR", "SOLVER_ERROR", "INVALID_RESULT"] = "NOT_EVALUATED"
    feasible: bool | None = None
    latest_analysis_ref: str | None = None
    current_objective: float | None = None
    constraint_ratios: dict[str, float] = Field(default_factory=dict)
    best_feasible_objective: float | None = None
    best_feasible_design_id: str | None = None
    objective_unit: Literal["mock_score"] = "mock_score"
    fea_budget: int = Field(ge=1)
    fea_calls_used: int = Field(default=0, ge=0)
    candidate_cursors: dict[str, int]
    pending_layout_id: str | None = None
    event_count: int = Field(default=0, ge=0)

    @property
    def fea_budget_remaining(self) -> int:
        return self.fea_budget - self.fea_calls_used

    @model_validator(mode="after")
    def consistency(self) -> DesignState:
        if self.fea_calls_used > self.fea_budget:
            raise ValueError("FEA budget exceeded")
        if any(value < 0 for value in self.candidate_cursors.values()):
            raise ValueError("Negative candidate cursor")
        if self.current_layout_id not in self.candidate_cursors:
            raise ValueError("Current layout missing from candidate cursors")
        if (self.status == "WAITING_APPROVAL") != (self.pending_layout_id is not None):
            raise ValueError("Approval state requires exactly one pending layout")
        if self.solver_status != "SUCCESS" and self.feasible is not None:
            raise ValueError("Unsuccessful/unevaluated solver cannot declare feasibility")
        if (self.best_feasible_objective is None) != (self.best_feasible_design_id is None):
            raise ValueError("Best feasible objective/design must be recorded together")
        return self


class Decision(Contract):
    action: Action
    reason: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    target_layout_id: str | None = None

    @model_validator(mode="after")
    def target(self) -> Decision:
        if (self.action == "SWITCH_LAYOUT") != (self.target_layout_id is not None):
            raise ValueError("Only SWITCH_LAYOUT requires a target layout")
        return self


class DecisionEvent(Contract):
    event_id: str
    kind: Literal["decision", "mock_approval"]
    decision: Decision | None
    reviewer: str | None
    before: DesignState
    after: DesignState
    analysis_ref: str | None = None
    fea_calls_delta: int = Field(ge=0, le=1)

    @model_validator(mode="after")
    def consistency(self) -> DecisionEvent:
        if self.after.event_count != self.before.event_count + 1:
            raise ValueError("Event counter must advance once")
        if self.after.fea_calls_used - self.before.fea_calls_used != self.fea_calls_delta:
            raise ValueError("Recorded evaluation cost must match state transition")
        if self.kind == "decision" and (self.decision is None or self.reviewer is not None):
            raise ValueError("Decision event requires decision and no reviewer")
        if self.kind == "mock_approval" and (self.decision is not None or not self.reviewer):
            raise ValueError("Approval event requires reviewer and no decision")
        return self
