"""Architecture-backed beam-grid screening before the first analysis.

This creates a trial layout. It does not establish slab strength or detailing.
"""

from __future__ import annotations

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from struct_agent.schemas import LayoutCandidate, Member, RoomGraph

from .architectural_joints import local_architecture_matches
from .architectural_layout import _free_beam_ends, architecture_candidates
from .beam_layout import review_beam_grid


def _line(member: Member) -> LineString:
    return LineString((member.start, member.end))


def _coverage(line: LineString, area) -> float:
    return line.intersection(area).length / line.length


def _close_parallel_support(member: Member, members: tuple[Member, ...]) -> bool:
    vertical = abs(member.start[0] - member.end[0]) < 0.002
    horizontal = abs(member.start[1] - member.end[1]) < 0.002
    if not (vertical or horizontal):
        return False
    variable = 1 if vertical else 0
    constant = 0 if vertical else 1
    start, end = sorted((member.start[variable], member.end[variable]))
    for other in members:
        if other.member_id == member.member_id:
            continue
        if abs(other.start[constant] - other.end[constant]) >= 0.002:
            continue
        distance = abs(member.start[constant] - other.start[constant])
        if not 0.05 < distance < 1.2:
            continue
        other_start, other_end = sorted((other.start[variable], other.end[variable]))
        if min(end, other_end) - max(start, other_start) >= 0.5 * (end - start):
            return True
    return False


def _opening_screen(member: Member, line: LineString, openings, members) -> bool:
    share = _coverage(line, openings)
    return share <= 0.08 or (share <= 0.2 and _close_parallel_support(member, members))


def _protected_floor_edge(line: LineString, floor) -> bool:
    distance = floor.boundary.distance(line)
    edge_share = floor.boundary.buffer(0.002).intersection(line).length / line.length
    return edge_share > 0.5 or 0 < distance < 0.15


def _mirrored_pairs(
    layout: LayoutCandidate, infill, openings, floor
) -> list[tuple[float, tuple[str, str]]]:
    axis_x = (floor.bounds[0] + floor.bounds[2]) / 2
    beams = [member for member in layout.members if member.role != "wall"]
    used: set[str] = set()
    pairs = []
    for first in beams:
        if first.member_id in used:
            continue
        line = _line(first)
        if not 0.3 <= line.length <= 4.0 or line.centroid.x >= axis_x:
            continue
        if _protected_floor_edge(line, floor):
            continue
        if _coverage(line, infill) > 0.25 or not _opening_screen(
            first, line, openings, layout.members
        ):
            continue
        if not local_architecture_matches(line, infill, openings, axis_x):
            continue
        mirrored = LineString([(2 * axis_x - x, y) for x, y in line.coords])
        matches = []
        for second in beams:
            if second.member_id in used or second.member_id == first.member_id:
                continue
            other = _line(second)
            if other.centroid.x <= axis_x or abs(other.length - line.length) > 0.25:
                continue
            if _protected_floor_edge(other, floor):
                continue
            if _coverage(other, infill) > 0.25 or not _opening_screen(
                second, other, openings, layout.members
            ):
                continue
            if (
                mirrored.distance(other) > 0.08
                or mirrored.intersection(other.buffer(0.08)).length < 0.8 * line.length
            ):
                continue
            matches.append((mirrored.distance(other), second))
        if not matches:
            continue
        second = min(matches, key=lambda item: item[0])[1]
        used.update((first.member_id, second.member_id))
        pairs.append(
            (line.length + _line(second).length, (first.member_id, second.member_id))
        )
    return sorted(pairs, reverse=True)


def screen_architectural_beam_grid(
    layout: LayoutCandidate,
    rooms: RoomGraph,
    *,
    max_wall_tip_loss_fraction: float = 0.2,
    max_panel_span_m: float = 4.5,
    max_panel_area_m2: float = 25.0,
) -> LayoutCandidate:
    """Retype embedded beams and remove locally mirrored, architecture-free pairs.

    The global floor midpoint only finds a counterpart. Each pair also needs
    matching local architectural layers, so an asymmetric plan is not forced to
    gain structural symmetry. Every deletion preserves beam-end connections and
    panel screening limits. The final layout still needs a full analysis.
    """
    if rooms.infill_wall_polygons is None or rooms.opening_polygons is None:
        return layout
    if not 0 <= max_wall_tip_loss_fraction < 1:
        raise ValueError("max_wall_tip_loss_fraction must be in [0, 1)")
    baseline = review_beam_grid(layout, rooms)
    infill = unary_union([Polygon(points) for points in rooms.infill_wall_polygons])
    openings = unary_union([Polygon(points) for points in rooms.opening_polygons])
    floor = unary_union([Polygon(points) for points in layout.slabs])
    embedded = {
        row["member_ids"][0]
        for row in architecture_candidates(layout, rooms)
        if row["kind"] == "reclassify_infill_beam"
    }
    current = layout.model_copy(
        update={
            "members": tuple(
                member.model_copy(update={"role": "wall"})
                if member.member_id in embedded
                else member
                for member in layout.members
            )
        }
    )
    for _, pair in _mirrored_pairs(current, infill, openings, floor):
        reduced = current.model_copy(
            update={
                "members": tuple(
                    member for member in current.members if member.member_id not in pair
                )
            }
        )
        if _free_beam_ends(reduced.members) - _free_beam_ends(current.members):
            continue
        review = review_beam_grid(reduced, rooms)
        if (
            review["beam_connected_wall_tip_count"]
            < baseline["beam_connected_wall_tip_count"]
            * (1 - max_wall_tip_loss_fraction)
            or review["max_panel_span_proxy_m"]
            > max(max_panel_span_m, baseline["max_panel_span_proxy_m"]) + 0.001
            or review["max_panel_area_m2"]
            > max(max_panel_area_m2, baseline["max_panel_area_m2"]) + 0.001
        ):
            continue
        current = reduced
    return current
