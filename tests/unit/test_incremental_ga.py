from dataclasses import asdict
import random
from types import SimpleNamespace

import pytest

from struct_agent.adapters.incremental_ga import IncrementalGA
from struct_agent._vendor.shearwall_optimization.algorithms.genetic import GeneticAlgorithmConfig, GeneticAlgorithmOptimizer
from struct_agent._vendor.shearwall_optimization.core.contracts import EvaluationResult, VariableSpec
from struct_agent._vendor.shearwall_optimization.local_calibration import OnlineLocalCalibrationConfig
from struct_agent._vendor.shearwall_optimization.surrogate_cost import SurrogateCostPrediction, SurrogateCostPreselectionConfig
from struct_agent._vendor.shearwall_optimization.surrogate_screening import ScreeningDecision
from struct_agent.io.artifacts import json_safe
from struct_agent.services.analysis import BudgetExhausted


class ToyProblem:
    """Synthetic objective for algorithm-order tests, never a structural solver."""
    def __init__(self, seed: int, budget: int = 10000) -> None:
        self.rng = random.Random(seed)
        self.variables = [VariableSpec("x", list(range(20))), VariableSpec("y", list(range(10)))]
        self.objective_cfg = SimpleNamespace(steel_price_per_kg=1.0)
        self.calls = []
        self.budget = budget

    @property
    def fea_evaluation_count(self) -> int:
        return len(self.calls)

    def sample(self) -> dict:
        return {v.name: self.rng.choice(v.domain) for v in self.variables}

    def repair(self, x: dict) -> dict:
        return dict(x)

    def evaluate(self, x: dict) -> EvaluationResult:
        if len(self.calls) >= self.budget:
            raise BudgetExhausted("synthetic budget exhausted")
        self.calls.append(dict(x))
        cost = float(100 + x["x"] * 2 + x["y"])
        return EvaluationResult(cost, {"material_cost": cost}, x["x"] % 2 == 0, {}, {"material_steel_kg": cost})


class SyntheticScreen:
    def __init__(self, reject_all: bool = False) -> None:
        self.reject_all = reject_all

    def screen(self, items: list[dict]) -> list[ScreeningDecision]:
        return [ScreeningDecision(self.reject_all, 0.2 + item["x"] / 40, 0.99 if self.reject_all else 0.0) for item in items]


class SyntheticCost:
    def predict(self, items: list[dict], *, feasible_probabilities: list) -> list[SurrogateCostPrediction]:
        return [SurrogateCostPrediction(100. + x["x"], 100. + x["x"], 0., 0., 100. + x["x"],
                                       100. + x["x"], p, 1. - p) for x, p in zip(items, feasible_probabilities)]


def make_optimizer(seed: int, *, surrogate: bool, reject_all: bool = False, budget: int = 10000) -> GeneticAlgorithmOptimizer:
    cfg = GeneticAlgorithmConfig(population_size=10, generations=4, seed=seed,
        cost_preselection=SurrogateCostPreselectionConfig(enabled=False, min_eval_count=4, eval_ratio=0.5),
        local_calibration=OnlineLocalCalibrationConfig(enabled=surrogate, min_samples=3, steel_min_samples=3))
    ga = GeneticAlgorithmOptimizer(ToyProblem(seed, budget), cfg)
    if surrogate:
        ga.evaluator.screener = SyntheticScreen(reject_all)
        if not reject_all:
            ga.evaluator.cost_estimator = SyntheticCost()
    return ga


@pytest.mark.parametrize("seed", [7, 42])
@pytest.mark.parametrize("surrogate", [False, True])
def test_native_continuous_and_chunked_are_identical(seed: int, surrogate: bool) -> None:
    native = make_optimizer(seed, surrogate=surrogate)
    expected = native.optimize()
    whole = IncrementalGA(make_optimizer(seed, surrogate=surrogate))
    whole.advance(4)
    chunks = IncrementalGA(make_optimizer(seed, surrogate=surrogate))
    assert chunks.advance(1) is None
    assert chunks.status == "paused" and chunks.completed_generations == 1
    retained = chunks.optimizer.evaluator.local_calibrator
    chunks.advance(2)
    chunks.advance(1)
    assert chunks.optimizer.evaluator.local_calibrator is retained
    for actual in (whole, chunks):
        assert json_safe(asdict(actual.result)) == json_safe(asdict(expected))
        assert actual.optimizer.problem.calls == native.problem.calls
        assert actual.optimizer.rng.getstate() == native.rng.getstate()
        assert actual.optimizer.problem.rng.getstate() == native.problem.rng.getstate()
        assert actual.optimizer.evaluator._rng.getstate() == native.evaluator._rng.getstate()
        assert actual.optimizer.evaluator.local_calibrator._records == native.evaluator.local_calibrator._records
        assert actual.optimizer.evaluator.local_summary() == native.evaluator.local_summary()
    if surrogate:
        assert retained._feas_model is not None and retained._steel_model is not None


def test_final_fallback_happens_once_not_at_each_pause() -> None:
    native = make_optimizer(42, surrogate=True, reject_all=True)
    expected = native.optimize()
    chunks = IncrementalGA(make_optimizer(42, surrogate=True, reject_all=True))
    chunks.advance(1)
    assert len(chunks.optimizer.problem.calls) == 0
    chunks.advance(3)
    assert len(chunks.optimizer.problem.calls) == len(native.problem.calls) == 1
    assert json_safe(asdict(chunks.result)) == json_safe(asdict(expected))
    with pytest.raises(RuntimeError, match="completed"):
        chunks.advance(1)


def test_budget_failure_does_not_restart_partial_population() -> None:
    chunks = IncrementalGA(make_optimizer(42, surrogate=False, budget=12))
    with pytest.raises(BudgetExhausted):
        chunks.advance(1)
    assert chunks.status == "failed" and chunks.completed_generations == 0
    assert len(chunks.history) == 1 and len(chunks.optimizer.problem.calls) == 12
    with pytest.raises(RuntimeError, match="failed"):
        chunks.advance(1)
    assert len(chunks.optimizer.problem.calls) == 12


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_chunk_never_evaluates(value: object) -> None:
    chunks = IncrementalGA(make_optimizer(42, surrogate=False))
    with pytest.raises(ValueError):
        chunks.advance(value)
    assert not chunks.optimizer.problem.calls and chunks.status == "ready"
