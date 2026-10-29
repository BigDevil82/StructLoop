"""Small analytical diagnostics; SI N/m/Pa, no engineering design verdict."""
from __future__ import annotations

import math
from pathlib import Path
import traceback
from typing import Any, Literal

from struct_agent.io.artifacts import create_run, write_json


def beam_response(length_m: float, theory: Literal['euler','timoshenko']) -> dict[str,Any]:
    """0.3x0.4m horizontal cantilever under 10kN vertical tip force."""
    import openseespy.opensees as ops
    from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import _beam_section_props
    if not math.isfinite(length_m) or length_m<=0. or theory not in ('euler','timoshenko'):
        raise ValueError('Positive length and a supported beam theory required')
    e,g,force = 30e9,12.5e9,10000.
    area,j,iy,iz = _beam_section_props(.3,.4)
    bending = force*length_m**3/(3*e*iy)
    shear = force*length_m/(g*(5/6)*area)
    expected = bending+(shear if theory=='timoshenko' else 0.)
    ops.wipe()
    try:
        ops.model('basic','-ndm',3,'-ndf',6)
        ops.node(1,0.,0.,0.)
        ops.node(2,length_m,0.,0.)
        ops.fix(1,1,1,1,1,1,1)
        ops.geomTransf('Linear',1,0.,0.,1.)
        if theory=='euler':
            ops.element('elasticBeamColumn',1,1,2,area,e,g,j,iy,iz,1)
        else:
            ops.element('ElasticTimoshenkoBeam',1,1,2,e,g,area,j,iy,iz,(5/6)*area,(5/6)*area,1)
        ops.timeSeries('Linear',1)
        ops.pattern('Plain',1,1)
        ops.load(2,0.,0.,-force,0.,0.,0.)
        ops.constraints('Plain')
        ops.numberer('Plain')
        ops.system('BandGeneral')
        ops.algorithm('Linear')
        ops.integrator('LoadControl',1.)
        ops.analysis('Static')
        if ops.analyze(1)!=0:
            raise RuntimeError('Beam substructure failed')
        actual = -ops.nodeDisp(2,3)
        return {'length_m':length_m,'theory':theory,'expected_m':expected,'actual_m':actual,
            'bending_m':bending,'shear_m':shear,'relative_error':actual/expected-1,
            'verified':math.isclose(actual,expected,rel_tol=1e-8,abs_tol=1e-12)}
    finally:
        ops.wipe()


def wall_response(vertical_divisions: int, fibers: int) -> dict[str,Any]:
    """12x2x0.2m elastic wall, rigid sections, 10kN in-plane tip load.

    Section masters have UX/UZ/RY; rigid links express plane-section kinematics.
    This tests MVLEM's beam idealization, not a deep-wall or rebar design model.
    """
    import openseespy.opensees as ops
    from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import wall_shear_stiffness
    if type(vertical_divisions) is not int or not 1<=vertical_divisions<=64 or type(fibers) is not int or not 2<=fibers<=128:
        raise ValueError('Bounded positive mesh divisions and at least two fibers required')
    height,length,thickness,e,g,force = 12.,2.,.2,30e9,12.5e9,10000.
    h = height/vertical_divisions
    expected = force*height**3/(3*e*(thickness*length**3/12))+force*height/((5/6)*g*length*thickness)
    # Independent strain-energy sum: the rotational spring in panel j is at
    # z=(j+c)h. Its lever to the tip is (k+1-c)h. Equal centroid fibers have
    # I_discrete=I_gross*(1-1/m^2). Sum (k+1-c)^2 analytically, c=0.4.
    a = .6
    quadrature = 1/3+(a-.5)/vertical_divisions+(a*a-a+1/6)/vertical_divisions**2
    discrete_i = thickness*length**3/12*(1-1/fibers**2)
    discrete_expected = force*height**3/(e*discrete_i)*quadrature+force*height/((5/6)*g*length*thickness)
    ops.wipe()
    try:
        ops.model('basic','-ndm',3,'-ndf',6)
        ops.uniaxialMaterial('Elastic',1,e)
        ops.uniaxialMaterial('Elastic',2,wall_shear_stiffness(length,thickness,h,g))
        for level in range(vertical_divisions+1):
            master,left,right = 3*level+1,3*level+2,3*level+3
            z = level*h
            ops.node(master,0.,0.,z)
            ops.node(left,-length/2,0.,z)
            ops.node(right,length/2,0.,z)
            ops.fix(master,*([1]*6 if level==0 else [0,1,0,1,0,1]))
            ops.rigidLink('beam',master,left)
            ops.rigidLink('beam',master,right)
            if level:
                ops.element('MVLEM_3D',level,3*(level-1)+2,3*(level-1)+3,right,left,fibers,
                    '-thick',*([thickness]*fibers),'-width',*([length/fibers]*fibers),'-rho',*([0.]*fibers),
                    '-matConcrete',*([1]*fibers),'-matSteel',*([1]*fibers),'-matShear',2,'-CoR',.4)
        top = 3*vertical_divisions+1
        ops.timeSeries('Linear',1)
        ops.pattern('Plain',1,1)
        ops.load(top,force,0.,0.,0.,0.,0.)
        ops.constraints('Transformation')
        ops.numberer('RCM')
        ops.system('UmfPack')
        ops.algorithm('Linear')
        ops.integrator('LoadControl',1.)
        ops.analysis('Static')
        if ops.analyze(1)!=0:
            raise RuntimeError('Wall convergence model failed')
        actual = ops.nodeDisp(top,1)
        native = ops.eleResponse(1,'globalForce')
        fx = native[0]+native[6]
        my = native[4]+native[10]+(length/2)*native[2]-(length/2)*native[8]
        balanced = math.isclose(fx,-force,rel_tol=1e-6,abs_tol=1e-4) and math.isclose(my,-force*height,rel_tol=1e-6,abs_tol=1e-4)
        if not math.isfinite(actual) or actual<=0. or not balanced:
            raise ValueError(f'Invalid wall response/equilibrium: displacement={actual}, Fx={fx}, My={my}')
        return {'vertical_divisions':vertical_divisions,'fibers':fibers,'expected_m':expected,'actual_m':actual,
            'relative_error':actual/expected-1,'base_fx_n':fx,'base_my_nm':my,'balanced':balanced,
            'discrete_expected_m':discrete_expected,'discrete_relative_error':actual/discrete_expected-1,
            'discrete_verified':math.isclose(actual,discrete_expected,rel_tol=1e-8,abs_tol=1e-12)}
    finally:
        ops.wipe()


def run_substructures(directory: Path) -> dict[str,Any]:
    import openseespy.opensees as ops
    mesh = (1,2,4,8,16,32,64)
    fibers = (8,16,32,64)
    create_run(directory,seed=0,inputs={},config={'purpose':'SYNTHETIC_LINEAR_MECHANICS',
        'wall_height_m':12.,'wall_length_m':2.,'wall_thickness_m':.2,'vertical_divisions':mesh,'fibers':fibers,
        'wall_center_of_rotation':.4,'beam_width_depth_m':[.3,.4],'beam_tip_force_n':10000.})
    try:
        beams = [beam_response(length,theory) for length in (3.,1.,.3) for theory in ('euler','timoshenko')]
        walls = [wall_response(n,m) for m in fibers for n in mesh]
        result = {'purpose':'SYNTHETIC_LINEAR_MECHANICS','solver':ops.version(),'units':'N_m_kg_s',
            'beams':beams,'wall_convergence':walls,'engineering_feasibility':'NOT_EVALUATED',
            'verified':all(b['verified'] for b in beams) and all(w['discrete_verified'] for w in walls)}
        write_json(directory/'results.json',result)
        return result
    except Exception as error:
        write_json(directory/'error.json',{'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()})
        raise
