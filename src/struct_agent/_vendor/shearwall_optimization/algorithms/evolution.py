"""Shared generation engine for continuous and incremental optimization."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from struct_agent._vendor.shearwall_optimization.algorithms.genetic import GeneticAlgorithmOptimizer
from struct_agent._vendor.shearwall_optimization.core.contracts import EvaluationResult, OptimizationResult


class IncrementalGA:
    """In-process continuation; a failed partial generation is terminal, not replayed.

    One generation means one evaluated population. Every evaluated population is
    ranked before pausing; no unranked trailing population consumes the budget.
    """

    def __init__(self, optimizer: GeneticAlgorithmOptimizer) -> None:
        self.optimizer = optimizer
        self.scored: list[tuple[dict[str, Any], EvaluationResult]] | None = None
        self.global_best: tuple[dict[str, Any], EvaluationResult] | None = None
        self.history: list[dict[str, Any]] = []
        self.completed_generations = 0
        self.result: OptimizationResult | None = None
        self.status = "ready"

    def advance(self, generations: int) -> OptimizationResult | None:
        if type(generations) is not int or generations < 1:
            raise ValueError("Positive integer generation count required")
        if self.status in ("completed", "failed"):
            raise RuntimeError(f"Cannot advance a {self.status} optimizer")
        ga = self.optimizer
        try:
            end = min(ga.config.generations, self.completed_generations + generations)
            while self.completed_generations < end:
                population = self._initial_population() if self.scored is None else self._next_population()
                self.scored = ga._evaluate_population(population)
                self._generation()
            if self.completed_generations == ga.config.generations:
                self._finalize()
                self.status = "completed"
            else:
                self.status = "paused"
        except Exception:
            self.status = "failed"
            raise
        return deepcopy(self.result)

    def _generation(self) -> None:
        ga = self.optimizer
        assert self.scored is not None
        raw_scored = list(self.scored)
        self.scored.sort(key=lambda item: ga._rank_key(item[1]))
        best_x, best_res = self.scored[0]
        if self.global_best is None or ga._rank_key(best_res) < ga._rank_key(self.global_best[1]):
            self.global_best = (dict(best_x), best_res)
        global_best_res = self.global_best[1]
        self.history.append({
            "generation": self.completed_generations + 1,
            "best_objective": best_res.objective, "best_feasible": best_res.feasible,
            "global_best_objective": global_best_res.objective, "global_best_feasible": global_best_res.feasible,
            **ga.evaluator.population_counts([res for _, res in raw_scored]),
            "fea_evaluation_count": int(getattr(ga.problem, "fea_evaluation_count", -1)),
            **ga.evaluator.local_summary(),
            "population": [ga.evaluator.population_item(res) for _, res in raw_scored],
            "best_constraints": dict(best_res.constraints), "worst_objectives": self.scored[-1][1].objectives,
        })
        self.completed_generations += 1

    def _initial_population(self) -> list[dict[str, Any]]:
        ga = self.optimizer
        seeds = getattr(ga.problem, "initial_candidates", lambda: [])()
        population = []
        for x in seeds:
            item = ga.problem.repair(x)
            if item not in population:
                population.append(item)
        return self._fill_population(population[:ga.config.population_size], initial=True)

    def _next_population(self) -> list[dict[str, Any]]:
        ga = self.optimizer
        assert self.scored is not None
        population = [dict(x) for x, _ in self.scored[:ga.config.elite_size]]
        # Deterministic domain moves supplement GA; their effect still requires FEA.
        if self.global_best is not None and not ga._is_synthetic_result(self.global_best[1]):
            proposals = getattr(ga.problem, "feedback_candidates", lambda x, r: [])(*self.global_best)
            for item in proposals:
                if len(population) >= ga.config.population_size:
                    break
                item = ga.problem.repair(item)
                if item not in population:
                    population.append(item)
        return self._fill_population(population, initial=False)

    def _fill_population(self, population: list[dict[str, Any]], *, initial: bool) -> list[dict[str, Any]]:
        ga = self.optimizer
        attempts = 0
        # Reject duplicates while practical; bounded retries permit finite domains.
        while len(population) < ga.config.population_size:
            attempts += 1
            if initial or attempts > 4 * ga.config.population_size:
                children = [ga.problem.repair(ga.problem.sample())]
            else:
                assert self.scored is not None
                p1, p2 = ga._tournament_pick(self.scored), ga._tournament_pick(self.scored)
                children = [ga._mutate(child) for child in ga._crossover(p1, p2)]
            for item in children:
                if len(population) >= ga.config.population_size:
                    break
                if item not in population or attempts > 20 * ga.config.population_size:
                    population.append(dict(item))
        return population

    def _finalize(self) -> None:
        ga = self.optimizer
        assert self.global_best is not None
        best_x, best_res = self.global_best
        if ga._is_synthetic_result(best_res):
            best_res = ga.problem.evaluate(best_x)
        if self.history:
            self.history[-1]["final_fea_evaluation_count"] = int(getattr(ga.problem, "fea_evaluation_count", -1))
        self.result = OptimizationResult(best_solution=best_x, best_objective=best_res.objective,
            best_objectives=best_res.objectives, best_feasible=best_res.feasible,
            best_constraints=best_res.constraints, history=self.history)
