"""Matched wall geometry and independent beam references; global XZ, SI N/m/Pa."""
from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field

from struct_agent.schemas.base import Contract
from .contracts import SingleWallSpec
from .residential_input import prepare
from .results import roof_equilibrium


class WallCase(Contract):
    case_id: str
    stories: int = Field(ge=1, le=12)
    story_height_m: float = Field(gt=0.)
    length_m: float = Field(gt=0.)
    thickness_m: float = Field(gt=0.)
    elastic_modulus_pa: float = Field(gt=0.)
    poisson: float = Field(ge=0., lt=.5)
    tip_force_n: float = Field(gt=0.)
    subdivisions: int = Field(ge=1, le=8)
    fibers: int = Field(ge=8, le=128)
    diaphragm: Literal['none', 'physical_floors']

    @property
    def height_m(self) -> float:
        return self.stories*self.story_height_m

    @property
    def panels(self) -> int:
        return self.stories*self.subdivisions

    @property
    def shear_modulus_pa(self) -> float:
        return self.elastic_modulus_pa/(2*(1+self.poisson))


def wall_cases(spec: SingleWallSpec) -> list[WallCase]:
    """Uniform bottom-zone thickness, source wall rotated/translated into XZ.

    The zero-nu cases are constitutive controls, never replacements for C30.
    No self-weight, floor mass, floor beam or geometric nonlinearity is added.
    """
    data = prepare(spec.residential)
    member = next(m for m in spec.residential.layout.members if m.member_id == spec.source_member_id)
    common = dict(stories=spec.residential.project.stories,
        story_height_m=spec.residential.project.story_height_m,
        length_m=math.dist(member.start, member.end), thickness_m=data.floors[0].wall_thickness_m,
        elastic_modulus_pa=data.elastic_modulus_pa, tip_force_n=spec.tip_force_n, fibers=spec.fibers)
    cases = [WallCase(case_id=f'{mode}_n{n}', subdivisions=n, diaphragm=mode,
        poisson=data.poisson, **common)
        for mode in ('none', 'physical_floors') for n in spec.subdivisions]
    cases += [WallCase(case_id=f'{mode}_nu0_n{spec.subdivisions[-1]}',
        subdivisions=spec.subdivisions[-1], diaphragm=mode, poisson=0., **common)
        for mode in ('none', 'physical_floors')]
    return cases


def beam_reference(case: WallCase) -> dict[str, float]:
    """Timoshenko free-section beam estimate and MVLEM strain-energy sum.

    Beam theory is not the exact solution of a clamped 2D elastic continuum.
    The discrete formula assumes plane sections, c=0.4, centroid fibers.
    """
    f, h, l, t, e = case.tip_force_n, case.height_m, case.length_m, case.thickness_m, case.elastic_modulus_pa
    inertia = t*l**3/12
    bending = f*h**3/(3*e*inertia)
    shear = f*h/((5/6)*case.shear_modulus_pa*l*t)
    n = case.panels
    quadrature = 1/3+.1/n+(0.6**2-0.6+1/6)/n**2
    discrete = f*h**3/(e*inertia*(1-1/case.fibers**2))*quadrature+shear
    return {'bending_m':bending, 'shear_m':shear, 'timoshenko_m':bending+shear,
        'mvlem_discrete_m':discrete}


def response_checks(case: WallCase, displacement: list[list[list[float]]], reaction: dict[str, Any],
                    reference: tuple[float, ...]) -> dict[str, bool]:
    """Shape [panels+1,2,6], float64 displacements XYZ[m], rotations XYZ[rad]."""
    checks = roof_equilibrium(reaction, reference, (0., 0., case.height_m), case.tip_force_n, 'X')
    checks['finite_displacements'] = (len(displacement) == case.panels+1
        and all(len(level) == 2 and all(len(node) == 6 and all(math.isfinite(v) for v in node)
            for node in level) for level in displacement))
    checks['positive_work'] = checks['finite_displacements'] and sum(node[0] for node in displacement[-1]) > 0.
    return checks
