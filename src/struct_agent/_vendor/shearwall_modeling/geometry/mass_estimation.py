from ..core.domain import BeamRole, FEMInput
from .primitives import polygon_area

def estimate_floor_area(input_data: FEMInput) -> float:
    slab_area = sum((area for area in (polygon_area(slab) for slab in input_data.slabs) if area > 0.0))
    if slab_area > 1e-09:
        return max(slab_area, 16.0)
    points = [point for member in input_data.all_members() for point in (member.start, member.end)]
    if len(points) < 2:
        return 36.0
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    return max((max(xs) - min(xs)) * (max(ys) - min(ys)), 16.0)

def estimate_structural_self_mass_per_floor(input_data: FEMInput, story_height: float, wall_thickness: float, primary_beam_width: float, primary_beam_depth: float, secondary_beam_width: float, secondary_beam_depth: float, slab_thickness: float, density_kg_m3: float, floor_area: float | None=None) -> dict[str, float]:
    area = estimate_floor_area(input_data) if floor_area is None else floor_area
    wall_length_total = sum((member.length for member in input_data.walls))
    primary_beam_length_total = input_data.beam_length_by_role(BeamRole.PRIMARY)
    secondary_beam_length_total = input_data.beam_length_by_role(BeamRole.SECONDARY)
    wall_vol = wall_length_total * wall_thickness * story_height
    primary_beam_vol = primary_beam_length_total * primary_beam_width * primary_beam_depth
    secondary_beam_vol = secondary_beam_length_total * secondary_beam_width * secondary_beam_depth
    beam_vol = primary_beam_vol + secondary_beam_vol
    slab_vol = area * slab_thickness
    wall_mass = wall_vol * density_kg_m3
    primary_beam_mass = primary_beam_vol * density_kg_m3
    secondary_beam_mass = secondary_beam_vol * density_kg_m3
    beam_mass = beam_vol * density_kg_m3
    slab_mass = slab_vol * density_kg_m3
    total_self_mass = wall_mass + beam_mass
    return {'floor_area': area, 'wall_mass': wall_mass, 'primary_beam_mass': primary_beam_mass, 'secondary_beam_mass': secondary_beam_mass, 'beam_mass': beam_mass, 'slab_mass': slab_mass, 'total_self_mass': total_self_mass}
