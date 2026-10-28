from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class VariableSpec:
    name: str
    domain: list[Any]

@dataclass(frozen=True)
class EvaluationResult:
    objective: float
    objectives: dict[str, float]
    feasible: bool
    constraints: dict[str, float]
    metrics: dict[str, Any]

@dataclass(frozen=True)
class OptimizationResult:
    best_solution: dict[str, Any]
    best_objective: float
    best_objectives: dict[str, float]
    best_feasible: bool
    best_constraints: dict[str, float]
    history: list[dict[str, Any]]

class OptimizationProblem(ABC):

    @property
    @abstractmethod
    def variables(self) -> list[VariableSpec]:
        pass

    @abstractmethod
    def sample(self) -> dict[str, Any]:
        pass

    @abstractmethod
    def repair(self, x: dict[str, Any]) -> dict[str, Any]:
        pass

    @abstractmethod
    def evaluate(self, x: dict[str, Any]) -> EvaluationResult:
        pass

    @abstractmethod
    def encode(self, x: dict[str, Any]) -> list[float]:
        pass

    @abstractmethod
    def decode(self, vec: list[float]) -> dict[str, Any]:
        pass
