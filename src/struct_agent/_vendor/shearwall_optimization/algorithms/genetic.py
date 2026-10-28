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

class GeneticAlgorithmOptimizer(Optimizer):

    def __init__(self, problem, config: GeneticAlgorithmConfig | None=None):
        super().__init__(problem)
        self.config = config or GeneticAlgorithmConfig()
        self.rng = random.Random(self.config.seed)
        self.evaluator = SurrogateCandidateEvaluator(problem, SurrogateEvaluationConfig(max_workers=self.config.max_workers, surrogate_screening=self.config.surrogate_screening, cost_preselection=self.config.cost_preselection, local_calibration=self.config.local_calibration))

    def optimize(self) -> OptimizationResult:
        print('[GA] Starting optimization')
        pop = [self.problem.repair(self.problem.sample()) for _ in range(self.config.population_size)]
        scored = self._evaluate_population(pop)
        history: list[dict[str, Any]] = []
        global_best_item: tuple[dict[str, Any], EvaluationResult] | None = None
        for gen in range(1, self.config.generations + 1):
            raw_scored = list(scored)
            scored.sort(key=lambda item: self._rank_key(item[1]))
            best_x, best_res = scored[0]
            if global_best_item is None or self._rank_key(best_res) < self._rank_key(global_best_item[1]):
                global_best_item = (dict(best_x), best_res)
            global_best_res = global_best_item[1]
            feasible_count = sum((1 for _, res in raw_scored if res.feasible))
            screened_count = sum((1 for _, res in raw_scored if res.constraints.get('surrogate_screen_reject', 0.0) > 0.0))
            cost_preselect_skipped_count = sum((1 for _, res in raw_scored if bool(res.metrics.get('cost_preselect_skip', False))))
            cost_preselect_selected_count = sum((1 for _, res in raw_scored if bool(res.metrics.get('cost_preselect_selected', False))))
            feasible_ratio = feasible_count / max(1, len(raw_scored))
            history.append({'generation': gen, 'best_objective': best_res.objective, 'best_feasible': best_res.feasible, 'global_best_objective': global_best_res.objective, 'global_best_feasible': global_best_res.feasible, 'feasible_count': feasible_count, 'feasible_ratio': feasible_ratio, 'screened_count': screened_count, 'screened_ratio': screened_count / max(1, len(raw_scored)), 'cost_preselect_selected_count': cost_preselect_selected_count, 'cost_preselect_selected_ratio': cost_preselect_selected_count / max(1, len(raw_scored)), 'cost_preselect_skipped_count': cost_preselect_skipped_count, 'cost_preselect_skipped_ratio': cost_preselect_skipped_count / max(1, len(raw_scored)), 'fea_evaluation_count': int(getattr(self.problem, 'fea_evaluation_count', -1)), **self.evaluator.local_summary(), 'population': [self.evaluator.population_item(res) for _, res in raw_scored], 'best_constraints': dict(best_res.constraints), 'worst_objectives': scored[-1][1].objectives})
            if self.config.verbose and (gen == 1 or gen == self.config.generations or gen % max(1, self.config.log_every) == 0):
                print(f"[GA] gen={gen:03d}/{self.config.generations} best={best_res.objective:.6g} global_best={global_best_res.objective:.6g} best_feasible={best_res.feasible} global_best_feasible={global_best_res.feasible} feasible_ratio={feasible_ratio:.1%} screened_ratio={screened_count / max(1, len(raw_scored)):.1%} cost_selected_ratio={cost_preselect_selected_count / max(1, len(raw_scored)):.1%} cost_skipped_ratio={cost_preselect_skipped_count / max(1, len(raw_scored)):.1%} fea_count={int(getattr(self.problem, 'fea_evaluation_count', -1))}")
            elites = [x for x, _ in scored[:self.config.elite_size]]
            next_pop = [dict(x) for x in elites]
            while len(next_pop) < self.config.population_size:
                p1 = self._tournament_pick(scored)
                p2 = self._tournament_pick(scored)
                c1, c2 = self._crossover(p1, p2)
                next_pop.append(self._mutate(c1))
                if len(next_pop) < self.config.population_size:
                    next_pop.append(self._mutate(c2))
            scored = self._evaluate_population(next_pop)
        if global_best_item is None:
            scored.sort(key=lambda item: self._rank_key(item[1]))
            global_best_item = scored[0]
        best_x, best_res = global_best_item
        if self._is_synthetic_result(best_res):
            best_res = self.problem.evaluate(best_x)
        if history:
            history[-1]['final_fea_evaluation_count'] = int(getattr(self.problem, 'fea_evaluation_count', -1))
        return OptimizationResult(best_solution=best_x, best_objective=best_res.objective, best_objectives=best_res.objectives, best_feasible=best_res.feasible, best_constraints=best_res.constraints, history=history)

    @staticmethod
    def _rank_key(res: EvaluationResult) -> tuple[bool, float]:
        return SurrogateCandidateEvaluator.rank_key(res)

    def _evaluate_population(self, pop: list[dict[str, Any]]) -> list[tuple[dict[str, Any], EvaluationResult]]:
        return self.evaluator.evaluate(pop)

    @staticmethod
    def _is_synthetic_result(res: EvaluationResult) -> bool:
        return SurrogateCandidateEvaluator.is_synthetic_result(res)

    def _tournament_pick(self, scored: list[tuple[dict[str, Any], EvaluationResult]]) -> dict[str, Any]:
        pool = self.rng.sample(scored, k=min(self.config.tournament_size, len(scored)))
        pool.sort(key=lambda item: (not item[1].feasible, item[1].objective))
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
