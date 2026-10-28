"""Real OpenSees cantilevers checked against elementary beam mechanics."""
import math

import openseespy.opensees as ops
import pytest

from struct_agent._vendor.shearwall_modeling.analysis.member_forces import extract_beam_force_tuple

pytestmark = pytest.mark.real


@pytest.mark.parametrize('angle', [0., math.pi/2, math.pi/4])
def test_cantilever_local_bending_and_shear(angle: float) -> None:
    ops.wipe()
    try:
        ops.model('basic', '-ndm', 3, '-ndf', 6)
        length, load = 3., 10000.
        ops.node(1, 0., 0., 0.)
        ops.node(2, length*math.cos(angle), length*math.sin(angle), 0.)
        ops.fix(1, 1, 1, 1, 1, 1, 1)
        ops.geomTransf('Linear', 1, 0., 0., 1.)
        ops.element('elasticBeamColumn', 1, 1, 2, .1, 3e10, 1.2e10, .002, .004, .001, 1)
        ops.timeSeries('Linear', 1)
        ops.pattern('Plain', 1, 1)
        ops.load(2, 0., 0., -load, 0., 0., 0.)
        ops.constraints('Plain')
        ops.numberer('Plain')
        ops.system('BandGeneral')
        ops.algorithm('Linear')
        ops.integrator('LoadControl', 1.)
        ops.analysis('Static')
        assert ops.analyze(1) == 0
        moment_i, moment_j, shear = extract_beam_force_tuple(1)
        assert moment_i == pytest.approx(-load*length, rel=1e-10)
        assert moment_j == pytest.approx(0., abs=1e-8)
        assert shear == pytest.approx(load, rel=1e-10)
        assert ops.nodeDisp(2, 3) == pytest.approx(-load*length**3/(3*3e10*.004), rel=1e-10)
    finally:
        ops.wipe()
