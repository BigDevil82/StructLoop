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
    control_combo_available: bool
    control_combo_type: Literal["Seismic", "NonSeismic"]
    combo_shear_n: dict[str, float]
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
        if self.control_combo_available != (self.control_combo in self.combo_shear_n):
            raise ValueError("Control-combination availability disagrees with original force data")
        if not self.control_combo_available and (self.control_combo or self.shear_n != 0.):
            raise ValueError("Only the native empty-combination zero envelope may be absent")
        return self
