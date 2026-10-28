"""Operator-provided, geometry/condition-bound approval; never a model tool."""
from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field
from struct_agent.schemas import LayoutCandidate, ProjectSpec
from struct_agent.schemas.base import Contract


class LayoutApproval(Contract):
    layout_id: str = Field(min_length=1)
    layout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1)
    purpose: Literal["smoke_only", "research"]
    authorization: str = Field(min_length=1)

    def check(self, layout: LayoutCandidate, spec: ProjectSpec, purpose: str) -> None:
        if (self.layout_id != layout.layout_id or self.purpose != purpose or not self.reviewer.strip()
                or self.layout_sha256 != hashlib.sha256(layout.model_dump_json().encode()).hexdigest()
                or self.spec_sha256 != hashlib.sha256(spec.model_dump_json().encode()).hexdigest()):
            raise ValueError("Approval does not match layout, conditions, purpose or reviewer")
