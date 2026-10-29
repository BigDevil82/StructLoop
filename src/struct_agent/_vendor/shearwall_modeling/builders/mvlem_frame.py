import math
from logging import Logger
import openseespy.opensees as ops
from ..core.config import ModelConfig
from ..core.domain import BeamRole, FEMInput
from ..geometry.mass_estimation import estimate_floor_area, estimate_structural_self_mass_per_floor
from .base import BeamElementUnit, ModelBuildResult, StructuralModelBuilder, WallBaseCheckUnit, WallStoryElementUnit

def _beam_section_props(width: float, depth: float) -> tuple[float, float, float, float]:
    area = width * depth
    iy = width * depth ** 3 / 12.0
    iz = depth * width ** 3 / 12.0
    # Saint-Venant torsion, not the polar second moment Iy+Iz. Exact rectangle
    # series truncated after 128 odd terms (relative tail < 1e-9 for a square).
    a, b = max(width,depth), min(width,depth)
    series = sum(math.tanh(n*math.pi*a/(2*b))/n**5 for n in range(1,256,2))
    j = a*b**3/3*(1-192*b/(math.pi**5*a)*series)
    return (area, j, iy, iz)


def wall_shear_stiffness(length: float, thickness: float, height: float, shear_modulus: float) -> float:
    """Rectangular elastic panel shear spring K=5GA/(6h), N/m (not Pa).

    MVLEM_3D passes shear displacement to its uniaxial material and uses the
    returned force directly. The axial/flexural materials instead use stress.
    """
    if any(not math.isfinite(v) or v<=0. for v in (length,thickness,height,shear_modulus)):
        raise ValueError('Positive wall dimensions and shear modulus required')
    return (5/6)*shear_modulus*length*thickness/height

class MVLEMFrameBuilder(StructuralModelBuilder):
    """Equivalent wall-frame model with MVLEM_3D wall elements.

    Notes:
    - One MVLEM_3D element is created for each input wall segment at each story.
    - Straight physical piers assemble these panels for force extraction/design;
      FE intersection nodes and element connectivity remain explicit.
    - Beams are modeled with elasticBeamColumn.
    - Floors are tied by rigid diaphragm with one master node per story.
    """
    name = 'mvlem_frame'

    def __init__(self, logger: Logger | None=None, fiber_width: float=0.2, rebar_ratio: float=0.01):
        self.logger = logger
        self.fiber_width = float(fiber_width)
        self.rebar_ratio = max(float(rebar_ratio), 0.0)

    def build(self, input_data: FEMInput, config: ModelConfig) -> ModelBuildResult:
        self.logger.info('Building MVLEM frame model...')
        ops.wipe()
        ops.model('basic', '-ndm', 3, '-ndf', 6)
        if not input_data.walls:
            raise ValueError('mvlem_frame builder requires at least one shear wall.')
        profiles = config.resolve_story_profiles()
        floor_area = estimate_floor_area(input_data)
        floor_masses: list[float] = []
        floor_load_masses: list[float] = []
        floor_self_masses: list[float] = []
        for profile in profiles:
            load_mass = profile.mass_source.load_to_mass_per_area() * floor_area
            sec_w, sec_d = profile.section.get_beam_section(BeamRole.SECONDARY)
            self_mass_info = estimate_structural_self_mass_per_floor(input_data=input_data, story_height=profile.story_height, wall_thickness=profile.section.wall_thickness, primary_beam_width=profile.section.beam_width, primary_beam_depth=profile.section.beam_depth, secondary_beam_width=sec_w, secondary_beam_depth=sec_d, slab_thickness=profile.section.slab_thickness, density_kg_m3=profile.material.density_kg_m3, floor_area=floor_area)
            self_mass = self_mass_info['total_self_mass'] if profile.mass_source.include_structural_self_weight else 0.0
            floor_load_masses.append(load_mass)
            floor_self_masses.append(self_mass)
            floor_masses.append(load_mass + self_mass)
        master_nodes: list[int] = []
        floor_story_nodes: list[list[int]] = []
        wall_base_units: list[WallBaseCheckUnit] = []
        beam_element_units: list[BeamElementUnit] = []
        wall_story_element_units: list[WallStoryElementUnit] = []
        node_tag = 1
        elem_tag = 1
        beam_transf = 999
        ops.geomTransf('Linear', beam_transf, 0.0, 0.0, 1.0)
        plan_floor_nodes: dict[tuple[float, float, int], int] = {}
        fixed_base_nodes: set[int] = set()
        mat_tag = 1
        mats_by_story: dict[int, tuple[int, int]] = {}
        for story, profile in enumerate(profiles, start=1):
            e = float(profile.material.E)
            g = float(profile.material.G)
            concrete_tag = mat_tag
            ops.uniaxialMaterial('Elastic', concrete_tag, e)
            mat_tag += 1
            steel_tag = mat_tag
            ops.uniaxialMaterial('Elastic', steel_tag, e)
            mat_tag += 1
            mats_by_story[story] = (concrete_tag, steel_tag)

        def floor_node(x: float, y: float, story: int, z: float) -> int:
            nonlocal node_tag
            key = (round(x, 6), round(y, 6), story)
            if key in plan_floor_nodes:
                return plan_floor_nodes[key]
            tag = node_tag
            node_tag += 1
            ops.node(tag, x, y, z)
            plan_floor_nodes[key] = tag
            return tag
        for story, profile in enumerate(profiles, start=1):
            z_bot = profile.z_bottom
            z_top = profile.z_top
            story_nodes_xy: set[tuple[float, float]] = set()
            story_floor_node_tags: set[int] = set()
            for wall in input_data.walls:
                x1, y1 = wall.start
                x2, y2 = wall.end
                wall_len = max(wall.length, 1e-06)
                t = profile.section.wall_thickness
                ni = floor_node(x1, y1, story - 1, z_bot)
                nj = floor_node(x2, y2, story - 1, z_bot)
                nk = floor_node(x2, y2, story, z_top)
                nl = floor_node(x1, y1, story, z_top)
                if story == 1:
                    if ni not in fixed_base_nodes:
                        ops.fix(ni, 1, 1, 1, 1, 1, 1)
                        fixed_base_nodes.add(ni)
                    if nj not in fixed_base_nodes:
                        ops.fix(nj, 1, 1, 1, 1, 1, 1)
                        fixed_base_nodes.add(nj)
                    wall_base_units.append(WallBaseCheckUnit(wall_id=wall.m_id, base_nodes=[ni, nj], length=wall.length, thickness=t))
                # One centroid fiber has zero in-plane bending inertia. Keep a
                # resolved section even for a short analysis mesh panel.
                m = max(8, int(math.ceil(wall_len / self.fiber_width)))
                width = [wall_len / m] * m
                thick = [t] * m
                rho = [self.rebar_ratio] * m
                concrete_tag, steel_tag = mats_by_story[story]
                shear_tag = mat_tag
                mat_tag += 1
                ops.uniaxialMaterial('Elastic',shear_tag,wall_shear_stiffness(
                    wall_len,t,profile.story_height,float(profile.material.G)))
                concrete_tags = [concrete_tag] * m
                steel_tags = [steel_tag] * m
                ops.element('MVLEM_3D', elem_tag, ni, nj, nk, nl, m, '-thick', *thick, '-width', *width, '-rho', *rho, '-matConcrete', *concrete_tags, '-matSteel', *steel_tags, '-matShear', shear_tag, '-CoR', 0.4)
                wall_story_element_units.append(WallStoryElementUnit(wall_id=wall.m_id, story=story, element_tags=[elem_tag], bottom_nodes=[ni, nj], top_nodes=[nk, nl], node_coords={ni: ops.nodeCoord(ni), nj: ops.nodeCoord(nj), nk: ops.nodeCoord(nk), nl: ops.nodeCoord(nl)}, member=wall, thickness=t, story_height=profile.story_height))
                elem_tag += 1
                story_nodes_xy.add((x1, y1))
                story_nodes_xy.add((x2, y2))
                story_floor_node_tags.update([nk, nl])
            e = float(profile.material.E)
            g = float(profile.material.G)
            for beam in input_data.beams:
                x1, y1 = beam.start
                x2, y2 = beam.end
                ni = floor_node(x1, y1, story, z_top)
                nj = floor_node(x2, y2, story, z_top)
                story_floor_node_tags.update([ni, nj])
                story_nodes_xy.add((x1, y1))
                story_nodes_xy.add((x2, y2))
                if ni == nj:
                    continue
                bw, bd = profile.section.get_beam_section(beam.role)
                area, j, iy, iz = _beam_section_props(bw, bd)
                ops.element('elasticBeamColumn', elem_tag, ni, nj, area, e, g, j, iy, iz, beam_transf)
                beam_element_units.append(BeamElementUnit(beam_id=beam.m_id, story=story, element_tag=elem_tag, member=beam, role=beam.role, width=bw, depth=bd, length=beam.length))
                elem_tag += 1
            if not story_nodes_xy:
                raise ValueError('No floor nodes generated for MVLEM story.')
            cx = sum((p[0] for p in story_nodes_xy)) / len(story_nodes_xy)
            cy = sum((p[1] for p in story_nodes_xy)) / len(story_nodes_xy)
            master = node_tag
            node_tag += 1
            ops.node(master, cx, cy, z_top)
            unique_slaves = sorted(story_floor_node_tags)
            story_mass = floor_masses[story - 1]
            nodal_mass = story_mass / max(len(unique_slaves), 1)
            rot_mass = sum((nodal_mass * ((ops.nodeCoord(n, 1) - cx) ** 2 + (ops.nodeCoord(n, 2) - cy) ** 2) for n in unique_slaves))
            ops.mass(master, story_mass, story_mass, 0.0, 0.0, 0.0, rot_mass)
            ops.fix(master, 0, 0, 1, 1, 1, 0)
            if unique_slaves:
                ops.rigidDiaphragm(3, master, *unique_slaves)
            master_nodes.append(master)
            floor_story_nodes.append(unique_slaves)
        self.logger.info('MVLEM model built: stories=%d, walls=%d, beams=%d', config.num_stories, len(input_data.walls), len(input_data.beams))
        from ..geometry.wall_piers import assemble_wall_units
        return ModelBuildResult(master_nodes=master_nodes, floor_area=floor_area, floor_load_masses=floor_load_masses, floor_self_masses=floor_self_masses, wall_base_units=wall_base_units, floor_story_nodes=floor_story_nodes, beam_element_units=beam_element_units, wall_story_element_units=assemble_wall_units(wall_story_element_units), wall_mesh_element_units=wall_story_element_units)
