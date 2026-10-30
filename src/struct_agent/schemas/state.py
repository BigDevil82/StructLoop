"""Shared actions and decisions for the real optimization workflow."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import Contract

Action = Literal["CONTINUE_OPTIMIZATION", "SWITCH_LAYOUT", "REQUEST_HUMAN_REVIEW", "FINALIZE"]


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
