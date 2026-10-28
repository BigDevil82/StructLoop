import logging
from typing import Any
import openseespy.opensees as ops
from ..analysis.evaluation import AnalysisResultBuilder, SeismicEvaluationPipeline
from ..builders.mvlem_frame import MVLEMFrameBuilder
from ..builders.base import AnalysisModelContext, StructuralModelBuilder
from ..core.config import MaterialConfig, ModelConfig, SectionConfig, SeismicConfig, StandardStoryGroupConfig
from ..core.domain import FEMInput
from ..design.pipeline import ReinforcementDesignPipeline
from .space import normalize_params, split_stories
from .types import BuilderName, DatasetGenerationConfig, ParametricAnalysisResult, ParametricModelParams

def build_model_config_from_params(params: ParametricModelParams | dict[str, Any], *, story_height: float | None=None, num_modes: int=6) -> ModelConfig:
    p = normalize_params(params)
    h_story = 2.9 if story_height is None else story_height
    slab_thickness = 0.12
    n_bottom, n_middle, n_top = split_stories(p.N)

    def make_section(tw_mm: int) -> SectionConfig:
        return SectionConfig(wall_thickness=tw_mm / 1000.0, beam_width=p.bb_main / 1000.0, beam_depth=p.hb_main / 1000.0, secondary_beam_width=p.bb_sec / 1000.0, secondary_beam_depth=p.hb_sec / 1000.0, slab_thickness=slab_thickness)
    groups = [StandardStoryGroupConfig(count=n_bottom, story_height=h_story, section=make_section(p.tw_bot), material=MaterialConfig(concrete_grade=p.conc_bot)), StandardStoryGroupConfig(count=n_middle, story_height=h_story, section=make_section(p.tw_mid), material=MaterialConfig(concrete_grade=p.conc_bot)), StandardStoryGroupConfig(count=n_top, story_height=h_story, section=make_section(p.tw_top), material=MaterialConfig(concrete_grade=p.conc_bot))]
    return ModelConfig(standard_story_groups=groups, seismic=SeismicConfig(intensity=p.intensity, site_class=p.site_class, seismic_group=p.seismic_group), num_modes=num_modes)

def analyze_parametric_model(input_data: FEMInput, params: ParametricModelParams, cfg: DatasetGenerationConfig, logger: logging.Logger | None=None) -> ParametricAnalysisResult:
    run_logger = logger or logging.getLogger('shearwall_parametric')
    run_logger.setLevel(logging.WARN)
    builder = _create_builder(cfg.builder_name, run_logger)
    try:
        model_cfg = build_model_config_from_params(params, num_modes=cfg.num_modes)
        build_result = builder.build(input_data, model_cfg)
        context = AnalysisModelContext(build_result=build_result, config=model_cfg, logger=run_logger)
        analysis_result = AnalysisResultBuilder(context).build()
        overall_result, dir_results = SeismicEvaluationPipeline(model_cfg).evaluate(analysis_result)
        periods = analysis_result.modal_summary.periods[:6]
        while len(periods) < 6:
            periods.append(float('nan'))
        all_metrics = [m for result in dir_results.values() for m in result.metrics]
        max_wall_axial_ratio = 0.0
        max_wall_axial_limit = 1.0
        max_wall_axial_util = 0.0
        max_wall_shear_ratio = 0.0
        max_wall_shear_limit = 1.0
        max_wall_shear_util = 0.0
        max_beam_shear_ratio = 0.0
        max_beam_shear_limit = 1.0
        max_beam_shear_util = 0.0
        for metric in analysis_result.wall_uls_metrics:
            axial_util = metric.axial_ratio / max(metric.axial_ratio_limit, 1e-12)
            if axial_util >= max_wall_axial_util:
                max_wall_axial_util = axial_util
                max_wall_axial_ratio = metric.axial_ratio
                max_wall_axial_limit = metric.axial_ratio_limit
            wall_shear_util = metric.shear_pressure_ratio / max(metric.shear_pressure_ratio_limit, 1e-12)
            if wall_shear_util >= max_wall_shear_util:
                max_wall_shear_util = wall_shear_util
                max_wall_shear_ratio = metric.shear_pressure_ratio
                max_wall_shear_limit = metric.shear_pressure_ratio_limit
        for metric in analysis_result.beam_uls_metrics:
            beam_shear_util = metric.shear_pressure_ratio / max(metric.shear_pressure_ratio_limit, 1e-12)
            if beam_shear_util >= max_beam_shear_util:
                max_beam_shear_util = beam_shear_util
                max_beam_shear_ratio = metric.shear_pressure_ratio
                max_beam_shear_limit = metric.shear_pressure_ratio_limit
        mass_total_kg = sum(build_result.floor_load_masses) + sum(build_result.floor_self_masses)
        design_summary = ReinforcementDesignPipeline(build_result=build_result, analysis_result=analysis_result, config=model_cfg, logger=run_logger).run()
        period_ratio_available = analysis_result.modal_summary.period_ratio is not None
        return ParametricAnalysisResult(converged=True, feasible=overall_result.is_passed, design_passed=design_summary.is_passed, design_failed_beam_count=len(design_summary.failed_beams), design_failed_wall_count=len(design_summary.failed_walls), material_concrete_kg=design_summary.total_concrete_kg, material_steel_kg=design_summary.total_steel_kg, mass_total_t=mass_total_kg / 1000.0, T1=periods[0], T2=periods[1], T3=periods[2], T4=periods[3], T5=periods[4], T6=periods[5], period_ratio=analysis_result.modal_summary.period_ratio or periods[0] / periods[2], torsion_ratio=max((m.torsion_ratio for m in all_metrics)), min_shear_weight_ratio=min((m.shear_weight_ratio for m in all_metrics)), max_drift_ratio=max((result.max_interstory_drift_ratio for result in dir_results.values())), min_stiffness_ratio=min((m.stiffness_ratio_adjacent for m in all_metrics)), max_wall_axial_ratio=max_wall_axial_ratio, max_wall_axial_limit=max_wall_axial_limit, max_wall_shear_ratio=max_wall_shear_ratio, max_wall_shear_limit=max_wall_shear_limit, max_beam_shear_ratio=max_beam_shear_ratio, max_beam_shear_limit=max_beam_shear_limit, period_ratio_available=period_ratio_available, torsion_passed=overall_result.is_torsion_passed, shear_weight_passed=overall_result.is_shear_weight_passed, stiffness_passed=overall_result.is_stiffness_passed, drift_passed=overall_result.is_interstory_drift_passed, period_ratio_passed=overall_result.is_period_ratio_passed, wall_axial_passed=overall_result.is_wall_axial_passed, wall_shear_passed=overall_result.is_wall_shear_pressure_passed, beam_shear_passed=overall_result.is_beam_shear_pressure_passed, error='')
    except Exception as exc:
        raise
    finally:
        ops.wipe()

def _create_builder(name: BuilderName, logger: logging.Logger) -> StructuralModelBuilder:
    if name == 'mvlem_frame':
        return MVLEMFrameBuilder(logger, fiber_width=0.2)
    raise ValueError(f'Only migrated builder mvlem_frame is supported: {name}')
