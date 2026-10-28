"""Member evidence in global XY metres, N, Pa; ratios are dimensionless."""
from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, model_validator
from .base import Contract


class MemberDiagnostic(Contract):
    native_id: int = Field(ge=0)
    member_id: str
    role: Literal["wall", "primary", "secondary"]
    story: int = Field(ge=1)
    start_m: tuple[float, float]
    end_m: tuple[float, float]
    length_m: float = Field(gt=0.)
    width_m: float = Field(gt=0.)
    depth_m: float = Field(gt=0.)
    concrete_grade: str
    fc_pa: float = Field(gt=0.)
    beta_c: float = Field(gt=0.)
    shear_n: float = Field(ge=0.)
    denominator_n: float = Field(gt=0.)
    shear_ratio: float = Field(ge=0.)
    shear_limit: float = Field(gt=0.)
    control_combo: str
    control_combo_type: Literal["Seismic", "NonSeismic"]
    combo_shear_n: dict[str, float]
    combo_shear_limits: dict[str, float]
    shear_passed: bool
    reinforcement_checked: bool
    reinforcement_passed: bool | None
    reinforcement_messages: tuple[str, ...] = ()

    @property
    def utilization(self) -> float:
        return self.shear_ratio / self.shear_limit

    @property
    def absolute_combo_shear_n(self) -> float:
        """Diagnostic comparison only, does not replace the native selected force."""
        return max((abs(x) for x in self.combo_shear_n.values()), default=0.)

    @model_validator(mode="after")
    def consistent(self) -> MemberDiagnostic:
        if not math.isclose(self.shear_n / self.denominator_n, self.shear_ratio, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("Member force/denominator does not reproduce native shear ratio")
        if self.shear_passed != (self.shear_ratio <= self.shear_limit):
            raise ValueError("Member shear pass flag disagrees with native ratio/limit")
        if self.reinforcement_checked != (self.reinforcement_passed is not None):
            raise ValueError("Absent reinforcement check must have unknown pass status")
        if self.control_combo not in self.combo_shear_n:
            raise ValueError("Control combination missing from force data")
        if self.combo_shear_n.keys() != self.combo_shear_limits.keys() or any(v <= 0 for v in self.combo_shear_limits.values()):
            raise ValueError("Each combination requires its own positive shear limit")
        if self.shear_limit != self.combo_shear_limits[self.control_combo] or not math.isclose(self.shear_n, abs(self.combo_shear_n[self.control_combo]), rel_tol=1e-9, abs_tol=1e-8):
            raise ValueError("Selected shear and limit must belong to the controlling combination")
        worst = max(abs(v)/self.denominator_n/self.combo_shear_limits[k] for k,v in self.combo_shear_n.items())
        if not math.isclose(self.utilization, worst, rel_tol=1e-9, abs_tol=1e-8):
            raise ValueError("Selected combination must govern utilization across all limits")
        return self
