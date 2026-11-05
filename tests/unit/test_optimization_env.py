"""Execution-gate tests with synthetic sessions; no engineering claims."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

def _field_default(field: object) -> object:
    """A placeholder for every ParametricAnalysisResult field.

    Optional fields take None, which is a real state: a run that skipped
    reinforcement design leaves the five design fields unset.
    """
    kinds = getattr(getattr(field, "type", None), "__args__", (getattr(field, "type", None),))
    for kind, value in ((bool, True), (int, 0), (float, 1.0), (str, "")):
        if kind in kinds:
            return value
    return None



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


def local_env(tmp_path: Path, *, mode: str='improve', budget: int=4, design_review: bool=False,
              allow_parameter_edits: bool=False) -> OptimizationEnvironment:
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
        def evaluate(self,candidate,parameters,conditions,*,evaluation_id,detail=True):
            if not allow_parameter_edits:
                assert parameters.values==design.values
            if mode=='fail' and evaluation_id=='eval_00002':raise ArithmeticError('synthetic local trial failure')
            initial=evaluation_id=='eval_00001';passed=initial or mode!='reject'
            raw={f.name:_field_default(f) for f in fields(ParametricAnalysisResult)}
            raw.update(feasible=passed,design_passed=passed,design_failed_wall_count=0 if passed else 1,
                material_concrete_kg=100000. if initial else 101000. if mode=='cost_increase' else 99000.,material_steel_kg=1000.,
                torsion_ratio=1.2,period_ratio=.8,max_drift_ratio=.0005,
                max_wall_axial_ratio=.2,max_wall_axial_limit=.5,max_wall_shear_ratio=.1,max_wall_shear_limit=.2,
                max_beam_shear_ratio=.196 if initial else .13,max_beam_shear_limit=.2)
            beam=candidate.members[1];ratio=raw['max_beam_shear_ratio'];original=diagnostic(1)
            member=original.model_copy(update={'start_m':beam.start,'end_m':beam.end,
                'length_m':__import__('math').dist(beam.start,beam.end),
                'shear_ratio':ratio,'shear_n':ratio*original.denominator_n,'shear_passed':True,
                'reinforcement_passed':True,'combo_shear_n':{'test':ratio*original.denominator_n},
                'combo_design_shear_n':{'test':ratio*original.denominator_n}})
            if allow_parameter_edits:
                from struct_agent._vendor.shearwall_modeling.core.constants import concrete_fc_pa
                width, depth = float(parameters.values['bb_sec']), float(parameters.values['hb_sec'])
                fc = concrete_fc_pa(parameters.values['conc_bot'])
                denominator = fc*width*(depth-.04)
                member = member.model_copy(update={'width_m':width,'depth_m':depth,'effective_depth_m':depth-.04,
                    'concrete_grade':parameters.values['conc_bot'],'fc_pa':fc,'denominator_n':denominator,
                    'shear_n':ratio*denominator,'combo_shear_n':{'test':ratio*denominator},
                    'combo_design_shear_n':{'test':ratio*denominator}})
            path=self.diagnostics_directory/evaluation_id;path.mkdir(parents=True)
            write_json(path/'members.json',{'fidelity':'mock','units':{'length':'m','force':'N','stress':'Pa'},'members':[member.model_dump()]})
            write_json(path/'checks.json',{'overall':{'passed':passed},'directions':{}})
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
        local_config=LocalAdjustmentConfig(target_utilization=.95,steps_m=(.1,),max_trials=2),design_review=design_review)
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


def review_decision(env: OptimizationEnvironment, action: str, **changes) -> Decision:
    from struct_agent.schemas.state import DesignReview, DesignModification, DesignQuery
    state=env.observe()
    instruction=None
    if action=='PROPOSE_MODIFICATION':
        # Synthetic Agent fixture explicitly investigates before suggesting an edit.
        env.step(Decision(action='QUERY_DESIGN',reason='Inspect affected test member',evidence_refs=state.evidence_refs,
            query=DesignQuery(tool='inspect_member',member_id='b')))
        state=env.observe()
        instruction=DesignModification(operation='move_wall_tip',source_evaluation_id=state.design_evidence['evaluation_id'],
            source_layout_sha256=state.design_evidence['layout_sha256'],target_member_id='wl',connected_member_id='b',
            endpoint='end',delta_length_m=-.1,expected_effect='Synthetic test: longer beam span')
        instruction=instruction.model_copy(update=changes)
    return Decision(action=action,reason='Synthetic review test',evidence_refs=state.evidence_refs,
        review=DesignReview(diagnosis='Synthetic short beam review',cause_hypothesis='Test hypothesis only',
            affected_member_ids=('b',),assessment='Compare the actual trial before accepting',unresolved=('Test only',)),
        modification=instruction)


def parameter_decision(env: OptimizationEnvironment, **updates) -> Decision:
    from struct_agent.schemas.state import ParameterModification
    wall = review_decision(env, 'PROPOSE_MODIFICATION')
    state = env.observe()
    return wall.model_copy(update={'modification': ParameterModification(operation='set_design_parameters',
        source_evaluation_id=state.design_evidence['evaluation_id'],source_layout_sha256=state.design_evidence['layout_sha256'],
        parameter_updates=updates,expected_effect='Synthetic material or section trial; compare real feedback before adopting')})


@pytest.mark.parametrize('accept', [True, False])
def test_parameter_trial_requires_agent_judgment_and_retains_layout(tmp_path: Path, accept: bool) -> None:
    env = local_env(tmp_path, design_review=True, allow_parameter_edits=True)
    layout = env.layouts[env.layout_id]
    before = env.observe().design_evidence['design']
    state = env.step(parameter_decision(env, conc_bot='C35'))
    assert env.layouts[env.layout_id] == layout
    assert state.design_evidence['design'] == before
    assert state.modification_feedback['changed_parameters'] == {'conc_bot': {'before':'C30','after':'C35'}}
    assert state.modification_feedback['after']['design']['values']['conc_bot'] == 'C35'
    assert 'ACCEPT_MODIFICATION' in state.allowed_actions and len(env.evaluator.records) == 2
    env.step(review_decision(env, 'ACCEPT_MODIFICATION' if accept else 'REJECT_MODIFICATION'))
    assert env.observe().design_evidence['design']['values']['conc_bot'] == ('C35' if accept else 'C30')
    assert env.layouts[env.layout_id] == layout
    if accept:
        assert not env.query_results
        reverted = env.step(parameter_decision(env, conc_bot='C30'))
        assert reverted.modification_feedback['status'] == 'PARAMETERS_REJECTED'
        assert reverted.modification_feedback['fea_consumed'] == 0 and reverted.fea_calls_used == 2


def test_parameter_domain_noop_duplicates_and_failed_trial_keep_current_design(tmp_path: Path) -> None:
    env = local_env(tmp_path, design_review=True, allow_parameter_edits=True, mode='reject')
    for updates in ({'bb_sec': .123}, {'conc_bot':'C30'}):
        state = env.step(parameter_decision(env, **updates))
        assert state.modification_feedback['status'] == 'PARAMETERS_REJECTED'
        assert state.fea_calls_used == 1
    state = env.step(parameter_decision(env, conc_bot='C35'))
    assert 'ACCEPT_MODIFICATION' not in state.allowed_actions
    env.step(review_decision(env, 'REJECT_MODIFICATION'))
    assert env.observe().design_evidence['design']['values']['conc_bot'] == 'C30'
    state = env.step(parameter_decision(env, conc_bot='C35'))
    assert state.modification_feedback['status'] == 'PARAMETERS_REJECTED' and state.fea_calls_used == 2


def test_modification_requires_relevant_current_query_not_overview_or_stale_query(tmp_path: Path) -> None:
    from struct_agent.schemas.agent import validate_decision
    env = local_env(tmp_path, design_review=True)
    decision = review_decision(env, 'PROPOSE_MODIFICATION')
    state = env.observe()
    assert validate_decision(decision, state) == decision
    for results in ((), ({**state.design_query_results[0],
            'result':{**state.design_query_results[0]['result'],'evaluation_id':'stale'}},),
            ({**state.design_query_results[0],'query':{'tool':'get_design_overview','source':'current'}},)):
        stale = state.model_copy(update={'design_query_results':results})
        with pytest.raises(ValueError, match='Inspect an affected'):
            validate_decision(decision, stale)


def test_design_review_receives_actual_plan_and_can_finish_without_modification(tmp_path: Path) -> None:
    env=local_env(tmp_path,design_review=True)
    state=env.observe();e=state.design_evidence
    assert 'layout' not in e and 'rooms' not in e and 'member_checks' not in e
    assert e['conditions']['stories'] and e['plan_summary']['room_count']==1
    env.step(review_decision(env,'FINALIZE'))
    assert env.status=='COMPLETED' and len(env.evaluator.records)==1 and not env.sessions


@pytest.mark.parametrize('accept',[True,False])
def test_trial_requires_agent_judgment_and_does_not_replace_parent_early(tmp_path: Path,accept: bool) -> None:
    env=local_env(tmp_path,design_review=True,budget=2)
    parent=env.layout_id
    state=env.step(review_decision(env,'PROPOSE_MODIFICATION'))
    assert state.layout_id==parent and state.fea_calls_used==2
    assert state.modification_feedback['before']['raw_response']['max_beam_shear_ratio']==.196
    assert state.modification_feedback['after']['raw_response']['max_beam_shear_ratio']==.13
    assert 'ACCEPT_MODIFICATION' in state.allowed_actions and 'FINALIZE' not in state.allowed_actions
    env.step(review_decision(env,'ACCEPT_MODIFICATION' if accept else 'REJECT_MODIFICATION'))
    assert (env.layout_id!=parent)==accept
    assert len(env.evaluator.records)==2
    if accept:
        assert env._session().optimizer.problem.results[0][0].layout_id==env.layout_id


@pytest.mark.parametrize('mode',['reject','fail'])
def test_design_review_cannot_adopt_failed_or_worse_trial(tmp_path: Path,mode: str) -> None:
    env=local_env(tmp_path,design_review=True,mode=mode)
    parent=env.layout_id
    state=env.step(review_decision(env,'PROPOSE_MODIFICATION'))
    assert not state.modification_feedback['eligible_for_adoption'] and state.layout_id==parent
    assert 'ACCEPT_MODIFICATION' not in state.allowed_actions and len(env.evaluator.records)==2


def test_invalid_geometry_is_feedback_without_fea_and_stale_instruction_is_rejected(tmp_path: Path) -> None:
    env=local_env(tmp_path,design_review=True)
    state=env.step(review_decision(env,'PROPOSE_MODIFICATION',connected_member_id='missing'))
    assert state.modification_feedback['status']=='GEOMETRY_REJECTED'
    assert state.fea_calls_used==1 and env.execution_error is None
    with pytest.raises(ValueError,match='currently reviewed'):
        env.step(review_decision(env,'PROPOSE_MODIFICATION',source_evaluation_id='old'))
    assert len(env.evaluator.records)==1


def test_agent_may_accept_higher_material_cost_with_safe_checks(tmp_path: Path) -> None:
    env=local_env(tmp_path,design_review=True,mode='cost_increase')
    parent=env.layout_id
    state=env.step(review_decision(env,'PROPOSE_MODIFICATION'))
    feedback=state.modification_feedback
    assert feedback['material_cost_after']>feedback['material_cost_before']
    assert 'ACCEPT_MODIFICATION' in state.allowed_actions
    env.step(review_decision(env,'ACCEPT_MODIFICATION'))
    assert env.layout_id!=parent


def test_agent_can_cite_new_physical_member_ids_from_trial_evidence(tmp_path: Path) -> None:
    from struct_agent.schemas.agent import validate_decision
    env=local_env(tmp_path,design_review=True)
    state=env.step(review_decision(env,'PROPOSE_MODIFICATION'))
    feedback={**state.modification_feedback,'after':{'member_checks':[{'member_id':'new_trial_pier'}]}}
    state=state.model_copy(update={'modification_feedback':feedback})
    decision=review_decision(env,'REJECT_MODIFICATION')
    decision=decision.model_copy(update={'review':decision.review.model_copy(update={'affected_member_ids':('new_trial_pier',)})})
    assert validate_decision(decision,state)==decision
    with pytest.raises(ValueError,match='unknown members'):
        validate_decision(decision,env.observe())


def test_agent_queries_geometry_connections_and_paged_region_without_fea(tmp_path: Path) -> None:
    from struct_agent.schemas.state import DesignQuery
    env=local_env(tmp_path,design_review=True)
    env.investigation_only=True
    before=env.observe()
    assert 'PROPOSE_MODIFICATION' not in before.allowed_actions
    assert 'layout' not in before.design_evidence
    def query(q: DesignQuery):
        state=env.observe()
        return env.step(Decision(action='QUERY_DESIGN',reason='Inspect before editing',evidence_refs=state.evidence_refs,query=q))
    state=query(DesignQuery(tool='inspect_member',member_id='b'))
    result=state.design_query_results[-1]['result']
    assert result['axis_length_m']==2.
    assert result['members'][0]['start']==[1.,3.]
    assert result['endpoint_connections'][0]['connected_members'][0]['member_id']=='wl'
    assert result['generation_provenance']['available'] is False
    assert result['layout_relations']['wall_piers']==[]  # Requested object is a beam.
    state=query(DesignQuery(tool='inspect_member',member_id='b'))
    assert 'no new evidence' in state.design_query_results[-1]['result']['error']
    assert any(r['result'].get('requested_member_id')=='b' for r in state.design_query_results)
    assert state.fea_calls_used==1
    state=query(DesignQuery(tool='inspect_region',bounds_m=(-1.,-1.,5.,4.),limit=2))
    result=state.design_query_results[-1]['result']
    assert result['total_members']==5 and len(result['members'])==2 and result['next_offset']==2
    state=query(DesignQuery(tool='inspect_region',bounds_m=(-1.,-1.,5.,4.),offset=2,limit=2))
    assert state.design_query_results[-1]['result']['members'][0]['member_id']=='wr'
    state=query(DesignQuery(tool='inspect_member',member_id='missing'))
    assert 'error' in state.design_query_results[-1]['result']
    state=query(DesignQuery(tool='get_design_overview'))
    assert 'layout' not in state.design_query_results[-1]['result']
    assert state.design_query_results[-1]['result']['plan_summary']['room_count']==1
    assert state.fea_calls_used==1 and state.layout_id==before.layout_id and env.execution_error is None
    assert all((env.directory/r['evidence_ref']).is_file() for r in state.design_query_results)
    with pytest.raises(ValueError,match='not allowed'):
        env.step(review_decision(env,'PROPOSE_MODIFICATION'))


def test_trial_comparison_uses_source_coverage_when_physical_group_ids_change(tmp_path: Path) -> None:
    import copy
    from struct_agent.services.diagnostics import compare_design_trials
    env=local_env(tmp_path,design_review=True)
    evidence=env._review_evidence(env.verified_results[env.layout_id][0][0])
    before=copy.deepcopy(evidence)
    row=before['member_checks'][0]
    row.update(member_id='old_group',source_member_ids=['a','b'],
        problems=[{'story':1,'shear_passed':False,'reinforcement_passed':True}])
    before['member_checks']=[row]
    after=copy.deepcopy(before)
    after['member_checks']=[dict(row,member_id='new_a',source_member_ids=['a']),
                            dict(row,member_id='new_b',source_member_ids=['b'])]
    result=compare_design_trials(before,after,{'a':'a','b':'b'})
    assert result['failed_source_story_checks_before']==result['failed_source_story_checks_after']==2
    assert not result['new_source_story_checks'] and not result['resolved_source_story_checks']
    after['member_checks'][1]['problems']=[]
    result=compare_design_trials(before,after,{'a':'a','b':'b'})
    assert result['resolved_source_story_checks']==[('b',1,'shear')]


def test_query_trial_is_bound_to_trial_analysis_and_retained_design_stays_current(tmp_path: Path) -> None:
    from struct_agent.schemas.state import DesignQuery
    env=local_env(tmp_path,design_review=True)
    parent=env.layout_id
    env.step(review_decision(env,'PROPOSE_MODIFICATION'))
    state=env.observe()
    state=env.step(Decision(action='QUERY_DESIGN',reason='Inspect real trial',evidence_refs=state.evidence_refs,
        query=DesignQuery(tool='inspect_member',source='trial',member_id='b')))
    result=state.design_query_results[-1]['result']
    assert result['evaluation_id']=='eval_00002' and result['axis_length_m']==pytest.approx(2.1)
    assert state.design_evidence['evaluation_id']=='eval_00001' and state.layout_id==parent and state.fea_calls_used==2


def test_short_beam_axis_coverage_is_not_reported_as_physical_clear_span(tmp_path: Path) -> None:
    from struct_agent.services.diagnostics import inspect_member
    env=local_env(tmp_path,design_review=True)
    evidence=env._review_evidence(env.verified_results[env.layout_id][0][0])
    import copy
    evidence=copy.deepcopy(evidence)
    evidence['layout']['members'][1]['end']=[1.056,3.]
    evidence['layout']['members'].append({'member_id':'perpendicular_wall','role':'wall',
        'start':[1.056,2.],'end':[1.056,4.],'adjacent_room_indices':[0]})
    result=inspect_member(evidence,'b')
    assert result['axis_length_m']==pytest.approx(.056)
    assert all(c['exposed_axis_m']==pytest.approx(0.) for c in result['wall_footprint_axis_coverage'])
    assert result['anomalies']['beam_axis_inside_wall_footprint']
    assert 'clear_span_m' not in result
    row={'start':[1.,3.+1e-13],'end':[3.,3.+1e-13],'role':'beam'}
    provenance={'layout_sha256':evidence['layout_sha256'],'stages':{'before':[row]},
        'preprocessing_beam_chains':[{'members':[row],'axis_chain_length_m':2.}],
        'preprocessing_chain_rule':'synthetic collinear grouping'}
    result=inspect_member(evidence,'b',provenance=provenance)
    assert result['generation_provenance']['stages']['before']==[row]
    assert len(result['generation_provenance']['preprocessing_beam_chains'])==1


def test_generation_provenance_replay_binds_the_whole_layout() -> None:
    import numpy as np
    from tests.unit.test_search_feedback import local_case
    from struct_agent.adapters.rcgnn import layout_from_prediction,trace_layout_generation
    _,rooms,_,_=local_case()
    ratios=np.full((1,16),.4,dtype=np.float32)
    layout=layout_from_prediction(rooms,ratios,layout_id='synthetic_trace')
    trace=trace_layout_generation(rooms,ratios,layout)
    assert trace['verified'] and 'intersection_split' in trace['stages']
    bad=layout.model_copy(update={'source':'mismatched_source'})
    # Replay uses this source label, so geometry, not display metadata, must differ.
    member=bad.members[0].model_copy(update={'end':(bad.members[0].end[0]+.01,bad.members[0].end[1])})
    bad=bad.model_copy(update={'members':(member,)+bad.members[1:]})
    with pytest.raises(ValueError,match='differs'):
        trace_layout_generation(rooms,ratios,bad)


def feedback_fixture(tmp_path: Path, mode: str, budget: int = 8) -> tuple:
    """Synthetic response families validate control flow, never engineering."""
    from dataclasses import fields
    from tests.unit.test_search_feedback import local_case
    from struct_agent.schemas import ProjectSpec, AnalysisRecord
    from struct_agent.io.artifacts import write_json
    from struct_agent.services.analysis import AnalysisService
    from struct_agent._vendor.shearwall_modeling.parametric.types import ParametricAnalysisResult
    layout, rooms, design, diagnostic = local_case()
    spec = ProjectSpec.model_validate_json(Path('configs/reference_spec.json').read_text(encoding='utf-8'))
    spec = spec.model_copy(update={'stories': 3})
    design = design.model_copy(update={'condition_id': spec.condition_id,
        'values': {v.name: v.values[0] for v in spec.design_variables}})
    class Solver:
        fidelity = 'mock'
        analysis_signature = 'synthetic_feedback_only'
        diagnostics_directory = tmp_path/'diagnostics'
        def __init__(self) -> None:
            self.seen: set[str] = set()
        def evaluate(self, candidate, parameters, conditions, *, evaluation_id, detail=True):
            if mode == 'solver_error':
                raise ArithmeticError('Synthetic analysis failure')
            token = json.dumps(parameters.values, sort_keys=True)
            repeat = token in self.seen
            self.seen.add(token)
            grade = parameters.values['conc_bot']
            passed = mode == 'already' or grade != 'C30'
            if mode == 'no_solution':
                passed = False
            if mode == 'geometry_wall_failure':
                passed = grade not in ('C30', 'C35')
            wall_failure = mode == 'geometry_wall_failure' and candidate.members != layout.members
            if wall_failure or (mode == 'verification_error' and repeat):
                passed = False
            ratio = .15 if passed else .24 if grade == 'C30' else .22
            raw = {f.name: _field_default(f) for f in fields(ParametricAnalysisResult)}
            raw.update(feasible=passed, design_passed=passed, design_failed_beam_count=0 if passed else 1,
                design_failed_wall_count=int(wall_failure), material_concrete_kg=100000., material_steel_kg=1000.,
                torsion_ratio=1.2, period_ratio=.8, max_drift_ratio=.0005, max_wall_axial_ratio=.2,
                max_wall_axial_limit=.5, max_wall_shear_ratio=.1, max_wall_shear_limit=.2,
                max_beam_shear_ratio=ratio, max_beam_shear_limit=.2, beam_shear_passed=passed)
            original = diagnostic(1)
            beam = candidate.members[1]
            member = original.model_copy(update={'start_m': beam.start, 'end_m': beam.end,
                'length_m': math.dist(beam.start, beam.end), 'shear_ratio': ratio,
                'shear_n': ratio*original.denominator_n, 'shear_passed': ratio <= .2,
                'reinforcement_passed': passed, 'combo_shear_n': {'test': ratio*original.denominator_n},
                'combo_design_shear_n': {'test': ratio*original.denominator_n}})
            rows = [member.model_dump()]
            if wall_failure:
                wall = candidate.members[0]
                rows.append(member.model_copy(update={'member_id': wall.member_id, 'source_member_ids': (wall.member_id,),
                    'role': 'wall', 'start_m': wall.start, 'end_m': wall.end}).model_dump())
            path = self.diagnostics_directory/evaluation_id
            path.mkdir(parents=True)
            write_json(path/'members.json', {'fidelity': 'mock', 'units': {'length': 'm', 'force': 'N', 'stress': 'Pa'}, 'members': rows})
            return AnalysisRecord(evaluation_id=evaluation_id, layout_id=candidate.layout_id,
                design_id=parameters.design_id, condition_id=conditions.condition_id, fidelity='mock',
                status='SUCCESS', solver='synthetic_only', solver_version='1', elapsed_s=0., feasible=passed,
                raw=raw, error=None)
    import math
    service = AnalysisService(Solver(), budget=budget, directory=tmp_path/'analyses')
    return layout, rooms, spec, design, service


def test_feedback_task_stops_on_already_feasible_and_forced_reanalysis_uses_budget(tmp_path: Path) -> None:
    from struct_agent.workflows.optimization_env import run_feedback_design_task
    layout, rooms, spec, design, service = feedback_fixture(tmp_path, 'already')
    result = run_feedback_design_task(layout, rooms, spec, design, service, directory=tmp_path, seed=42)
    assert result['status'] == 'ALREADY_FEASIBLE' and result['fea_attempts'] == 1
    assert (tmp_path/'parameter_configuration.json').is_file()
    first = service.evaluate(layout, design, spec)
    assert len(service.records) == 1
    again = service.evaluate(layout, design, spec, force_reanalysis=True)
    assert len(service.records) == 2 and first.input_hash == again.input_hash
    assert first.evaluation_id != again.evaluation_id


@pytest.mark.parametrize('mode,status', [('grade', 'FEASIBLE'), ('no_solution', 'BUDGET_EXHAUSTED_NO_FEASIBLE'),
    ('solver_error', 'ANALYSIS_FAILED'), ('verification_error', 'VERIFICATION_FAILED')])
def test_feedback_task_outputs_honest_result_and_shares_final_verification_budget(tmp_path: Path, mode: str, status: str) -> None:
    from struct_agent.workflows.optimization_env import run_feedback_design_task
    layout, rooms, spec, design, service = feedback_fixture(tmp_path, mode, budget=4)
    result = run_feedback_design_task(layout, rooms, spec, design, service, directory=tmp_path, seed=42)
    assert result['status'] == status and result['fea_attempts'] <= 4
    assert result['implemented_checks_passed'] == (status == 'FEASIBLE')
    assert result['engineering_review'] == 'PENDING'
    if status in ('FEASIBLE', 'VERIFICATION_FAILED'):
        assert result['verification']['force_reanalysis'] and result['fea_attempts'] == 3


def test_feedback_task_rejects_new_wall_failure_and_keeps_parameter_search_available(tmp_path: Path) -> None:
    from struct_agent.workflows.optimization_env import run_feedback_design_task
    from struct_agent.schemas.agent import LocalAdjustmentConfig
    layout, rooms, spec, design, service = feedback_fixture(tmp_path, 'geometry_wall_failure', budget=8)
    result = run_feedback_design_task(layout, rooms, spec, design, service, directory=tmp_path, seed=42,
        local_config=LocalAdjustmentConfig(steps_m=(.1,), max_trials=1))
    assert result['status'] == 'FEASIBLE'
    events = [json.loads(p.read_text()) for p in sorted((tmp_path/'events').glob('trial_*.json'))]
    moves = [e for e in events if e['family'] == 'geometry']
    assert len(moves) == 1 and moves[0]['new_wall_failure_slots'] and not moves[0]['retained_for_search']
    selected = json.loads((tmp_path/'selected_layout.json').read_text())
    assert selected == layout.model_dump(mode='json')


def test_feedback_preflight_blocks_new_geometry_issue_before_fea(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from struct_agent.workflows import optimization_env as module
    from struct_agent.schemas.agent import LocalAdjustmentConfig
    from struct_agent.services.model_review import GeometryIssue
    layout, rooms, spec, design, service = feedback_fixture(tmp_path, 'geometry_wall_failure', budget=8)
    original = module.review_geometry
    def review(plan, **kwargs):
        result = original(plan, **kwargs)
        if plan.source == 'member_feedback_wall_tip_move':
            issue = GeometryIssue(code='COLUMN_OR_COMPOSITE_DESIGN_REQUIRED',
                source_member_ids=('wl',), length_m=.9, ratio=3.)
            return result.model_copy(update={'issues': result.issues+(issue,)})
        return result
    monkeypatch.setattr(module, 'review_geometry', review)
    result = module.run_feedback_design_task(layout, rooms, spec, design, service,
        directory=tmp_path, seed=42, local_config=LocalAdjustmentConfig(steps_m=(.1,), max_trials=1))
    assert result['status'] == 'FEASIBLE' and result['fea_attempts'] == 4
    events = [json.loads(p.read_text()) for p in (tmp_path/'events').glob('trial_*.json')]
    blocked = [e for e in events if e['family'] == 'geometry']
    assert len(blocked) == 1 and blocked[0]['rejected_before_fea']
    assert 'analysis_path' not in blocked[0]
