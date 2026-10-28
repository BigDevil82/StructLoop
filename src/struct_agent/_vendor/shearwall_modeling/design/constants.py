from dataclasses import dataclass
CONCRETE_COMPRESSIVE_STRENGTH_MPA: dict[str, float] = {'C30': 14.3, 'C35': 16.7, 'C40': 19.1, 'C45': 21.2, 'C50': 23.1}
CONCRETE_TENSILE_STRENGTH_MPA: dict[str, float] = {'C30': 1.43, 'C35': 1.57, 'C40': 1.71, 'C45': 1.8, 'C50': 1.89}

@dataclass(frozen=True)
class ReinforcementDesignConstants:
    seismic_grade: int = 2
    fy_mpa: float = 400.0
    fyv_mpa: float = 400.0
    gamma_re_bending: float = 0.75
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
