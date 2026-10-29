"""Deterministic execution gate around layout-bound CASINO sessions."""
from __future__ import annotations

import hashlib
import traceback
from pathlib import Path
from typing import Callable

from struct_agent.adapters.casino_session import CasinoSession
from struct_agent._vendor.shearwall_optimization.surrogate_candidate import SurrogateCandidateEvaluator
from struct_agent.io.artifacts import write_json
from struct_agent.schemas import ErrorRecord, LayoutCandidate
from struct_agent.schemas.agent import OptimizationState, validate_decision
from struct_agent.schemas.state import Action, Decision
from struct_agent.services.analysis import AnalysisService


class OptimizationEnvironment:
    """One shared FEA budget; new layout means new isolated calibration/session.

    Approvals are trusted application calls, never LLM tools. Disk snapshots are
    audit records; process restoration is not implemented here.
    """

    def __init__(self, case_id: str, layouts: tuple[LayoutCandidate, ...],
                 evaluator: AnalysisService, factory: Callable[[LayoutCandidate, Path], CasinoSession],
                 directory: Path) -> None:
        if not layouts or len({x.layout_id for x in layouts}) != len(layouts):
            raise ValueError("A nonempty pool with unique layout IDs is required")
        self.layouts = {x.layout_id: x.model_copy(deep=True) for x in layouts}
        self.case_id, self.evaluator, self.factory, self.directory = case_id, evaluator, factory, directory
        (directory / "events").mkdir(parents=True, exist_ok=False)
        self.sessions: dict[str, CasinoSession] = {}
        self.layout_id = layouts[0].layout_id
        self.status = "RUNNING"
        self.pending: str | None = None
        self.history: list[Action] = []
        self.stagnation = 0
        self.event_count = 0
        self.execution_error: ErrorRecord | None = None

    def _session(self) -> CasinoSession:
        if self.layout_id not in self.sessions:
            self.sessions[self.layout_id] = self.factory(self.layouts[self.layout_id],
                self.directory / f"sessions/session_{len(self.sessions):03d}")
        return self.sessions[self.layout_id]

    def observe(self) -> OptimizationState:
        session = self.sessions.get(self.layout_id)
        summary = session.summary() if session else {}
        rows = session.optimizer.problem.results if session else []
        best = min(rows, key=lambda row: SurrogateCandidateEvaluator.rank_key(row[1]), default=None)
        feasible = [r.objectives["material_cost"] for s in self.sessions.values()
                    for _, r in s.optimizer.problem.results if r.feasible]
        records = [r for r in self.evaluator.records if r.layout_id == self.layout_id]
        latest = records[-1] if records else None
        remaining = self.evaluator.budget - len(self.evaluator.records)
        status = "optimizer_failed" if self.execution_error else summary.get("termination", "ready")
        available = tuple(k for k in self.layouts if k != self.layout_id and k not in self.sessions)
        allowed = ["REQUEST_HUMAN_REVIEW"]
        failed = status in ("analysis_failed", "optimizer_failed") or (latest and latest.status != "SUCCESS")
        if self.status == "RUNNING" and not failed:
            if remaining and status in ("ready", "paused"):
                allowed.insert(0, "CONTINUE_OPTIMIZATION")
            if remaining and available and latest and latest.status == "SUCCESS" and not latest.feasible:
                allowed.append("SWITCH_LAYOUT")
            if not remaining or status in ("completed", "budget_exhausted"):
                allowed.append("FINALIZE")
        refs = [str((self.evaluator.directory / f"{r.evaluation_id}.json").relative_to(self.directory)).replace("\\", "/") for r in records]
        if session and session.advance_count:
            refs.append((session.directory / f"steps/advance_{session.advance_count:05d}.json").relative_to(self.directory).as_posix())
        if self.execution_error:
            refs.append("execution_error.json")
        return OptimizationState(case_id=self.case_id, fidelity=getattr(self.evaluator.solver, "fidelity", "full"),
            layout_id=self.layout_id, session_status=status,
            solver_status=latest.status if latest else "NOT_EVALUATED",
            latest_feasible=latest.feasible if latest else None,
            fea_budget=self.evaluator.budget, fea_calls_used=len(self.evaluator.records), fea_budget_remaining=remaining,
            completed_generations=summary.get("completed_generations", 0),
            best_feasible_cost=float(min(feasible)) if feasible else None,
            current_best_objective=float(best[1].objective) if best else None,
            current_best_violation=float(best[1].objectives.get("violation_score", best[1].objective)) if best else None,
            current_best_feasible=best[1].feasible if best else None,
            normalized_violations={k: float(v) for k, v in best[1].metrics.get("normalized_violations", {}).items()} if best else {},
            stagnation_steps=self.stagnation, calibration_samples=summary.get("local_calibration_samples", 0),
            available_layouts=available, allowed_actions=tuple(allowed), evidence_refs=tuple(refs),
            action_history=tuple(self.history))

    def step(self, decision: Decision) -> OptimizationState:
        if self.status != "RUNNING":
            raise RuntimeError(f"Cannot execute while {self.status}")
        before = self.observe()
        validate_decision(decision, before)
        if decision.action == "CONTINUE_OPTIMIZATION":
            session = None
            try:
                session = self._session()
                session.advance(1)
            except Exception as exc:
                # CasinoSession records full typed exception/traceback before raising.
                if session is None or session.status != "optimizer_failed":
                    self.execution_error = ErrorRecord(error_type=type(exc).__name__, message=str(exc),
                        traceback=traceback.format_exc(), context={"layout_id": self.layout_id,
                        "phase": "session_creation_or_advance"}, attempt=1)
                    write_json(self.directory / "execution_error.json", self.execution_error.model_dump())
            after = self.observe()
            def progress(state: OptimizationState) -> tuple[bool, float, float]:
                return (not state.current_best_feasible,
                    0.0 if state.current_best_feasible else float(state.current_best_violation or 0.),
                    float(state.current_best_objective or 0.))
            improved = after.current_best_objective is not None and (
                before.current_best_objective is None or progress(after) < progress(before))
            self.stagnation = 0 if improved else self.stagnation + 1
        elif decision.action == "SWITCH_LAYOUT":
            self.pending, self.status = decision.target_layout_id, "WAITING_APPROVAL"
        elif decision.action == "REQUEST_HUMAN_REVIEW":
            self.status = "AWAITING_REVIEW"
        else:
            self.status = "COMPLETED"
        self.history.append(decision.action)
        after = self.observe()
        self._event({"decision": decision.model_dump(), "before": before.model_dump(), "after": after.model_dump(),
            "status": self.status, "approval_required": decision.action == "SWITCH_LAYOUT",
            "fea_attempts_delta": after.fea_calls_used - before.fea_calls_used,
            "objective_delta": None if before.current_best_objective is None or after.current_best_objective is None
                else before.current_best_objective - after.current_best_objective,
            "violation_delta": None if before.current_best_violation is None or after.current_best_violation is None
                else before.current_best_violation - after.current_best_violation})
        return after

    def approve_layout(self, layout_id: str, *, reviewer: str, expected_sha256: str) -> None:
        if self.status != "WAITING_APPROVAL" or self.pending != layout_id or not reviewer.strip():
            raise ValueError("Approval must name the pending candidate and reviewer")
        digest = hashlib.sha256(self.layouts[layout_id].model_dump_json().encode()).hexdigest()
        if digest != expected_sha256:
            raise ValueError("Approval geometry hash mismatch")
        self._event({"approval": "APPROVED", "layout_id": layout_id, "layout_sha256": digest, "reviewer": reviewer})
        self.layout_id, self.pending, self.status, self.stagnation = layout_id, None, "RUNNING", 0

    def _event(self, value: dict) -> None:
        self.event_count += 1
        write_json(self.directory / f"events/event_{self.event_count:05d}.json", value)

    def summary(self) -> dict:
        return {"status": self.status, "state": self.observe().model_dump(), "pending_layout": self.pending,
                "pending_layout_sha256": hashlib.sha256(self.layouts[self.pending].model_dump_json().encode()).hexdigest()
                    if self.pending else None,
                "sessions": {k: s.summary() for k, s in self.sessions.items()},
                "solver_failures": sum(r.status != "SUCCESS" for r in self.evaluator.records),
                "execution_error": self.execution_error.model_dump() if self.execution_error else None,
                "engineering_review": "PENDING"}
