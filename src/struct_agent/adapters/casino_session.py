"""A layout-bound CASINO session with immutable per-advance audit snapshots."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import logging
from pathlib import Path
import traceback
from typing import Any

from struct_agent.io.artifacts import sha256, write_json
from struct_agent.schemas import ErrorRecord, LayoutCandidate, ProjectSpec, RoomGraph
from struct_agent.services.analysis import AnalysisFailed, AnalysisService, BudgetExhausted
from .casino import CasinoConfig, create_optimizer
from struct_agent._vendor.shearwall_optimization.algorithms.evolution import IncrementalGA

logger = logging.getLogger(__name__)


class CasinoSession:
    """Continue the same layout in-process; use a NEW session when layout/conditions change.

    JSON snapshots are audit artifacts, not executable/pickle checkpoints. No disk
    restoration or mid-generation retry is supported in this first implementation.
    """

    def __init__(self, layout: LayoutCandidate, rooms: RoomGraph, spec: ProjectSpec,
                 evaluator: AnalysisService, cfg: CasinoConfig, *, directory: Path) -> None:
        layout, rooms, spec = (item.model_copy(deep=True) for item in (layout, rooms, spec))
        self.directory, self.evaluator = directory, evaluator
        self.optimizer = create_optimizer(layout, rooms, spec, evaluator, cfg, directory=directory)
        self.engine = IncrementalGA(self.optimizer)
        self.status = "ready"
        self.error: ErrorRecord | None = None
        self.advance_count = 0
        self.session_fea_attempts = 0
        self.binding = {"layout_id": layout.layout_id, "condition_id": spec.condition_id,
            "layout_sha256": hashlib.sha256(layout.model_dump_json().encode()).hexdigest(),
            "rooms_sha256": hashlib.sha256(rooms.model_dump_json().encode()).hexdigest(),
            "spec_sha256": hashlib.sha256(spec.model_dump_json().encode()).hexdigest()}
        (directory / "steps").mkdir()
        for name, value in (("layout", layout), ("rooms", rooms), ("spec", spec)):
            write_json(directory / f"{name}.json", value.model_dump())
        write_json(directory / "session.json", {**self.binding, "config": cfg.model_dump(mode="json"),
            "fidelity": getattr(evaluator.solver, "fidelity", "full"),
            "weights_sha256": {k: sha256(p) for k, p in (("feasibility", cfg.feasibility_weights), ("steel", cfg.steel_weights))
                               if cfg.use_surrogate and p is not None},
            "upstream_random_seeds": {"exploration": 20260621, "calibration": 0},
            "resume_scope": "in_process_generation_boundary"})

    def advance(self, generations: int = 1) -> dict[str, Any]:
        if type(generations) is not int or generations < 1:
            raise ValueError("Positive integer generation count required")
        if self.status not in ("ready", "paused"):
            raise RuntimeError(f"Cannot advance session with status {self.status}")
        before = len(self.evaluator.records)
        self.advance_count += 1
        unexpected: Exception | None = None
        try:
            self.engine.advance(generations)
            self.status = self.engine.status
        except BudgetExhausted as exc:
            self.status = "budget_exhausted"
            self.error = self._error(exc)
        except AnalysisFailed as exc:
            self.status = "analysis_failed"
            self.error = exc.record.error
        except Exception as exc:
            self.status = "optimizer_failed"
            self.error = self._error(exc)
            unexpected = exc
        delta = len(self.evaluator.records) - before
        self.session_fea_attempts += delta
        summary = self.summary()
        calibration = self.optimizer.evaluator.local_calibrator
        snapshot = {"summary": summary, "requested_generations": generations, "fea_attempts_delta": delta,
            "population": None if self.engine.scored is None else [
                {"decision": x, "evaluation": asdict(result)} for x, result in self.engine.scored],
            "history": self.engine.history,
            "rng_states": {"ga": self.optimizer.rng.getstate(), "sampling": self.optimizer.problem.rng.getstate(),
                           "exploration": self.optimizer.evaluator._rng.getstate()},
            "calibration_records": list(calibration._records.values()),
            "has_seen_feasible": self.optimizer.evaluator._has_seen_feasible,
            "error": None if self.error is None else self.error.model_dump()}
        write_json(self.directory / f"steps/advance_{self.advance_count:05d}.json", snapshot)
        if self.status not in ("ready", "paused"):
            write_json(self.directory / "history.json", self.engine.history)
            write_json(self.directory / "summary.json", summary)
        logger.info("CASINO advance=%d status=%s generations=%d evaluations_delta=%d",
                    self.advance_count, self.status, self.engine.completed_generations, delta)
        if unexpected is not None:
            raise unexpected
        return summary

    def _error(self, exc: Exception) -> ErrorRecord:
        return ErrorRecord(error_type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc(),
            context={"layout_id": self.binding["layout_id"], "condition_id": self.binding["condition_id"],
                     "advance": str(self.advance_count)}, attempt=1)

    def summary(self) -> dict[str, Any]:
        """Diagnostics only: do not trigger extra model fitting at pause boundaries."""
        best = min(self.optimizer.problem.results, key=lambda row: self.optimizer._rank_key(row[1]), default=None)
        local = self.optimizer.evaluator.local_calibrator
        return {**self.binding, "termination": self.status,
            "completed_generations": self.engine.completed_generations,
            "recorded_generations": len(self.engine.history), "advance_count": self.advance_count,
            "fea_attempts": self.session_fea_attempts, "global_fea_attempts": len(self.evaluator.records),
            "fea_budget_remaining": self.evaluator.budget - len(self.evaluator.records),
            "best_design": None if best is None else best[0].model_dump(),
            "best_feasible": None if best is None else best[1].feasible,
            "best_objectives": None if best is None else best[1].objectives,
            "local_calibration_samples": local.sample_count, "calibration_fit_pending": local._dirty,
            "local_feasibility_model": "platt" if local._feas_model is not None else "global",
            "local_steel_model": local._steel_model_name, "history_complete": self.status == "completed",
            "fidelity": getattr(self.evaluator.solver, "fidelity", "full"), "engineering_review": "PENDING",
            "error": None if self.error is None else self.error.model_dump()}
