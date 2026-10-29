"""Physical straight wall piers independent of FE intersection subdivisions.

Global XY, metres. Only collinear, endpoint-connected segments are assembled;
no opening is bridged and no orthogonal flange is silently added to a section.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math

from ..builders.base import WallStoryElementUnit
from ..core.domain import PlanMember, Point2D


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
