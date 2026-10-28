from abc import ABC, abstractmethod
from dataclasses import dataclass
from .contracts import OptimizationProblem, OptimizationResult

@dataclass(frozen=True)
class OptimizerConfig:
    seed: int = 42

class Optimizer(ABC):

    def __init__(self, problem: OptimizationProblem):
        self.problem = problem

    @abstractmethod
    def optimize(self) -> OptimizationResult:
        pass
