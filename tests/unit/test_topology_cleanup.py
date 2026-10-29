from shapely.geometry import LineString

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
