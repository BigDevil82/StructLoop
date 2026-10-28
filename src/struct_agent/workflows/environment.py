"""Small, mock-only state machine with explicit approval and one evaluation gate."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from struct_agent.io.artifacts import write_json
from struct_agent.schemas.state import Decision, DecisionEvent, DesignState, MockCase
from struct_agent.services.analysis import AnalysisService


class MockDesignEnv:
    def __init__(self, case: MockCase, service: AnalysisService, directory: Path) -> None:
        if getattr(service.solver, "fidelity", None) != "mock" or service.records:
            raise ValueError("Mock workflow requires a fresh mock analysis service")
        self.case, self.service, self.directory = case, service, directory
        self.layouts = {item.layout_id: item for item in case.layouts}
        self.candidates = {key: tuple(d for d in case.designs if d.layout_id == key)
                           for key in self.layouts}
        self.state = DesignState(case_id=case.case_id, fidelity="mock",
            current_layout_id=case.initial_layout_id, fea_budget=service.budget,
            candidate_cursors={key: 0 for key in self.layouts})
        (directory / "states").mkdir(exist_ok=False)
        (directory / "events.jsonl").touch(exist_ok=False)
        write_json(directory / "states/state_00000.json", self.state.model_dump())

    def has_candidate(self) -> bool:
        key = self.state.current_layout_id
        return self.state.candidate_cursors[key] < len(self.candidates[key])

    def unvisited_layouts(self) -> tuple[str, ...]:
        return tuple(key for key, cursor in self.state.candidate_cursors.items()
                     if cursor == 0 and key != self.state.current_layout_id)

    def step(self, decision: Decision) -> DesignState:
        state = self.state
        if state.status != "RUNNING":
            raise ValueError(f"Cannot decide in state {state.status}")
        expected = (state.latest_analysis_ref,) if state.latest_analysis_ref else ()
        if decision.evidence_refs != expected:
            raise ValueError("Decision must cite the current analysis evidence")
        failed = state.solver_status not in ("SUCCESS", "NOT_EVALUATED")
        if failed and decision.action != "REQUEST_HUMAN_REVIEW":
            raise ValueError("Solver failure requires review, not structural infeasibility")
        changes: dict[str, Any] = {}
        analysis_ref = None
        before_calls = len(self.service.records)
        if decision.action == "CONTINUE_OPTIMIZATION":
            if not self.has_candidate() or state.fea_budget_remaining < 1:
                raise ValueError("No candidate or evaluation budget remaining")
            key = state.current_layout_id
            design = self.candidates[key][state.candidate_cursors[key]]
            record = self.service.evaluate(self.layouts[key], design, self.case.spec)
            analysis_ref = f"analyses/{record.evaluation_id}.json"
            score = float(record.raw["mock_score"]) if record.status == "SUCCESS" else None
            changes = {"current_design_id": design.design_id, "solver_status": record.status,
                "feasible": record.feasible, "latest_analysis_ref": analysis_ref,
                "current_objective": score, "constraint_ratios": record.raw.get("constraint_ratios", {}),
                "fea_calls_used": len(self.service.records),
                "candidate_cursors": {**state.candidate_cursors, key: state.candidate_cursors[key] + 1}}
            if record.feasible and (state.best_feasible_objective is None or score < state.best_feasible_objective):
                changes.update(best_feasible_objective=score, best_feasible_design_id=design.design_id)
        elif decision.action == "SWITCH_LAYOUT":
            if state.solver_status != "SUCCESS" or state.feasible is not False:
                raise ValueError("Switch requires a successful, mock-infeasible evaluation")
            if decision.target_layout_id not in self.unvisited_layouts() or state.fea_budget_remaining < 1:
                raise ValueError("Unknown/visited target or exhausted budget")
            changes = {"status": "WAITING_APPROVAL", "pending_layout_id": decision.target_layout_id}
        elif decision.action == "REQUEST_HUMAN_REVIEW":
            changes = {"status": "AWAITING_REVIEW"}
        elif decision.action == "FINALIZE":
            if state.feasible is True:
                status = "COMPLETED"
            elif state.fea_budget_remaining == 0:
                status = "BUDGET_EXHAUSTED"
            elif not self.has_candidate():
                status = "NO_MORE_CANDIDATES"
            else:
                raise ValueError("Cannot finalize before a stopping condition")
            changes = {"status": status}
        return self._record(changes, kind="decision", decision=decision, reviewer=None,
                            analysis_ref=analysis_ref, delta=len(self.service.records) - before_calls)

    def approve_mock_layout(self, layout_id: str, *, reviewer: str) -> DesignState:
        """Explicit simulation approval only; not an engineering sign-off."""
        if self.state.status != "WAITING_APPROVAL" or layout_id != self.state.pending_layout_id:
            raise ValueError("Approval must match the pending layout")
        if not reviewer.strip():
            raise ValueError("Approval requires an identified simulation reviewer")
        return self._record({"status": "RUNNING", "current_layout_id": layout_id,
            "pending_layout_id": None, "current_design_id": None, "solver_status": "NOT_EVALUATED",
            "feasible": None, "latest_analysis_ref": None, "current_objective": None,
            "constraint_ratios": {}}, kind="mock_approval", decision=None, reviewer=reviewer,
            analysis_ref=None, delta=0)

    def _record(self, changes: dict[str, Any], *, kind: Literal["decision", "mock_approval"], decision: Decision | None,
                reviewer: str | None, analysis_ref: str | None, delta: int) -> DesignState:
        after = DesignState.model_validate({**self.state.model_dump(), **changes,
                                           "event_count": self.state.event_count + 1})
        event = DecisionEvent(event_id=f"event_{after.event_count:05d}", kind=kind,
            decision=decision, reviewer=reviewer, before=self.state, after=after,
            analysis_ref=analysis_ref, fea_calls_delta=delta)
        write_json(self.directory / f"states/state_{after.event_count:05d}.json", after.model_dump())
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json() + "\n")
        self.state = after
        return after
