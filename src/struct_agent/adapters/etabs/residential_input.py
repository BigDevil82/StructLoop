"""Explicit SI verification inputs, independently computed geometric quantities."""
from __future__ import annotations

from dataclasses import dataclass
import math

from struct_agent.schemas import LayoutCandidate, Member
from .contracts import ResidentialSpec


@dataclass(frozen=True)
class FloorInput:
    story: int
    height_m: float
    elevation_m: float
    wall_thickness_m: float
    mass_kg: float
    inertia_kg_m2: float


@dataclass(frozen=True)
class ResidentialInput:
    layout: LayoutCandidate
    origin_xy_m: tuple[float,float]
    centre_xy_m: tuple[float,float]
    points: tuple[tuple[float,float],...]
    floors: tuple[FloorInput,...]
    area_m2: float
    elastic_modulus_pa: float
    poisson: float


def prepare(spec: ResidentialSpec) -> ResidentialInput:
    from struct_agent._vendor.shearwall_modeling.core.config import MaterialConfig
    from struct_agent._vendor.shearwall_modeling.parametric.space import split_stories
    source = spec.layout
    origin = tuple(min(p[i] for m in source.members for p in (m.start,m.end)) for i in (0,1))
    def local(p: tuple[float,float]) -> tuple[float,float]:
        return round(p[0]-origin[0],6),round(p[1]-origin[1],6)
    layout = LayoutCandidate(layout_id=source.layout_id,source=source.source,length_unit='m',coordinate_system='global_xy',
        members=tuple(Member(member_id=m.member_id,start=local(m.start),end=local(m.end),role=m.role) for m in source.members),
        slabs=tuple(tuple(local(p) for p in poly) for poly in source.slabs))
    points = tuple(sorted({p for m in layout.members for p in (m.start,m.end)}))
    centre = (sum(p[0] for p in points)/len(points),sum(p[1] for p in points)/len(points))
    radius2 = sum((p[0]-centre[0])**2+(p[1]-centre[1])**2 for p in points)/len(points)
    area = sum(abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(poly,poly[1:]+poly[:1])))/2 for poly in layout.slabs)
    if area < 16.:
        raise ValueError('Diagnostic does not support the upstream minimum-floor-area fallback')
    values = spec.design.values
    material = MaterialConfig(concrete_grade=str(values['conc_bot']))
    n1,n2,n3 = split_stories(spec.project.stories)
    thicknesses = [float(values['tw_bot'])]*n1+[float(values['tw_mid'])]*n2+[float(values['tw_top'])]*n3
    floors = []
    for story,thickness in enumerate(thicknesses,1):
        volume = sum(math.dist(m.start,m.end)*(thickness*spec.project.story_height_m if m.role=='wall'
            else float(values['bb_main' if m.role=='primary' else 'bb_sec'])*float(values['hb_main' if m.role=='primary' else 'hb_sec']))
            for m in layout.members)
        # Migrated protocol: 5 kPa dead includes slab weight, plus 0.5*2 kPa live.
        # Identical prescribed masses isolate stiffness/model differences. This
        # does not validate the physical adequacy of the endpoint-based inertia.
        mass = volume*material.density_kg_m3+area*6000./9.81
        floors.append(FloorInput(story,spec.project.story_height_m,story*spec.project.story_height_m,
            thickness,mass,mass*radius2))
    poisson = float(material.E)/(2*float(material.G))-1
    return ResidentialInput(layout,origin,centre,points,tuple(floors),area,float(material.E),poisson)
