from dataclasses import asdict, dataclass
from typing import Any
from struct_agent._vendor.shearwall_modeling.core.constants import MIN_SHEAR_WEIGHT_RATIO_BY_INTENSITY
from struct_agent._vendor.shearwall_modeling.parametric.types import ParametricAnalysisResult, ParametricModelParams
from ..core.contracts import EvaluationResult
from ..cost_estimation import material_cost

@dataclass(frozen=True)
class ShearWallObjectiveConfig:
    steel_price_per_kg: float = 5
    infeasible_penalty: float = 100000.0
    infeasible_violation_weight: float = 10000000.0
    infeasible_cost_weight: float = 0.01

@dataclass(frozen=True)
class ShearWallConstraintConfig:
    require_analysis_feasible: bool = True
    require_design_passed: bool = True

@dataclass(frozen=True)
class ShearWallLimitConfig:
    max_torsion_ratio: float = 1.5
    max_drift_ratio: float = 1.0 / 1000.0
    min_shear_weight_ratio: float = 0.016
    min_stiffness_ratio: float = 0.7
    max_period_ratio: float = 0.9
DEFAULT_DECISION_SPACE: dict[str, list[Any]] = {'tw_bot': [200, 250, 300, 350, 400], 'tw_mid': [160, 180, 200, 250, 300], 'tw_top': [160, 180, 200, 250], 'hb_main': [400, 500, 550, 600, 650, 700], 'bb_main': [200, 250, 300, 350], 'hb_sec': [300, 400, 450, 500], 'bb_sec': [200, 250, 300], 'conc_bot': ['C30', 'C35', 'C40', 'C45', 'C50']}
DEFAULT_FIXED_PARAMS: dict[str, Any] = {'N': 28, 'hs': 120, 'h_story': 2.9, 'intensity': 8.0, 'site_class': 'II', 'seismic_group': 1}

def summarize_analysis(*, analysis_result: ParametricAnalysisResult, params: ParametricModelParams,
                       geom_scale: float, objective_cfg: ShearWallObjectiveConfig,
                       constraint_cfg: ShearWallConstraintConfig, limit_cfg: ShearWallLimitConfig,
                       member_counts: dict[str, int]) -> EvaluationResult:
    cost = material_cost(concrete_kg=analysis_result.material_concrete_kg, steel_kg=analysis_result.material_steel_kg, row=asdict(params), steel_price_per_kg=objective_cfg.steel_price_per_kg)
    metric_values = {'torsion_ratio': float(analysis_result.torsion_ratio), 'max_drift_ratio': float(analysis_result.max_drift_ratio), 'period_ratio': float(analysis_result.period_ratio), 'min_shear_weight_ratio': float(analysis_result.min_shear_weight_ratio), 'min_stiffness_ratio': float(analysis_result.min_stiffness_ratio), 'wall_axial_ratio': float(analysis_result.max_wall_axial_ratio), 'wall_axial_limit': float(analysis_result.max_wall_axial_limit), 'wall_shear_ratio': float(analysis_result.max_wall_shear_ratio), 'wall_shear_limit': float(analysis_result.max_wall_shear_limit), 'beam_shear_ratio': float(analysis_result.max_beam_shear_ratio), 'beam_shear_limit': float(analysis_result.max_beam_shear_limit)}
    limits = {'torsion_ratio': float(limit_cfg.max_torsion_ratio), 'max_drift_ratio': float(limit_cfg.max_drift_ratio), 'period_ratio': float(limit_cfg.max_period_ratio), 'min_shear_weight_ratio': _shear_weight_limit(float(params.intensity), limit_cfg.min_shear_weight_ratio), 'min_stiffness_ratio': float(limit_cfg.min_stiffness_ratio), 'wall_axial_ratio': metric_values['wall_axial_limit'], 'wall_shear_ratio': metric_values['wall_shear_limit'], 'beam_shear_ratio': metric_values['beam_shear_limit']}
    normalized_violations: dict[str, float] = {}
    for key in ['torsion_ratio', 'max_drift_ratio', 'period_ratio', 'wall_axial_ratio', 'wall_shear_ratio', 'beam_shear_ratio']:
        actual = metric_values[key]
        limit = limits[key]
        normalized_violations[key] = max(0.0, (actual - limit) / limit)
    for key in ['min_shear_weight_ratio', 'min_stiffness_ratio']:
        actual = metric_values[key]
        limit = limits[key]
        normalized_violations[key] = max(0.0, (limit - actual) / limit)
    if not analysis_result.period_ratio_available and constraint_cfg.require_analysis_feasible:
        normalized_violations['period_ratio_unavailable'] = 1.0
    constraints: dict[str, float] = {'not_converged': 0.0 if analysis_result.converged else 1.0, 'analysis_unfeasible': 0.0 if analysis_result.feasible or not constraint_cfg.require_analysis_feasible else 1.0, 'design_failed': 0.0 if analysis_result.design_passed or not constraint_cfg.require_design_passed else 1.0, 'torsion_failed': _failed(analysis_result.torsion_passed, constraint_cfg.require_analysis_feasible), 'shear_weight_failed': _failed(analysis_result.shear_weight_passed, constraint_cfg.require_analysis_feasible), 'stiffness_failed': _failed(analysis_result.stiffness_passed, constraint_cfg.require_analysis_feasible), 'drift_failed': _failed(analysis_result.drift_passed, constraint_cfg.require_analysis_feasible), 'period_ratio_failed': _failed(analysis_result.period_ratio_passed, constraint_cfg.require_analysis_feasible), 'wall_axial_failed': _failed(analysis_result.wall_axial_passed, constraint_cfg.require_analysis_feasible), 'wall_shear_failed': _failed(analysis_result.wall_shear_passed, constraint_cfg.require_analysis_feasible), 'beam_shear_failed': _failed(analysis_result.beam_shear_passed, constraint_cfg.require_analysis_feasible)}
    feasible = all((v <= 0.0 for v in constraints.values()))
    if constraint_cfg.require_design_passed:
        for role in ('wall', 'beam'):
            count = member_counts[role]
            failures = getattr(analysis_result, f'design_failed_{role}_count')
            if failures < 0 or failures > count:
                raise ValueError(f'Invalid {role} design failure count: {failures}/{count}')
            normalized_violations[f'{role}_design_failure_fraction'] = failures / max(1, count)
    violation_sum = sum(normalized_violations.values())
    max_violation = max(normalized_violations.values()) if normalized_violations else 0.0
    total_violation = violation_sum / len(normalized_violations) if normalized_violations else 0.0
    constraint_violation = sum((v for k, v in constraints.items() if k != 'analysis_unfeasible'))
    # Binary duplicates must not outweigh actual improvement in the same check.
    # Keep a residual only for a failed flag lacking a positive numeric violation.
    covered = {'torsion_failed': 'torsion_ratio', 'shear_weight_failed': 'min_shear_weight_ratio',
        'stiffness_failed': 'min_stiffness_ratio', 'drift_failed': 'max_drift_ratio',
        'period_ratio_failed': 'period_ratio', 'wall_axial_failed': 'wall_axial_ratio',
        'wall_shear_failed': 'wall_shear_ratio', 'beam_shear_failed': 'beam_shear_ratio'}
    residual = constraints['not_converged']
    residual += sum(v for k, v in constraints.items() if k in covered and normalized_violations[covered[k]] == 0)
    if constraints['design_failed'] and not (analysis_result.design_failed_beam_count or analysis_result.design_failed_wall_count):
        residual += 1.0
    if not feasible and violation_sum + residual == 0:
        residual = 1.0
    violation_score = violation_sum + residual
    if feasible:
        objective = cost.material_cost
    else:
        objective = objective_cfg.infeasible_penalty + objective_cfg.infeasible_violation_weight * violation_score + objective_cfg.infeasible_cost_weight * cost.material_cost
    objectives = {'material_cost': cost.material_cost, 'concrete_cost': cost.concrete_cost, 'steel_cost': cost.steel_cost, 'total_violation': total_violation, 'violation_sum': violation_sum, 'max_violation': max_violation, 'constraint_violation': constraint_violation, 'violation_score': violation_score, 'constraints': constraints}
    return EvaluationResult(objective=objective, objectives=objectives, feasible=feasible, constraints=constraints, metrics={'geom_scale': geom_scale, **asdict(params), **asdict(analysis_result), 'normalized_violations': normalized_violations, **objectives, 'objective': objective})

def _failed(passed: bool, required: bool) -> float:
    return 0.0 if passed or not required else 1.0

def _shear_weight_limit(intensity: float, fallback: float) -> float:
    key = round(float(intensity), 2)
    return float(MIN_SHEAR_WEIGHT_RATIO_BY_INTENSITY.get(key, fallback))
