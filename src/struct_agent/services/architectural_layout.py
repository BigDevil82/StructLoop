"""Architectural evidence for bounded, mirrored layout repairs.

This module reads original infill and opening footprints. ROOM partition edges
and the legacy beam generator are never used as evidence for a missing member.
The current layout is only the object being checked and edited.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from struct_agent.schemas import LayoutCandidate, Member, RoomGraph

from .architectural_joints import (
    joint_alignment_candidates,
    local_architecture_matches,
)


def _line(member: Member) -> LineString:
    return LineString((member.start, member.end))


def _lines(geometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [line for part in geometry.geoms for line in _lines(part)]
    return []


def _evidence(rooms: RoomGraph):
    if rooms.infill_wall_polygons is None or rooms.opening_polygons is None:
        return None
    walls = unary_union([Polygon(p) for p in rooms.infill_wall_polygons])
    openings = unary_union([Polygon(p) for p in rooms.opening_polygons])
    return walls, openings


def _mirror(line: LineString, axis_x: float) -> LineString:
    return LineString([(2 * axis_x - x, y) for x, y in line.coords])


def _rounded(line: LineString) -> tuple[tuple[float, float], tuple[float, float]]:
    return tuple(
        tuple(round(v, 3) for v in p) for p in (line.coords[0], line.coords[-1])
    )


def _coverage(line: LineString, area) -> float:
    return line.intersection(area).length / line.length


def _candidate_id(layout: LayoutCandidate, parts: list[dict]) -> str:
    raw = layout.model_dump_json().encode() + repr(parts).encode()
    return "architecture_" + hashlib.sha256(raw).hexdigest()[:12]


def architecture_candidates(
    layout: LayoutCandidate, rooms: RoomGraph
) -> list[dict[str, Any]]:
    """Find mirror gaps backed by actual wall or opening polygons.

    A proposal is a connected group of missing intervals on one axis. Only an
    existing structural counterpart can seed it; every new interval must match
    its own architectural layer and the completed beam ends must be connected.
    This is geometric preflight, never a slab or member-design approval.
    """
    evidence = _evidence(rooms)
    if evidence is None:
        return []
    infill, openings = evidence
    floor = unary_union([Polygon(p) for p in layout.slabs])
    floor_eps = floor.buffer(0.002)
    infill_eps = infill.buffer(0.02)
    openings_eps = openings.buffer(0.02)
    axis_x = (floor.bounds[0] + floor.bounds[2]) / 2
    occupied = unary_union([_line(m) for m in layout.members])
    occupied_eps = occupied.buffer(1e-8)
    parts_by_axis: dict[tuple[str, float, str], list[dict]] = defaultdict(list)
    for source in layout.members:
        line = _line(source)
        if min(abs(source.start[0] - axis_x), abs(source.end[0] - axis_x)) < 0.002:
            continue
        if (source.start[0] - axis_x) * (source.end[0] - axis_x) <= 0:
            continue
        mirrored = _mirror(line, axis_x)
        if not floor_eps.covers(mirrored):
            continue
        for missing in _lines(mirrored.difference(occupied_eps)):
            if missing.length < 0.12:
                continue
            start, end = _rounded(missing)
            segment = LineString((start, end))
            if segment.length < 0.12 or segment.intersection(occupied).length > 0.002:
                continue
            if not local_architecture_matches(
                segment, infill_eps, openings_eps, axis_x
            ):
                continue
            architectural = infill_eps if source.role == "wall" else openings_eps
            fraction = _coverage(segment, architectural)
            if fraction < (0.8 if source.role == "wall" else 0.7):
                continue
            if source.role == "wall" and _coverage(segment, openings_eps) > 0.05:
                continue
            if abs(start[1] - end[1]) < 0.002:
                key = (
                    "h",
                    round(start[1], 3),
                    "left" if start[0] < axis_x else "right",
                )
            elif abs(start[0] - end[0]) < 0.002:
                key = (
                    "v",
                    round(start[0], 3),
                    "left" if start[0] < axis_x else "right",
                )
            else:
                continue
            parts_by_axis[key].append(
                {
                    "role": source.role,
                    "start_m": start,
                    "end_m": end,
                    "source_member_id": source.member_id,
                    "architectural_coverage": round(fraction, 3),
                }
            )
    proposals = []
    for key, parts in sorted(parts_by_axis.items()):
        # Components are grouped by touching endpoints, so a beam and its wall
        # support are accepted or rejected together.
        remaining = list(parts)
        while remaining:
            group = [remaining.pop(0)]
            changed = True
            while changed:
                changed = False
                for part in remaining[:]:
                    tips = [
                        Point(p)
                        for item in group
                        for p in (item["start_m"], item["end_m"])
                    ]
                    if (
                        min(
                            t.distance(Point(p))
                            for t in tips
                            for p in (part["start_m"], part["end_m"])
                        )
                        < 0.004
                    ):
                        group.append(part)
                        remaining.remove(part)
                        changed = True
            # A matching infill wall by itself is not a structural demand. Only
            # a connected wall-and-opening-beam chain justifies a mirror repair.
            if {part["role"] == "wall" for part in group} != {True, False}:
                continue
            group, updates = _align_wall_opening_joint(group, layout, infill, axis_x)
            if not _safe_joint_alignment(
                layout, group, updates, infill_eps, openings_eps
            ):
                continue
            identity = [{"parts": group, "source_joint_updates": updates}]
            candidate_id = _candidate_id(layout, identity)
            members = _apply_parts(layout, group, candidate_id, updates)
            if members is None or not _connected(layout, members, group):
                continue
            proposals.append(
                {
                    "candidate_id": candidate_id,
                    "kind": "complete_mirrored_architecture_gap",
                    "axis": key,
                    "parts": group,
                    "source_joint_updates": updates,
                    "gap_length_m": round(
                        sum(
                            LineString((p["start_m"], p["end_m"])).length for p in group
                        ),
                        3,
                    ),
                    "scope": "Architectural and connection preflight; full FEA and slab review required.",
                }
            )
    proposals.extend(
        _classification_candidates(layout, infill_eps, openings_eps, axis_x)
    )
    for row in joint_alignment_candidates(layout, infill, openings, axis_x):
        row["candidate_id"] = _candidate_id(layout, [row["joint_updates"]])
        proposals.append(row)
    proposals.extend(_redundant_pairs(layout, infill_eps, openings_eps, axis_x))
    priority = {
        "complete_mirrored_architecture_gap": 0,
        "align_mirrored_wall_beam_joints": 1,
        "reclassify_infill_beam": 2,
        "remove_mirrored_architecture_free_pair": 3,
    }
    return sorted(
        proposals,
        key=lambda row: (
            priority[row["kind"]],
            -int(
                {part["role"] == "wall" for part in row.get("parts", [])}
                == {True, False}
            ),
            -row.get("gap_length_m", row.get("axis_length_m", 0)),
            row["candidate_id"],
        ),
    )


def _safe_joint_alignment(layout, parts, updates, infill, openings) -> bool:
    for part in parts:
        line = LineString((part["start_m"], part["end_m"]))
        if part["role"] == "wall":
            if _coverage(line, infill) < 0.8 or _coverage(line, openings) > 0.05:
                return False
        elif _coverage(line, openings) < 0.7:
            return False
    by_id = {member.member_id: member for member in layout.members}
    for update in updates:
        before = by_id[update["member_id"]]
        if before.role != "wall":
            continue
        after = before.model_copy(update={update["endpoint"]: update["after_m"]})
        if _line(after).intersection(openings).length > (
            _line(before).intersection(openings).length + 1e-6
        ):
            return False
    return True


def _classification_candidates(layout, infill, openings, axis_x) -> list[dict]:
    walls = unary_union([_line(m) for m in layout.members if m.role == "wall"])
    walls_near = walls.buffer(0.22)
    rows = []
    for member in layout.members:
        if member.role == "wall":
            continue
        line = _line(member)
        if _coverage(line, infill) < 0.9 or _coverage(line, openings) > 0.1:
            continue
        if not local_architecture_matches(line, infill, openings, axis_x):
            continue
        counterpart = _mirror(line, axis_x)
        mirrored_wall_fraction = _coverage(counterpart, walls_near)
        if mirrored_wall_fraction < 0.5:
            continue
        rows.append(
            {
                "candidate_id": _candidate_id(
                    layout, [{"retype_wall": member.member_id}]
                ),
                "kind": "reclassify_infill_beam",
                "member_ids": [member.member_id],
                "axis_length_m": round(line.length, 3),
                "infill_coverage": round(_coverage(line, infill), 3),
                "mirrored_wall_coverage": round(mirrored_wall_fraction, 3),
                "scope": "Architectural and mirror screening only; full FEA required.",
            }
        )
    return rows


def _align_wall_opening_joint(
    group: list[dict], layout: LayoutCandidate, infill, axis_x: float
):
    """Move a mirrored wall/beam transition to the original wall footprint edge."""
    if len(group) != 2 or {p["role"] == "wall" for p in group} != {True, False}:
        return group, []
    wall_part = next(p for p in group if p["role"] == "wall")
    beam_part = next(p for p in group if p["role"] != "wall")
    joint = next(
        (
            a
            for a in (wall_part["start_m"], wall_part["end_m"])
            for b in (beam_part["start_m"], beam_part["end_m"])
            if Point(a).distance(Point(b)) < 0.004
        ),
        None,
    )
    if joint is None:
        return group, []
    points = [p for item in group for p in (item["start_m"], item["end_m"])]
    if max(p[1] for p in points) - min(p[1] for p in points) < 0.002:
        axis = LineString(
            (
                (min(p[0] for p in points), joint[1]),
                (max(p[0] for p in points), joint[1]),
            )
        )
    elif max(p[0] for p in points) - min(p[0] for p in points) < 0.002:
        axis = LineString(
            (
                (joint[0], min(p[1] for p in points)),
                (joint[0], max(p[1] for p in points)),
            )
        )
    else:
        return group, []
    wall_line = LineString((wall_part["start_m"], wall_part["end_m"]))
    boundaries = [
        point
        for section in _lines(axis.intersection(infill))
        if section.intersection(wall_line).length >= 0.7 * wall_line.length
        for point in (section.coords[0], section.coords[-1])
    ]
    if not boundaries:
        return group, []
    edge = min(boundaries, key=lambda p: Point(p).distance(Point(joint)))
    edge = tuple(round(v, 3) for v in edge)
    move = Point(edge).distance(Point(joint))
    if not 0.01 <= move <= 0.15:
        return group, []
    source_old = (round(2 * axis_x - joint[0], 3), joint[1])
    source_new = (round(2 * axis_x - edge[0], 3), edge[1])
    by_id = {m.member_id: m for m in layout.members}
    updates = []
    for part in group:
        source = by_id[part["source_member_id"]]
        endpoint = next(
            (
                name
                for name in ("start", "end")
                if Point(getattr(source, name)).distance(Point(source_old)) < 0.004
            ),
            None,
        )
        if endpoint is None:
            return group, []
        updates.append(
            {
                "member_id": source.member_id,
                "endpoint": endpoint,
                "before_m": source_old,
                "after_m": source_new,
            }
        )
    adjusted = []
    for part in group:
        item = dict(part)
        for name in ("start_m", "end_m"):
            if Point(item[name]).distance(Point(joint)) < 0.004:
                item[name] = edge
        adjusted.append(item)
    return adjusted, updates


def _redundant_pairs(layout, infill, openings, axis_x) -> list[dict]:
    beams = [m for m in layout.members if m.role != "wall"]
    prior_free = _free_beam_ends(layout.members)
    rows = []
    for i, first in enumerate(beams):
        line = _line(first)
        if line.centroid.x >= axis_x or line.length > 4:
            continue
        if max(_coverage(line, infill), _coverage(line, openings)) > 0.2:
            continue
        mirrored = _mirror(line, axis_x)
        for second in beams[i + 1 :]:
            other = _line(second)
            if other.centroid.x <= axis_x or abs(other.length - line.length) > 0.25:
                continue
            if max(_coverage(other, infill), _coverage(other, openings)) > 0.2:
                continue
            if (
                mirrored.distance(other) > 0.08
                or mirrored.intersection(other.buffer(0.08)).length < 0.8 * line.length
            ):
                continue
            removed = {first.member_id, second.member_id}
            remaining = tuple(m for m in layout.members if m.member_id not in removed)
            if _free_beam_ends(remaining) - prior_free:
                continue
            rows.append(
                {
                    "candidate_id": _candidate_id(
                        layout, [{"remove_pair": sorted(removed)}]
                    ),
                    "kind": "remove_mirrored_architecture_free_pair",
                    "member_ids": sorted(removed),
                    "axis_length_m": round(line.length + other.length, 3),
                    "scope": "No opening overlap or new free beam end; slab transfer and full FEA remain unchecked.",
                }
            )
            break
    return rows


def _free_beam_ends(members: tuple[Member, ...]) -> set[tuple[str, str]]:
    axes = [_line(member) for member in members]
    return {
        (member.member_id, endpoint)
        for i, member in enumerate(members)
        if member.role != "wall"
        for endpoint in ("start", "end")
        if not any(
            axis.distance(Point(getattr(member, endpoint))) < 0.002
            for j, axis in enumerate(axes)
            if j != i
        )
    }


def _connected(
    layout: LayoutCandidate, members: tuple[Member, ...], parts: list[dict]
) -> bool:
    """No new free beam end; a wall-only addition must touch the old structure."""
    axes = [_line(m) for m in members]
    old_axes = axes[: len(layout.members)]
    for index, part in enumerate(parts, start=len(layout.members)):
        ends = [Point(part["start_m"]), Point(part["end_m"])]
        contacts = [
            any(
                axis.distance(point) < 0.002
                for j, axis in enumerate(axes)
                if j != index
            )
            for point in ends
        ]
        if part["role"] != "wall" and not all(contacts):
            return False
        if part["role"] == "wall" and not any(
            any(axis.distance(point) < 0.002 for axis in old_axes) for point in ends
        ):
            return False
    return True


def _apply_parts(
    layout: LayoutCandidate,
    parts: list[dict],
    candidate_id: str,
    updates: list[dict] | None = None,
):
    members = list(layout.members)
    for update in updates or ():
        index = next(
            i for i, m in enumerate(members) if m.member_id == update["member_id"]
        )
        members[index] = members[index].model_copy(
            update={update["endpoint"]: update["after_m"]}
        )
    existing = {m.member_id for m in members}
    for index, part in enumerate(parts):
        member_id = f"{candidate_id}_{index}"
        if member_id in existing:
            return None
        members.append(
            Member(
                member_id=member_id,
                start=part["start_m"],
                end=part["end_m"],
                role=part["role"],
            )
        )
    return tuple(members)


def apply_architecture_candidate(
    layout: LayoutCandidate, rooms: RoomGraph, candidate_id: str
) -> LayoutCandidate:
    """Apply one freshly listed candidate; caller cannot supply coordinates."""
    proposal = next(
        (
            row
            for row in architecture_candidates(layout, rooms)
            if row["candidate_id"] == candidate_id
        ),
        None,
    )
    if proposal is None:
        raise ValueError("Unknown or stale architecture candidate")
    kind = proposal["kind"]
    if kind == "complete_mirrored_architecture_gap":
        members = _apply_parts(
            layout, proposal["parts"], candidate_id, proposal["source_joint_updates"]
        )
        if members is None:
            raise ValueError("Architecture candidate collides with existing member IDs")
    elif kind == "align_mirrored_wall_beam_joints":
        updates = {row["member_id"]: row for row in proposal["joint_updates"]}
        members = tuple(
            member.model_copy(
                update={
                    updates[member.member_id]["endpoint"]: updates[member.member_id][
                        "after_m"
                    ]
                }
            )
            if member.member_id in updates
            else member
            for member in layout.members
        )
    elif kind == "reclassify_infill_beam":
        selected = set(proposal["member_ids"])
        members = tuple(
            m.model_copy(update={"role": "wall"}) if m.member_id in selected else m
            for m in layout.members
        )
    else:
        selected = set(proposal["member_ids"])
        members = tuple(m for m in layout.members if m.member_id not in selected)
    return LayoutCandidate.model_validate(
        {
            **layout.model_dump(),
            "layout_id": f"{layout.layout_id}_{candidate_id}",
            "source": "architecture_mirror_repair",
            "members": members,
        }
    )
