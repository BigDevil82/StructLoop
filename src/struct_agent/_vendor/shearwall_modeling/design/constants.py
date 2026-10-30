from dataclasses import dataclass
import math
CONCRETE_COMPRESSIVE_STRENGTH_MPA: dict[str, float] = {'C30': 14.3, 'C35': 16.7, 'C40': 19.1, 'C45': 21.2, 'C50': 23.1}
CONCRETE_TENSILE_STRENGTH_MPA: dict[str, float] = {'C30': 1.43, 'C35': 1.57, 'C40': 1.71, 'C45': 1.8, 'C50': 1.89}

@dataclass(frozen=True)
class ReinforcementDesignConstants:
    seismic_grade: int = 2
    # HRB400 design strengths, not the nominal 400 MPa yield grade.
    fy_mpa: float = 360.0
    fyv_mpa: float = 360.0
    gamma_re_bending: float = 0.75
    gamma_re_wall: float = 0.85
    gamma_re_shear: float = 0.85
    xi_b: float = 0.518
    alpha_1: float = 1.0
    beta_c: float = 1.0
    cover_to_centroid_mm: float = 40.0
    beam_longitudinal_min_ratio: float = 0.002
    wall_vertical_min_ratio: float = 0.002
    wall_horizontal_min_ratio: float = 0.002
    wall_horizontal_spacing_mm: float = 200.0
    beam_stirrup_bar_area_mm2: float = 50.3
    beam_stirrup_legs: int = 2
    beam_dense_spacing_limit_mm: float = 100.0
    beam_regular_spacing_limit_mm: float = 200.0
    concrete_density_kg_m3: float = 2500.0
    steel_density_kg_m3: float = 7850.0
    boundary_constrained_min_ratio: float = 0.008
    boundary_constructive_min_ratio: float = 0.005
    boundary_stirrup_spacing_constrained_mm: float = 100.0
    boundary_stirrup_spacing_constructive_mm: float = 150.0
    boundary_stirrup_limb_spacing_mm: float = 100.0


def effective_depth_m(depth_m: float) -> float:
    """Existing 40 mm bar-centroid allowance, in metres; reject invalid sections."""
    value = depth_m - ReinforcementDesignConstants().cover_to_centroid_mm / 1000.
    if not math.isfinite(value) or value <= 0.:
        raise ValueError(f'Nonpositive effective depth: section={depth_m} m')
    return value


def beam_shear_limit(width_m: float, depth_m: float, span_m: float, seismic: bool) -> float:
    """V/(beta_c*fc*b*h0) limit, ordinary stirrups, GB50010 6.3.1/11.7.9.

    Short beams without identified wall supports retain the stricter 0.15
    screening coefficient; this does not certify their structural type.
    """
    h0 = effective_depth_m(depth_m)
    if min(width_m, span_m) <= 0 or not all(map(math.isfinite, (width_m, span_m))):
        raise ValueError('Positive finite beam width and physical span required')
    if seismic:
        coefficient = .20 if span_m / depth_m > 2.5 else .15
        return coefficient / ReinforcementDesignConstants().gamma_re_shear
    return .25 - .025 * min(2., max(0., h0 / width_m - 4.))
