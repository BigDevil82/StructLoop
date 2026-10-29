"""Real builder: assembly must retain all intersection nodes, panels and mass."""
from dataclasses import replace
import logging

import openseespy.opensees as ops
import pytest

from struct_agent.adapters.fea import native_params
from struct_agent.schemas import DesignCandidate, ProjectSpec
from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import MVLEMFrameBuilder
from struct_agent._vendor.shearwall_modeling.core.domain import FEMInput, PlanMember, Point2D
from struct_agent._vendor.shearwall_modeling.parametric.analysis import build_model_config_from_params

pytestmark = pytest.mark.real


def test_t_wall_assembly_retains_all_mesh_nodes_elements_and_mass(spec: ProjectSpec, design: DesignCandidate) -> None:
    params = replace(native_params(design, spec), N=3)
    config = build_model_config_from_params(params, num_modes=3)
    topology = FEMInput(walls=[
        PlanMember(0,'shearwall',Point2D(0.,0.),Point2D(.1,0.)),
        PlanMember(1,'shearwall',Point2D(.1,0.),Point2D(2.4,0.)),
        PlanMember(2,'shearwall',Point2D(.1,0.),Point2D(.1,.7))],
        beams=[], slabs=[[Point2D(0.,0.),Point2D(6.,0.),Point2D(6.,6.),Point2D(0.,6.)]])
    try:
        build = MVLEMFrameBuilder(logging.getLogger('test')).build(topology, config)
        assert len(build.wall_mesh_element_units) == len(ops.getEleTags()) == 9
        # Short panels must retain a bending-resolved section, not one axial
        # centroid fiber with zero in-plane bending inertia.
        assert len(ops.eleResponse(1,'Fiber_Strain')) >= 8
        assert len(build.wall_story_element_units) == 6
        assert sorted(tag for u in build.wall_story_element_units for tag in u.element_tags) == sorted(ops.getEleTags())
        for story in range(1,4):
            pier = next(u for u in build.wall_story_element_units if u.story == story and u.wall_id == 0)
            assert pier.member.length == 2.4 and pier.source_wall_ids == (0,1)
            shared = [n for n in pier.top_nodes if ops.nodeCoord(n,1) == .1]
            assert len(shared) == 1
            flange = next(u for u in build.wall_story_element_units if u.story == story and u.wall_id == 2)
            assert shared[0] in flange.top_nodes
        for i, profile in enumerate(config.resolve_story_profiles()):
            # Upstream dead_kpa already includes slab self-weight; the separate
            # structural contribution is walls/beams, not the slab a second time.
            volume = 3.1*profile.section.wall_thickness*2.9
            assert build.floor_self_masses[i] == pytest.approx(volume*profile.material.density_kg_m3)
            assert ops.nodeMass(build.master_nodes[i],1) == pytest.approx(build.floor_self_masses[i]+build.floor_load_masses[i])
    finally:
        ops.wipe()
