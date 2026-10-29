from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from struct_agent.schemas.base import Contract
from struct_agent.schemas import LayoutCandidate, ProjectSpec, DesignCandidate


class ETABSConfig(Contract):
    install_root: Path = Path('C:/Program Files/Computers and Structures/ETABS 18')
    timeout_s: float = Field(default=180., ge=10., le=1200.)
    beam_theory: Literal['timoshenko','euler_comparison'] = 'timoshenko'
    wall_vertical_subdivisions: int = Field(default=1,ge=1,le=4)


class CantileverSpec(Contract):
    """Synthetic mechanics benchmark. SI: N, m, kg, Pa, s; global XYZ."""
    kind: Literal['cantilever'] = 'cantilever'
    height_m: float = Field(default=3., gt=0., allow_inf_nan=False)
    side_m: float = Field(default=.4, gt=0., allow_inf_nan=False)
    elastic_modulus_pa: float = Field(default=30e9, gt=0., allow_inf_nan=False)
    poisson: float = Field(default=.2, gt=0., lt=.5)
    tip_force_n: float = Field(default=10000., gt=0., allow_inf_nan=False)
    tip_mass_kg: float = Field(default=10000., gt=0., allow_inf_nan=False)


class ResidentialSpec(Contract):
    """Controlled lateral diagnostic; not seismic/code-design certification."""
    kind: Literal['residential'] = 'residential'
    layout: LayoutCandidate
    project: ProjectSpec
    design: DesignCandidate
    roof_force_n: float = Field(default=1e6, gt=0., allow_inf_nan=False)

    @model_validator(mode='after')
    def consistent(self) -> ResidentialSpec:
        self.design.validate_against(self.project)
        if self.design.layout_id != self.layout.layout_id or self.project.stories > 12:
            raise ValueError('Residential diagnostic requires matching layout and at most 12 stories')
        return self


class SingleWallSpec(Contract):
    """Residential-derived, uniform-thickness reduction; not a design model."""
    kind: Literal['single_wall'] = 'single_wall'
    residential: ResidentialSpec
    source_member_id: str = Field(min_length=1)
    subdivisions: tuple[int, ...] = (1, 2, 4, 8)
    fibers: int = Field(default=64, ge=8, le=128)
    tip_force_n: float = Field(default=10000., gt=0.)

    @model_validator(mode='after')
    def bounded_study(self) -> SingleWallSpec:
        if (not self.subdivisions or tuple(sorted(set(self.subdivisions))) != self.subdivisions
                or any(n not in (1, 2, 4, 8) for n in self.subdivisions)):
            raise ValueError('Unique increasing subdivisions from 1/2/4/8 required')
        walls = [m for m in self.residential.layout.members
                 if m.member_id == self.source_member_id and m.role == 'wall']
        if len(walls) != 1:
            raise ValueError('Source must identify exactly one current wall member')
        return self


class ETABSRequest(Contract):
    config: ETABSConfig
    spec: CantileverSpec | ResidentialSpec | SingleWallSpec = Field(discriminator='kind')

    @model_validator(mode='after')
    def theory_scope(self) -> ETABSRequest:
        if not isinstance(self.spec,ResidentialSpec) and (self.config.beam_theory!='timoshenko' or self.config.wall_vertical_subdivisions!=1):
            raise ValueError('Beam/mesh comparison options are supported only for the residential diagnostic')
        return self
