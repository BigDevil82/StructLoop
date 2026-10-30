import math
from ..core.config import MaterialConfig
from .constants import CONCRETE_COMPRESSIVE_STRENGTH_MPA, CONCRETE_TENSILE_STRENGTH_MPA, ReinforcementDesignConstants, beam_shear_limit, effective_depth_m
from .results import BeamDesignDemand, BeamReinforcementResult, MaterialUsage

def _resolve_fc_ft(material: MaterialConfig) -> tuple[float, float]:
    grade = material.concrete_grade.strip().upper()
    return (CONCRETE_COMPRESSIVE_STRENGTH_MPA[grade], CONCRETE_TENSILE_STRENGTH_MPA[grade])

class BeamReinforcementDesigner:

    def __init__(self, constants: ReinforcementDesignConstants | None=None):
        self.constants = constants or ReinforcementDesignConstants()

    def design(self, demand: BeamDesignDemand, material: MaterialConfig) -> BeamReinforcementResult:
        fc_mpa, ft_mpa = _resolve_fc_ft(material)
        b_mm = demand.width_m * 1000.0
        h_mm = demand.depth_m * 1000.0
        length_m = demand.length_m
        h0_mm = effective_depth_m(demand.depth_m)*1000.
        cases = demand.moment_cases or ((demand.positive_moment_n_m,-demand.negative_moment_n_m,False),)
        top = [self._design_flexural_steel(max(0.,-mi,-mj),b_mm,h0_mm,fc_mpa,seismic=seismic) for mi,mj,seismic in cases]
        bottom = [self._design_flexural_steel(max(0.,mi,mj),b_mm,h0_mm,fc_mpa,seismic=seismic) for mi,mj,seismic in cases]
        top_area, bottom_area = max(x[0] for x in top),max(x[0] for x in bottom)
        top_over, bottom_over = any(x[1] for x in top),any(x[1] for x in bottom)
        top_msgs, bottom_msgs = [m for x in top for m in x[2]],[m for x in bottom for m in x[2]]
        shear_cases = demand.shear_cases or ((demand.shear_n,beam_shear_limit(demand.width_m,demand.depth_m,demand.length_m,False),False),)
        shear_results = [self._design_shear_steel(v,b_mm,h0_mm,fc_mpa,ft_mpa,seismic=seismic,
            section_limit=limit,coupling=demand.coupling) for v,limit,seismic in shear_cases]
        stirrup_ratio = max(x[0] for x in shear_results)
        stirrup_spacing = min(x[1] for x in shear_results)
        shear_insufficient = any(x[2] for x in shear_results)
        shear_msgs = sorted({m for x in shear_results for m in x[3]})
        concrete_kg = demand.width_m * demand.depth_m * demand.length_m * self.constants.concrete_density_kg_m3
        longitudinal_kg = (top_area + bottom_area) * 1e-06 * length_m * self.constants.steel_density_kg_m3
        # A closed rectangular hoop has two width and two depth segments. The
        # legs used for shear capacity are not a substitute for its full length.
        stirrup_perimeter_m = 2.0 * (max(b_mm - 2.0 * self.constants.cover_to_centroid_mm, 0.0)
            + max(h_mm - 2.0 * self.constants.cover_to_centroid_mm, 0.0)) / 1000.0
        stirrup_area_mm2 = self.constants.beam_stirrup_bar_area_mm2
        stirrup_count = length_m * 1000.0 / max(stirrup_spacing, 1.0)
        stirrup_kg = stirrup_area_mm2 * 1e-06 * stirrup_perimeter_m * stirrup_count * self.constants.steel_density_kg_m3
        return BeamReinforcementResult(beam_id=demand.beam_id, story=demand.story, top_steel_area_mm2=top_area, bottom_steel_area_mm2=bottom_area, stirrup_area_per_spacing_mm2_per_mm=stirrup_ratio, stirrup_spacing_mm=stirrup_spacing, material_usage=MaterialUsage(concrete_kg=concrete_kg, steel_kg=longitudinal_kg + stirrup_kg), is_over_reinforced=top_over or bottom_over, is_section_insufficient=shear_insufficient, messages=top_msgs + bottom_msgs + shear_msgs)

    def _design_flexural_steel(self, moment_n_m: float, width_mm: float, effective_depth_mm: float, fc_mpa: float, *, seismic: bool=True) -> tuple[float, bool, list[str]]:
        msgs: list[str] = []
        design_moment_n_mm = (self.constants.gamma_re_bending if seismic else 1.) * abs(moment_n_m) * 1000.0
        denom = self.constants.alpha_1 * fc_mpa * width_mm * effective_depth_mm ** 2
        alpha_s = design_moment_n_mm / max(denom, 1e-09)
        over_reinforced = False
        if 1.0 - 2.0 * alpha_s < 0.0:
            over_reinforced = True
            msgs.append('flexural_over_reinforced')
            gamma_s = 0.5
        else:
            gamma_s = 0.5 * (1.0 + math.sqrt(max(1.0 - 2.0 * alpha_s, 0.0)))
        xi = 1.0-math.sqrt(max(0.,1.0-2.0*alpha_s))
        if xi > self.constants.xi_b:
            over_reinforced = True
            msgs.append('compression_zone_limit_exceeded')
        steel_area = design_moment_n_mm / max(gamma_s * self.constants.fy_mpa * effective_depth_mm, 1e-09)
        min_area = self.constants.beam_longitudinal_min_ratio * width_mm * effective_depth_mm
        max_area = self.constants.alpha_1 * fc_mpa * width_mm * effective_depth_mm * self.constants.xi_b / self.constants.fy_mpa
        if steel_area < min_area:
            steel_area = min_area
            msgs.append('minimum_longitudinal_steel_governs')
        if steel_area > max_area:
            over_reinforced = True
            msgs.append('maximum_longitudinal_steel_exceeded')
        return (steel_area, over_reinforced, msgs)

    def _design_shear_steel(self, shear_n: float, width_mm: float, effective_depth_mm: float, fc_mpa: float, ft_mpa: float, *, seismic: bool=False, section_limit: float=.25, coupling: bool=False) -> tuple[float, float, bool, list[str]]:
        msgs: list[str] = []
        design_shear_n = (self.constants.gamma_re_shear if seismic else 1.) * abs(shear_n)
        section_insufficient = abs(shear_n) > section_limit*self.constants.beta_c*fc_mpa*width_mm*effective_depth_mm
        if section_insufficient:
            msgs.append('beam_shear_section_insufficient')
        concrete_factor = (.38 if coupling else .42) if seismic else .7
        stirrup_ratio = (design_shear_n - concrete_factor * ft_mpa * width_mm * effective_depth_mm) / max(self.constants.fyv_mpa * effective_depth_mm, 1e-09)
        stirrup_min_ratio = 0.24 * ft_mpa / self.constants.fyv_mpa * width_mm
        stirrup_ratio = max(stirrup_ratio, stirrup_min_ratio)
        if stirrup_ratio == stirrup_min_ratio:
            msgs.append('minimum_stirrup_requirement_governs')
        stirrup_area_mm2 = self.constants.beam_stirrup_bar_area_mm2 * self.constants.beam_stirrup_legs
        spacing_mm = stirrup_area_mm2 / max(stirrup_ratio, 1e-09)
        spacing_mm = min(spacing_mm, self.constants.beam_dense_spacing_limit_mm, self.constants.beam_regular_spacing_limit_mm)
        return (stirrup_ratio, spacing_mm, section_insufficient, msgs)
