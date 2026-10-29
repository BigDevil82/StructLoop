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


class SubstructureSelection(Contract):
    name: Literal['L_wall', 'T_wall', 'wall_beam']
    member_ids: tuple[str, ...] = Field(min_length=2, max_length=20)

    @model_validator(mode='after')
    def unique_members(self) -> SubstructureSelection:
        if len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError('Duplicate selected members')
        return self


class StructuralBatchSpec(Contract):
    """Parent-derived 12-story elastic subsystems with prescribed floor masses."""
    kind: Literal['structural_batch'] = 'structural_batch'
    residential: ResidentialSpec
    selections: tuple[SubstructureSelection, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode='after')
    def source_members_exist(self) -> StructuralBatchSpec:
        if len({s.name for s in self.selections}) != len(self.selections):
            raise ValueError('Duplicate subsystem names')
        source = {m.member_id:m for m in self.residential.layout.members}
        for selection in self.selections:
            if any(key not in source for key in selection.member_ids):
                raise ValueError(f'Unknown source member in {selection.name}')
            if not any(source[key].role == 'wall' for key in selection.member_ids):
                raise ValueError('A subsystem requires walls')
        return self


class StructuralBatchSettings(Contract):
    layout: Path
    project: Path
    design: Path
    archive: Path
    single_wall: Path
    selections: tuple[SubstructureSelection, ...] = Field(min_length=1, max_length=3)


class ConnectionAuditSpec(Contract):
    """Read-only connection queries on a copied, hash-bound diagnostic EDB."""
    kind: Literal['connection_audit'] = 'connection_audit'
    model: Path
    model_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    frame_names: tuple[str, ...] | None = Field(default=None,min_length=1,max_length=1000)
    detailed_axes: bool = False
    read_generated_lines: bool = False

    @model_validator(mode='after')
    def edb_only(self) -> ConnectionAuditSpec:
        if not self.model.is_absolute() or self.model.suffix.lower() != '.edb':
            raise ValueError('An absolute EDB path is required')
        return self


class ConnectionStudySpec(Contract):
    """Fixed beam-connection counterfactuals, with unchanged parent inputs."""
    kind: Literal['connection_study'] = 'connection_study'
    residential: ResidentialSpec
    modes: tuple[Literal['default','pinned_bending'], ...] = ('default','pinned_bending')
    release_scope: Literal['all','wall_to_wall'] = 'all'

    @model_validator(mode='after')
    def bounded_beams(self) -> ConnectionStudySpec:
        count = sum(m.role != 'wall' for m in self.residential.layout.members)
        if not 1 <= count <= 100:
            raise ValueError('Connection study requires one to 100 source beams')
        if self.modes not in (('default','pinned_bending'),('pinned_bending',)):
            raise ValueError('Only the fixed paired or pinned-only diagnostic is supported')
        wall_points = {p for m in self.residential.layout.members if m.role == 'wall' for p in (m.start,m.end)}
        if self.release_scope == 'all' and any(m.start not in wall_points or m.end not in wall_points
                for m in self.residential.layout.members if m.role != 'wall'):
            raise ValueError('All-end releases leave unsupported vertical joints; use wall_to_wall scope')
        return self


class ModelFormReviewSpec(Contract):
    """Final parameter audit and walls-only stiffness counterfactual."""
    kind: Literal['model_form_review'] = 'model_form_review'
    residential: ResidentialSpec
    audit: ConnectionAuditSpec


class ETABSRequest(Contract):
    config: ETABSConfig
    spec: CantileverSpec | ResidentialSpec | SingleWallSpec | StructuralBatchSpec | ConnectionAuditSpec | ConnectionStudySpec | ModelFormReviewSpec = Field(discriminator='kind')

    @model_validator(mode='after')
    def theory_scope(self) -> ETABSRequest:
        if isinstance(self.spec,(ConnectionStudySpec,ModelFormReviewSpec)) and self.config.beam_theory != 'euler_comparison':
            raise ValueError('Connection study fixes Euler beams')
        if not isinstance(self.spec,(ResidentialSpec,StructuralBatchSpec,ConnectionStudySpec,ModelFormReviewSpec)) and (self.config.beam_theory!='timoshenko' or self.config.wall_vertical_subdivisions!=1):
            raise ValueError('Beam/mesh comparison options are supported only for the residential diagnostic')
        return self
