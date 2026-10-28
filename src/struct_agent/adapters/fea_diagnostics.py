"""Opt-in detailed FEA using the same native build/check/design components."""
from __future__ import annotations

from dataclasses import asdict
import logging
from pathlib import Path

import openseespy.opensees as ops
from struct_agent._vendor.shearwall_modeling.analysis.evaluation import AnalysisResultBuilder, SeismicEvaluationPipeline
from struct_agent._vendor.shearwall_modeling.builders.base import AnalysisModelContext
from struct_agent._vendor.shearwall_modeling.design.pipeline import ReinforcementDesignPipeline
from struct_agent._vendor.shearwall_modeling.core.domain import FEMInput
from struct_agent._vendor.shearwall_modeling.parametric.analysis import _create_builder, build_model_config_from_params
from struct_agent._vendor.shearwall_modeling.parametric.types import DatasetGenerationConfig, ParametricAnalysisResult, ParametricModelParams
from struct_agent.io.artifacts import write_json
from struct_agent.schemas import LayoutCandidate
from .fea_member_evidence import collect_members
from struct_agent._vendor.shearwall_modeling.parametric.summary import summarize_native


class DiagnosticEvidenceError(RuntimeError):
    """Postprocessing failure after the native solve/check/design returned."""


def analyze_detailed(topology: FEMInput, params: ParametricModelParams, cfg: DatasetGenerationConfig,
                     *, layout: LayoutCandidate, directory: Path) -> ParametricAnalysisResult:
    """One real solve, no monkey-patching, no change to upstream algorithms/limits."""
    directory.mkdir(parents=True, exist_ok=False)
    logger = logging.getLogger("shearwall_diagnostics")
    logger.setLevel(logging.WARN)
    try:
        model_cfg = build_model_config_from_params(params, num_modes=cfg.num_modes)
        build = _create_builder(cfg.builder_name, logger).build(topology, model_cfg)
        context = AnalysisModelContext(build_result=build, config=model_cfg, logger=logger)
        builder = AnalysisResultBuilder(context)
        analysis = builder.build()
        overall, directions = SeismicEvaluationPipeline(model_cfg).evaluate(analysis)
        design = ReinforcementDesignPipeline(build, analysis, model_cfg, logger).run()
        summary = summarize_native(build, analysis, overall, directions, design)
        try:
            write_json(directory / "native_summary.json", asdict(summary))
            members = collect_members(layout, context, analysis, design, beta_c=builder.uls_analyzer.beta_c,
                combination_types=builder.uls_analyzer.combo_type_by_name)
            write_json(directory / "members.json", {"fidelity": "full", "coordinate_system": "global_xy",
                "units": {"length": "m", "force": "N", "stress": "Pa"},
                "all_modeled_walls_reinforcement_checked": True,
                "members": [m.model_dump() for m in members]})
            write_json(directory / "model_config.json", asdict(model_cfg))
            write_json(directory / "checks.json", {"overall": asdict(overall),
                "directions": {k: asdict(v) for k, v in directions.items()},
                "design_failed_beams": [asdict(x) for x in design.failed_beams],
                "design_failed_walls": [asdict(x) for x in design.failed_walls]})
        except Exception as exc:
            raise DiagnosticEvidenceError(f"{type(exc).__name__}: {exc}") from exc
        return summary
    finally:
        ops.wipe()
