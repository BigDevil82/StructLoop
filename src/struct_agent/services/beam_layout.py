"""Constrained beam-grid proposals on one repeated floor (global XY, metres).

These geometric screens are design aids, not slab analysis or code checks.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from struct_agent.schemas import LayoutCandidate, Member, RoomGraph


def _line(member: Member) -> LineString:
    return LineString((member.start, member.end))


def _floor(layout: LayoutCandidate):
    return unary_union([Polygon(points) for points in layout.slabs])


def _panels(layout: LayoutCandidate) -> list[Polygon]:
    floor = _floor(layout)
    axes = [Polygon(points).boundary for points in layout.slabs]
    axes.extend(_line(member) for member in layout.members)
    return [
        panel
        for panel in polygonize(unary_union(axes))
        if panel.area > 1e-4 and floor.covers(panel.representative_point())
    ]


def _panel_span(panel: Polygon) -> float:
    corners = list(panel.minimum_rotated_rectangle.exterior.coords)
    return min(math.dist(corners[i], corners[i + 1]) for i in range(4))


def review_beam_grid(layout: LayoutCandidate, rooms: RoomGraph) -> dict[str, Any]:
    """Report support and panel proxies; no force, deflection or detailing claim."""
    architecture = unary_union([Polygon(points) for points in rooms.room_polygons])
    components = (
        (architecture,) if architecture.geom_type == "Polygon" else architecture.geoms
    )
    expected = unary_union([Polygon(component.exterior) for component in components])
    if _floor(layout).hausdorff_distance(expected) > 0.002:
        raise ValueError("Room graph does not match layout slabs")
    members = layout.members
    axes = [_line(member) for member in members]
    walls = [axis for axis, member in zip(axes, members) if member.role == "wall"]
    beams = [axis for axis, member in zip(axes, members) if member.role != "wall"]
    unsupported = []
    for i, member in enumerate(members):
        if member.role == "wall":
            continue
        for endpoint in ("start", "end"):
            point = Point(getattr(member, endpoint))
            if not any(
                axis.distance(point) < 0.002 for j, axis in enumerate(axes) if j != i
            ):
                unsupported.append(
                    {"member_id": member.member_id, "endpoint": endpoint}
                )
    wall_tips = []
    for member in members:
        if member.role != "wall":
            continue
        for endpoint in ("start", "end"):
            point = Point(getattr(member, endpoint))
            if any(axis.distance(point) < 0.002 for axis in beams):
                wall_tips.append((member.member_id, endpoint))
    panels = _panels(layout)
    return {
        "panel_count": len(panels),
        "max_panel_span_proxy_m": round(
            max((_panel_span(p) for p in panels), default=0.0), 3
        ),
        "max_panel_area_m2": round(max((p.area for p in panels), default=0.0), 3),
        "unsupported_beam_ends": unsupported,
        "beam_connected_wall_tip_count": len(wall_tips),
        "beam_length_m": round(
            sum(
                axis.length
                for axis, member in zip(axes, members)
                if member.role != "wall"
            ),
            3,
        ),
        "wall_count": len(walls),
        "scope": (
            "Geometric panel and beam-end proxies only; no slab FEM, "
            "tributary loading, deflection or code pass."
        ),
    }


def _candidate_id(kind: str, members: tuple[str, ...], start=None, end=None) -> str:
    source = repr((kind, members, start, end)).encode()
    return f"{kind}_{hashlib.sha256(source).hexdigest()[:12]}"


def beam_candidates(
    layout: LayoutCandidate,
    rooms: RoomGraph,
    *,
    max_panel_span_m: float = 4.5,
    max_panel_area_m2: float = 25.0,
) -> list[dict[str, Any]]:
    """Offer finite edits; rectangle partition lines have no protected status."""
    if max_panel_span_m <= 0 or max_panel_area_m2 <= 0:
        raise ValueError("Positive panel screening targets required")
    before = review_beam_grid(layout, rooms)
    members = layout.members
    walls = [_line(member) for member in members if member.role == "wall"]
    wall_axis = unary_union(walls)
    floor = _floor(layout)
    proposals = []
    for member in members:
        if member.role == "wall":
            continue
        line = _line(member)
        # A wall-to-wall opening may be a coupling beam; never remove it here.
        if all(
            wall_axis.distance(Point(point)) < 0.002
            for point in (member.start, member.end)
        ):
            continue
        reduced = layout.model_copy(
            update={"members": tuple(m for m in members if m != member)}
        )
        after = review_beam_grid(reduced, rooms)
        prior_ends = {
            (row["member_id"], row["endpoint"])
            for row in before["unsupported_beam_ends"]
        }
        new_ends = {
            (row["member_id"], row["endpoint"])
            for row in after["unsupported_beam_ends"]
        }
        allowed = (
            not new_ends - prior_ends
            and after["beam_connected_wall_tip_count"]
            >= before["beam_connected_wall_tip_count"]
            and after["max_panel_span_proxy_m"]
            <= max(max_panel_span_m, before["max_panel_span_proxy_m"]) + 0.001
            and after["max_panel_area_m2"]
            <= max(max_panel_area_m2, before["max_panel_area_m2"]) + 0.001
        )
        if allowed:
            proposals.append(
                {
                    "candidate_id": _candidate_id("remove", (member.member_id,)),
                    "kind": "remove",
                    "member_ids": [member.member_id],
                    "beam_length_reduction_m": round(line.length, 3),
                    "panel_count_after": after["panel_count"],
                    "panel_span_after_m": after["max_panel_span_proxy_m"],
                    "panel_area_after_m2": after["max_panel_area_m2"],
                }
            )
    for i, first in enumerate(members):
        if first.role == "wall":
            continue
        for second in members[i + 1 :]:
            if second.role != first.role:
                continue
            shared = set((first.start, first.end)) & set((second.start, second.end))
            if len(shared) != 1:
                continue
            joint = next(iter(shared))
            if (
                sum(_line(member).distance(Point(joint)) < 0.002 for member in members)
                != 2
            ):
                continue
            start = first.end if first.start == joint else first.start
            end = second.end if second.start == joint else second.start
            if (
                abs(
                    (start[0] - joint[0]) * (end[1] - joint[1])
                    - (start[1] - joint[1]) * (end[0] - joint[0])
                )
                > 1e-6
            ):
                continue
            proposals.append(
                {
                    "candidate_id": _candidate_id(
                        "merge", (first.member_id, second.member_id)
                    ),
                    "kind": "merge",
                    "member_ids": [first.member_id, second.member_id],
                    "start_m": start,
                    "end_m": end,
                }
            )
    # Addition is limited to aligned, wall-supported axes inside the slab footprint.
    points = sorted(
        {
            point
            for member in members
            if member.role == "wall"
            for point in (member.start, member.end)
        }
    )
    occupied_axes = [_line(member) for member in members]
    occupied = unary_union(occupied_axes)
    for i, start in enumerate(points):
        for end in points[i + 1 :]:
            if not (abs(start[0] - end[0]) < 0.002 or abs(start[1] - end[1]) < 0.002):
                continue
            line = LineString((start, end))
            if not 0.8 <= line.length <= 8.0 or not floor.buffer(0.002).covers(line):
                continue
            if line.intersection(occupied).length > 0.002:
                continue
            if any(
                (hit := line.intersection(axis)).geom_type != "Point"
                and not hit.is_empty
                or hit.geom_type == "Point"
                and 0.002 < line.project(hit) < line.length - 0.002
                for axis in occupied_axes
            ):
                continue
            if line.intersection(wall_axis).length > 0.002:
                continue
            proposals.append(
                {
                    "candidate_id": _candidate_id("add", (), start, end),
                    "kind": "add",
                    "member_ids": [],
                    "start_m": start,
                    "end_m": end,
                    "beam_length_increase_m": round(line.length, 3),
                }
            )
    return sorted(
        proposals,
        key=lambda row: (
            {"remove": 0, "merge": 1, "add": 2}[row["kind"]],
            -row.get("beam_length_reduction_m", 0.0),
            row["candidate_id"],
        ),
    )


def prune_redundant_beams(
    layout: LayoutCandidate, rooms: RoomGraph, *, max_edits: int = 12
) -> LayoutCandidate:
    """Drop only lines that form no panel edge or unique wall-tip connection.

    This deliberately leaves uncertain beam decisions to the bounded edit tool.
    """
    current = layout
    baseline = review_beam_grid(current, rooms)
    for member in sorted(
        (m for m in layout.members if m.role != "wall"),
        key=lambda m: (-_line(m).length, m.member_id),
    ):
        if len(layout.members) - len(current.members) >= max_edits:
            break
        if all(
            any(
                _line(wall).distance(Point(point)) < 0.002
                for wall in current.members
                if wall.role == "wall"
            )
            for point in (member.start, member.end)
        ):
            continue
        reduced = current.model_copy(
            update={
                "members": tuple(
                    m for m in current.members if m.member_id != member.member_id
                )
            }
        )
        after = review_beam_grid(reduced, rooms)
        if (
            after["panel_count"] != baseline["panel_count"]
            or after["max_panel_area_m2"] != baseline["max_panel_area_m2"]
            or after["max_panel_span_proxy_m"] != baseline["max_panel_span_proxy_m"]
            or after["beam_connected_wall_tip_count"]
            < baseline["beam_connected_wall_tip_count"]
            or after["unsupported_beam_ends"]
        ):
            continue
        current, baseline = reduced, after
    return current


def apply_beam_edit(
    layout: LayoutCandidate, rooms: RoomGraph, candidate_id: str
) -> LayoutCandidate:
    """Apply exactly one listed edit; arbitrary coordinates are never accepted."""
    proposal = next(
        (
            row
            for row in beam_candidates(layout, rooms)
            if row["candidate_id"] == candidate_id
        ),
        None,
    )
    if proposal is None:
        raise ValueError("Unknown or stale beam-grid candidate")
    if proposal["kind"] == "remove":
        members = tuple(
            m for m in layout.members if m.member_id not in proposal["member_ids"]
        )
    elif proposal["kind"] == "merge":
        first = next(
            m for m in layout.members if m.member_id == proposal["member_ids"][0]
        )
        members = tuple(
            m for m in layout.members if m.member_id not in proposal["member_ids"]
        )
        members += (
            Member(
                member_id=first.member_id,
                start=tuple(proposal["start_m"]),
                end=tuple(proposal["end_m"]),
                role=first.role,
            ),
        )
    else:
        member_id = "beam_agent_" + candidate_id.rsplit("_", 1)[-1]
        members = (
            *layout.members,
            Member(
                member_id=member_id,
                start=tuple(proposal["start_m"]),
                end=tuple(proposal["end_m"]),
                role="primary",
            ),
        )
    digest = hashlib.sha256(
        repr([(m.member_id, m.start, m.end, m.role) for m in members]).encode()
    ).hexdigest()[:12]
    return LayoutCandidate.model_validate(
        {
            **layout.model_dump(),
            "members": members,
            "layout_id": f"{layout.layout_id}_beam_{digest}",
            "source": "reviewed_beam_grid_edit",
        }
    )
