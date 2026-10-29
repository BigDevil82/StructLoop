"""Fixed-layout search with feasibility-first selection and real FEA feedback."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
from typing import Any, Literal
from struct_agent._vendor.shearwall_optimization.algorithms.genetic import GeneticAlgorithmOptimizer

from pydantic import Field

from struct_agent._vendor.shearwall_optimization.core.contracts import EvaluationResult, OptimizationProblem, VariableSpec
from struct_agent._vendor.shearwall_optimization.problems.shearwall_problem import (
    ShearWallConstraintConfig, ShearWallLimitConfig, ShearWallObjectiveConfig, summarize_analysis)
from struct_agent.adapters.fea import native_params
from struct_agent.io.artifacts import write_json
from struct_agent.schemas import DesignCandidate, LayoutCandidate, ProjectSpec, RoomGraph
from struct_agent.schemas.base import Contract
from struct_agent.services.analysis import AnalysisFailed, AnalysisService, BudgetExhausted
from .casino_assets import prepare_context


class CasinoConfig(Contract):
    feasibility_weights: Path | None = None
    steel_weights: Path | None = None
    use_surrogate: bool = False
    surrogate_analysis_signature: str | None = None
    seed: int
    initial_values: dict[str, float | str] | None = None
    device: Literal["cpu", "cuda"] = "cpu"
    population_size: int = Field(default=24, ge=2)
    generations: int = Field(default=20, ge=1)
    eval_ratio: float = Field(default=0.4, gt=0., le=1.)
    min_eval_count: int = Field(default=8, ge=1)
    calibration_min_samples: int = Field(default=25, ge=2)
    screening_threshold: float | None = Field(default=None, ge=0., le=1.)


class CasinoProblem(OptimizationProblem):
    """Native optimizer sees integer mm; all real analysis goes through service."""
    def __init__(self, layout: LayoutCandidate, spec: ProjectSpec, evaluator: AnalysisService,
                 *, layout_path: Path, seed: int, initial_values: dict[str, float | str] | None = None) -> None:
        self.layout, self.spec, self.evaluator, self.layout_path = layout, spec, evaluator, layout_path
        self.rng = random.Random(seed)
        self.objective_cfg = ShearWallObjectiveConfig()
        self.constraint_cfg, self.limit_cfg = ShearWallConstraintConfig(), ShearWallLimitConfig()
        self.fixed_params = dict(N=spec.stories, hs=120, h_story=spec.story_height_m,
            intensity=spec.intensity, site_class=spec.site_class, seismic_group=spec.seismic_group)
        self._variables = [VariableSpec(v.name, [round(float(x)*1000) if v.unit == "m" else x for x in v.values])
                           for v in spec.design_variables]
        self.results: list[tuple[DesignCandidate, EvaluationResult]] = []
        self.initial_values = initial_values
        if initial_values is not None:
            DesignCandidate(design_id="initial", layout_id=layout.layout_id,
                condition_id=spec.condition_id, values=initial_values).validate_against(spec)

    def initial_candidates(self) -> list[dict[str, Any]]:
        """Preserve the supplied design before exploring an upper-domain corner."""
        seeds = []
        if self.initial_values is not None:
            seeds.append({k: round(float(v)*1000) if k != "conc_bot" else v
                          for k, v in self.initial_values.items()})
            from .design_search import ordered_domain
            # This is an exploratory corner, never a claimed feasibility bound.
            seeds.append(self.repair({v.name: ordered_domain(v)[-1] for v in self.variables}))
        return seeds

    def feedback_candidates(self, x: dict[str, Any], result: EvaluationResult) -> list[dict[str, Any]]:
        from .design_search import feedback_candidates
        evaluated = [{k: round(float(v)*1000) if k != "conc_bot" else v for k, v in d.values.items()}
                     for d, _ in self.results]
        return feedback_candidates(x, result, self.variables, self.repair, evaluated)

    @property
    def variables(self) -> list[VariableSpec]:
        return self._variables

    @property
    def fea_evaluation_count(self) -> int:
        return len(self.evaluator.records)

    def sample(self) -> dict[str, Any]:
        return {v.name:self.rng.choice(v.domain) for v in self.variables}

    def repair(self, x: dict[str, Any]) -> dict[str, Any]:
        repaired = dict(x)
        domains = {v.name:v.domain for v in self.variables}
        for name, parent in (("tw_mid", "tw_bot"), ("tw_top", "tw_mid")):
            target = min(repaired[name], repaired[parent])
            allowed = [v for v in domains[name] if v <= target]
            if not allowed:
                raise ValueError(f"Incompatible wall-thickness domains: {name}")
            repaired[name] = max(allowed)
        return repaired

    def evaluate(self, x: dict[str, Any]) -> EvaluationResult:
        values = {k:float(v)/1000. if k != "conc_bot" else v for k,v in self.repair(x).items()}
        design_key = hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()[:16]
        design = DesignCandidate(design_id=f"design_{design_key}", layout_id=self.layout.layout_id,
            condition_id=self.spec.condition_id, values=values)
        record = self.evaluator.evaluate(self.layout, design, self.spec)
        if record.status != "SUCCESS":
            raise AnalysisFailed(record)
        from struct_agent._vendor.shearwall_modeling.parametric.types import ParametricAnalysisResult
        result = summarize_analysis(analysis_result=ParametricAnalysisResult(**record.raw),
            params=native_params(design, self.spec), geom_scale=1., objective_cfg=self.objective_cfg,
            constraint_cfg=self.constraint_cfg, limit_cfg=self.limit_cfg,
            member_counts={"wall": self.spec.stories * sum(m.role == "wall" for m in self.layout.members),
                           "beam": self.spec.stories * sum(m.role != "wall" for m in self.layout.members)})
        if not any(d.design_id == design.design_id for d,_ in self.results):
            self.results.append((design,result))
        return result

    def encode(self, x: dict[str, Any]) -> list[float]:
        return [v.domain.index(x[v.name])/max(1,len(v.domain)-1) for v in self.variables]

    def decode(self, vec: list[float]) -> dict[str, Any]:
        if len(vec) != len(self.variables):
            raise ValueError("Vector length mismatch")
        return self.repair({v.name:v.domain[round(min(1.,max(0.,a))*max(1,len(v.domain)-1))]
                            for v,a in zip(self.variables,vec)})


def create_optimizer(layout: LayoutCandidate, rooms: RoomGraph, spec: ProjectSpec, evaluator: AnalysisService,
                     cfg: CasinoConfig, *, directory: Path) -> GeneticAlgorithmOptimizer:
    """New bound native optimizer; caller owns its lifetime and continuation."""
    import torch
    from struct_agent._vendor.shearwall_optimization.algorithms.genetic import GeneticAlgorithmConfig, GeneticAlgorithmOptimizer
    from struct_agent._vendor.shearwall_optimization.local_calibration import OnlineLocalCalibrationConfig
    from struct_agent._vendor.shearwall_optimization.surrogate_cost import SurrogateCostPreselectionConfig
    from struct_agent._vendor.shearwall_optimization.surrogate_screening import SurrogateScreeningConfig
    if cfg.use_surrogate and getattr(evaluator.solver, 'fidelity', 'full') == 'full':
        if cfg.surrogate_analysis_signature != getattr(evaluator.solver, 'analysis_signature', None) or cfg.surrogate_analysis_signature is None:
            raise ValueError('BLOCKED: surrogate training physics do not match the current corrected FEA implementation')
    for path in (cfg.feasibility_weights, cfg.steel_weights) if cfg.use_surrogate else ():
        if path is None or not path.is_file():
            raise FileNotFoundError(f"BLOCKED: CASINO weights missing: {path}")
    if cfg.use_surrogate and cfg.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("BLOCKED: explicitly requested CUDA is unavailable")
    directory.mkdir(parents=True, exist_ok=False)
    context = directory / "context"
    layout_path = prepare_context(layout, rooms, context)
    problem = CasinoProblem(layout,spec,evaluator,layout_path=layout_path,seed=cfg.seed,initial_values=cfg.initial_values)
    settings = GeneticAlgorithmConfig(population_size=cfg.population_size, generations=cfg.generations,
        elite_size=min(2,cfg.population_size-1), max_workers=None, seed=cfg.seed,
        surrogate_screening=SurrogateScreeningConfig(enabled=cfg.use_surrogate, artifact_path=str(cfg.feasibility_weights),
            graph_cache_dir=str(context), layout_features_path=str(context/"layout_features.parquet"),
            screening_threshold=cfg.screening_threshold),
        cost_preselection=SurrogateCostPreselectionConfig(enabled=cfg.use_surrogate, steel_artifact_path=str(cfg.steel_weights),
            graph_cache_dir=str(context), layout_features_path=str(context/"layout_features.parquet"),
            eval_ratio=cfg.eval_ratio, min_eval_count=cfg.min_eval_count),
        local_calibration=OnlineLocalCalibrationConfig(enabled=cfg.use_surrogate, min_samples=cfg.calibration_min_samples,
            steel_min_samples=cfg.calibration_min_samples))
    # Weight construction must not overwrite the caller's process-global RNG states.
    with torch.random.fork_rng():
        torch.manual_seed(cfg.seed)
        optimizer = GeneticAlgorithmOptimizer(problem,settings)
        # Upstream constructors auto-select CUDA. Make execution device explicit
        # at the adapter boundary; CPU is the reproducible regression default.
        for predictor in (optimizer.evaluator.screener, optimizer.evaluator.cost_estimator):
            if predictor is not None:
                predictor.device = torch.device(cfg.device)
                predictor.model.to(predictor.device)
    return optimizer


def optimize(layout: LayoutCandidate, rooms: RoomGraph, spec: ProjectSpec, evaluator: AnalysisService,
             cfg: CasinoConfig, *, directory: Path) -> dict[str, Any]:
    """One-shot execution of the same generation engine used by CasinoSession."""
    optimizer = create_optimizer(layout, rooms, spec, evaluator, cfg, directory=directory)
    problem = optimizer.problem
    reason, history = "completed", []
    try:
        result = optimizer.optimize()
        history = result.history
    except BudgetExhausted:
        reason = "budget_exhausted"
    except AnalysisFailed:
        reason = "analysis_failed"
    # Only actual completed evaluations can supply a reported optimum.
    best = min(problem.results, key=lambda r:optimizer._rank_key(r[1]), default=None)
    summary = {"termination":reason, "fea_attempts":len(evaluator.records),
        "best_design":None if best is None else best[0].model_dump(),
        "best_feasible":None if best is None else best[1].feasible,
        "best_objectives":None if best is None else best[1].objectives,
        "calibration":optimizer.evaluator.local_summary(), "history_complete":reason == "completed",
        "engineering_review":"PENDING", "fidelity":getattr(evaluator.solver,"fidelity","full"),
        "upstream_random_seeds":{"exploration":20260621,"calibration":0}}
    write_json(directory/"history.json",history)
    write_json(directory/"summary.json",summary)
    return summary
