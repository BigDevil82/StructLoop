"""Section assembly is geometry/force bookkeeping, not a reinforcement code test."""
from dataclasses import replace
import math

import pytest

from struct_agent._vendor.shearwall_modeling.core.domain import PlanMember, Point2D
from struct_agent._vendor.shearwall_modeling.builders.base import WallStoryElementUnit
from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import wall_piers, assemble_wall_units
from struct_agent._vendor.shearwall_modeling.analysis import member_forces
from struct_agent._vendor.shearwall_modeling.analysis.combinations import cqc


def wall(index: int, a: tuple[float, float], b: tuple[float, float]) -> PlanMember:
    return PlanMember(index, 'shearwall', Point2D(*a), Point2D(*b))


def unit(member: PlanMember, tag: int, nodes: tuple[int, int]) -> WallStoryElementUnit:
    coords = {nodes[0]: (member.start.x, member.start.y, 0.), nodes[1]: (member.end.x, member.end.y, 0.),
              nodes[0]+10: (member.start.x, member.start.y, 3.), nodes[1]+10: (member.end.x, member.end.y, 3.)}
    return WallStoryElementUnit(member.m_id, 1, [tag], list(nodes), [n+10 for n in nodes], coords, member, .2, 3.)


def test_t_intersection_subdivision_is_not_an_independent_short_wall() -> None:
    panels = [wall(2, (0.,0.), (.1,0.)), wall(3, (.1,0.), (2.4,0.)), wall(9, (.1,0.), (.1,.7))]
    piers = wall_piers(panels)
    assert [p.source_ids for p in piers] == [(2,3), (9,)]
    assert piers[0].member.length == 2.4
    assert sum(p.member.length for p in piers) == pytest.approx(sum(w.length for w in panels))


@pytest.mark.parametrize('angle', [0., math.pi/2, math.pi/4])
def test_direction_and_segmentation_do_not_change_straight_pier(angle: float) -> None:
    point = lambda x: (x*math.cos(angle), x*math.sin(angle))
    parts = [wall(3, point(2.), point(1.)), wall(2, point(0.), point(1.))]
    result = wall_piers(parts)
    assert len(result) == 1 and result[0].source_ids == (2,3)
    assert result[0].member.length == pytest.approx(2.)


def test_no_opening_or_orthogonal_flange_is_merged() -> None:
    parts = [wall(0, (0.,0.), (1.,0.)), wall(1, (1.01,0.), (2.,0.)), wall(2, (1.,0.), (1.,1.))]
    assert len(wall_piers(parts)) == 3
    with pytest.raises(ValueError, match='Overlapping'):
        wall_piers([wall(0, (0.,0.), (2.,0.)), wall(1, (0.,0.), (1.,0.))])


def test_grouping_preserves_shared_nodes_elements_and_checks_section_consistency() -> None:
    first, second = unit(wall(0, (0.,0.), (1.,0.)), 1, (1,2)), unit(wall(1, (1.,0.), (2.,0.)), 2, (2,3))
    combined = assemble_wall_units([first, second])[0]
    assert combined.element_tags == [1,2] and combined.bottom_nodes == [1,2,3]
    assert combined.top_nodes == [11,12,13] and combined.source_wall_ids == (0,1)
    assert first.element_tags == [1] and second.element_tags == [2]
    with pytest.raises(ValueError, match='Changing section'):
        assemble_wall_units([first, replace(second, thickness=.3)])


def test_force_integration_includes_axial_force_moment_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = unit(wall(0, (0.,0.), (1.,0.)), 1, (1,2)), unit(wall(1, (1.,0.), (2.,0.)), 2, (2,3))
    # Each panel has zero moment about its own centroid, with N=10 and 30.
    # About group x=1: M=10*(-.5)+30*(.5)=10; V=3+7=10.
    responses = {1: [1.5,0.,5.,0.,0.,0.]*2+[0.]*12,
                 2: [3.5,0.,15.,0.,0.,0.]*2+[0.]*12}
    monkeypatch.setattr(member_forces.ops, 'eleResponse', lambda tag, *args: responses[tag])
    monkeypatch.setattr(member_forces.ops, 'eleNodes', lambda tag: [1,2,12,11] if tag == 1 else [2,3,13,12])
    assert member_forces.extract_wall_force_tuple(first) == pytest.approx((10.,0.,3.))
    assert member_forces.extract_wall_force_tuple(second) == pytest.approx((30.,0.,7.))
    grouped = assemble_wall_units([first, second])[0]
    assert member_forces.extract_wall_force_tuple(grouped) == pytest.approx((40.,10.,10.))


def test_opposite_panel_modal_forces_cancel_before_cqc(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = unit(wall(0, (0.,0.), (1.,0.)), 1, (1,2)), unit(wall(1, (1.,0.), (2.,0.)), 2, (2,3))
    grouped = assemble_wall_units([first, second])[0]
    monkeypatch.setattr(member_forces.ops, 'eleNodes', lambda tag: [1,2,12,11] if tag == 1 else [2,3,13,12])
    grouped_modes = []
    panel_modes = [[], []]
    for amplitude in (10.,20.):
        def response(tag: int, *args: object) -> list[float]:
            value = amplitude if tag == 1 else -amplitude
            return [value/2,0.,0.,0.,0.,0.]*2+[0.]*12
        monkeypatch.setattr(member_forces.ops, 'eleResponse', response)
        grouped_modes.append(member_forces.extract_wall_force_tuple(grouped)[2])
        for i, item in enumerate((first, second)):
            panel_modes[i].append(member_forces.extract_wall_force_tuple(item)[2])
    assert cqc(grouped_modes, [1.,4.], [.05,.05], [1.,1.]) == 0.
    assert sum(cqc(v, [1.,4.], [.05,.05], [1.,1.]) for v in panel_modes) > 40.
