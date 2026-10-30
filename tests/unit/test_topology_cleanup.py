import pytest
from shapely.geometry import LineString

from struct_agent.adapters.geometry import layout_from_legacy
from struct_agent.adapters.rcgnn import layout_from_prediction, preprocess_short_members
from struct_agent.schemas import LayoutCandidate, RoomGraph
from struct_agent._vendor.data_engine.postprocess.fem_builder import FEMTopologyBuilder
from struct_agent._vendor.data_engine.postprocess.topology_cleanup import clean_segments


def segment(a: tuple, b: tuple, kind: str = 'beam') -> dict:
    line = LineString([a, b])
    return {'geometry': line, 'type': kind, 'length': line.length}


def test_endpoint_sliver_collapses_without_detaching_junction() -> None:
    segments = [segment((0,0),(1000,0),'shearwall'), segment((1000,0),(1001,0),'shearwall'),
                segment((1001,0),(2000,0),'shearwall'), segment((1000,0),(1000,1000))]
    result = clean_segments(segments, snap_tolerance=2., min_wall_length=100.)
    assert len(result) == 3
    assert all(s['length'] >= 100. for s in result)
    shared = [p for s in result for p in s['geometry'].coords if p == (1000.,0.)]
    assert len(shared) == 3


def test_small_predicted_wall_is_preserved_for_model_review_not_invented_beam() -> None:
    result = clean_segments([segment((0,0),(90,0),'shearwall')], snap_tolerance=2., min_wall_length=100.)
    assert len(result) == 1 and result[0]['type'] == 'shearwall' and result[0]['length'] == 90.
    builder = FEMTopologyBuilder(gap_tolerance=2., min_length=100.)
    walls, beams = builder._subtract_wall_from_edge(LineString([(0,0),(1000,0)]), [(0.,.09)])
    assert len(walls) == 1 and walls[0]['length'] == 90.
    assert sum(s['length'] for s in beams) == 910.


def test_unpredicted_short_gap_stays_beam_and_zero_interval_disappears() -> None:
    builder = FEMTopologyBuilder(gap_tolerance=10., min_length=100.)
    walls, beams = builder._subtract_wall_from_edge(LineString([(0,0),(2000,0)]), [(0.,.5),(.6,1.)])
    assert sum(x['length'] for x in walls) == 1800.
    assert len(beams) == 1 and beams[0]['length'] == 200.


def test_endpoint_snapping_does_not_chain_unboundedly() -> None:
    result = clean_segments([segment((x,0),(x,1000)) for x in (0.,1.5,3.)], snap_tolerance=2., min_wall_length=100.)
    assert len(result) == 2
    assert {tuple(s['geometry'].coords[0]) for s in result} == {(0.,0.),(3.,0.)}


def make_layout(segments: list[dict]) -> LayoutCandidate:
    raw = {'shearwalls': [], 'beams': [], 'slabs': [[(0,0),(3000,0),(3000,3000),(0,3000)]]}
    for item in segments:
        a, b = item['geometry'].coords
        raw['shearwalls' if item['type'] == 'shearwall' else 'beams'].append({'start': a, 'end': b})
    return layout_from_legacy(raw, unit='mm', layout_id='synthetic_cleanup', source='unit_test')


def member_geometry(layout: LayoutCandidate) -> set[tuple]:
    return {(tuple(sorted((m.start, m.end))), m.role) for m in layout.members}


@pytest.mark.parametrize('length_mm', [90., 180., 181.])
def test_short_wall_threshold_and_beam_role_are_preserved(length_mm: float) -> None:
    layout = make_layout([segment((0,0),(0,1000),'shearwall'),
        segment((0,0),(length_mm,0),'shearwall'), segment((length_mm,0),(2000,0))])
    layout = layout.model_copy(update={'members': tuple(
        m.model_copy(update={'role': 'secondary'}) if m.role != 'wall' else m for m in layout.members)})
    result = preprocess_short_members(layout)
    if length_mm <= 180.:
        assert member_geometry(result) == {(((0.,0.),(0.,1.)), 'wall'), (((0.,0.),(2.,0.)), 'secondary')}
    else:
        assert member_geometry(result) == member_geometry(layout)
    assert result.slabs == layout.slabs and result.layout_id == layout.layout_id and result.source == layout.source


def test_short_beam_fills_gap_and_keeps_crossing_node() -> None:
    layout = make_layout([segment((0,0),(900,0),'shearwall'), segment((900,0),(1000,0)),
        segment((1000,0),(1000,1000)), segment((1000,0),(1000,-1000))])
    result = preprocess_short_members(layout)
    assert member_geometry(result) == {(((0.,0.),(1.,0.)), 'wall'),
        (((1.,0.),(1.,1.)), 'primary'), (((1.,-1.),(1.,0.)), 'primary')}
    assert sum((1.,0.) in (m.start,m.end) for m in result.members) == 3


def test_prediction_conversion_closes_short_wall_end_gap(rooms: RoomGraph) -> None:
    import numpy as np
    ratios = np.ones((1,16))
    ratios[0,4], ratios[0,5] = 0., .95
    layout = layout_from_prediction(rooms, ratios, layout_id='synthetic_generation')
    assert len(layout.members) == 4 and all(m.role == 'wall' for m in layout.members)
    assert sorted(LineString([m.start,m.end]).length for m in layout.members) == [4.]*4


def test_long_wall_subdivision_is_not_flipped() -> None:
    layout = make_layout([segment((0,0),(90,0),'shearwall'), segment((90,0),(1000,0),'shearwall'),
        segment((90,0),(90,1000),'shearwall'), segment((1000,0),(2000,0))])
    assert member_geometry(preprocess_short_members(layout)) == member_geometry(layout)


def test_short_wall_without_collinear_beam_is_retained() -> None:
    layout = make_layout([segment((0,0),(180,0),'shearwall'), segment((180,0),(180,1000))])
    assert member_geometry(preprocess_short_members(layout)) == member_geometry(layout)


def test_flips_are_simultaneous_and_idempotent() -> None:
    layout = make_layout([segment((0,0),(1000,0)), segment((1000,0),(1100,0),'shearwall'),
        segment((1100,0),(1200,0)), segment((1200,0),(2200,0),'shearwall')])
    result = preprocess_short_members(layout)
    assert member_geometry(result) == {(((0.,0.),(1.1,0.)), 'primary'), (((1.1,0.),(2.2,0.)), 'wall')}
    assert preprocess_short_members(result) == result


def test_merged_primary_and_secondary_beams_require_review() -> None:
    layout = make_layout([segment((0,0),(0,1000),'shearwall'), segment((0,0),(1000,0)),
        segment((1000,0),(1100,0),'shearwall'), segment((1100,0),(2100,0))])
    layout = layout.model_copy(update={'members': tuple(
        m.model_copy(update={'role': 'secondary'}) if m.start == (1.1,0.) else m for m in layout.members)})
    with pytest.raises(ValueError, match='Merged beam roles need review'):
        preprocess_short_members(layout)
