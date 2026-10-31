"""Deterministic execution gate around layout-bound CASINO sessions."""
from __future__ import annotations

import hashlib
import json
import math
import traceback
from pathlib import Path
from typing import Callable

from struct_agent.adapters.casino_session import CasinoSession
from struct_agent.adapters.casino import CasinoProblem
from struct_agent.adapters.design_search import local_layout_candidates
from struct_agent._vendor.shearwall_optimization.surrogate_candidate import SurrogateCandidateEvaluator
from struct_agent.io.artifacts import write_json
from struct_agent.schemas import ErrorRecord, LayoutCandidate, DesignCandidate, ProjectSpec, RoomGraph
from struct_agent.schemas.agent import (OptimizationState, validate_decision, LocalAdjustmentConfig,
    LocalLayoutChoice, LocalAdjustmentOutcome)
from struct_agent.schemas.layout import LocalLayoutProposal
from struct_agent.schemas.state import Action, Decision
from struct_agent.services.analysis import AnalysisService, AnalysisFailed
from struct_agent.services.diagnostics import load_members
from struct_agent.services.model_review import review_geometry, review_local_layout_change


class OptimizationEnvironment:
    """One shared FEA budget; new layout means new isolated calibration/session.

    Approvals are trusted application calls, never LLM tools. Disk snapshots are
    audit records; process restoration is not implemented here.
    """

    def __init__(self, case_id: str, layouts: tuple[LayoutCandidate, ...],
                 evaluator: AnalysisService, factory: Callable[[LayoutCandidate, Path], CasinoSession],
                 directory: Path, *, rooms: RoomGraph | None=None, spec: ProjectSpec | None=None,
                 local_config: LocalAdjustmentConfig | None=None) -> None:
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
        self.rooms,self.spec,self.local_config=rooms,spec,local_config
        if local_config is not None and (rooms is None or spec is None
                or getattr(evaluator.solver,'diagnostics_directory',None) is None):
            raise ValueError('Local adjustment requires rooms, conditions and member diagnostics')
        self.verified_results: dict[str,list[tuple]] = {}
        self.local_proposals: dict[str,LocalLayoutProposal] = {}
        self.local_outcomes: list[LocalAdjustmentOutcome] = []
        self.local_tried: set[str] = set()
        self.visited={self.layout_id}
        self.local_source: tuple | None = None
        self.local_ref: str | None = None
        if local_config is not None:
            (directory/'local').mkdir(exist_ok=False)
            write_json(directory/'local/authorization.json',{'config':local_config.model_dump(),
                'root_layout_sha256':{k:hashlib.sha256(v.model_dump_json().encode()).hexdigest() for k,v in self.layouts.items()},
                'rooms_sha256':hashlib.sha256(rooms.model_dump_json().encode()).hexdigest(),
                'spec_sha256':hashlib.sha256(spec.model_dump_json().encode()).hexdigest(),
                'scope':'bounded local exploratory FEA; no member retyping or engineering release'})

    def _session(self) -> CasinoSession:
        if self.layout_id not in self.sessions:
            self.sessions[self.layout_id] = self.factory(self.layouts[self.layout_id],
                self.directory / f"sessions/session_{len(self.sessions):03d}")
            rows=self.verified_results.get(self.layout_id,[])
            if rows:
                self.sessions[self.layout_id].seed_verified_design(*min(rows,key=lambda row:SurrogateCandidateEvaluator.rank_key(row[1])))
        return self.sessions[self.layout_id]

    def observe(self) -> OptimizationState:
        session = self.sessions.get(self.layout_id)
        summary = session.summary() if session else {}
        rows = (session.optimizer.problem.results if session else [])+self.verified_results.get(self.layout_id,[])
        best = min(rows, key=lambda row: SurrogateCandidateEvaluator.rank_key(row[1]), default=None)
        feasible = [r.objectives["material_cost"] for s in self.sessions.values()
                    for _, r in s.optimizer.problem.results if r.feasible]
        feasible += [r.objectives['material_cost'] for rows in self.verified_results.values() for _,r in rows if r.feasible]
        records = [r for r in self.evaluator.records if r.layout_id == self.layout_id]
        latest = records[-1] if records else None
        remaining = self.evaluator.budget - len(self.evaluator.records)
        status = "optimizer_failed" if self.execution_error else summary.get("termination", "ready")
        available = tuple(k for k in self.layouts if k not in self.visited)
        allowed = ["REQUEST_HUMAN_REVIEW"]
        failed = status in ("analysis_failed", "optimizer_failed") or (latest and latest.status != "SUCCESS")
        if self.status == "RUNNING" and not failed:
            if remaining and status in ("ready", "paused"):
                allowed.insert(0, "CONTINUE_OPTIMIZATION")
            if remaining and available and latest and latest.status == "SUCCESS" and not latest.feasible:
                allowed.append("SWITCH_LAYOUT")
            if remaining and self.local_proposals and self.local_config and len(self.local_outcomes)<self.local_config.max_trials:
                allowed.append('ADJUST_LOCAL_LAYOUT')
            if not remaining or status in ("completed", "budget_exhausted"):
                allowed.append("FINALIZE")
        refs = [str((self.evaluator.directory / f"{r.evaluation_id}.json").relative_to(self.directory)).replace("\\", "/") for r in records]
        if session and session.advance_count:
            refs.append((session.directory / f"steps/advance_{session.advance_count:05d}.json").relative_to(self.directory).as_posix())
        if self.execution_error:
            refs.append("execution_error.json")
        if self.local_ref:
            refs.append(self.local_ref)
        if self.local_config:
            refs.append('local/authorization.json')
        refs.extend(o.evidence_ref for o in self.local_outcomes)
        refs=list(dict.fromkeys(refs))
        response={}
        if best and self.local_config:
            raw=self._source_record(best[0]).raw
            response={k:float(raw[k]) for k in ('max_drift_ratio','torsion_ratio','period_ratio','material_concrete_kg','material_steel_kg')}
            response.update(max_beam_utilization=float(raw['max_beam_shear_ratio']/raw['max_beam_shear_limit']),
                max_wall_utilization=float(raw['max_wall_shear_ratio']/raw['max_wall_shear_limit']))
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
            action_history=tuple(self.history),local_adjustment_enabled=self.local_config is not None,
            local_trials_used=len(self.local_outcomes),
            local_trials_remaining=max(0,self.local_config.max_trials-len(self.local_outcomes)) if self.local_config else 0,
            local_target_utilization=self.local_config.target_utilization if self.local_config else None,
            current_response=response,local_layout_choices=tuple(LocalLayoutChoice(candidate_id=p.layout.layout_id,
                control_member_id=p.control_member_id,control_story=p.control_story,metric=p.metric,
                control_utilization=p.control_utilization,operation=p.operation,
                displacement_m=math.dist(p.move.before_m,p.move.after_m),reason=p.reason,evidence_ref=self.local_ref)
                for p in self.local_proposals.values()),local_adjustment_history=tuple(self.local_outcomes))

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
        elif decision.action=='ADJUST_LOCAL_LAYOUT':
            try:
                self._adjust_local(decision.target_layout_id)
            except Exception as exc:
                self._execution_failure(exc,'local_adjustment')
        elif decision.action == "REQUEST_HUMAN_REVIEW":
            self.status = "AWAITING_REVIEW"
        else:
            self.status = "COMPLETED"
        self.history.append(decision.action)
        if self.local_config and self.status=='RUNNING' and not self.execution_error:
            try:
                self._refresh_local()
            except Exception as exc:
                self._execution_failure(exc,'local_candidate_generation')
        after = self.observe()
        self._event({"decision": decision.model_dump(), "before": before.model_dump(), "after": after.model_dump(),
            "status": self.status, "approval_required": decision.action == "SWITCH_LAYOUT",
            "fea_attempts_delta": after.fea_calls_used - before.fea_calls_used,
            "objective_delta": None if before.current_best_objective is None or after.current_best_objective is None
                else before.current_best_objective - after.current_best_objective,
            "violation_delta": None if before.current_best_violation is None or after.current_best_violation is None
                else before.current_best_violation - after.current_best_violation})
        return after

    def _source_record(self, design: DesignCandidate):
        return next(r for r,d in reversed(list(zip(self.evaluator.records,self.evaluator.designs)))
            if r.layout_id==design.layout_id and d.values==design.values)

    @staticmethod
    def _trial_key(layout: LayoutCandidate, design: DesignCandidate) -> str:
        """Ignore layout names to prevent cycles through equivalent geometry."""
        return hashlib.sha256(json.dumps({'members':[m.model_dump() for m in layout.members],
            'slabs':layout.slabs,'values':design.values},sort_keys=True).encode()).hexdigest()

    def _evaluate_design(self, layout: LayoutCandidate, design: DesignCandidate) -> tuple:
        problem=CasinoProblem(layout,self.spec,self.evaluator,layout_path=Path('unused'),seed=42)
        native={k:round(float(v)*1000) if k!='conc_bot' else v for k,v in design.values.items()}
        result=problem.evaluate(native)
        actual=problem.results[-1][0]
        return actual,result,self._source_record(actual)

    def initialize_design(self, design: DesignCandidate) -> OptimizationState:
        """One operator-supplied initial evaluation before policy decisions."""
        if not self.local_config or self.history or self.evaluator.records or self.verified_results:
            raise ValueError('Initial local-loop evaluation requires enabled, unevaluated environment')
        design.validate_against(self.spec)
        if design.layout_id!=self.layout_id:
            raise ValueError('Initial design/layout mismatch')
        if review_geometry(self.layouts[self.layout_id],design=design).requires_model_repair:
            raise ValueError('Initial layout requires preprocessing before optimization')
        before=self.observe()
        try:
            actual,result,_=self._evaluate_design(self.layouts[self.layout_id],design)
            self.verified_results[self.layout_id]=[(actual,result)]
            self._refresh_local()
        except Exception as exc:
            self._execution_failure(exc,'initial_design')
        after=self.observe()
        self._event({'initial_design':design.model_dump(),'before':before.model_dump(),'after':after.model_dump(),
            'fea_attempts_delta':after.fea_calls_used-before.fea_calls_used})
        return after

    def _refresh_local(self) -> None:
        self.local_proposals={};self.local_source=None;self.local_ref=None
        if len(self.local_outcomes)>=self.local_config.max_trials or len(self.evaluator.records)>=self.evaluator.budget:
            return
        session=self.sessions.get(self.layout_id)
        rows=(session.optimizer.problem.results if session else [])+self.verified_results.get(self.layout_id,[])
        if not rows:return
        design,result=min(rows,key=lambda row:SurrogateCandidateEvaluator.rank_key(row[1]))
        record=self._source_record(design)
        if record.status!='SUCCESS':return
        directory=self.evaluator.solver.diagnostics_directory/record.evaluation_id
        members=load_members(directory/'members.json',expected_fidelity=record.fidelity)
        search=local_layout_candidates(self.layouts[self.layout_id],self.rooms,design,members,
            steps_m=self.local_config.steps_m,target_utilization=self.local_config.target_utilization,
            max_candidates=self.local_config.max_candidates,
            protected_member_ids=frozenset(self.local_config.protected_member_ids))
        self.local_tried.add(self._trial_key(self.layouts[self.layout_id],design))
        self.local_proposals={p.layout.layout_id:p for p in search.proposals
            if self._trial_key(p.layout,design) not in self.local_tried}
        self.local_source=(design,result,record)
        self.local_ref=f'local/proposals_{record.evaluation_id}.json'
        path=self.directory/self.local_ref
        if not path.exists():
            write_json(path,{'parent_layout_id':self.layout_id,'source_analysis':record.model_dump(),
                'source_design':design.model_dump(),'search':search.model_dump()})

    def _adjust_local(self, candidate_id: str) -> None:
        proposal=self.local_proposals[candidate_id]
        design,baseline,source=self.local_source
        parent=self.layouts[self.layout_id]
        if (proposal.parent_layout_sha256!=hashlib.sha256(parent.model_dump_json().encode()).hexdigest()
                or proposal.room_graph_sha256!=hashlib.sha256(self.rooms.model_dump_json().encode()).hexdigest()
                or design.layout_id!=self.layout_id):
            raise ValueError('Local proposal binding changed; no FEA executed')
        issues=review_local_layout_change(parent,proposal.layout,self.rooms,design=design)
        changed={a.member_id for a,b in zip(parent.members,proposal.layout.members) if a!=b}
        if issues or changed&set(self.local_config.protected_member_ids):
            raise ValueError(f'Local candidate failed execution checks: {issues}')
        key=self._trial_key(proposal.layout,design)
        if key in self.local_tried:raise ValueError('Local geometry/design already tried')
        self.local_tried.add(key)
        next_design=design.model_copy(update={'layout_id':candidate_id})
        accepted=False;result=None;control_after=None
        try:
            actual,result,record=self._evaluate_design(proposal.layout,next_design)
        except AnalysisFailed as exc:
            record=exc.record
            self.stagnation+=1
        else:
            members=load_members(self.evaluator.solver.diagnostics_directory/record.evaluation_id/'members.json',
                expected_fidelity=record.fidelity)
            control_after=next(m.utilization for m in members
                if m.member_id==proposal.control_member_id and m.story==proposal.control_story)
            accepted=SurrogateCandidateEvaluator.rank_key(result)<SurrogateCandidateEvaluator.rank_key(baseline)
            if accepted:
                self.layouts[candidate_id]=proposal.layout
                self.verified_results[candidate_id]=[(actual,result)]
                self.layout_id=candidate_id;self.visited.add(candidate_id);self.stagnation=0
            else:self.stagnation+=1
        ref=f'local/trial_{len(self.local_outcomes)+1:05d}.json'
        outcome=LocalAdjustmentOutcome(parent_layout_id=parent.layout_id,candidate_id=candidate_id,
            accepted=accepted,solver_status=record.status,feasible=record.feasible,
            control_member_id=proposal.control_member_id,control_utilization_before=proposal.control_utilization,
            control_utilization_after=control_after,material_cost_before=float(baseline.objectives['material_cost']),
            material_cost_after=float(result.objectives['material_cost']) if result else None,
            max_beam_utilization_before=float(source.raw['max_beam_shear_ratio']/source.raw['max_beam_shear_limit']),
            max_beam_utilization_after=float(record.raw['max_beam_shear_ratio']/record.raw['max_beam_shear_limit']) if result else None,
            evidence_ref=ref)
        self.local_outcomes.append(outcome)
        write_json(self.directory/ref,{'outcome':outcome.model_dump(),'proposal':proposal.model_dump(),
            'source_analysis':source.model_dump(),'analysis':record.model_dump(),
            'source_design':design.model_dump(),'parameters_changed':False,'calibration_reused':False})

    def _execution_failure(self, exc: Exception, phase: str) -> None:
        self.execution_error=ErrorRecord(error_type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc(),
            context={'layout_id':self.layout_id,'phase':phase},attempt=1)
        write_json(self.directory/'execution_error.json',self.execution_error.model_dump())

    def approve_layout(self, layout_id: str, *, reviewer: str, expected_sha256: str) -> None:
        if self.status != "WAITING_APPROVAL" or self.pending != layout_id or not reviewer.strip():
            raise ValueError("Approval must name the pending candidate and reviewer")
        digest = hashlib.sha256(self.layouts[layout_id].model_dump_json().encode()).hexdigest()
        if digest != expected_sha256:
            raise ValueError("Approval geometry hash mismatch")
        self._event({"approval": "APPROVED", "layout_id": layout_id, "layout_sha256": digest, "reviewer": reviewer})
        self.layout_id, self.pending, self.status, self.stagnation = layout_id, None, "RUNNING", 0
        self.visited.add(layout_id)
        self.local_proposals={};self.local_ref=None;self.local_source=None

    def _event(self, value: dict) -> None:
        self.event_count += 1
        write_json(self.directory / f"events/event_{self.event_count:05d}.json", value)

    def summary(self) -> dict:
        return {"status": self.status, "state": self.observe().model_dump(), "pending_layout": self.pending,
                "pending_layout_sha256": hashlib.sha256(self.layouts[self.pending].model_dump_json().encode()).hexdigest()
                    if self.pending else None,
                "sessions": {k: s.summary() for k, s in self.sessions.items()},
                "solver_failures": sum(r.status != "SUCCESS" for r in self.evaluator.records),
                'local_adjustment_trials':[o.model_dump() for o in self.local_outcomes],
                "execution_error": self.execution_error.model_dump() if self.execution_error else None,
                "engineering_review": "PENDING"}
