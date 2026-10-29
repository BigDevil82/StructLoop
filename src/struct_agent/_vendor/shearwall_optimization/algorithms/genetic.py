import random
from dataclasses import dataclass
from typing import Any
from ..core.contracts import EvaluationResult, OptimizationResult
from ..core.optimizer import Optimizer
from ..local_calibration import OnlineLocalCalibrationConfig
from ..surrogate_candidate import SurrogateCandidateEvaluator, SurrogateEvaluationConfig
from ..surrogate_cost import SurrogateCostPreselectionConfig
from ..surrogate_screening import SurrogateScreeningConfig

@dataclass(frozen=True)
class GeneticAlgorithmConfig:
    population_size: int = 24
    generations: int = 20
    crossover_rate: float = 0.9
    mutation_rate: float = 0.2
    elite_size: int = 2
    tournament_size: int = 3
    max_workers: int | None = None
    verbose: bool = False
    log_every: int = 1
    seed: int = 42
    surrogate_screening: SurrogateScreeningConfig | None = None
    cost_preselection: SurrogateCostPreselectionConfig | None = None
    local_calibration: OnlineLocalCalibrationConfig | None = None

    def __post_init__(self) -> None:
        if self.population_size < 2 or self.generations < 1:
            raise ValueError("Population >=2 and generations >=1 required")
        if not 1 <= self.elite_size < self.population_size:
            raise ValueError("Elite size must leave at least one offspring slot")
        if self.tournament_size < 1 or not 0 <= self.mutation_rate <= 1 or not 0 <= self.crossover_rate <= 1:
            raise ValueError("Invalid GA selection/probability settings")

class GeneticAlgorithmOptimizer(Optimizer):

    def __init__(self, problem, config: GeneticAlgorithmConfig | None=None):
        super().__init__(problem)
        self.config = config or GeneticAlgorithmConfig()
        self.rng = random.Random(self.config.seed)
        self.evaluator = SurrogateCandidateEvaluator(problem, SurrogateEvaluationConfig(max_workers=self.config.max_workers, surrogate_screening=self.config.surrogate_screening, cost_preselection=self.config.cost_preselection, local_calibration=self.config.local_calibration))

    def optimize(self) -> OptimizationResult:
        from .evolution import IncrementalGA
        engine = IncrementalGA(self)
        engine.advance(self.config.generations)
        assert engine.result is not None
        return engine.result

    @staticmethod
    def _rank_key(res: EvaluationResult) -> tuple[bool, float, float]:
        return SurrogateCandidateEvaluator.rank_key(res)

    def _evaluate_population(self, pop: list[dict[str, Any]]) -> list[tuple[dict[str, Any], EvaluationResult]]:
        return self.evaluator.evaluate(pop)

    @staticmethod
    def _is_synthetic_result(res: EvaluationResult) -> bool:
        return SurrogateCandidateEvaluator.is_synthetic_result(res)

    def _tournament_pick(self, scored: list[tuple[dict[str, Any], EvaluationResult]]) -> dict[str, Any]:
        pool = self.rng.sample(scored, k=min(self.config.tournament_size, len(scored)))
        pool.sort(key=lambda item: self._rank_key(item[1]))
        return dict(pool[0][0])

    def _crossover(self, p1: dict[str, Any], p2: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.rng.random() > self.config.crossover_rate:
            return (dict(p1), dict(p2))
        c1: dict[str, Any] = {}
        c2: dict[str, Any] = {}
        for spec in self.problem.variables:
            if self.rng.random() < 0.5:
                c1[spec.name] = p1[spec.name]
                c2[spec.name] = p2[spec.name]
            else:
                c1[spec.name] = p2[spec.name]
                c2[spec.name] = p1[spec.name]
        return (self.problem.repair(c1), self.problem.repair(c2))

    def _mutate(self, x: dict[str, Any]) -> dict[str, Any]:
        out = dict(x)
        for spec in self.problem.variables:
            if self.rng.random() < self.config.mutation_rate:
                out[spec.name] = self.rng.choice(spec.domain)
        return self.problem.repair(out)
