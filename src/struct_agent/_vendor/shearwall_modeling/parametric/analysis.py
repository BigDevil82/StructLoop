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
from .summary import summarize_native
from .types import BuilderName, DatasetGenerationConfig, ParametricAnalysisResult, ParametricModelParams

def build_model_config_from_params(params: ParametricModelParams | dict[str, Any], *, story_height: float | None=None, num_modes: int=6) -> ModelConfig:
    p = normalize_params(params)
    h_story = 2.9 if story_height is None else story_height
    slab_thickness = 0.12
    n_bottom, n_middle, n_top = split_stories(p.N)

    def make_section(tw_mm: int) -> SectionConfig:
        return SectionConfig(wall_thickness=tw_mm / 1000.0, beam_width=p.bb_main / 1000.0, beam_depth=p.hb_main / 1000.0, secondary_beam_width=p.bb_sec / 1000.0, secondary_beam_depth=p.hb_sec / 1000.0, slab_thickness=slab_thickness)
    groups = [StandardStoryGroupConfig(count=n_bottom, story_height=h_story, section=make_section(p.tw_bot), material=MaterialConfig(concrete_grade=p.conc_bot)), StandardStoryGroupConfig(count=n_middle, story_height=h_story, section=make_section(p.tw_mid), material=MaterialConfig(concrete_grade=p.conc_bot)), StandardStoryGroupConfig(count=n_top, story_height=h_story, section=make_section(p.tw_top), material=MaterialConfig(concrete_grade=p.conc_bot))]
    # Three-story inputs can have an empty middle zone; it is not a story group.
    return ModelConfig(standard_story_groups=[g for g in groups if g.count > 0], seismic=SeismicConfig(intensity=p.intensity, site_class=p.site_class, seismic_group=p.seismic_group), num_modes=num_modes)

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
        design_summary = ReinforcementDesignPipeline(build_result=build_result, analysis_result=analysis_result, config=model_cfg, logger=run_logger).run()
        return summarize_native(build_result, analysis_result, overall_result, dir_results, design_summary)
    except Exception as exc:
        raise
    finally:
        ops.wipe()

def _create_builder(name: BuilderName, logger: logging.Logger) -> StructuralModelBuilder:
    if name == 'mvlem_frame':
        return MVLEMFrameBuilder(logger, fiber_width=0.2)
    raise ValueError(f'Only migrated builder mvlem_frame is supported: {name}')
