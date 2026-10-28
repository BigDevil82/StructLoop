"""Read-only summary of native detailed results; kept equal to parametric/analysis.py."""
from __future__ import annotations

from ..analysis.results import AnalysisResult, DirectionCheckResult, OverallCheckResult
from ..builders.base import ModelBuildResult
from ..design.results import ReinforcementDesignSummary
from .types import ParametricAnalysisResult


def summarize_native(build: ModelBuildResult, analysis: AnalysisResult, overall: OverallCheckResult,
                     directions: dict[str, DirectionCheckResult], design: ReinforcementDesignSummary) -> ParametricAnalysisResult:
    """Reproduce upstream worst utilization, including last-item tie resolution."""
    def worst(items: list, value: str, limit: str) -> tuple[float, float]:
        best_value, best_limit, best_util = 0., 1., 0.
        for item in items:
            util = getattr(item, value) / max(getattr(item, limit), 1e-12)
            if util >= best_util:
                best_value, best_limit, best_util = getattr(item, value), getattr(item, limit), util
        return best_value, best_limit
    wall_axial, wall_axial_limit = worst(analysis.wall_uls_metrics, "axial_ratio", "axial_ratio_limit")
    wall_shear, wall_shear_limit = worst(analysis.wall_uls_metrics, "shear_pressure_ratio", "shear_pressure_ratio_limit")
    beam_shear, beam_shear_limit = worst(analysis.beam_uls_metrics, "shear_pressure_ratio", "shear_pressure_ratio_limit")
    periods = analysis.modal_summary.periods[:6]
    periods += [float("nan")] * (6-len(periods))
    metrics = [m for result in directions.values() for m in result.metrics]
    return ParametricAnalysisResult(converged=True, feasible=overall.is_passed, design_passed=design.is_passed,
        design_failed_beam_count=len(design.failed_beams), design_failed_wall_count=len(design.failed_walls),
        material_concrete_kg=design.total_concrete_kg, material_steel_kg=design.total_steel_kg,
        mass_total_t=(sum(build.floor_load_masses)+sum(build.floor_self_masses))/1000.,
        T1=periods[0], T2=periods[1], T3=periods[2], T4=periods[3], T5=periods[4], T6=periods[5],
        period_ratio=periods[0]/periods[2] if analysis.modal_summary.period_ratio is None else analysis.modal_summary.period_ratio,
        torsion_ratio=max(m.torsion_ratio for m in metrics),
        min_shear_weight_ratio=min(m.shear_weight_ratio for m in metrics),
        max_drift_ratio=max(r.max_interstory_drift_ratio for r in directions.values()),
        min_stiffness_ratio=min(m.stiffness_ratio_adjacent for m in metrics),
        max_wall_axial_ratio=wall_axial, max_wall_axial_limit=wall_axial_limit,
        max_wall_shear_ratio=wall_shear, max_wall_shear_limit=wall_shear_limit,
        max_beam_shear_ratio=beam_shear, max_beam_shear_limit=beam_shear_limit,
        period_ratio_available=analysis.modal_summary.period_ratio is not None,
        torsion_passed=overall.is_torsion_passed, shear_weight_passed=overall.is_shear_weight_passed,
        stiffness_passed=overall.is_stiffness_passed, drift_passed=overall.is_interstory_drift_passed,
        period_ratio_passed=overall.is_period_ratio_passed, wall_axial_passed=overall.is_wall_axial_passed,
        wall_shear_passed=overall.is_wall_shear_pressure_passed, beam_shear_passed=overall.is_beam_shear_pressure_passed,
        error="")
