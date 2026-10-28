"""Validated aggregate response of the retained OpenSees analysis pipeline."""
from typing import Literal

from pydantic import Field

from .base import Contract


class NativeResponse(Contract):
    """Ratios dimensionless, periods s, mass t, material quantities kg.

    The stiffness flag covers both adjacent/average-storey rules; only the
    adjacent minimum is exposed by upstream. Preserve the aggregate flag.
    This is the native check scope, not a declaration of full code compliance.
    """
    converged: Literal[True]
    feasible: bool
    design_passed: bool
    design_failed_beam_count: int = Field(ge=0)
    design_failed_wall_count: int = Field(ge=0)
    material_concrete_kg: float = Field(ge=0.)
    material_steel_kg: float = Field(ge=0.)
    mass_total_t: float = Field(gt=0.)
    T1: float = Field(gt=0.)
    T2: float = Field(gt=0.)
    T3: float = Field(gt=0.)
    T4: float | None
    T5: float | None
    T6: float | None
    period_ratio: float
    torsion_ratio: float
    min_shear_weight_ratio: float
    max_drift_ratio: float
    min_stiffness_ratio: float
    max_wall_axial_ratio: float
    max_wall_axial_limit: float = Field(gt=0.)
    max_wall_shear_ratio: float
    max_wall_shear_limit: float = Field(gt=0.)
    max_beam_shear_ratio: float
    max_beam_shear_limit: float = Field(gt=0.)
    period_ratio_available: Literal[True]
    torsion_passed: bool
    shear_weight_passed: bool
    stiffness_passed: bool
    drift_passed: bool
    period_ratio_passed: bool
    wall_axial_passed: bool
    wall_shear_passed: bool
    beam_shear_passed: bool
    error: Literal[""]
