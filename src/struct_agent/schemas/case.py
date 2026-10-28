"""Provenance of the user-selected engineering drawing, not a design approval."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import Contract


class GenerationCase(Contract):
    schema_version: Literal[1] = 1
    case_id: str = Field(min_length=1)
    dxf: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: str = Field(min_length=1)
    category: Literal[0, 1, 2]
    category_evidence: str = Field(min_length=1)
    native_coordinate_unit: Literal["mm"]
    dxf_header_insunits: int = Field(ge=0)
    unit_note: str = Field(min_length=1)
    symmetry_mode: Literal["none"]
    design_conditions_status: Literal["PENDING_ENGINEER_CONFIRMATION"]
