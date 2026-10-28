"""One budget/cache/recording gate for every actual solver call."""
from __future__ import annotations

import hashlib
from pathlib import Path

from struct_agent.adapters.fea import Solver
from struct_agent.io.artifacts import write_json
from struct_agent.schemas import AnalysisRecord, DesignCandidate, LayoutCandidate, ProjectSpec


class BudgetExhausted(RuntimeError):
    pass


class AnalysisFailed(RuntimeError):
    def __init__(self, record: AnalysisRecord) -> None:
        self.record = record
        super().__init__(f"{record.status}: {record.error.error_type}: {record.error.message}")


class AnalysisService:
    def __init__(self, solver: Solver, *, budget: int, directory: Path) -> None:
        if budget < 1:
            raise ValueError("Positive FEA budget required")
        directory.mkdir(parents=True, exist_ok=False)
        self.solver, self.budget, self.directory = solver, budget, directory
        self.records: list[AnalysisRecord] = []
        self.designs: list[DesignCandidate] = []
        self._cache: dict[str, AnalysisRecord] = {}

    def evaluate(self, layout: LayoutCandidate, design: DesignCandidate, spec: ProjectSpec) -> AnalysisRecord:
        design.validate_against(spec)
        if design.layout_id != layout.layout_id:
            raise ValueError("Design/layout mismatch")
        key = hashlib.sha256((layout.model_dump_json()+spec.model_dump_json()+str(sorted(design.values.items()))).encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]
        if len(self.records) >= self.budget:
            raise BudgetExhausted(f"FEA budget {self.budget} exhausted")
        evaluation_id = f"eval_{len(self.records)+1:05d}"
        # Every attempted call, including exceptions, must consume budget and retain context.
        try:
            record = self.solver.evaluate(layout, design, spec, evaluation_id=evaluation_id)
        except Exception as exc:
            import traceback
            from struct_agent.schemas import ErrorRecord
            record = AnalysisRecord(evaluation_id=evaluation_id, layout_id=layout.layout_id,
                condition_id=spec.condition_id, design_id=design.design_id, fidelity=getattr(self.solver,"fidelity","full"),
                status="SOLVER_ERROR", solver=type(self.solver).__name__, solver_version="unavailable",
                elapsed_s=0., feasible=None, raw={}, error=ErrorRecord(error_type=type(exc).__name__,
                    message=str(exc), traceback=traceback.format_exc(),
                    context={"layout_id":layout.layout_id, "condition_id":spec.condition_id}, attempt=1))
        record = record.model_copy(update={"input_hash":key})
        self.records.append(record)
        self.designs.append(design)
        self._cache[key] = record
        write_json(self.directory / f"{evaluation_id}.json", {"design":design.model_dump(), "analysis":record.model_dump()})
        return record
