"""Beam-grid proposals preserve supports and label geometric proxies honestly."""

import pytest

from struct_agent.schemas import LayoutCandidate, Member, RoomGraph
from struct_agent.services.beam_layout import (
    apply_beam_edit,
    beam_candidates,
    prune_redundant_beams,
    review_beam_grid,
)


def _layout(rooms: RoomGraph, *members: Member) -> LayoutCandidate:
    return LayoutCandidate(
        layout_id="beam_unit",
        source="unit_test",
        length_unit="m",
        coordinate_system="global_xy",
        members=members,
        slabs=(rooms.room_polygons[0],),
    )


def test_redundant_partition_beam_is_pruned_but_wall_to_wall_beam_remains(rooms):
    walls = (
        Member(member_id="left", start=(0.0, 0.0), end=(0.0, 4.0), role="wall"),
        Member(member_id="right", start=(4.0, 0.0), end=(4.0, 4.0), role="wall"),
    )
    supported = Member(
        member_id="supported", start=(0.0, 2.0), end=(4.0, 2.0), role="primary"
    )
    partition = Member(
        member_id="partition", start=(1.0, 1.0), end=(2.0, 1.0), role="secondary"
    )
    layout = _layout(rooms, *walls, supported, partition)
    pruned = prune_redundant_beams(layout, rooms)
    assert {member.member_id for member in pruned.members} == {
        "left",
        "right",
        "supported",
    }
    assert review_beam_grid(pruned, rooms)["max_panel_span_proxy_m"] == 2.0
    assert not any(
        row["member_ids"] == ["supported"] for row in beam_candidates(layout, rooms)
    )


def test_add_and_merge_only_use_listed_axes(rooms):
    walls = (
        Member(member_id="left", start=(0.0, 1.0), end=(0.0, 3.0), role="wall"),
        Member(member_id="right", start=(4.0, 1.0), end=(4.0, 3.0), role="wall"),
    )
    layout = _layout(rooms, *walls)
    additions = [row for row in beam_candidates(layout, rooms) if row["kind"] == "add"]
    assert additions
    added = apply_beam_edit(layout, rooms, additions[0]["candidate_id"])
    assert len(added.members) == 3
    with pytest.raises(ValueError, match="Unknown or stale"):
        apply_beam_edit(added, rooms, additions[0]["candidate_id"])
    split = _layout(
        rooms,
        *walls,
        Member(member_id="a", start=(0.0, 2.0), end=(2.0, 2.0), role="primary"),
        Member(member_id="b", start=(2.0, 2.0), end=(4.0, 2.0), role="primary"),
    )
    merges = [row for row in beam_candidates(split, rooms) if row["kind"] == "merge"]
    assert len(merges) == 1
    merged = apply_beam_edit(split, rooms, merges[0]["candidate_id"])
    assert len(merged.members) == 3
    assert any(
        {member.start, member.end} == {(0.0, 2.0), (4.0, 2.0)}
        for member in merged.members
    )
