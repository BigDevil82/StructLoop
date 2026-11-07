"""Architectural candidates come from wall/opening evidence, not ROOM edges."""

import pytest
from struct_agent.schemas import LayoutCandidate, Member
from struct_agent.services.architectural_layout import (
    apply_architecture_candidate,
    architecture_candidates,
)


def _rectangle(a, b, c, d):
    return ((a, b), (c, b), (c, d), (a, d))


def test_mirrored_opening_and_wall_gap_is_one_bounded_edit(rooms):
    graph = rooms.model_copy(
        update={
            "infill_wall_polygons": (
                _rectangle(1, 1.9, 1.5, 2.1),
                _rectangle(2.5, 1.9, 3, 2.1),
            ),
            "opening_polygons": (
                _rectangle(0.5, 1.9, 1, 2.1),
                _rectangle(3, 1.9, 3.5, 2.1),
            ),
        }
    )
    layout = LayoutCandidate(
        layout_id="mirror_gap",
        source="unit",
        length_unit="m",
        coordinate_system="global_xy",
        slabs=(rooms.room_polygons[0],),
        members=(
            Member(
                member_id="left_beam", start=(0.5, 2), end=(0.75, 2), role="secondary"
            ),
            Member(
                member_id="left_support", start=(1.5, 2), end=(1.5, 2.8), role="wall"
            ),
            Member(member_id="right_wall", start=(2.5, 2), end=(3, 2), role="wall"),
            Member(
                member_id="right_beam", start=(3, 2), end=(3.5, 2), role="secondary"
            ),
        ),
    )
    proposal = next(
        row
        for row in architecture_candidates(layout, graph)
        if row["kind"] == "complete_mirrored_architecture_gap"
    )
    assert proposal["gap_length_m"] == 0.75
    assert {part["role"] for part in proposal["parts"]} == {"wall", "secondary"}
    changed = apply_architecture_candidate(layout, graph, proposal["candidate_id"])
    assert len(changed.members) == len(layout.members) + 2
    assert {m.role for m in changed.members[-2:]} == {"wall", "secondary"}
    with pytest.raises(ValueError, match="stale"):
        apply_architecture_candidate(changed, graph, proposal["candidate_id"])
    assert architecture_candidates(layout, rooms) == []


def test_embedded_beam_and_architecture_free_mirror_pair_are_separate_candidates(rooms):
    graph = rooms.model_copy(
        update={
            "infill_wall_polygons": (
                _rectangle(0.5, 0.9, 1.5, 1.1),
                _rectangle(2.5, 0.9, 3.5, 1.1),
            ),
            "opening_polygons": (),
        }
    )
    layout = LayoutCandidate(
        layout_id="role_and_pair",
        source="unit",
        length_unit="m",
        coordinate_system="global_xy",
        slabs=(rooms.room_polygons[0],),
        members=(
            Member(
                member_id="left_embedded", start=(0.5, 1), end=(1.5, 1), role="primary"
            ),
            Member(member_id="right_wall", start=(2.5, 1), end=(3.5, 1), role="wall"),
            Member(
                member_id="left_partition",
                start=(0.5, 2),
                end=(1.5, 2),
                role="secondary",
            ),
            Member(
                member_id="right_partition",
                start=(2.5, 2),
                end=(3.5, 2),
                role="secondary",
            ),
            Member(member_id="left_support", start=(0.5, 1), end=(0.5, 2), role="wall"),
            Member(
                member_id="right_support", start=(3.5, 1), end=(3.5, 2), role="wall"
            ),
        ),
    )
    rows = architecture_candidates(layout, graph)
    retype = next(row for row in rows if row["kind"] == "reclassify_infill_beam")
    assert retype["member_ids"] == ["left_embedded"]
    changed = apply_architecture_candidate(layout, graph, retype["candidate_id"])
    assert (
        next(m for m in changed.members if m.member_id == "left_embedded").role
        == "wall"
    )
    pair = next(
        row for row in rows if row["kind"] == "remove_mirrored_architecture_free_pair"
    )
    assert set(pair["member_ids"]) == {"left_partition", "right_partition"}
    removed = apply_architecture_candidate(layout, graph, pair["candidate_id"])
    assert {m.member_id for m in removed.members}.isdisjoint(pair["member_ids"])


def test_wall_beam_joints_align_only_when_original_openings_match(rooms):
    graph = rooms.model_copy(
        update={
            "infill_wall_polygons": (
                _rectangle(0.9, 1.6, 1.1, 2.6),
                _rectangle(2.9, 1.6, 3.1, 2.6),
            ),
            "opening_polygons": (
                _rectangle(0.9, 1, 1.1, 1.6),
                _rectangle(2.9, 1, 3.1, 1.6),
            ),
        }
    )
    layout = LayoutCandidate(
        layout_id="two_joints",
        source="unit",
        length_unit="m",
        coordinate_system="global_xy",
        slabs=(rooms.room_polygons[0],),
        members=(
            Member(member_id="left_beam", start=(1, 1), end=(1, 1.9), role="secondary"),
            Member(member_id="left_wall", start=(1, 1.9), end=(1, 2.5), role="wall"),
            Member(
                member_id="right_beam", start=(3, 1), end=(3, 1.8), role="secondary"
            ),
            Member(member_id="right_wall", start=(3, 1.8), end=(3, 2.5), role="wall"),
        ),
    )
    aligned = next(
        row
        for row in architecture_candidates(layout, graph)
        if row["kind"] == "align_mirrored_wall_beam_joints"
    )
    assert aligned["joint_mismatch_m"] == 0.1
    changed = apply_architecture_candidate(layout, graph, aligned["candidate_id"])
    assert all(
        next(m for m in changed.members if m.member_id == member_id).end == (x, 1.6)
        for member_id, x in (("left_beam", 1), ("right_beam", 3))
    )
    asymmetric = graph.model_copy(
        update={
            "opening_polygons": (
                _rectangle(0.9, 1, 1.1, 1.6),
                _rectangle(2.9, 1, 3.1, 1.4),
            )
        }
    )
    assert not any(
        row["kind"] == "align_mirrored_wall_beam_joints"
        for row in architecture_candidates(layout, asymmetric)
    )
