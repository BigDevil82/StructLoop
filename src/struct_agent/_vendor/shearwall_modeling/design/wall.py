from ..core.config import MaterialConfig
from .constants import CONCRETE_COMPRESSIVE_STRENGTH_MPA, CONCRETE_TENSILE_STRENGTH_MPA, ReinforcementDesignConstants
from .results import MaterialUsage, WallDesignDemand, WallReinforcementResult

def _resolve_fc_ft(material: MaterialConfig) -> tuple[float, float]:
    grade = material.concrete_grade.strip().upper()
    return (CONCRETE_COMPRESSIVE_STRENGTH_MPA[grade], CONCRETE_TENSILE_STRENGTH_MPA[grade])

class WallReinforcementDesigner:

    def __init__(self, constants: ReinforcementDesignConstants | None=None):
        self.constants = constants or ReinforcementDesignConstants()

    def design(self, demand: WallDesignDemand, material: MaterialConfig) -> WallReinforcementResult:
        fc_mpa, ft_mpa = _resolve_fc_ft(material)
        bw_mm = demand.thickness_m * 1000.0
        lw_mm = demand.length_m * 1000.0
        hc_mm = max(2.0 * bw_mm, 0.15 * lw_mm)
        bc_mm = bw_mm
        h0_mm = lw_mm - self.constants.cover_to_centroid_mm
        vertical_area = self.constants.wall_vertical_min_ratio * bw_mm * 1000.0
        horizontal_area = self._design_horizontal_distributed_steel(demand, bw_mm, h0_mm, ft_mpa)
        boundary_type = self._resolve_boundary_type(demand.axial_ratio, demand.is_bottom_reinforced_zone)
        boundary_longitudinal, boundary_stirrup_area, boundary_spacing, sec_insufficient, messages = self._design_boundary_steel(demand, bc_mm, hc_mm, h0_mm, fc_mpa, boundary_type)
        concrete_kg = demand.thickness_m * demand.length_m * demand.story_height_m * self.constants.concrete_density_kg_m3
        vertical_kg = vertical_area * demand.length_m * demand.story_height_m * self.constants.steel_density_kg_m3 * 1e-06
        horizontal_kg = horizontal_area * demand.length_m * demand.story_height_m * self.constants.steel_density_kg_m3 * 1e-06
        boundary_kg = (boundary_longitudinal * hc_mm / 1000.0 + boundary_stirrup_area * (hc_mm / max(boundary_spacing, 1.0)) * bc_mm / 1000.0) * 2.0 * self.constants.steel_density_kg_m3 * 1e-06
        return WallReinforcementResult(wall_id=demand.wall_id, story=demand.story, vertical_distributed_steel_mm2_per_m=vertical_area, horizontal_distributed_steel_mm2_per_m=horizontal_area, boundary_longitudinal_steel_mm2=boundary_longitudinal, boundary_stirrup_area_mm2=boundary_stirrup_area, boundary_stirrup_spacing_mm=boundary_spacing, boundary_type=boundary_type, material_usage=MaterialUsage(concrete_kg=concrete_kg, steel_kg=vertical_kg + horizontal_kg + boundary_kg), is_over_reinforced=False, is_section_insufficient=sec_insufficient, messages=messages)

    def _design_horizontal_distributed_steel(self, demand: WallDesignDemand, wall_thickness_mm: float, effective_length_mm: float, ft_mpa: float) -> float:
        spacing_mm = self.constants.wall_horizontal_spacing_mm
        design_shear_n = self.constants.gamma_re_shear * abs(demand.shear_n)
        steel_area = (design_shear_n - 0.4 * ft_mpa * wall_thickness_mm * effective_length_mm) * spacing_mm / max(0.8 * self.constants.fyv_mpa * effective_length_mm, 1e-09)
        steel_area_per_m = max(steel_area / max(spacing_mm, 1e-09) * 1000.0, self.constants.wall_horizontal_min_ratio * wall_thickness_mm * 1000.0)
        return steel_area_per_m

    def _resolve_boundary_type(self, axial_ratio: float, is_bottom_reinforced_zone: bool) -> str:
        threshold = 0.3 if is_bottom_reinforced_zone else 0.4
        return 'constrained' if axial_ratio > threshold else 'constructive'

    def _design_boundary_steel(self, demand: WallDesignDemand, boundary_width_mm: float, boundary_height_mm: float, effective_length_mm: float, fc_mpa: float, boundary_type: str) -> tuple[float, float, float, bool, list[str]]:
        messages: list[str] = []
        design_axial_n = self.constants.gamma_re_bending * abs(demand.axial_force_n)
        design_moment_n_mm = self.constants.gamma_re_bending * abs(demand.moment_n_m) * 1000.0
        b = boundary_width_mm
        h = boundary_height_mm
        h0 = effective_length_mm
        a_s = self.constants.cover_to_centroid_mm
        fy = self.constants.fy_mpa
        alpha1 = self.constants.alpha_1
        xi_b = self.constants.xi_b
        beta1 = getattr(self.constants, 'beta1', 0.8)
        max_reinforcement_ratio = getattr(self.constants, 'boundary_max_ratio', 0.04)
        section_insufficient = False
        x_mm = design_axial_n / max(alpha1 * fc_mpa * b, 1e-09)
        xi = x_mm / max(h0, 1e-09)
        if xi > xi_b:
            e0 = design_moment_n_mm / max(design_axial_n, 1e-09)
            ea = max(20.0, h / 30.0)
            ei = e0 + ea
            e = ei + h / 2.0 - a_s
            numerator_xi = design_axial_n - xi_b * alpha1 * fc_mpa * b * h0
            denominator_xi = (design_axial_n * e - 0.43 * alpha1 * fc_mpa * b * h0 * h0) / ((beta1 - xi_b) * (h0 - a_s))
            xi = numerator_xi / denominator_xi + xi_b
            xi = max(xi_b, min(xi, h / h0))
            numerator = design_axial_n * e - alpha1 * fc_mpa * b * h0 * h0 * xi * (1 - 0.5 * xi)
            denominator = fy * (h0 - a_s)
            longitudinal_area = max(numerator / max(denominator, 1e-09), 0.0)
        else:
            numerator = design_moment_n_mm - alpha1 * fc_mpa * b * x_mm * (h0 - 0.5 * x_mm)
            longitudinal_area = max(numerator / max(fy * (h0 - a_s), 1e-09), 0.0)
        min_ratio = self.constants.boundary_constrained_min_ratio if boundary_type == 'constrained' else self.constants.boundary_constructive_min_ratio
        min_area = min_ratio * b * h
        if longitudinal_area < min_area - 1e-06:
            longitudinal_area = min_area
            messages.append('minimum_boundary_longitudinal_steel_governs')
        calculated_ratio = longitudinal_area / (b * h)
        if calculated_ratio > max_reinforcement_ratio:
            section_insufficient = True
            messages.append('boundary_steel_ratio_exceeds_max')
        if xi > 0.9:
            section_insufficient = True
            messages.append('xi_too_large')
        volume_ratio = 0.006 if boundary_type == 'constrained' else 0.004
        spacing_mm = self.constants.boundary_stirrup_spacing_constrained_mm if boundary_type == 'constrained' else self.constants.boundary_stirrup_spacing_constructive_mm
        stirrup_area = volume_ratio * b * h * spacing_mm / max(self.constants.boundary_stirrup_limb_spacing_mm, 1e-09)
        return (longitudinal_area, stirrup_area, spacing_mm, section_insufficient, messages)
