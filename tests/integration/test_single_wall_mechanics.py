"""Real OpenSees, no ETABS/license invoked by pytest."""
from pathlib import Path

import pytest

from struct_agent.adapters.etabs.wall_input import WallCase
from struct_agent.adapters.etabs.wall_opensees import solve_wall

pytestmark = pytest.mark.real


@pytest.mark.parametrize('subdivisions', [1, 2, 8])
def test_wall_without_artificial_section_links_matches_discrete_energy(
        tmp_path: Path, subdivisions: int) -> None:
    case = WallCase(case_id='native', stories=12, story_height_m=2.9, length_m=2.3,
        thickness_m=.2, elastic_modulus_pa=30e9, poisson=.2, tip_force_n=10000.,
        subdivisions=subdivisions, fibers=64, diaphragm='none')
    free = solve_wall(case, tmp_path/'free')
    floor = solve_wall(case.model_copy(update={'diaphragm':'physical_floors'}), tmp_path/'floors')
    for result in (free, floor):
        assert result['verified'] and result['discrete_verified']
        assert result['nodes'] == 2*(case.panels+1)
        assert result['elements'] == case.panels
        assert all(abs(node[1])+abs(node[3])+abs(node[5]) < 1e-12
            for level in result['displacement'] for node in level)
    assert floor['tip_x_m'] == pytest.approx(free['tip_x_m'], rel=1e-7)
    assert abs(free['beam_relative_difference']) < (.024 if subdivisions == 1 else .02)
