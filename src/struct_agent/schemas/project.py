from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import Contract

VARIABLE_NAMES = ("tw_bot", "tw_mid", "tw_top", "hb_main", "bb_main", "hb_sec", "bb_sec", "conc_bot")


class DesignVariable(Contract):
    name: str
    unit: Literal["m", "grade"]
    values: tuple[float | str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def domain(self) -> DesignVariable:
        if self.name not in VARIABLE_NAMES:
            raise ValueError("Unsupported CASINO decision variable")
        if self.name == "conc_bot":
            if self.unit != "grade" or any(v not in ("C30", "C35", "C40", "C45", "C50") for v in self.values):
                raise ValueError("Unsupported concrete domain")
        elif self.unit != "m" or any(not isinstance(v, float) or v <= 0 for v in self.values):
            raise ValueError("Dimensions must be positive floats in m")
        if len(set(self.values)) != len(self.values):
            raise ValueError("Duplicate domain values")
        return self


class ProjectSpec(Contract):
    schema_version: Literal[1] = 1
    condition_id: str = Field(min_length=1)
    stories: int = Field(ge=3)
    story_height_m: Literal[2.9]
    slab_thickness_m: Literal[0.12]
    intensity: Literal[6.0, 7.0, 7.5, 8.0, 8.5, 9.0]
    site_class: Literal["I0", "I", "II", "III", "IV"]
    seismic_group: Literal[1, 2, 3]
    objective: Literal["upstream_material_cost_cny"]
    code_basis: str = Field(min_length=1)
    design_variables: tuple[DesignVariable, ...]

    @model_validator(mode="after")
    def complete(self) -> ProjectSpec:
        if sorted(v.name for v in self.design_variables) != sorted(VARIABLE_NAMES):
            raise ValueError("Explicitly define all 8 CASINO variables, once each")
        return self


class DesignCandidate(Contract):
    design_id: str = Field(min_length=1)
    layout_id: str = Field(min_length=1)
    condition_id: str = Field(min_length=1)
    values: dict[str, float | str]

    def validate_against(self, spec: ProjectSpec) -> None:
        if self.condition_id != spec.condition_id:
            raise ValueError("Design condition mismatch")
        if set(self.values) != {v.name for v in spec.design_variables}:
            raise ValueError("Decision keys mismatch")
        for var in spec.design_variables:
            if self.values[var.name] not in var.values:
                raise ValueError(f"Out-of-domain decision: {var.name}")
        if not self.values["tw_top"] <= self.values["tw_mid"] <= self.values["tw_bot"]:
            raise ValueError("Wall thickness must be non-increasing up the building")
