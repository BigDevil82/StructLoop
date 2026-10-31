"""Physical straight wall piers independent of FE intersection subdivisions.

Global XY, metres. Only collinear, endpoint-connected segments are assembled;
no opening is bridged and no orthogonal flange is silently added to a section.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math

from ..builders.base import WallStoryElementUnit
from ..core.domain import BeamMember, PlanMember, Point2D
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


@dataclass(frozen=True)
class WallPier:
    pier_id: int
    source_ids: tuple[int, ...]
    start: Point2D
    end: Point2D

    @property
    def member(self) -> PlanMember:
        return PlanMember(self.pier_id, 'shearwall', self.start, self.end)


def wall_piers(walls: list[PlanMember]) -> list[WallPier]:
    """Assemble straight connected intervals, retaining every source ID once.

    Endpoint identity uses the builder's six-decimal-metre node key. Overlapping
    intervals are errors: merging them would hide duplicate stiffness and mass.
    """
    if len({w.m_id for w in walls}) != len(walls):
        raise ValueError('Duplicate wall segment IDs')
    parents = list(range(len(walls)))
    endpoints: dict[tuple[float, float], list[int]] = defaultdict(list)
    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    for i, wall in enumerate(walls):
        if wall.length <= 1e-9:
            raise ValueError(f'Zero wall segment {wall.m_id}')
        for point in (wall.start, wall.end):
            endpoints[round(point.x, 6), round(point.y, 6)].append(i)
    for indices in endpoints.values():
        for position, i in enumerate(indices):
            a = walls[i]
            ax, ay = a.end.x-a.start.x, a.end.y-a.start.y
            for j in indices[position+1:]:
                b = walls[j]
                bx, by = b.end.x-b.start.x, b.end.y-b.start.y
                if abs(ax*by-ay*bx) <= 1e-8*a.length*b.length:
                    parents[find(j)] = find(i)
    components: dict[int, list[PlanMember]] = defaultdict(list)
    for i, wall in enumerate(walls):
        components[find(i)].append(wall)
    result = []
    for parts in components.values():
        anchor = parts[0]
        ux = (anchor.end.x-anchor.start.x)/anchor.length
        uy = (anchor.end.y-anchor.start.y)/anchor.length
        points = [p for w in parts for p in (w.start, w.end)]
        start, end = min(points, key=lambda p: p.x*ux+p.y*uy), max(points, key=lambda p: p.x*ux+p.y*uy)
        span = start.distance_to(end)
        if not math.isclose(span, sum(w.length for w in parts), rel_tol=1e-9, abs_tol=2e-6):
            raise ValueError(f'Overlapping/disconnected wall pier {[w.m_id for w in parts]}')
        # Stable direction also makes reported signed force components reproducible.
        if (start.x, start.y) > (end.x, end.y):
            start, end = end, start
        ids = tuple(sorted(w.m_id for w in parts))
        result.append(WallPier(ids[0], ids, start, end))
    return sorted(result, key=lambda p: p.pier_id)


def assemble_wall_units(units: list[WallStoryElementUnit]) -> list[WallStoryElementUnit]:
    """Group before static/modal force extraction; leave FE nodes/elements intact."""
    stories: dict[int, list[WallStoryElementUnit]] = defaultdict(list)
    for unit in units:
        stories[unit.story].append(unit)
    result = []
    for story, mesh in sorted(stories.items()):
        by_id = {u.wall_id: u for u in mesh}
        for pier in wall_piers([u.member for u in mesh]):
            parts = [by_id[i] for i in pier.source_ids]
            first = parts[0]
            if any(u.thickness != first.thickness or u.story_height != first.story_height for u in parts):
                raise ValueError(f'Changing section within wall pier {pier.pier_id}, story {story}')
            tags = [tag for u in parts for tag in u.element_tags]
            if len(set(tags)) != len(tags):
                raise ValueError('Repeated finite element in assembled wall pier')
            result.append(WallStoryElementUnit(wall_id=pier.pier_id, story=story,
                element_tags=tags, bottom_nodes=sorted({n for u in parts for n in u.bottom_nodes}),
                top_nodes=sorted({n for u in parts for n in u.top_nodes}),
                node_coords={n: xyz for u in parts for n, xyz in u.node_coords.items()},
                member=pier.member, thickness=first.thickness, story_height=first.story_height,
                source_wall_ids=pier.source_ids))
    return result


@dataclass(frozen=True)
class BeamSpan:
    source_ids: tuple[int, ...]
    start: Point2D
    end: Point2D
    coupling: bool

    @property
    def length(self) -> float:
        return self.start.distance_to(self.end)


def beam_spans(beams: list[BeamMember], walls: list[PlanMember]) -> list[BeamSpan]:
    """Physical collinear spans; a wall is a support, an intersecting beam is not.

    Global XY metres. Keep all FE segments and branch nodes. Coupling requires
    walls at both ends and at least one wall within 30 degrees of the beam axis.
    """
    def supports(point: Point2D) -> list[PlanMember]:
        result = []
        for wall in walls:
            dx, dy = wall.end.x-wall.start.x, wall.end.y-wall.start.y
            px, py = point.x-wall.start.x, point.y-wall.start.y
            along = (px*dx+py*dy)/wall.length**2
            if -1e-7 <= along <= 1+1e-7 and abs(px*dy-py*dx)/wall.length <= 1e-6:
                result.append(wall)
        return result
    # Reuse collinear grouping, splitting a connected chain at actual wall supports.
    by_id = {b.m_id: b for b in beams}
    result = []
    for chain in wall_piers(beams):
        dx, dy = chain.end.x-chain.start.x, chain.end.y-chain.start.y
        ordered = sorted((by_id[i] for i in chain.source_ids), key=lambda b:
            min((p.x-chain.start.x)*dx+(p.y-chain.start.y)*dy for p in (b.start,b.end)))
        parts = []
        start = chain.start
        for beam in ordered:
            parts.append(beam)
            end = max((beam.start,beam.end), key=lambda p:(p.x-chain.start.x)*dx+(p.y-chain.start.y)*dy)
            if supports(end) or beam is ordered[-1]:
                left, right = supports(start), supports(end)
                aligned = any(abs(dx*(w.end.x-w.start.x)+dy*(w.end.y-w.start.y)) /
                    (chain.member.length*w.length) >= math.cos(math.pi/6)-1e-8 for w in left+right)
                result.append(BeamSpan(tuple(b.m_id for b in parts),start,end,bool(left and right and aligned)))
                start, parts = end, []
    return result


@dataclass(frozen=True)
class CompoundWallSection:
    """A local connected section, global XY metres; no FE elements are changed."""
    section_id: int
    story: int
    units: tuple[WallStoryElementUnit, ...]
    polygon: BaseGeometry
    boundary: BaseGeometry
    kind: str

    @property
    def wall_ids(self) -> tuple[int, ...]:
        return tuple(u.wall_id for u in self.units)

    @property
    def centroid(self) -> tuple[float, float]:
        return (self.polygon.centroid.x,self.polygon.centroid.y)


def compound_wall_sections(units: list[WallStoryElementUnit]) -> list[CompoundWallSection]:
    """Attach column-like short limbs (length/thickness<=3) to their host wall.

    Shared FE edge nodes are required. Do not collect the entire connected wall
    network: each short limb selects its longest nonparallel adjoining host.
    Collinear piers have already been assembled, without bridging openings.
    """
    stories: dict[int,list[WallStoryElementUnit]] = defaultdict(list)
    for unit in units:
        stories[unit.story].append(unit)
    result = []
    for story,parts in sorted(stories.items()):
        parent = list(range(len(parts)))
        active: set[int] = set()
        def find(i: int) -> int:
            while parent[i]!=i:
                i=parent[i]
            return i
        for i,u in enumerate(parts):
            if u.member.length/u.thickness>3.+1e-8:
                continue
            active.add(i)
            ux,uy=u.member.end.x-u.member.start.x,u.member.end.y-u.member.start.y
            hosts=[]
            for j,v in enumerate(parts):
                vx,vy=v.member.end.x-v.member.start.x,v.member.end.y-v.member.start.y
                connected=bool(set(u.bottom_nodes)&set(v.bottom_nodes)) and bool(set(u.top_nodes)&set(v.top_nodes))
                if i!=j and connected and abs(ux*vy-uy*vx)>1e-8*u.member.length*v.member.length:
                    hosts.append(j)
            if hosts:
                host=max(hosts,key=lambda j:(parts[j].member.length,-parts[j].wall_id))
                parent[find(i)]=find(host)
        roots={find(i) for i in active}
        for root in sorted(roots):
            members=tuple(sorted((u for i,u in enumerate(parts) if find(i)==root),key=lambda u:u.wall_id))
            rectangles=[];boundaries=[]
            for u in members:
                line=LineString([(u.member.start.x,u.member.start.y),(u.member.end.x,u.member.end.y)])
                rectangles.append(line.buffer(u.thickness/2,cap_style=2))
                hc=min(max(2*u.thickness,.15*u.member.length),u.member.length/2)
                for a,b in ((0.,hc),(u.member.length-hc,u.member.length)):
                    end_zone=LineString([line.interpolate(a),line.interpolate(b)])
                    boundaries.append(end_zone.buffer(u.thickness/2,cap_style=2))
            polygon=unary_union(rectangles)
            if polygon.geom_type!='Polygon' or polygon.interiors:
                raise ValueError(f'Disconnected/holed compound wall {[u.wall_id for u in members]}')
            result.append(CompoundWallSection(min(u.wall_id for u in members),story,members,polygon,
                unary_union(boundaries).intersection(polygon),'compound' if len(members)>1 else 'column'))
    return result
