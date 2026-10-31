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


def test_compound_geometry_shares_boundary_and_does_not_bridge_an_opening() -> None:
    from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import compound_wall_sections
    host=unit(wall(1,(0.,0.),(2.,0.)),1,(1,2))
    limb=unit(wall(2,(2.,0.),(2.,.2)),2,(2,3))
    far=unit(wall(3,(2.01,0.),(2.01,.2)),3,(4,5))
    result=compound_wall_sections([host,limb,far])
    together=next(s for s in result if 1 in s.wall_ids)
    assert together.wall_ids==(1,2) and together.kind=='compound'
    assert together.polygon.area==pytest.approx(.43)
    assert together.boundary.area<together.polygon.area
    assert next(s for s in result if 3 in s.wall_ids).kind=='column'


def test_compound_resultants_include_both_moments_and_reference_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    from struct_agent._vendor.shearwall_modeling.analysis.member_forces import extract_wall_section_resultant
    host=unit(wall(1,(0.,0.),(2.,0.)),1,(1,2))
    limb=unit(wall(2,(2.,0.),(2.,.5)),2,(2,3))
    monkeypatch.setattr(member_forces.ops,'eleResponse',lambda tag,*args:([1.,0.,10.,0.,0.,0.] if tag==1 else [2.,0.,20.,0.,0.,0.])*2+[0.]*12)
    monkeypatch.setattr(member_forces.ops,'eleNodes',lambda tag:[1,2,12,11] if tag==1 else [2,3,13,12])
    a=extract_wall_section_resultant((host,limb),(1.,0.))
    b=extract_wall_section_resultant((host,limb),(3.,3.))
    assert a==pytest.approx((60.,10.,-40.,6.,0.,-1.))
    assert b==pytest.approx((60.,10.-3*60.,-40.+2*60.,6.,0.,-1.+3*6.))
    with pytest.raises(ValueError,match='Duplicate panel'):
        extract_wall_section_resultant((host,host),(1.,0.))


def test_compound_membership_and_area_are_invariant_to_host_subdivision() -> None:
    from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import compound_wall_sections
    host=unit(wall(1,(0.,0.),(2.,0.)),1,(1,2))
    limb=unit(wall(3,(2.,0.),(2.,.2)),3,(2,3))
    whole=compound_wall_sections([host,limb])[0]
    pieces=assemble_wall_units([unit(wall(1,(0.,0.),(1.,0.)),1,(1,4)),unit(wall(2,(1.,0.),(2.,0.)),2,(4,2)),limb])
    split=compound_wall_sections(pieces)[0]
    assert split.polygon.symmetric_difference(whole.polygon).area<1e-10


def test_compound_design_converges_with_refined_integration_and_counts_shared_steel_once() -> None:
    from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import compound_wall_sections
    from struct_agent._vendor.shearwall_modeling.design.results import CompoundWallDesignDemand
    from struct_agent._vendor.shearwall_modeling.design.wall import design_compound_section
    from struct_agent._vendor.shearwall_modeling.design.constants import ReinforcementDesignConstants
    from struct_agent._vendor.shearwall_modeling.core.config import MaterialConfig
    section=compound_wall_sections([unit(wall(1,(0.,0.),(2.,0.)),1,(1,2)),unit(wall(2,(2.,0.),(2.,.2)),2,(2,3))])[0]
    demand=CompoundWallDesignDemand(section,(('biaxial',400000.,10000.,100000.,True),),.5)
    coarse=design_compound_section(demand,MaterialConfig('C30'),ReinforcementDesignConstants(),spacing_mm=40.)
    fine=design_compound_section(demand,MaterialConfig('C30'),ReinforcementDesignConstants(),spacing_mm=20.)
    assert coarse.is_passed and fine.is_passed
    assert fine.longitudinal_steel_mm2==pytest.approx(coarse.longitudinal_steel_mm2,rel=.02)
    expected=coarse.boundary_ratio*section.boundary.area*1e6+.0025*(section.polygon.area-section.boundary.area)*1e6
    assert coarse.longitudinal_steel_mm2==pytest.approx(expected)
    assert max(c.relative_error for c in fine.checks)<1e-6


def test_standalone_short_limb_requires_column_review_even_when_section_balances() -> None:
    from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import compound_wall_sections
    from struct_agent._vendor.shearwall_modeling.design.results import CompoundWallDesignDemand
    from struct_agent._vendor.shearwall_modeling.design.wall import design_compound_section
    from struct_agent._vendor.shearwall_modeling.design.constants import ReinforcementDesignConstants
    from struct_agent._vendor.shearwall_modeling.core.config import MaterialConfig
    section=compound_wall_sections([unit(wall(1,(0.,0.),(.4,0.)),1,(1,2))])[0]
    result=design_compound_section(CompoundWallDesignDemand(section,(('gravity',10000.,0.,0.,False),),.5),
        MaterialConfig('C30'),ReinforcementDesignConstants())
    assert all(check.passed for check in result.checks)
    assert not result.is_passed
    assert 'column_stability_and_detailing_review_required' in result.messages


def test_compound_cqc_envelope_checks_all_independent_component_signs() -> None:
    from types import SimpleNamespace as NS
    from struct_agent._vendor.shearwall_modeling.design.extractor import DesignDemandExtractor
    from struct_agent._vendor.shearwall_modeling.analysis.uls_combinations import DEFAULT_COMBINATIONS
    host=unit(wall(1,(0.,0.),(2.,0.)),1,(1,2))
    limb=unit(wall(2,(2.,0.),(2.,.2)),2,(2,3))
    names={name for combo in DEFAULT_COMBINATIONS for name in combo.factors}
    cases={name:{(1,1):(10.,20.,30.,0.,0.,0.) if name.startswith('Eq') else (100.,0.,0.,0.,0.,0.)} for name in names}
    extractor=DesignDemandExtractor(NS(wall_story_element_units=[host,limb]),NS(seismic=NS(axial_compression_ratio_limit=.5)),NS())
    extractor._combine_beam_demands=lambda _:[]
    extractor._combine_wall_demands=lambda _:[]
    extractor.extract(NS(beam_uls_metrics=[],wall_uls_metrics=[],beam_forces_by_combo={},wall_forces_by_combo={},compound_forces_by_case=cases))
    loads=extractor.compound_demands[0].load_cases
    for combo in DEFAULT_COMBINATIONS:
        quake=[name for name in combo.factors if name.startswith('Eq')]
        if not quake or combo.factors[quake[0]]<0:continue
        rows=[row for row in loads if row[0].startswith(combo.name+':')]
        gravity=sum(f*100. for name,f in combo.factors.items() if not name.startswith('Eq'))
        amplitude=combo.factors[quake[0]]
        assert len(rows)==8
        assert {tuple(round((value-base)/scale) for value,base,scale in zip(row[1:4],(gravity,0.,0.),(10.*amplitude,20.*amplitude,30.*amplitude))) for row in rows}=={
            (n,mx,my) for n in (-1,1) for mx in (-1,1) for my in (-1,1)}
