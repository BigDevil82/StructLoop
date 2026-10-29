"""Real native-element checks, with independent force-displacement solutions."""
import math

import openseespy.opensees as ops
import pytest

from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import _beam_section_props, wall_shear_stiffness

pytestmark = pytest.mark.real


@pytest.mark.parametrize('width',[.2,2.])
def test_wall_material_is_force_displacement_not_stress_strain(width: float) -> None:
    height,thickness,g,load = 3.,.2,12e9,10000.
    ops.wipe()
    try:
        ops.model('basic','-ndm',3,'-ndf',6)
        for tag,(x,z) in enumerate(((0.,0.),(width,0.),(width,height),(0.,height)),1):
            ops.node(tag,x,0.,z)
            ops.fix(tag,*([1]*6 if tag<3 else [0,1,1,1,1,1]))
        ops.uniaxialMaterial('Elastic',1,30e9)
        ops.uniaxialMaterial('Elastic',2,wall_shear_stiffness(width,thickness,height,g))
        ops.element('MVLEM_3D',1,1,2,3,4,8,'-thick',*([thickness]*8),'-width',*([width/8]*8),
            '-rho',*([0.]*8),'-matConcrete',*([1]*8),'-matSteel',*([1]*8),'-matShear',2)
        ops.timeSeries('Linear',1)
        ops.pattern('Plain',1,1)
        for tag in (3,4):
            ops.load(tag,load/2,0.,0.,0.,0.,0.)
        ops.constraints('Plain')
        ops.numberer('Plain')
        ops.system('BandGeneral')
        ops.algorithm('Linear')
        ops.integrator('LoadControl',1.)
        ops.analysis('Static')
        assert ops.analyze(1)==0
        assert ops.nodeDisp(3,1)==pytest.approx(load*height/((5/6)*g*width*thickness),rel=1e-8)
        assert ops.nodeDisp(4,1)==pytest.approx(ops.nodeDisp(3,1),rel=1e-8)
    finally:
        ops.wipe()


def test_square_torsion_matches_saint_venant_and_scales_to_fourth_power() -> None:
    _,j,iy,iz = _beam_section_props(1.,1.)
    assert j==pytest.approx(.140577014955,rel=1e-8)
    assert j < .85*(iy+iz)
    assert _beam_section_props(2.,2.)[1]==pytest.approx(16*j)
    assert _beam_section_props(.3,.5)[1]==pytest.approx(_beam_section_props(.5,.3)[1])
