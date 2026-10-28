from abc import ABC, abstractmethod
from dataclasses import dataclass
from ..core.constants import MIN_SHEAR_WEIGHT_RATIO_BY_INTENSITY
from .results import DirectionCheckResult, DirectionResponse, ModalSummary, OverallCheckResult
from .uls_combinations import BeamULSMetric, WallULSMetric

class DirectionChecker(ABC):

    @abstractmethod
    def apply(self, response: DirectionResponse, result: DirectionCheckResult) -> None:
        raise NotImplementedError

@dataclass(frozen=True)
class TorsionChecker(DirectionChecker):
    limit_ratio: float = 1.5

    def apply(self, response: DirectionResponse, result: DirectionCheckResult) -> None:
        result.is_torsion_passed = all((metric.torsion_ratio <= self.limit_ratio for metric in response.metrics))

@dataclass(frozen=True)
class ShearWeightRatioChecker(DirectionChecker):
    min_ratio: float

    @classmethod
    def from_intensity(cls, intensity: float) -> 'ShearWeightRatioChecker':
        key = round(float(intensity), 2)
        return cls(min_ratio=MIN_SHEAR_WEIGHT_RATIO_BY_INTENSITY.get(key, 0.016))

    def apply(self, response: DirectionResponse, result: DirectionCheckResult) -> None:
        result.is_shear_weight_passed = all((metric.shear_weight_ratio >= self.min_ratio for metric in response.metrics))

@dataclass(frozen=True)
class StiffnessChecker(DirectionChecker):
    adjacent_limit: float = 0.7
    average_limit: float = 0.8

    def apply(self, response: DirectionResponse, result: DirectionCheckResult) -> None:
        result.is_stiffness_passed = all((metric.stiffness_ratio_adjacent >= self.adjacent_limit and metric.stiffness_ratio_average >= self.average_limit for metric in response.metrics))

@dataclass(frozen=True)
class InterstoryDriftChecker(DirectionChecker):
    drift_limit: float = 0.001

    def apply(self, response: DirectionResponse, result: DirectionCheckResult) -> None:
        max_metric = max(response.metrics, key=lambda metric: metric.drift_max)
        result.max_interstory_drift_ratio = max_metric.drift_max
        result.max_interstory_drift_story = max_metric.story
        result.interstory_drift_limit = self.drift_limit
        result.is_interstory_drift_passed = max_metric.drift_max <= self.drift_limit

@dataclass(frozen=True)
class PeriodRatioChecker:
    limit_ratio: float = 0.9

    def apply(self, modal_summary: ModalSummary, result: OverallCheckResult) -> None:
        result.is_period_ratio_passed = modal_summary.period_ratio is not None and modal_summary.period_ratio < self.limit_ratio

@dataclass(frozen=True)
class WallULSChecker:

    def apply(self, wall_uls_metrics: list[WallULSMetric], result: OverallCheckResult) -> None:
        result.is_wall_axial_passed = all((metric.is_axial_passed for metric in wall_uls_metrics))
        result.is_wall_shear_pressure_passed = all((metric.is_shear_pressure_passed for metric in wall_uls_metrics))

@dataclass(frozen=True)
class BeamShearPressureChecker:

    def apply(self, beam_uls_metrics: list[BeamULSMetric], result: OverallCheckResult) -> None:
        result.is_beam_shear_pressure_passed = all((metric.is_shear_pressure_passed for metric in beam_uls_metrics))
