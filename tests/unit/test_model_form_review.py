import math
from pathlib import Path

import pytest

from struct_agent.adapters.etabs.axis_review import review_axes
from struct_agent.adapters.etabs.contracts import ConnectionAuditSpec, ETABSConfig, ETABSRequest, ModelFormReviewSpec, ResidentialSpec
from struct_agent.adapters.etabs.reference_mesh import ReferenceMesh
from struct_agent.schemas import DesignCandidate, LayoutCandidate, ProjectSpec


@pytest.mark.parametrize('angle',[0.,.63,math.pi/2,math.pi])
def test_physical_bending_tensor_handles_different_axis_names_and_reversed_beams(
        angle: float, spec: ProjectSpec, design: DesignCandidate, layout: LayoutCandidate) -> None:
    parent = ResidentialSpec(project=spec.model_copy(update={'stories':12}),layout=layout,design=design)
    c,s = math.cos(angle),math.sin(angle)
    width,depth = design.values['bb_main'],design.values['hb_main']
    weak,strong = depth*width**3/12,width*depth**3/12
    audit = {'frames':{'beam':{'coordinates_m':[[0.,0.,2.9],[2*c,2*s,2.9]],'section':['primary',''],
        'transformation':[c,0.,s,s,0.,-c,0.,1.,0.]}},
        'section_properties':{'primary':[width*depth,0.,0.,0.,weak,strong]}}
    assert review_axes(audit,parent)['verified']
    audit['section_properties']['primary'][4:6] = [strong,weak]
    assert not review_axes(audit,parent)['verified']
    audit['frames']['beam']['transformation'] = [0.]*9
    with pytest.raises(ValueError,match='transformation'):
        review_axes(audit,parent)


def test_review_schema_and_mutually_exclusive_stiffness_probes(
        tmp_path: Path, spec: ProjectSpec, design: DesignCandidate, layout: LayoutCandidate) -> None:
    parent = ResidentialSpec(project=spec.model_copy(update={'stories':12}),layout=layout,design=design)
    review = ModelFormReviewSpec(residential=parent,audit=ConnectionAuditSpec(
        model=tmp_path/'model.EDB',model_sha256='0'*64,frame_names=('a',),detailed_axes=True))
    request = ETABSRequest(spec=review,config=ETABSConfig(beam_theory='euler_comparison',wall_vertical_subdivisions=4))
    assert ETABSRequest.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValueError,match='separate counterfactuals'):
        ReferenceMesh(remove_beam_stiffness=True,beam_bending_released=True)
