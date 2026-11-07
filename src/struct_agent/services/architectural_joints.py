"""Local wall/opening evidence for mirrored wall-to-beam junctions."""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point

from struct_agent.schemas import LayoutCandidate


def local_architecture_matches(line, infill, openings, axis_x) -> bool:
    """Compare the two original layers locally, without assuming global symmetry."""
    count = min(100, max(10, math.ceil(line.length / 0.05)))
    mismatch = 0
    for index in range(count):
        point = line.interpolate((index + 0.5) / count, normalized=True)
        twin = Point(2 * axis_x - point.x, point.y)
        if infill.covers(point) != infill.covers(twin) or openings.covers(
            point
        ) != openings.covers(twin):
            mismatch += 1
    return mismatch / count <= 0.1


def joint_alignment_candidates(
    layout: LayoutCandidate, infill, openings, axis_x: float
) -> list[dict]:
    """Align paired wall/beam tips to matching original opening boundaries."""
    junctions = _wall_beam_junctions(layout, infill, openings)
    rows = []
    for index, left in enumerate(junctions):
        if left["x"] >= axis_x:
            continue
        for right in junctions[index + 1 :]:
            if right["x"] <= axis_x:
                continue
            if abs(left["x"] + right["x"] - 2 * axis_x) > 0.005:
                continue
            if left["beam_direction"] != right["beam_direction"]:
                continue
            if abs(left["edge_y"] - right["edge_y"]) > 0.03:
                continue
            if abs(left["joint_y"] - right["joint_y"]) > 0.25:
                continue
            y_min = max(left["extent_min"], right["extent_min"])
            y_max = min(left["extent_max"], right["extent_max"])
            corridor = LineString(((left["x"], y_min), (left["x"], y_max)))
            if corridor.length < 0.5 or not local_architecture_matches(
                corridor, infill, openings, axis_x
            ):
                continue
            updates = [
                update for junction in (left, right) for update in junction["updates"]
            ]
            rows.append(
                {
                    "kind": "align_mirrored_wall_beam_joints",
                    "member_ids": [
                        left["wall_id"],
                        left["beam_id"],
                        right["wall_id"],
                        right["beam_id"],
                    ],
                    "joint_updates": updates,
                    "architectural_edge_y_m": round(
                        (left["edge_y"] + right["edge_y"]) / 2, 3
                    ),
                    "joint_mismatch_m": round(
                        abs(left["joint_y"] - right["joint_y"]), 3
                    ),
                    "scope": "Local architectural mirror and connection preflight; full FEA required.",
                }
            )
            break
    return rows


def _wall_beam_junctions(layout, infill, openings) -> list[dict]:
    walls = [member for member in layout.members if member.role == "wall"]
    rows = []
    for beam in layout.members:
        if beam.role == "wall" or abs(beam.start[0] - beam.end[0]) > 0.002:
            continue
        for wall in walls:
            if abs(wall.start[0] - wall.end[0]) > 0.002:
                continue
            if abs(wall.start[0] - beam.start[0]) > 0.002:
                continue
            joint = next(
                (
                    (beam_end, wall_end)
                    for beam_end in ("start", "end")
                    for wall_end in ("start", "end")
                    if Point(getattr(beam, beam_end)).distance(
                        Point(getattr(wall, wall_end))
                    )
                    < 0.002
                ),
                None,
            )
            if joint is None:
                continue
            beam_end, wall_end = joint
            x, joint_y = getattr(beam, beam_end)
            beam_other = getattr(beam, "end" if beam_end == "start" else "start")
            wall_other = getattr(wall, "end" if wall_end == "start" else "start")
            if (beam_other[1] - joint_y) * (wall_other[1] - joint_y) >= 0:
                continue
            extent_min = min(beam_other[1], wall_other[1])
            extent_max = max(beam_other[1], wall_other[1])
            line = LineString(((x, extent_min), (x, extent_max)))
            for opening_section in _lines(line.intersection(openings)):
                for edge in (opening_section.coords[0], opening_section.coords[-1]):
                    edge_y = edge[1]
                    if not 0.05 < abs(edge_y - joint_y) < 0.65:
                        continue
                    new_wall = LineString((wall_other, (x, edge_y)))
                    new_beam = LineString((beam_other, (x, edge_y)))
                    if min(new_wall.length, new_beam.length) < 0.12:
                        continue
                    if (
                        new_wall.intersection(infill).length / new_wall.length < 0.8
                        or new_wall.intersection(openings).length / new_wall.length
                        > 0.05
                        or new_beam.intersection(openings).length / new_beam.length
                        < 0.7
                    ):
                        continue
                    new_tip = (round(x, 3), round(edge_y, 3))
                    rows.append(
                        {
                            "x": x,
                            "joint_y": joint_y,
                            "edge_y": edge_y,
                            "extent_min": extent_min,
                            "extent_max": extent_max,
                            "beam_direction": 1 if beam_other[1] > joint_y else -1,
                            "wall_id": wall.member_id,
                            "beam_id": beam.member_id,
                            "updates": [
                                {
                                    "member_id": wall.member_id,
                                    "endpoint": wall_end,
                                    "before_m": getattr(wall, wall_end),
                                    "after_m": new_tip,
                                },
                                {
                                    "member_id": beam.member_id,
                                    "endpoint": beam_end,
                                    "before_m": getattr(beam, beam_end),
                                    "after_m": new_tip,
                                },
                            ],
                        }
                    )
    return rows


def _lines(geometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [line for part in geometry.geoms for line in _lines(part)]
    return []
