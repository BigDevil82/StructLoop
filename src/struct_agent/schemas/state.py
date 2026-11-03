"""Shared actions and decisions for the real optimization workflow."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import Contract

Action = Literal["CONTINUE_OPTIMIZATION", "ADJUST_LOCAL_LAYOUT", "SWITCH_LAYOUT", "REQUEST_HUMAN_REVIEW", "FINALIZE",
                 "PROPOSE_MODIFICATION", "ACCEPT_MODIFICATION", "REJECT_MODIFICATION", "QUERY_DESIGN"]


class DesignQuery(Contract):
    tool: Literal['get_design_overview','inspect_member','inspect_region']
    source: Literal['current','trial'] = 'current'
    member_id: str | None = None
    bounds_m: tuple[float,float,float,float] | None = None
    offset: int = Field(default=0,ge=0)
    limit: int = Field(default=12,ge=1,le=32)

    @model_validator(mode='after')
    def arguments(self) -> DesignQuery:
        if (self.tool=='inspect_member') != (self.member_id is not None):
            raise ValueError('Only inspect_member requires member_id')
        if (self.tool=='inspect_region') != (self.bounds_m is not None):
            raise ValueError('Only inspect_region requires bounds_m')
        if self.bounds_m and (self.bounds_m[0]>=self.bounds_m[2] or self.bounds_m[1]>=self.bounds_m[3]):
            raise ValueError('Invalid region bounds')
        return self


class DesignReview(Contract):
    diagnosis: str = Field(min_length=1, description="One sentence stating the observed problem or no problem")
    cause_hypothesis: str = Field(min_length=1, description="One sentence; hypotheses are not established causes")
    affected_member_ids: tuple[str, ...] = ()
    assessment: str = Field(min_length=1, description="Observed effect, new problems, and next-step basis")
    unresolved: tuple[str, ...] = ()


class DesignModification(Contract):
    """Typed design operation; currently only wall-tip moves are executable. XY m."""
    operation: Literal['move_wall_tip']
    source_evaluation_id: str
    source_layout_sha256: str
    target_member_id: str
    connected_member_id: str
    endpoint: Literal['start', 'end']
    delta_length_m: float = Field(allow_inf_nan=False)
    expected_effect: str = Field(min_length=1)

    @model_validator(mode='after')
    def millimetres(self) -> DesignModification:
        if self.delta_length_m == 0 or abs(self.delta_length_m*1000-round(self.delta_length_m*1000))>1e-7:
            raise ValueError('Length change must use whole millimetres')
        return self


class Decision(Contract):
    action: Action
    reason: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    target_layout_id: str | None = None
    review: DesignReview | None = None
    modification: DesignModification | None = None
    query: DesignQuery | None = None

    @model_validator(mode="after")
    def target(self) -> Decision:
        if (self.action=='QUERY_DESIGN') != (self.query is not None):
            raise ValueError('Only QUERY_DESIGN requires a query')
        if (self.action == 'PROPOSE_MODIFICATION') != (self.modification is not None):
            raise ValueError('Only PROPOSE_MODIFICATION requires a modification')
        if (self.action in ('SWITCH_LAYOUT','ADJUST_LOCAL_LAYOUT')) != (self.target_layout_id is not None):
            raise ValueError("Only SWITCH_LAYOUT/ADJUST_LOCAL_LAYOUT require a target layout")
        return self
