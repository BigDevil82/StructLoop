from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .base import Contract
from .response import NativeResponse


class ErrorRecord(Contract):
    error_type: str
    message: str
    traceback: str
    context: dict[str, str]
    attempt: int = Field(ge=1)


class AnalysisRecord(Contract):
    """Actual solver record; surrogate exclusions never produce this object."""
    evaluation_id: str
    layout_id: str
    condition_id: str
    design_id: str
    fidelity: Literal["full", "mock"]
    status: Literal["SUCCESS", "MODEL_ERROR", "SOLVER_ERROR", "INVALID_RESULT"]
    solver: str
    solver_version: str
    elapsed_s: float = Field(ge=0)
    feasible: bool | None
    raw: dict[str, Any]
    error: ErrorRecord | None
    input_hash: str | None = None
    solver_log: str | None = None

    @model_validator(mode="after")
    def failure_semantics(self) -> AnalysisRecord:
        if self.status != "SUCCESS" and (self.feasible is not None or self.error is None):
            raise ValueError("Failed analysis requires error and feasible=None")
        if self.status == "SUCCESS" and (self.feasible is None or self.error is not None):
            raise ValueError("Successful analysis requires feasibility and no error")
        if self.status == "SUCCESS" and self.fidelity == "full":
            response = NativeResponse.model_validate(self.raw)
            if self.feasible != (response.feasible and response.design_passed):
                raise ValueError("Feasibility disagrees with native check/design results")
        return self
