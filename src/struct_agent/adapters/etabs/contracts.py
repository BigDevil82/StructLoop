from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from struct_agent.schemas.base import Contract
from struct_agent.schemas import LayoutCandidate, ProjectSpec, DesignCandidate


class ETABSConfig(Contract):
    install_root: Path = Path('C:/Program Files/Computers and Structures/ETABS 18')
    timeout_s: float = Field(default=180., ge=10., le=1200.)


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


class ETABSRequest(Contract):
    config: ETABSConfig
    spec: CantileverSpec | ResidentialSpec = Field(discriminator='kind')
