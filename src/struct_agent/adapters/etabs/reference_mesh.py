"""Diagnostic-only MVLEM refinement. Physical stories, beams and masses stay fixed."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from struct_agent.schemas.base import Contract


class ReferenceMesh(Contract):
    vertical_subdivisions: int = Field(default=1,ge=1,le=4)
    fiber_refinement: int = Field(default=1,ge=1,le=4)
    rebuild_walls: bool = False


def refine(build: Any, config: Any, mesh: ReferenceMesh) -> dict[str,Any]:
    """Replace wall panels only, preserving floor nodes, beam tags and masses.

    New midheight nodes share coordinates between connected walls. There are
    no new diaphragms, floor beams or masses at these internal mesh levels.
    This does not produce member-design units or labels for the Agent/GA.
    """
    import openseespy.opensees as ops
    from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import wall_shear_stiffness
    if mesh==ReferenceMesh():
        return {'options':mesh.model_dump(),'wall_elements':len(build.wall_mesh_element_units),
            'beam_elements':len(build.beam_element_units),'node_count':len(ops.getNodeTags())}
    units = build.wall_mesh_element_units
    if len(units)>10000:
        raise ValueError('Diagnostic wall mesh exceeds the controlled input size')
    initial_tags = set(ops.getEleTags())
    beams = {unit.element_tag for unit in build.beam_element_units}
    if len(beams)+len(units)!=len(initial_tags):
        raise ValueError('Unexpected initial element coverage')
    profiles = config.resolve_story_profiles()
    next_node,next_element = max(ops.getNodeTags())+1,max(initial_tags)+1
    nodes: dict[tuple[float,...],int] = {}
    for unit in units:
        for tag in (*unit.bottom_nodes,*unit.top_nodes):
            x,y,z = ops.nodeCoord(tag)
            nodes[round(x,6),round(y,6),round(z,8)] = tag
    sections = []
    for unit in units:
        if len(unit.element_tags)!=1:
            raise ValueError('Only original, single-panel wall mesh units may be refined')
        count = len(ops.eleResponse(unit.element_tags[0],'Fiber_Strain'))
        if count<2:
            raise ValueError('Unresolved source section')
        sections.append(count*mesh.fiber_refinement)
        ops.remove('element',unit.element_tags[0])
    for story,profile in enumerate(profiles,1):
        ops.uniaxialMaterial('Elastic',1000000+story,float(profile.material.E))
    mapping = []
    for index,(unit,count) in enumerate(zip(units,sections)):
        profile = profiles[unit.story-1]
        h = unit.story_height/mesh.vertical_subdivisions
        shear_tag = 2000000+index
        ops.uniaxialMaterial('Elastic',shear_tag,wall_shear_stiffness(unit.member.length,unit.thickness,h,float(profile.material.G)))
        levels = []
        for step in range(mesh.vertical_subdivisions+1):
            pair = []
            for bottom,top in zip(unit.bottom_nodes,unit.top_nodes[::-1]):
                # The source top order is [right,left], bottom [left,right].
                x,y,z0 = ops.nodeCoord(bottom)
                tx,ty,tz = ops.nodeCoord(top)
                if max(abs(tx-x),abs(ty-y),abs(tz-z0-unit.story_height))>1e-8:
                    raise ValueError('Source panel corner order/geometry is inconsistent')
                z = z0+step*h
                key = (round(x,6),round(y,6),round(z,8))
                if key not in nodes:
                    nodes[key] = next_node
                    ops.node(next_node,x,y,z)
                    next_node += 1
                pair.append(nodes[key])
            if len(pair)!=2:
                raise ValueError('A rectangular source panel must have two corner nodes per level')
            levels.append(pair)
        tags = []
        for bottom,top in zip(levels,levels[1:]):
            tag = next_element
            next_element += 1
            ops.element('MVLEM_3D',tag,bottom[0],bottom[1],top[1],top[0],count,
                '-thick',*([unit.thickness]*count),'-width',*([unit.member.length/count]*count),'-rho',*([0.01]*count),
                '-matConcrete',*([1000000+unit.story]*count),'-matSteel',*([1000000+unit.story]*count),'-matShear',shear_tag,'-CoR',.4)
            tags.append(tag)
        mapping.append({'story':unit.story,'source_id':unit.wall_id,'original_tag':unit.element_tags[0],
            'new_element_tags':tags,'fibers_per_section':count})
    actual = set(ops.getEleTags())
    if not beams.issubset(actual) or len(actual)!=len(beams)+len(units)*mesh.vertical_subdivisions:
        raise ValueError('Refinement lost or duplicated a physical member')
    return {'options':mesh.model_dump(),'wall_elements':len(units)*mesh.vertical_subdivisions,
        'beam_elements':len(beams),'node_count':len(ops.getNodeTags()),'wall_mapping':mapping,
        'added_floor_masses':0,'added_floor_beams':0,'added_diaphragms':0,'member_design_extraction_supported':False}
