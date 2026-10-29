import pytest
from dataclasses import replace
import logging
from struct_agent.schemas import ProjectSpec,DesignCandidate

from struct_agent.adapters.etabs.substructures import beam_response,wall_response

pytestmark = pytest.mark.real


@pytest.mark.parametrize('length',[3.,1.,.3])
def test_beam_theories_match_their_own_independent_closed_forms(length: float) -> None:
    euler = beam_response(length,'euler')
    timoshenko = beam_response(length,'timoshenko')
    assert euler['verified'] and timoshenko['verified']
    assert timoshenko['actual_m']-euler['actual_m']==pytest.approx(timoshenko['shear_m'],rel=1e-8)


def test_refined_mvlem_wall_approaches_elastic_beam_limit() -> None:
    coarse = wall_response(8,16)
    fine = wall_response(64,64)
    assert fine['balanced'] and coarse['balanced']
    assert fine['discrete_verified'] and coarse['discrete_verified']
    assert abs(fine['relative_error'])<abs(coarse['relative_error'])
    assert abs(fine['relative_error'])<.01


def test_diagnostic_remesh_preserves_mass_beams_and_shared_intersection(spec: ProjectSpec,design: DesignCandidate) -> None:
    import openseespy.opensees as ops
    from struct_agent.adapters.fea import native_params
    from struct_agent.adapters.etabs.reference_mesh import ReferenceMesh,refine
    from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import MVLEMFrameBuilder
    from struct_agent._vendor.shearwall_modeling.parametric.analysis import build_model_config_from_params
    from struct_agent._vendor.shearwall_modeling.core.domain import FEMInput,PlanMember,BeamMember,BeamRole,Point2D
    cfg=build_model_config_from_params(replace(native_params(design,spec),N=3))
    topology=FEMInput(walls=[PlanMember(0,'shearwall',Point2D(0.,0.),Point2D(.1,0.)),
        PlanMember(1,'shearwall',Point2D(.1,0.),Point2D(2.4,0.)),
        PlanMember(2,'shearwall',Point2D(.1,0.),Point2D(.1,.7))],
        beams=[BeamMember(3,'beam',Point2D(0.,0.),Point2D(.1,.7),BeamRole.PRIMARY)],
        slabs=[[Point2D(0.,0.),Point2D(6.,0.),Point2D(6.,6.),Point2D(0.,6.)]])
    try:
        build=MVLEMFrameBuilder(logging.getLogger('test')).build(topology,cfg)
        masses=[ops.nodeMass(p) for p in build.master_nodes]
        beams={u.element_tag for u in build.beam_element_units}
        info=refine(build,cfg,ReferenceMesh(vertical_subdivisions=2,fiber_refinement=2))
        assert info['wall_elements']==18 and info['beam_elements']==3
        assert beams.issubset(set(ops.getEleTags()))
        assert [ops.nodeMass(p) for p in build.master_nodes]==masses
        mid=[p for p in ops.getNodeTags() if tuple(round(v,7) for v in ops.nodeCoord(p))==(.1,0.,1.45)]
        assert len(mid)==1
        assert sum(mid[0] in ops.eleNodes(tag) for tag in ops.getEleTags())==6
    finally:
        ops.wipe()


def test_one_to_one_wall_reconstruction_preserves_static_response(spec: ProjectSpec,design: DesignCandidate) -> None:
    import openseespy.opensees as ops
    from struct_agent.adapters.fea import native_params
    from struct_agent.adapters.etabs.reference_mesh import ReferenceMesh,refine
    from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import MVLEMFrameBuilder
    from struct_agent._vendor.shearwall_modeling.parametric.analysis import build_model_config_from_params
    from struct_agent._vendor.shearwall_modeling.core.domain import FEMInput,PlanMember,Point2D
    cfg=build_model_config_from_params(replace(native_params(design,spec),N=3))
    topology=FEMInput(walls=[PlanMember(0,'shearwall',Point2D(0.,0.),Point2D(2.,0.)),
        PlanMember(1,'shearwall',Point2D(0.,0.),Point2D(0.,2.))],beams=[],
        slabs=[[Point2D(0.,0.),Point2D(4.,0.),Point2D(4.,4.),Point2D(0.,4.)]])
    def solve(master: int,tag: int) -> tuple[float,...]:
        ops.reset();ops.wipeAnalysis()
        ops.constraints('Transformation');ops.numberer('RCM');ops.system('UmfPack')
        ops.timeSeries('Linear',tag);ops.pattern('Plain',tag,tag)
        ops.load(master,10000.,0.,0.,0.,0.,0.)
        ops.algorithm('Linear');ops.integrator('LoadControl',1.);ops.analysis('Static')
        assert ops.analyze(1)==0
        value=tuple(ops.nodeDisp(master))
        ops.remove('loadPattern',tag)
        return value
    try:
        build=MVLEMFrameBuilder(logging.getLogger('test')).build(topology,cfg)
        before=solve(build.master_nodes[-1],1)
        refine(build,cfg,ReferenceMesh(rebuild_walls=True))
        after=solve(build.master_nodes[-1],2)
        assert after==pytest.approx(before,rel=1e-9,abs=1e-12)
    finally:
        ops.wipe()
