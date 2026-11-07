"""New drawing screening uses local architecture evidence before analysis."""

from shapely.geometry import LineString, Polygon

from struct_agent.schemas import LayoutCandidate, Member
from struct_agent.services.architecture_beam_screen import (
    _protected_floor_edge,
    screen_architectural_beam_grid,
)


def _layout(rooms):
    return LayoutCandidate(
        layout_id="paired_partition",
        source="unit",
        length_unit="m",
        coordinate_system="global_xy",
        slabs=(rooms.room_polygons[0],),
        members=(
            Member(
                member_id="left_wall", start=(0.5, 0.5), end=(0.5, 2.5), role="wall"
            ),
            Member(
                member_id="right_wall", start=(3.5, 0.5), end=(3.5, 2.5), role="wall"
            ),
            Member(
                member_id="left_beam", start=(0.5, 2), end=(1.5, 2), role="secondary"
            ),
            Member(
                member_id="right_beam", start=(2.5, 2), end=(3.5, 2), role="secondary"
            ),
        ),
    )


def test_architecture_free_pair_is_removed_together(rooms):
    graph = rooms.model_copy(
        update={"infill_wall_polygons": (), "opening_polygons": ()}
    )
    screened = screen_architectural_beam_grid(_layout(rooms), graph)
    assert {member.member_id for member in screened.members} == {
        "left_wall",
        "right_wall",
    }


def test_asymmetric_architecture_does_not_force_pair_removal(rooms):
    graph = rooms.model_copy(
        update={
            "infill_wall_polygons": (
                ((0.5, 1.9), (0.65, 1.9), (0.65, 2.1), (0.5, 2.1)),
            ),
            "opening_polygons": (),
        }
    )
    screened = screen_architectural_beam_grid(_layout(rooms), graph)
    assert len(screened.members) == 4


def test_missing_architecture_keeps_original_grid(rooms):
    layout = _layout(rooms)
    assert screen_architectural_beam_grid(layout, rooms) is layout


def test_floor_perimeter_is_protected_but_touching_end_is_not():
    floor = Polygon(((0, 0), (4, 0), (4, 4), (0, 4)))
    assert _protected_floor_edge(LineString(((0, 0), (1, 0))), floor)
    assert not _protected_floor_edge(LineString(((1, 1), (1, 0))), floor)
