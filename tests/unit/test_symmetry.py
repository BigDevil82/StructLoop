import pytest
from shapely.geometry import LineString
from shapely.ops import unary_union

from struct_agent.adapters.symmetry import union_walls


def test_union_adds_mirror_only_on_buildable_edges() -> None:
    raw = [LineString([(0., 0.), (0., 1000.)])]
    boundaries = raw + [LineString([(2000., 0.), (2000., 2000.)])]
    result = union_walls(raw, boundaries, axis_mm=1000.)
    assert unary_union(result).length == 2000.
    assert unary_union(result).difference(unary_union(boundaries)).is_empty
    assert unary_union(union_walls(raw, raw, axis_mm=1000.)).equals(raw[0])


@pytest.mark.parametrize("axis", [float("nan"), float("inf")])
def test_invalid_axis_rejected(axis: float) -> None:
    with pytest.raises(ValueError):
        union_walls([], [], axis_mm=axis)
