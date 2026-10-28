import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class Point2D:
    x: float
    y: float

    def __iter__(self):
        yield self.x
        yield self.y

    def __getitem__(self, index: int) -> float:
        return (self.x, self.y)[index]

    def scaled(self, factor: float) -> 'Point2D':
        return Point2D(self.x * factor, self.y * factor)

    def distance_to(self, other: 'Point2D') -> float:
        return math.hypot(other.x - self.x, other.y - self.y)

def _parse_point(raw: Any, xy_scale_to_m: float) -> Point2D:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        raise ValueError('Point must be a list/tuple with at least 2 values.')
    return Point2D(float(raw[0]) * xy_scale_to_m, float(raw[1]) * xy_scale_to_m)

@dataclass
class PlanMember:
    m_id: int
    cate: str
    start: Point2D
    end: Point2D

    @property
    def length(self) -> float:
        return self.start.distance_to(self.end)

    def scaled(self, factor: float) -> 'PlanMember':
        return PlanMember(m_id=self.m_id, cate=self.cate, start=self.start.scaled(factor), end=self.end.scaled(factor))

class BeamRole(str, Enum):
    PRIMARY = 'primary'
    SECONDARY = 'secondary'

    @classmethod
    def from_raw(cls, raw: Any) -> 'BeamRole':
        if isinstance(raw, BeamRole):
            return raw
        if raw is None:
            return cls.PRIMARY
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized == cls.PRIMARY.value:
                return cls.PRIMARY
            if normalized == cls.SECONDARY.value:
                return cls.SECONDARY
        raise ValueError(f"Unsupported beam_role={raw}. Expected 'primary' or 'secondary'.")

@dataclass
class BeamMember(PlanMember):
    role: BeamRole = BeamRole.PRIMARY

    def scaled(self, factor: float) -> 'BeamMember':
        return BeamMember(m_id=self.m_id, cate=self.cate, start=self.start.scaled(factor), end=self.end.scaled(factor), role=self.role)

@dataclass
class FEMInput:
    walls: list[PlanMember]
    beams: list['BeamMember']
    slabs: list[list[Point2D]]

    @classmethod
    def from_json(cls, json_path: Path, xy_scale_to_m: float=0.001) -> 'FEMInput':
        with json_path.open('r', encoding='utf-8') as f:
            data = json.load(f)
        walls = [PlanMember(m_id=i, cate='shearwall', start=_parse_point(w['start'], xy_scale_to_m), end=_parse_point(w['end'], xy_scale_to_m)) for i, w in enumerate(data.get('shearwalls', []))]
        beams = [BeamMember(m_id=i, cate='beam', start=_parse_point(b['start'], xy_scale_to_m), end=_parse_point(b['end'], xy_scale_to_m), role=BeamRole.from_raw(b.get('beam_role'))) for i, b in enumerate(data.get('beams', []))]
        slabs = [[Point2D(float(p[0]) * xy_scale_to_m, float(p[1]) * xy_scale_to_m) for p in slab if isinstance(p, (list, tuple)) and len(p) >= 2] for slab in data.get('slabs', []) if isinstance(slab, list)]
        return cls(walls=walls, beams=beams, slabs=slabs)

    def all_members(self) -> list[PlanMember]:
        return self.walls + self.beams

    def beams_by_role(self, role: BeamRole) -> list['BeamMember']:
        return [beam for beam in self.beams if beam.role == role]

    def beam_length_by_role(self, role: BeamRole) -> float:
        return sum((beam.length for beam in self.beams if beam.role == role and beam.length > 1e-09))

    def scaled(self, factor: float) -> 'FEMInput':
        return FEMInput(walls=[w.scaled(factor) for w in self.walls], beams=[b.scaled(factor) for b in self.beams], slabs=[[point.scaled(factor) for point in slab] for slab in self.slabs])
