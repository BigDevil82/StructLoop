"""Diagnostic-only MVLEM refinement. Physical stories, beams and masses stay fixed."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from struct_agent.schemas.base import Contract


class ReferenceMesh(Contract):
    vertical_subdivisions: int = Field(default=1,ge=1,le=4)
    fiber_refinement: int = Field(default=1,ge=1,le=4)
    rebuild_walls: bool = False
    wall_formulation: Literal['mvlem', 'shell_dkgq', 'shell_asd'] = 'mvlem'
    center_of_rotation: Literal[0.4, 0.5] = 0.4
    plate_poisson: float | None = Field(default=None, ge=0., lt=.5)
    beam_bending_released: bool = False
    beam_release_scope: Literal['all','wall_to_wall'] = 'all'
    remove_beam_stiffness: bool = False

    @model_validator(mode='after')
    def applicable_options(self) -> ReferenceMesh:
        if self.remove_beam_stiffness and self.beam_bending_released:
            raise ValueError('Beam removal and bending release are separate counterfactuals')
        if not self.beam_bending_released and self.beam_release_scope != 'all':
            raise ValueError('A beam release scope requires beam_bending_released')
        if self.wall_formulation != 'mvlem' and (self.center_of_rotation != .4
                or self.plate_poisson is not None or self.fiber_refinement != 1):
            raise ValueError('MVLEM-specific options cannot be applied to a shell diagnostic')
        return self


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
    released_beams = []
    removed_beams, auxiliary_nodes = [], []
    if mesh.remove_beam_stiffness:
        removed_beams = sorted(beams)
        for tag in removed_beams:
            ops.remove('element',tag)
        beams = set()
        wall_nodes = {p for unit in units for p in (*unit.bottom_nodes,*unit.top_nodes)}
        # These nodes retain only the horizontal diaphragm constraint. Eliminate
        # their now-unused UZ/RX/RY; never restrain a wall node or UX/UY/RZ.
        floor_nodes = {p for tags in build.floor_story_nodes for p in tags}
        auxiliary_nodes = sorted(floor_nodes-wall_nodes)
        for tag in auxiliary_nodes:
            ops.fix(tag,0,0,1,1,1,0)
    if mesh.beam_bending_released:
        from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import _beam_section_props
        if not build.beam_element_units:
            raise ValueError('No source beams to release')
        transform = 9000000
        ops.geomTransf('Linear',transform,0.,0.,1.)
        wall_nodes = {p for unit in units for p in (*unit.bottom_nodes,*unit.top_nodes)}
        for beam in build.beam_element_units:
            ends = ops.eleNodes(beam.element_tag)
            supported = all(p in wall_nodes for p in ends)
            if not supported:
                if mesh.beam_release_scope == 'all':
                    raise ValueError('All-end releases leave unsupported vertical joints')
                continue
            profile = profiles[beam.story-1]
            area,j,iy,iz = _beam_section_props(beam.width,beam.depth)
            ops.remove('element',beam.element_tag)
            ops.element('elasticBeamColumn',beam.element_tag,*ends,area,float(profile.material.E),
                float(profile.material.G),j,iy,iz,transform,'-releasey',3,'-releasez',3)
            released_beams.append(beam.element_tag)
        if not released_beams:
            raise ValueError('No wall-supported beam pairs to release')
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
        if mesh.wall_formulation == 'mvlem':
            ops.uniaxialMaterial('Elastic',1000000+story,float(profile.material.E))
        else:
            e, g = float(profile.material.E), float(profile.material.G)
            # Same membrane thickness and 0.63^3 plate bending multiplier as
            # ETABS ShellThin. This is a diagnostic element substitution only.
            ops.section('ElasticMembranePlateSection',3000000+story,e,e/(2*g)-1,
                profile.section.wall_thickness,0.,.63**3)
    mapping = []
    for index,(unit,count) in enumerate(zip(units,sections)):
        profile = profiles[unit.story-1]
        h = unit.story_height/mesh.vertical_subdivisions
        shear_tag = 2000000+index
        if mesh.wall_formulation == 'mvlem':
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
            corners = (bottom[0],bottom[1],top[1],top[0])
            if mesh.wall_formulation != 'mvlem':
                element = 'ShellDKGQ' if mesh.wall_formulation == 'shell_dkgq' else 'ASDShellQ4'
                ops.element(element,tag,*corners,3000000+unit.story)
            else:
                poisson = [] if mesh.plate_poisson is None else ['-Poisson',mesh.plate_poisson]
                ops.element('MVLEM_3D',tag,*corners,count,
                    '-thick',*([unit.thickness]*count),'-width',*([unit.member.length/count]*count),'-rho',*([0.01]*count),
                    '-matConcrete',*([1000000+unit.story]*count),'-matSteel',*([1000000+unit.story]*count),
                    '-matShear',shear_tag,'-CoR',mesh.center_of_rotation,*poisson)
            tags.append(tag)
        mapping.append({'story':unit.story,'source_id':unit.wall_id,'original_tag':unit.element_tags[0],
            'new_element_tags':tags,'fibers_per_section':count if mesh.wall_formulation == 'mvlem' else None})
    actual = set(ops.getEleTags())
    if not beams.issubset(actual) or len(actual)!=len(beams)+len(units)*mesh.vertical_subdivisions:
        raise ValueError('Refinement lost or duplicated a physical member')
    return {'options':mesh.model_dump(),'wall_elements':len(units)*mesh.vertical_subdivisions,
        'beam_elements':len(beams),'node_count':len(ops.getNodeTags()),'wall_mapping':mapping,
        'released_beam_tags':released_beams,
        'removed_beam_tags':removed_beams,'auxiliary_null_dof_nodes':auxiliary_nodes,
        'added_floor_masses':0,'added_floor_beams':0,'added_diaphragms':0,'member_design_extraction_supported':False}
