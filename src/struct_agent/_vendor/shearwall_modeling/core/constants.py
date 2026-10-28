from dataclasses import dataclass
CONCRETE_ELASTIC_MODULUS_MPA: dict[str, float] = {'C30': 30000.0, 'C35': 31500.0, 'C40': 32500.0, 'C45': 33500.0, 'C50': 34500.0}
CONCRETE_COMPRESSIVE_STRENGTH_PA: dict[str, float] = {'C30': 14300000.0, 'C35': 16700000.0, 'C40': 19100000.0, 'C45': 21200000.0, 'C50': 23100000.0}
SEISMIC_ALPHA_MAX_BY_INTENSITY: dict[float, float] = {6.0: 0.04, 7.0: 0.08, 7.5: 0.12, 8.0: 0.16, 8.5: 0.24, 9.0: 0.32}
GB50011_TG_BY_SITE_CLASS: dict[str, dict[int, float]] = {'I0': {1: 0.2, 2: 0.25, 3: 0.3}, 'I': {1: 0.25, 2: 0.3, 3: 0.35}, 'II': {1: 0.35, 2: 0.4, 3: 0.45}, 'III': {1: 0.45, 2: 0.55, 3: 0.65}, 'IV': {1: 0.65, 2: 0.75, 3: 0.9}}
MIN_SHEAR_WEIGHT_RATIO_BY_INTENSITY: dict[float, float] = {6.0: 0.008, 7.0: 0.016, 7.5: 0.024, 8.0: 0.032, 8.5: 0.048, 9.0: 0.064}
MIN_WALL_LEN_CHECK_THRESHOLD_M = 0.5

@dataclass(frozen=True)
class RectSlabFilterBounds:
    min_span: float = 2.0
    max_span: float = 8.0
    min_depth: float = 3.0
    max_depth: float = 12.0
    max_aspect_ratio: float = 3.5
    median_span_factor: float = 0.55
    median_depth_factor: float = 0.55
    median_area_factor: float = 0.35
    min_span_floor: float = 0.8
    min_depth_floor: float = 1.0
    min_area_floor: float = 2.0

def concrete_fc_pa(concrete_grade: str) -> float:
    grade = concrete_grade.strip().upper()
    if grade not in CONCRETE_COMPRESSIVE_STRENGTH_PA:
        raise ValueError(f'Unsupported concrete grade for axial check: {concrete_grade}')
    return CONCRETE_COMPRESSIVE_STRENGTH_PA[grade]
