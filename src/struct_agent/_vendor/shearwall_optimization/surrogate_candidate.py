from __future__ import annotations
import random
from dataclasses import dataclass
from typing import Any
from .core.contracts import EvaluationResult
from .local_calibration import OnlineLocalCalibrationConfig, OnlineLocalCalibrator
from .surrogate_cost import GNNMaterialCostEstimator, SurrogateCostPrediction, SurrogateCostPreselectionConfig
from .surrogate_screening import GNNFeasibilityScreener, ScreeningDecision, SurrogateScreeningConfig

@dataclass(frozen=True)
class SurrogateEvaluationConfig:
    max_workers: int | None = None
    surrogate_screening: SurrogateScreeningConfig | None = None
    cost_preselection: SurrogateCostPreselectionConfig | None = None
    local_calibration: OnlineLocalCalibrationConfig | None = None

class SurrogateCandidateEvaluator:

    def __init__(self, problem, cfg: SurrogateEvaluationConfig):
        self.problem = problem
        self.cfg = cfg
        self.screener = self._build_screener()
        self.cost_estimator = self._build_cost_estimator()
        self.local_calibrator = OnlineLocalCalibrator(cfg.local_calibration or OnlineLocalCalibrationConfig(enabled=False))
        self._has_seen_feasible = False
        self._rng = random.Random(20260621)

    @property
    def enabled(self) -> bool:
        return self.screener is not None or self.cost_estimator is not None

    def evaluate(self, decisions: list[dict[str, Any]]) -> list[tuple[dict[str, Any], EvaluationResult]]:
        repaired = [self.problem.repair(x) for x in decisions]
        if not self.enabled:
            results = self.real_evaluate_many(repaired)
            return list(zip(repaired, results))
        return self._evaluate_with_surrogates(repaired)

    def real_evaluate_many(self, items: list[dict[str, Any]]) -> list[EvaluationResult]:
        if not items:
            return []
        if hasattr(self.problem, 'evaluate_many'):
            return self.problem.evaluate_many(items, max_workers=self.cfg.max_workers)
        return [self.problem.evaluate(x) for x in items]

    def local_summary(self) -> dict[str, Any]:
        return self.local_calibrator.summary()

    @staticmethod
    def rank_key(res: EvaluationResult) -> tuple[bool, float]:
        return (not res.feasible, float(res.objective))

    @staticmethod
    def is_synthetic_result(res: EvaluationResult) -> bool:
        return bool(res.metrics.get('cost_preselect_skip', False) or res.metrics.get('surrogate_screen_reject', False))

    @staticmethod
    def population_item(res: EvaluationResult) -> dict[str, Any]:
        return {'objective': float(res.objective), 'feasible': bool(res.feasible), 'material_cost': float(res.objectives.get('material_cost', float('nan'))), 'total_violation': float(res.objectives.get('total_violation', float('nan'))), 'violation_sum': float(res.objectives.get('violation_sum', float('nan'))), 'max_violation': float(res.objectives.get('max_violation', float('nan'))), 'constraint_violation': float(res.objectives.get('constraint_violation', float('nan'))), 'violation_score': float(res.objectives.get('violation_score', float('nan'))), 'surrogate_screen_reject': bool(res.constraints.get('surrogate_screen_reject', 0.0) > 0.0), 'cost_preselect_skip': bool(res.metrics.get('cost_preselect_skip', False)), 'cost_preselect_selected': bool(res.metrics.get('cost_preselect_selected', False)), 'surrogate_cost_score': float(res.metrics.get('surrogate_cost_score', float('nan'))), 'surrogate_material_cost': float(res.metrics.get('surrogate_material_cost', float('nan'))), 'surrogate_concrete_cost': float(res.metrics.get('surrogate_concrete_cost', float('nan'))), 'surrogate_steel_cost': float(res.metrics.get('surrogate_steel_cost', float('nan'))), 'surrogate_concrete_kg': float(res.metrics.get('surrogate_concrete_kg', float('nan'))), 'surrogate_steel_kg': float(res.metrics.get('surrogate_steel_kg', float('nan'))), 'surrogate_final_pass_prob': float(res.metrics.get('surrogate_final_pass_prob', float('nan'))), 'surrogate_infeasible_risk': float(res.metrics.get('surrogate_infeasible_risk', float('nan')))}

    @staticmethod
    def population_counts(results: list[EvaluationResult]) -> dict[str, Any]:
        n = max(1, len(results))
        feasible = sum((1 for r in results if r.feasible))
        screened = sum((1 for r in results if r.constraints.get('surrogate_screen_reject', 0.0) > 0.0))
        skipped = sum((1 for r in results if bool(r.metrics.get('cost_preselect_skip', False))))
        selected = sum((1 for r in results if bool(r.metrics.get('cost_preselect_selected', False))))
        return {'feasible_count': feasible, 'feasible_ratio': feasible / n, 'screened_count': screened, 'screened_ratio': screened / n, 'cost_preselect_selected_count': selected, 'cost_preselect_selected_ratio': selected / n, 'cost_preselect_skipped_count': skipped, 'cost_preselect_skipped_ratio': skipped / n}

    def _evaluate_with_surrogates(self, repaired: list[dict[str, Any]]) -> list[tuple[dict[str, Any], EvaluationResult]]:
        n = len(repaired)
        results: list[EvaluationResult | None] = [None] * n
        raw_screening = self.screener.screen(repaired) if self.screener is not None else [None] * n
        screening = self._calibrate_screening(raw_screening)
        candidate_indices = []
        for i, decision in enumerate(screening):
            if decision is not None and decision.reject:
                results[i] = self._screened_result(decision)
            else:
                candidate_indices.append(i)
        cost_preds: dict[int, SurrogateCostPrediction] = {}
        global_cost_preds: dict[int, SurrogateCostPrediction] = {}
        if self.cost_estimator is not None and candidate_indices:
            items = [repaired[i] for i in candidate_indices]
            probs = [None if screening[i] is None else float(screening[i].probability) for i in candidate_indices]
            preds = self.cost_estimator.predict(items, feasible_probabilities=probs)
            global_cost_preds = dict(zip(candidate_indices, preds))
            cost_preds = {idx: self._calibrate_cost_prediction(repaired[idx], pred) for idx, pred in global_cost_preds.items()}
            selected_indices = self._select_cost_candidates(candidate_indices, cost_preds)
        else:
            selected_indices = list(candidate_indices)
        selected_items = [repaired[i] for i in selected_indices]
        eval_results = self.real_evaluate_many(selected_items)
        for idx, res in zip(selected_indices, eval_results):
            metrics = dict(res.metrics)
            pred = cost_preds.get(idx)
            if pred is not None:
                metrics.update(self._cost_prediction_metrics(pred, selected=True))
            self._update_local_calibration(repaired[idx], res, raw_screening[idx], global_cost_preds.get(idx))
            if res.feasible:
                self._has_seen_feasible = True
            results[idx] = EvaluationResult(objective=res.objective, objectives=res.objectives, feasible=res.feasible, constraints=res.constraints, metrics=metrics)
        for i in range(n):
            if results[i] is None:
                results[i] = self._cost_preselect_skipped_result(cost_preds.get(i))
        return [(x, res) for x, res in zip(repaired, results) if res is not None]

    def _calibrate_screening(self, raw: list[ScreeningDecision | None]) -> list[ScreeningDecision | None]:
        out = []
        for decision in raw:
            if decision is None:
                out.append(None)
                continue
            cal = self.local_calibrator.calibrate_feasibility(decision.probability, decision.threshold)
            out.append(ScreeningDecision(reject=cal.reject, probability=cal.probability, threshold=cal.threshold))
        return out

    def _calibrate_cost_prediction(self, decision: dict[str, Any], pred: SurrogateCostPrediction) -> SurrogateCostPrediction:
        steel_kg, _, _ = self.local_calibrator.calibrate_steel(decision, pred.steel_kg)
        steel_cost = self.problem.objective_cfg.steel_price_per_kg * steel_kg
        material = pred.concrete_cost + steel_cost
        cfg = self.cfg.cost_preselection or SurrogateCostPreselectionConfig(enabled=False)
        score = material + float(cfg.feasibility_penalty_cost) * float(pred.infeasible_risk)
        return SurrogateCostPrediction(score=float(score), steel_kg=float(steel_kg), concrete_kg=float(pred.concrete_kg), concrete_cost=float(pred.concrete_cost), steel_cost=float(steel_cost), material_cost=float(material), feasible_probability=pred.feasible_probability, infeasible_risk=float(pred.infeasible_risk))

    def _update_local_calibration(self, decision: dict[str, Any], result: EvaluationResult, screening: ScreeningDecision | None, pred: SurrogateCostPrediction | None) -> None:
        if not self.local_calibrator.cfg.enabled:
            return
        self.local_calibrator.update(decision, result, global_probability=None if screening is None else float(screening.probability), global_steel_kg=None if pred is None else float(pred.steel_kg))

    def _select_cost_candidates(self, indices: list[int], preds: dict[int, SurrogateCostPrediction]) -> list[int]:
        cfg = self.cfg.cost_preselection or SurrogateCostPreselectionConfig(enabled=False)
        n = len(indices)
        ratio = cfg.eval_ratio if self._has_seen_feasible else cfg.pre_feasible_eval_ratio
        eval_count = min(n, max(int(cfg.min_eval_count), int(round(n * ratio))))
        if eval_count >= n:
            return sorted(indices)
        if not self._has_seen_feasible:
            return sorted(sorted(indices, key=lambda i: preds[i].score)[:eval_count])
        selected: set[int] = set()
        self._add_quota(selected, sorted(indices, key=lambda i: preds[i].score), eval_count, cfg.cost_quota_ratio)
        self._add_quota(selected, sorted(indices, key=lambda i: (preds[i].infeasible_risk, preds[i].score)), eval_count, cfg.feasibility_quota_ratio)
        remain = [i for i in indices if i not in selected]
        self._rng.shuffle(remain)
        self._add_quota(selected, remain, eval_count, cfg.exploration_quota_ratio)
        if len(selected) < eval_count:
            for idx in sorted(indices, key=lambda i: preds[i].score):
                selected.add(idx)
                if len(selected) >= eval_count:
                    break
        return sorted(selected)

    @staticmethod
    def _add_quota(selected: set[int], ranked: list[int], total: int, ratio: float) -> None:
        if total <= 0 or ratio <= 0.0:
            return
        target = min(total, len(selected) + max(1, int(round(total * ratio))))
        for idx in ranked:
            selected.add(idx)
            if len(selected) >= target:
                break

    def _screened_result(self, decision: ScreeningDecision) -> EvaluationResult:
        cfg = self.cfg.surrogate_screening or SurrogateScreeningConfig(enabled=False)
        objective = float(cfg.rejected_objective)
        return EvaluationResult(objective=objective, objectives={'material_cost': objective, 'total_violation': 1.0}, feasible=False, constraints={'surrogate_screen_reject': 1.0}, metrics={'surrogate_screen_reject': True, 'surrogate_final_pass_prob': float(decision.probability), 'surrogate_screening_threshold': float(decision.threshold)})

    def _cost_preselect_skipped_result(self, pred: SurrogateCostPrediction | None) -> EvaluationResult:
        cfg = self.cfg.cost_preselection or SurrogateCostPreselectionConfig(enabled=False)
        objective = float(cfg.skipped_objective)
        metrics: dict[str, float | bool] = {'cost_preselect_skip': True}
        if pred is not None:
            metrics.update(self._cost_prediction_metrics(pred, selected=False))
        return EvaluationResult(objective=objective, objectives={'material_cost': objective, 'total_violation': 1.0}, feasible=False, constraints={'cost_preselect_skip': 1.0}, metrics=metrics)

    @staticmethod
    def _cost_prediction_metrics(pred: SurrogateCostPrediction, *, selected: bool) -> dict[str, float | bool]:
        return {'surrogate_cost_score': float(pred.score), 'surrogate_material_cost': float(pred.material_cost), 'surrogate_concrete_cost': float(pred.concrete_cost), 'surrogate_steel_cost': float(pred.steel_cost), 'surrogate_concrete_kg': float(pred.concrete_kg), 'surrogate_steel_kg': float(pred.steel_kg), 'surrogate_final_pass_prob': float('nan') if pred.feasible_probability is None else float(pred.feasible_probability), 'surrogate_infeasible_risk': float(pred.infeasible_risk), 'cost_preselect_selected': bool(selected)}

    def _build_screener(self) -> GNNFeasibilityScreener | None:
        cfg = self.cfg.surrogate_screening
        if cfg is None or not cfg.enabled:
            return None
        if not hasattr(self.problem, 'layout_path') or not hasattr(self.problem, 'fixed_params'):
            raise ValueError('Surrogate screening requires problem.layout_path and problem.fixed_params.')
        return GNNFeasibilityScreener(cfg, layout_id=self.problem.layout_path.stem, fixed_params=self.problem.fixed_params)

    def _build_cost_estimator(self) -> GNNMaterialCostEstimator | None:
        cfg = self.cfg.cost_preselection
        if cfg is None or not cfg.enabled:
            return None
        if not hasattr(self.problem, 'layout_path') or not hasattr(self.problem, 'fixed_params') or (not hasattr(self.problem, 'objective_cfg')):
            raise ValueError('Cost preselection requires problem.layout_path, fixed_params and objective_cfg.')
        return GNNMaterialCostEstimator(cfg, layout_id=self.problem.layout_path.stem, fixed_params=self.problem.fixed_params, steel_price_per_kg=self.problem.objective_cfg.steel_price_per_kg)
