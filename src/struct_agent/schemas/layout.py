from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import Contract


class Member(Contract):
    """Plan segment: Shape [2,2], float64, global XY, length m."""
    member_id: str = Field(min_length=1)
    start: tuple[float, float]
    end: tuple[float, float]
    role: Literal["wall", "primary", "secondary"]

    @model_validator(mode="after")
    def nonzero(self) -> Member:
        if self.start == self.end:
            raise ValueError("Zero-length member")
        return self


class LayoutCandidate(Contract):
    """Single repeated standard floor; includes beams/slabs required by FEA."""
    schema_version: Literal[1] = 1
    layout_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    length_unit: Literal["m"]
    coordinate_system: Literal["global_xy"]
    members: tuple[Member, ...] = Field(min_length=1)
    slabs: tuple[tuple[tuple[float, float], ...], ...]

    @model_validator(mode="after")
    def valid_topology(self) -> LayoutCandidate:
        if not any(m.role == "wall" for m in self.members):
            raise ValueError("Layout requires at least one wall")
        ids = [m.member_id for m in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate member IDs")
        if not self.slabs:
            raise ValueError("FEA requires explicit slab polygons")
        for poly in self.slabs:
            area = sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(poly, poly[1:]+poly[:1])) / 2
            if len(poly) < 3 or abs(area) <= 1e-12:
                raise ValueError("Invalid slab polygon")
        return self
