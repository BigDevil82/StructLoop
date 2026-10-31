"""Execution-gate tests with synthetic sessions; no engineering claims."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from struct_agent.agents.policies import FixedPolicy, RulePolicy
from struct_agent.schemas import LayoutCandidate
from struct_agent.schemas.state import Decision
from struct_agent.workflows.optimization_env import OptimizationEnvironment


@pytest.fixture
def env(tmp_path: Path) -> OptimizationEnvironment:
    layout = LayoutCandidate.model_validate_json(json.dumps({"layout_id": "a", "source": "synthetic_test",
        "length_unit": "m", "coordinate_system": "global_xy", "members": [
            {"member_id": "w", "start": [0., 0.], "end": [1., 0.], "role": "wall"}],
        "slabs": [[[0., 0.], [1., 0.], [0., 1.]]]}))
    service = SimpleNamespace(budget=5, records=[], solver=SimpleNamespace(fidelity="mock"), directory=tmp_path / "analyses")
    class Session:
        def __init__(self, layout: LayoutCandidate, directory: Path) -> None:
            self.layout, self.directory, self.advance_count, self.status = layout, directory, 0, "ready"
            self.optimizer = SimpleNamespace(problem=SimpleNamespace(results=[]))
        def summary(self) -> dict:
            return {"termination": self.status, "completed_generations": self.advance_count,
                    "local_calibration_samples": len(self.optimizer.problem.results)}
        def advance(self, n: int) -> None:
            self.advance_count += n
            service.records.append(SimpleNamespace(layout_id=self.layout.layout_id, status="SUCCESS", feasible=False,
                evaluation_id=f"eval_{len(service.records)+1:05d}"))
            self.optimizer.problem.results.append((None, SimpleNamespace(feasible=False, objective=100.,
                metrics={"normalized_violations": {"drift": 0.1}}, objectives={"material_cost": 20.})))
            self.status = "paused"
    return OptimizationEnvironment("test", (layout, layout.model_copy(update={"layout_id": "b"})), service, Session, tmp_path)


def test_continue_then_switch_requires_bound_approval(env: OptimizationEnvironment) -> None:
    policy = RulePolicy(stagnation_limit=1)
    env.step(policy.choose(env.observe()))
    first = env.sessions["a"]
    env.step(policy.choose(env.observe()))
    assert env.sessions["a"] is first
    assert env.observe().stagnation_steps == 1
    decision = policy.choose(env.observe())
    assert decision.action == "SWITCH_LAYOUT"
    env.step(decision)
    assert env.status == "WAITING_APPROVAL" and len(env.evaluator.records) == 2
    with pytest.raises(RuntimeError):
        env.step(decision)
    with pytest.raises(ValueError, match="hash"):
        env.approve_layout("b", reviewer="test reviewer", expected_sha256="bad")
    digest = hashlib.sha256(env.layouts["b"].model_dump_json().encode()).hexdigest()
    env.approve_layout("b", reviewer="test reviewer", expected_sha256=digest)
    assert env.observe().calibration_samples == 0
    env.step(policy.choose(env.observe()))
    assert env.sessions["a"] is first and env.sessions["b"] is not first
    assert len(env.evaluator.records) == 3
    assert env.observe().calibration_samples == 1


def test_budget_gate_and_fixed_policy(env: OptimizationEnvironment) -> None:
    policy = FixedPolicy()
    for _ in range(5):
        env.step(policy.choose(env.observe()))
    assert env.observe().fea_budget_remaining == 0
    assert "SWITCH_LAYOUT" not in env.observe().allowed_actions
    env.step(policy.choose(env.observe()))
    assert env.status == "COMPLETED" and len(env.sessions) == 1


def test_solver_failure_is_unknown_not_infeasible(env: OptimizationEnvironment) -> None:
    env.step(FixedPolicy().choose(env.observe()))
    env.evaluator.records[-1].status = "SOLVER_ERROR"
    env.evaluator.records[-1].feasible = None
    state = env.observe()
    assert state.latest_feasible is None and state.allowed_actions == ("REQUEST_HUMAN_REVIEW",)
    env.step(RulePolicy().choose(state))
    assert env.status == "AWAITING_REVIEW" and len(env.evaluator.records) == 1


def test_illegal_action_does_not_construct_session(env: OptimizationEnvironment) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        env.step(Decision(action="SWITCH_LAYOUT", target_layout_id="b", reason="premature", evidence_refs=()))
    assert not env.sessions and not env.evaluator.records


def test_immutable_events(env: OptimizationEnvironment) -> None:
    env.step(FixedPolicy().choose(env.observe()))
    event = json.loads((env.directory / "events/event_00001.json").read_text())
    assert event["fea_attempts_delta"] == 1 and event["before"]["fea_calls_used"] == 0
    assert event["after"]["fidelity"] == "mock"


def test_operator_approval_binds_layout_conditions_and_purpose(env: OptimizationEnvironment) -> None:
    from struct_agent.schemas import ProjectSpec
    from struct_agent.workflows.layout_approval import LayoutApproval
    spec = ProjectSpec.model_validate_json(Path("configs/reference_spec.json").read_text(encoding="utf-8"))
    layout = env.layouts["b"]
    approval = LayoutApproval(layout_id="b", reviewer="test reviewer", purpose="smoke_only",
        authorization="Explicit synthetic test approval",
        layout_sha256=hashlib.sha256(layout.model_dump_json().encode()).hexdigest(),
        spec_sha256=hashlib.sha256(spec.model_dump_json().encode()).hexdigest())
    approval.check(layout, spec, "smoke_only")
    for candidate, conditions, purpose in ((env.layouts["a"], spec, "smoke_only"),
        (layout, spec.model_copy(update={"condition_id": "different"}), "smoke_only"), (layout, spec, "research")):
        with pytest.raises(ValueError, match="Approval does not match"):
            approval.check(candidate, conditions, purpose)


def test_session_construction_failure_is_audited_and_stops_execution(env: OptimizationEnvironment) -> None:
    def broken_factory(*args: object) -> None:
        raise RuntimeError("Injected session construction error")
    env.factory = broken_factory
    env.step(FixedPolicy().choose(env.observe()))
    state = env.observe()
    assert state.session_status == "optimizer_failed" and state.latest_feasible is None
    assert state.allowed_actions == ("REQUEST_HUMAN_REVIEW",) and not env.evaluator.records
    record = json.loads((env.directory / "execution_error.json").read_text())
    assert record["error_type"] == "RuntimeError" and "broken_factory" in record["traceback"]
    env.step(FixedPolicy().choose(state))
    assert env.status == "AWAITING_REVIEW"


def local_env(tmp_path: Path, *, mode: str='improve', budget: int=4) -> OptimizationEnvironment:
    """Synthetic responses/diagnostics confined to tests; never physical evidence."""
    from dataclasses import fields,asdict
    from tests.unit.test_search_feedback import local_case
    from struct_agent.schemas import ProjectSpec,AnalysisRecord
    from struct_agent.schemas.agent import LocalAdjustmentConfig
    from struct_agent.services.analysis import AnalysisService
    from struct_agent.io.artifacts import write_json
    from struct_agent._vendor.shearwall_modeling.parametric.types import ParametricAnalysisResult
    layout,rooms,design,diagnostic=local_case()
    spec=ProjectSpec.model_validate_json(Path('configs/reference_spec.json').read_text(encoding='utf-8'))
    design=design.model_copy(update={'condition_id':spec.condition_id,'values':{v.name:v.values[0] for v in spec.design_variables}})
    class Solver:
        fidelity='mock'
        diagnostics_directory=tmp_path/'diagnostics'
        def evaluate(self,candidate,parameters,conditions,*,evaluation_id):
            assert parameters.values==design.values
            if mode=='fail' and evaluation_id=='eval_00002':raise ArithmeticError('synthetic local trial failure')
            initial=evaluation_id=='eval_00001';passed=initial or mode!='reject'
            raw={f.name:True if f.type is bool else 0 if f.type is int else 1. if f.type is float else ''
                for f in fields(ParametricAnalysisResult)}
            raw.update(feasible=passed,design_passed=passed,design_failed_wall_count=0 if passed else 1,
                material_concrete_kg=100000. if initial else 99000.,material_steel_kg=1000.,
                torsion_ratio=1.2,period_ratio=.8,max_drift_ratio=.0005,
                max_wall_axial_ratio=.2,max_wall_axial_limit=.5,max_wall_shear_ratio=.1,max_wall_shear_limit=.2,
                max_beam_shear_ratio=.196 if initial else .13,max_beam_shear_limit=.2)
            beam=candidate.members[1];ratio=raw['max_beam_shear_ratio'];original=diagnostic(1)
            member=original.model_copy(update={'start_m':beam.start,'end_m':beam.end,
                'length_m':__import__('math').dist(beam.start,beam.end),
                'shear_ratio':ratio,'shear_n':ratio*original.denominator_n,'shear_passed':True,
                'reinforcement_passed':True,'combo_shear_n':{'test':ratio*original.denominator_n},
                'combo_design_shear_n':{'test':ratio*original.denominator_n}})
            path=self.diagnostics_directory/evaluation_id;path.mkdir(parents=True)
            write_json(path/'members.json',{'fidelity':'mock','units':{'length':'m','force':'N','stress':'Pa'},'members':[member.model_dump()]})
            return AnalysisRecord(evaluation_id=evaluation_id,layout_id=candidate.layout_id,design_id=parameters.design_id,
                condition_id=conditions.condition_id,fidelity='mock',status='SUCCESS',solver='synthetic_test',solver_version='1',
                elapsed_s=0.,feasible=passed,raw=asdict(ParametricAnalysisResult(**raw)),error=None)
    service=AnalysisService(Solver(),budget=budget,directory=tmp_path/'analyses')
    class Session:
        def __init__(self,candidate,directory):
            self.layout,self.directory,self.advance_count=candidate,directory,0
            self.optimizer=SimpleNamespace(problem=SimpleNamespace(results=[]),local_calibrator=object())
        def seed_verified_design(self,seed,result):
            assert seed.layout_id==self.layout.layout_id
            self.optimizer.problem.results.append((seed,result))
        def summary(self):return {'termination':'ready','completed_generations':0,'local_calibration_samples':0}
    env=OptimizationEnvironment('local_mock_only',(layout,),service,Session,tmp_path,rooms=rooms,spec=spec,
        local_config=LocalAdjustmentConfig(target_utilization=.95,steps_m=(.1,),max_trials=2))
    env.initialize_design(design)
    return env


def test_local_policy_executes_verified_move_and_seeds_an_isolated_session(tmp_path: Path) -> None:
    env=local_env(tmp_path)
    before=env.observe();parent=env._session()
    assert before.local_layout_choices and before.current_response['max_beam_utilization']==.98
    assert FixedPolicy().choose(before).action=='CONTINUE_OPTIMIZATION'
    decision=RulePolicy().choose(before)
    assert decision.action=='ADJUST_LOCAL_LAYOUT'
    after=env.step(decision)
    assert after.layout_id!=before.layout_id and after.latest_feasible is True
    assert after.local_adjustment_history[-1].accepted and after.fea_calls_used==2
    assert after.current_response['max_beam_utilization']==.65
    child=env._session()
    assert child is not parent and child.optimizer.local_calibrator is not parent.optimizer.local_calibrator
    assert child.optimizer.problem.results[0][0].layout_id==after.layout_id
    assert parent.optimizer.problem.results[0][0].layout_id==before.layout_id
    assert all((env.directory/p).is_file() for p in after.evidence_refs)
    event=json.loads((env.directory/'events/event_00002.json').read_text(encoding='utf-8'))
    assert event['fea_attempts_delta']==1 and event['approval_required'] is False


@pytest.mark.parametrize('mode',['reject','fail'])
def test_local_rejection_or_failure_keeps_parent_and_records_budget(tmp_path: Path,mode: str) -> None:
    env=local_env(tmp_path,mode=mode,budget=3)
    before=env.observe();selected=RulePolicy().choose(before)
    after=env.step(selected)
    assert after.layout_id==before.layout_id and after.fea_calls_used==2
    outcome=after.local_adjustment_history[-1]
    assert not outcome.accepted and outcome.feasible is (None if mode=='fail' else False)
    assert selected.target_layout_id not in {c.candidate_id for c in after.local_layout_choices}
    trial=json.loads((env.directory/outcome.evidence_ref).read_text(encoding='utf-8'))
    if mode=='fail':assert trial['analysis']['error']['error_type']=='ArithmeticError'
    else:assert trial['analysis']['raw']['design_failed_wall_count']==1


def test_local_gate_rejects_invented_candidate_and_tampered_geometry(tmp_path: Path) -> None:
    env=local_env(tmp_path)
    state=env.observe()
    with pytest.raises(ValueError,match='supplied local candidate'):
        env.step(Decision(action='ADJUST_LOCAL_LAYOUT',target_layout_id='invented',reason='test',evidence_refs=state.evidence_refs))
    choice=RulePolicy().choose(state);proposal=env.local_proposals[choice.target_layout_id]
    changed=proposal.layout.members[0].model_copy(update={'role':'secondary'})
    bad=proposal.layout.model_copy(update={'members':(changed,)+proposal.layout.members[1:]})
    env.local_proposals[choice.target_layout_id]=proposal.model_copy(update={'layout':bad})
    after=env.step(choice)
    assert after.allowed_actions==('REQUEST_HUMAN_REVIEW',) and after.fea_calls_used==1
    assert env.execution_error.error_type=='ValueError'


def test_local_budget_exhaustion_closes_action_and_respects_trial_limit(tmp_path: Path) -> None:
    env=local_env(tmp_path,mode='reject',budget=2)
    env.step(RulePolicy().choose(env.observe()))
    state=env.observe()
    assert state.fea_calls_used==2 and 'ADJUST_LOCAL_LAYOUT' not in state.allowed_actions
    env.step(RulePolicy().choose(state));assert env.status=='COMPLETED'
