"""Deterministic execution gate around layout-bound CASINO sessions."""
from __future__ import annotations

import hashlib
import json
import math
import traceback
from pathlib import Path
from typing import Any, Callable

from struct_agent.adapters.casino_session import CasinoSession
from struct_agent.adapters.casino import CasinoProblem
from struct_agent.adapters.design_search import local_layout_candidates, apply_design_modification, apply_parameter_modification
from struct_agent._vendor.shearwall_optimization.surrogate_candidate import SurrogateCandidateEvaluator
from struct_agent.io.artifacts import write_json
from struct_agent.schemas import ErrorRecord, LayoutCandidate, DesignCandidate, ProjectSpec, RoomGraph
from struct_agent.schemas.agent import (OptimizationState, validate_decision, LocalAdjustmentConfig,
    LocalLayoutChoice, LocalAdjustmentOutcome)
from struct_agent.schemas.layout import LocalLayoutProposal
from struct_agent.schemas.state import Action, Decision
from struct_agent.services.analysis import AnalysisService, AnalysisFailed
from struct_agent.services.diagnostics import (load_members, design_review_evidence, compare_responses, member_summary,
    get_design_overview, inspect_member, inspect_region)
from struct_agent.services.model_review import review_geometry, review_local_layout_change


class OptimizationEnvironment:
    """One shared FEA budget; new layout means new isolated calibration/session.

    Approvals are trusted application calls, never LLM tools. Disk snapshots are
    audit records; process restoration is not implemented here.
    """

    def __init__(self, case_id: str, layouts: tuple[LayoutCandidate, ...],
                 evaluator: AnalysisService, factory: Callable[[LayoutCandidate, Path], CasinoSession],
                 directory: Path, *, rooms: RoomGraph | None=None, spec: ProjectSpec | None=None,
                 local_config: LocalAdjustmentConfig | None=None, design_review: bool=False,
                 investigation_only: bool=False, generation_provenance: dict | None=None) -> None:
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
        self.design_review=design_review
        if design_review and local_config is None:
            raise ValueError('Design review requires authorized local execution and diagnostics')
        self.review_cache: dict[str,dict] = {}
        self.modification_feedback: dict = {}
        self.pending_modification: tuple | None = None
        self.modification_count=0
        self.investigation_only=investigation_only
        self.generation_provenance=generation_provenance
        self.query_results: list[dict] = []
        self.trial_evidence: dict | None = None
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
        if self.design_review and self.status=='RUNNING':
            allowed=['REQUEST_HUMAN_REVIEW','QUERY_DESIGN']
            if self.pending_modification:
                allowed.append('REJECT_MODIFICATION')
                if self.modification_feedback['eligible_for_adoption']:
                    allowed.append('ACCEPT_MODIFICATION')
            else:
                allowed.append('FINALIZE')
                if best and remaining and not self.execution_error and not self.investigation_only:
                    allowed.append('PROPOSE_MODIFICATION')
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
        if self.design_review and self.modification_count:
            refs.append(f'local/design_trial_{self.modification_count:05d}.json')
        refs.extend(row['evidence_ref'] for row in self.query_results)
        refs=list(dict.fromkeys(refs))
        response={}
        if best and self.local_config:
            raw=self._source_record(best[0]).raw
            response={k:float(raw[k]) for k in ('max_drift_ratio','torsion_ratio','period_ratio','material_concrete_kg','material_steel_kg')}
            response.update(max_beam_utilization=float(raw['max_beam_shear_ratio']/raw['max_beam_shear_limit']),
                max_wall_utilization=float(raw['max_wall_shear_ratio']/raw['max_wall_shear_limit']))
        evidence=self._review_evidence(best[0]) if self.design_review and best else {}
        feedback={k:v for k,v in self.modification_feedback.items() if k not in ('before','after')}
        if self.trial_evidence:
            feedback['after']=get_design_overview(self.trial_evidence)
            feedback['before']={k:self.modification_feedback['before'][k] for k in ('evaluation_id','raw_response')}
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
            design_review_enabled=self.design_review,design_evidence=get_design_overview(evidence) if evidence else {},
            modification_feedback=feedback,design_query_results=tuple(self.query_results),
            investigation_only=self.investigation_only,
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
        if decision.action=='QUERY_DESIGN':
            self._query_design(decision)
        elif decision.action=='PROPOSE_MODIFICATION':
            try:
                self._propose_modification(decision)
            except Exception as exc:
                self._execution_failure(exc,'design_modification')
        elif decision.action in ('ACCEPT_MODIFICATION','REJECT_MODIFICATION'):
            candidate,actual,result=self.pending_modification
            if decision.action=='ACCEPT_MODIFICATION':
                self.layouts[candidate.layout_id]=candidate
                self.verified_results[candidate.layout_id]=[(actual,result)]
                self.layout_id=candidate.layout_id
                self.visited.add(candidate.layout_id)
                self.query_results=[]
            self.modification_feedback={**self.modification_feedback,'agent_action':decision.action,
                'agent_review':decision.review.model_dump(),'adopted':decision.action=='ACCEPT_MODIFICATION',
                'status':'ADOPTED' if decision.action=='ACCEPT_MODIFICATION' else 'REJECTED'}
            self.pending_modification=None
        elif decision.action == "CONTINUE_OPTIMIZATION":
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
        if self.local_config and not self.design_review and self.status=='RUNNING' and not self.execution_error:
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

    def _review_evidence(self, design: DesignCandidate) -> dict:
        record=self._source_record(design)
        if record.evaluation_id not in self.review_cache:
            self.review_cache[record.evaluation_id]=design_review_evidence(self.layouts[design.layout_id],
                self.rooms,design,self.spec,evaluation_id=record.evaluation_id,raw=record.raw,
                directory=self.evaluator.solver.diagnostics_directory/record.evaluation_id,fidelity=record.fidelity)
        return self.review_cache[record.evaluation_id]

    def _query_design(self, decision: Decision) -> None:
        """Execute one read-only professional query; no FEA or design changes."""
        query=decision.query
        before=self.observe()
        evidence=self.trial_evidence if query.source=='trial' else self.review_cache.get(before.design_evidence.get('evaluation_id'))
        try:
            if evidence is None:raise ValueError('No verified analysis is available for the requested source')
            if query.tool=='get_design_overview':result=get_design_overview(evidence)
            elif query.tool=='inspect_member':
                provenance=self.generation_provenance if self.generation_provenance and self.generation_provenance['layout_sha256']==evidence['layout_sha256'] else None
                result=inspect_member(evidence,query.member_id,provenance=provenance)
            else:result=inspect_region(evidence,query.bounds_m,offset=query.offset,limit=query.limit)
        except ValueError as exc:
            result={'error':str(exc)}
        row={'query':query.model_dump(),'result':result,'fea_consumed':0}
        (self.directory/'queries').mkdir(exist_ok=True)
        # Query IDs count files, so clearing stale in-context results never overwrites audit.
        index=len(list((self.directory/'queries').glob('query_*.json')))+1
        row['evidence_ref']=f'queries/query_{index:05d}.json'
        self.query_results.append(row)
        write_json(self.directory/row['evidence_ref'],row)

    def _propose_modification(self, decision: Decision) -> None:
        """Evaluate without replacing the retained design; Agent reviews the result next."""
        session=self.sessions.get(self.layout_id)
        rows=(session.optimizer.problem.results if session else [])+self.verified_results.get(self.layout_id,[])
        design,baseline=min(rows,key=lambda row:SurrogateCandidateEvaluator.rank_key(row[1]))
        source=self._source_record(design)
        before=self._review_evidence(design)
        self.modification_count+=1
        self.trial_evidence=None
        feedback={'instruction':decision.modification.model_dump(),'proposal_review':decision.review.model_dump(),
            'source_evaluation_id':source.evaluation_id,'adopted':False}
        try:
            if decision.modification.operation == 'set_design_parameters':
                candidate = self.layouts[self.layout_id]
                next_design = apply_parameter_modification(candidate, design, self.spec, decision.modification,
                    protected_member_ids=frozenset(self.local_config.protected_member_ids))
            else:
                candidate=apply_design_modification(self.layouts[self.layout_id],self.rooms,design,decision.modification,
                    protected_member_ids=frozenset(self.local_config.protected_member_ids))
                next_design=design.model_copy(update={'layout_id':candidate.layout_id})
            key=self._trial_key(candidate,next_design)
            if key in self.local_tried:
                raise ValueError('Geometry and parameters already evaluated; choose a different modification or stop')
        except ValueError as exc:
            feedback.update(status='PARAMETERS_REJECTED' if decision.modification.operation == 'set_design_parameters' else 'GEOMETRY_REJECTED',reason=str(exc),eligible_for_adoption=False,
                fea_consumed=0)
        else:
            self.local_tried.add(key)
            try:
                actual,result,record=self._evaluate_design(candidate,next_design)
            except AnalysisFailed as exc:
                feedback.update(status=exc.record.status,error=exc.record.error.model_dump(),
                    eligible_for_adoption=False,fea_consumed=1)
            else:
                after=design_review_evidence(candidate,self.rooms,actual,self.spec,
                    evaluation_id=record.evaluation_id,raw=record.raw,
                    directory=self.evaluator.solver.diagnostics_directory/record.evaluation_id,fidelity=record.fidelity)
                self.trial_evidence=after
                new_failures=[k for k,v in source.raw.items() if k.endswith('_passed') and v is True and record.raw[k] is not True]
                for key in ('design_failed_beam_count','design_failed_wall_count'):
                    if record.raw[key]>source.raw[key]:new_failures.append(key)
                old_issues={(i['code'],tuple(i['source_member_ids'])) for i in before['geometry_review']['issues']}
                new_issues=[i for i in after['geometry_review']['issues']
                    if (i['code'],tuple(i['source_member_ids'])) not in old_issues]
                def failed_member_checks(evidence: dict) -> set[tuple]:
                    return {(tuple(row['source_member_ids']),p['story'],kind)
                        for row in evidence['member_checks'] for p in row['problems']
                        for kind in (('shear',) if not p['shear_passed'] else ())+
                            (('reinforcement',) if p['reinforcement_passed'] is False else
                             ('reinforcement_unchecked',) if p['reinforcement_passed'] is None else ())}
                new_member_failures=sorted(failed_member_checks(after)-failed_member_checks(before))
                violation=lambda r:sum(r.metrics['normalized_violations'].values())
                eligible=not new_failures and not new_issues and not new_member_failures and (
                    result.feasible or (not baseline.feasible and violation(result)<=violation(baseline)+1e-12))
                # The retained plan/rooms are already in state. Supply every trial
                # member check and changed segment without repeating architecture.
                before_keys=('evaluation_id','layout_sha256','design','raw_response','global_checks','geometry_review')
                after_keys=before_keys+('direction_checks','member_checks','coverage')
                trial_view={k:after[k] for k in after_keys}
                trial_view['changed_members']=[b.model_dump() for a,b in zip(self.layouts[self.layout_id].members,candidate.members) if a!=b]
                trial_view['unchanged_geometry_from_layout_sha256']=before['layout_sha256']
                feedback['changed_parameters'] = {k: {'before': design.values[k], 'after': actual.values[k]}
                    for k in actual.values if actual.values[k] != design.values[k]}
                feedback.update(status='AWAITING_AGENT_ASSESSMENT',eligible_for_adoption=eligible,
                    new_failed_checks=new_failures,new_geometry_issues=new_issues,
                    new_member_failures=new_member_failures,fea_consumed=1,
                    before={k:before[k] for k in before_keys},after=trial_view,
                    material_cost_before=baseline.objectives['material_cost'],
                    material_cost_after=result.objectives['material_cost'],
                    adoption_gate='Agent must explicitly accept; no new failed global checks, increased failure counts, new geometry issues or worse total violation. Cost increase alone is permitted.')
                self.pending_modification=(candidate,actual,result)
        self.modification_feedback=feedback
        write_json(self.directory/f'local/design_trial_{self.modification_count:05d}.json',feedback)

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
            self.local_tried.add(self._trial_key(self.layouts[self.layout_id],actual))
            if not self.design_review:self._refresh_local()
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


def run_feedback_design_task(layout: LayoutCandidate, rooms: RoomGraph, spec: ProjectSpec,
        initial_design: DesignCandidate, evaluator: AnalysisService, *, directory: Path,
        seed: int, local_config: LocalAdjustmentConfig | None = None) -> dict[str, Any]:
    """Search actual component feedback; XY/dimensions m, forces N, stresses Pa.

    Alternate parameter and legal geometry trials on three retained search states.
    Trial states are not delivered designs. Only full checked feasibility ends
    the search, followed by uncached verification within the SAME FEA budget.
    Already-feasible input ends after its initial full analysis. No surrogate,
    hardcoded member IDs, model changes or engineering release is involved.
    """
    from dataclasses import asdict
    from time import perf_counter
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from struct_agent.adapters.fea import native_params
    initial_design.validate_against(spec)
    if initial_design.layout_id != layout.layout_id or evaluator.records:
        raise ValueError('Matching initial layout and a fresh evaluator are required')
    if unary_union([Polygon(p) for p in rooms.room_polygons]).hausdorff_distance(
            unary_union([Polygon(p) for p in layout.slabs])) > .002:
        raise ValueError('Room graph does not match input layout')
    started = perf_counter()
    (directory/'candidates').mkdir()
    (directory/'events').mkdir()
    seen: set[str] = set()
    pool: list[dict[str, Any]] = []
    status = 'MODEL_REVIEW_REQUIRED' if review_geometry(layout).requires_model_repair else 'SEARCHING'
    selected = None
    verification = None
    events = []

    def key(plan: LayoutCandidate, values: dict[str, Any]) -> str:
        geometry = {'members': [m.model_dump() for m in plan.members], 'slabs': plan.slabs}
        return hashlib.sha256(json.dumps([geometry, values], sort_keys=True).encode()).hexdigest()

    def evaluate(plan: LayoutCandidate, values: dict[str, Any], family: str,
                 parent: dict[str, Any] | None) -> dict[str, Any] | None:
        nonlocal status
        trial_key = key(plan, values)
        seen.add(trial_key)
        index = len(events)+1
        path = directory/f'candidates/layout_{index:03d}.json'
        write_json(path, plan.model_dump())
        problem = CasinoProblem(plan, spec, evaluator, layout_path=path, seed=seed)
        decision = {k: round(float(v)*1000) if k != 'conc_bot' else v for k, v in values.items()}
        event: dict[str, Any] = {'family': family, 'layout_path': str(path), 'values': values,
            'parent_evaluation': parent['record'].evaluation_id if parent else None}
        proposed = DesignCandidate(design_id=trial_key, layout_id=plan.layout_id,
            condition_id=spec.condition_id, values=values)
        proposed.validate_against(spec)
        preflight = review_geometry(plan, design=proposed)
        new_preflight = {(i.code, i.source_member_ids) for i in preflight.issues}-parent['issues'] if parent else set()
        if preflight.requires_model_repair or new_preflight:
            event.update(retained_for_search=False, rejected_before_fea=True,
                new_geometry_issues=sorted(new_preflight))
            events.append(event)
            write_json(directory/f'events/trial_{index:03d}.json', event)
            return None
        try:
            result = problem.evaluate(decision)
        except AnalysisFailed as exc:
            status = 'ANALYSIS_FAILED'
            event.update(analysis=exc.record.model_dump(), retained_for_search=False)
            state = None
        else:
            actual = problem.results[-1][0]
            record = evaluator.records[-1]
            members = load_members(evaluator.solver.diagnostics_directory/record.evaluation_id/'members.json',
                                   expected_fidelity=record.fidelity)
            review = review_geometry(plan, design=actual)
            issues = {(i.code, i.source_member_ids) for i in review.issues}
            wall_failures = {(m.source_member_ids, m.story) for m in members
                if m.role == 'wall' and (not m.shear_passed or m.reinforcement_passed is not True)}
            new_issues = issues-parent['issues'] if parent else set()
            new_wall_failures = wall_failures-parent['wall_failures'] if parent else set()
            eligible = not review.requires_model_repair and not new_issues and not new_wall_failures
            checked = all(m.shear_passed and m.reinforcement_passed is True for m in members)
            if result.feasible and not checked:
                status = 'VALIDATION_FAILED'
                eligible = False
            state = {'layout': plan, 'design': actual, 'result': result, 'record': record,
                'members': members, 'issues': issues, 'wall_failures': wall_failures} if eligible else None
            event.update(analysis_path=str(evaluator.directory/f'{record.evaluation_id}.json'),
                feasible=result.feasible, retained_for_search=eligible,
                new_geometry_issues=sorted(new_issues), new_wall_failure_slots=sorted(new_wall_failures),
                material_cost=result.objectives['material_cost'], violation=result.objectives['violation_score'])
        events.append(event)
        write_json(directory/f'events/trial_{index:03d}.json', event)
        print(f'feedback trial={index} family={family} FEA={len(evaluator.records)}/{evaluator.budget}; retained={state is not None}', flush=True)
        return state

    if status == 'SEARCHING':
        initial = evaluate(layout, dict(initial_design.values), 'initial', None)
        if initial:
            pool.append(initial)
            if initial['result'].feasible:
                selected, status = initial, 'ALREADY_FEASIBLE'
    turn = 0
    while status == 'SEARCHING' and len(evaluator.records) < evaluator.budget-1:
        proposal = None
        for family in (('parameters', 'geometry') if turn % 2 == 0 else ('geometry', 'parameters')):
            for parent in sorted(pool, key=lambda p: SurrogateCandidateEvaluator.rank_key(p['result']))[:3]:
                plan, design = parent['layout'], parent['design']
                if family == 'parameters':
                    problem = CasinoProblem(plan, spec, evaluator, layout_path=directory/'candidates', seed=seed)
                    x = {k: round(float(v)*1000) if k != 'conc_bot' else v for k, v in design.values.items()}
                    candidates = [(plan, {k: float(v)/1000 if k != 'conc_bot' else v for k, v in row.items()})
                        for row in problem.feedback_candidates(x, parent['result'])]
                    active = {k for k, v in parent['result'].metrics['normalized_violations'].items() if v > 0}
                    controlling = {m.role for m in parent['members'] if m.role != 'wall' and m.utilization > 1}
                    def priority(candidate: tuple[LayoutCandidate, dict[str, Any]]) -> int:
                        values = candidate[1]
                        changed = {k for k in values if values[k] != design.values[k]}
                        heights = {'hb_main' if role == 'primary' else 'hb_sec' for role in controlling}
                        if not any('wall' in k for k in active) and len(changed) == 1 and changed <= heights:
                            name = next(iter(changed))
                            if values[name] < design.values[name]:
                                return 0
                        return 1 if changed == {'conc_bot'} else 2
                    candidates.sort(key=priority)
                elif local_config and sum(e['family'] == 'geometry' for e in events) < local_config.max_trials:
                    search = local_layout_candidates(plan, rooms, design, parent['members'],
                        steps_m=local_config.steps_m, target_utilization=local_config.target_utilization,
                        max_candidates=32, protected_member_ids=frozenset(local_config.protected_member_ids))
                    candidates = [(p.layout, dict(design.values)) for p in search.proposals
                        if key(p.layout, dict(design.values)) not in seen][:local_config.max_candidates]
                else:
                    candidates = []
                for candidate, values in candidates:
                    if key(candidate, values) not in seen:
                        proposal = candidate, values, family, parent
                        break
                if proposal:
                    break
            if proposal:
                break
        if not proposal:
            status = 'NO_ADMISSIBLE_CANDIDATES'
            break
        candidate, values, family, parent = proposal
        trial = evaluate(candidate, values, family, parent)
        turn += 1
        if trial:
            pool.append(trial)
            pool = sorted(pool, key=lambda p: SurrogateCandidateEvaluator.rank_key(p['result']))[:3]
            if trial['result'].feasible:
                selected = trial
                repeated = evaluator.evaluate(candidate, trial['design'], spec, force_reanalysis=True)
                verification = {'evaluation_id': repeated.evaluation_id, 'status': repeated.status,
                    'feasible': repeated.feasible, 'force_reanalysis': True}
                parity = compare_responses(repeated.raw, trial['record'].raw) if repeated.status == 'SUCCESS' else {}
                verification['response_parity_passed'] = bool(parity) and all(r['passed'] for r in parity.values())
                checked = False
                if repeated.status == 'SUCCESS':
                    repeated_members = load_members(evaluator.solver.diagnostics_directory/repeated.evaluation_id/'members.json',
                        expected_fidelity=repeated.fidelity)
                    checked = all(m.shear_passed and m.reinforcement_passed is True for m in repeated_members)
                status = 'FEASIBLE' if repeated.feasible and checked and verification['response_parity_passed'] else 'VERIFICATION_FAILED'
    if status == 'SEARCHING':
        status = 'BUDGET_EXHAUSTED_NO_FEASIBLE'
    best = selected or min(pool, key=lambda p: SurrogateCandidateEvaluator.rank_key(p['result']), default=None)
    success = status in ('FEASIBLE', 'ALREADY_FEASIBLE')
    summary = {'status': status, 'implemented_checks_passed': success, 'engineering_review': 'PENDING',
        'fea_attempts': len(evaluator.records), 'fea_budget': evaluator.budget, 'seed': seed,
        'elapsed_s': perf_counter()-started, 'verification': verification,
        'best_observed_feasible': bool(best and best['result'].feasible),
        'unresolved': [] if success else ['No verified feasible design delivered; see actual checks, trials or solver error.'],
        'trial_count': len(events),
        'remaining_violations': {k: v for k, v in best['result'].metrics['normalized_violations'].items() if v > 0} if best else {},
        'selected_evaluation_id': best['record'].evaluation_id if best else None,
        'solver_failures': sum(r.status != 'SUCCESS' for r in evaluator.records)}
    if best:
        write_json(directory/'selected_layout.json', best['layout'].model_dump())
        write_json(directory/'selected_design.json', best['design'].model_dump())
        write_json(directory/'parameter_configuration.json', {'design': best['design'].model_dump(),
            'project_spec': spec.model_dump(), 'native_parameters_mm': asdict(native_params(best['design'], spec)),
            'layout_path': 'selected_layout.json', 'implemented_checks_passed': success,
            'engineering_review': 'PENDING', 'member_checks': member_summary(best['members']),
            'raw_response': best['record'].raw, 'geometry_review': review_geometry(best['layout'], design=best['design']).model_dump()})
    write_json(directory/'summary.json', summary)
    return summary
