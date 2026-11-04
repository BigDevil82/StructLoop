import json
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from struct_agent.agents.chat_client import ChatClient, ChatConfig, GatewayError, read_api_key
from struct_agent.agents.policies import FixedPolicy, LLMPolicy, ReplayPolicy, RulePolicy
from struct_agent.schemas.agent import OptimizationState


@pytest.fixture
def state() -> OptimizationState:
    return OptimizationState(case_id="test_only", fidelity="mock", layout_id="a", session_status="paused",
        solver_status="SUCCESS", latest_feasible=False, fea_budget=10, fea_calls_used=2, fea_budget_remaining=8,
        completed_generations=1, stagnation_steps=2, calibration_samples=2, available_layouts=("b",),
        allowed_actions=("CONTINUE_OPTIMIZATION", "SWITCH_LAYOUT", "REQUEST_HUMAN_REVIEW"),
        evidence_refs=("analyses/eval_00002.json",))


def tool_response(name: str, arguments: dict | None = None, *, content: str | None = None) -> dict:
    return {'choices':[{'message':{'content':content,'tool_calls':[{'id':'synthetic_call','type':'function',
        'function':{'name':name,'arguments':json.dumps(arguments or {})}}]},'finish_reason':'tool_calls'}],
        'usage':{'total_tokens':20}}


def answer(action: str, state: OptimizationState) -> dict:
    from struct_agent.agents.policies import ACTION_TO_TOOL
    return tool_response(ACTION_TO_TOOL[action],{'target_layout_id':'b'} if action=='SWITCH_LAYOUT' else {})


def test_fixed_and_rules_diverge_on_stagnation(state: OptimizationState) -> None:
    assert FixedPolicy().choose(state).action == "CONTINUE_OPTIMIZATION"
    assert RulePolicy().choose(state).action == "SWITCH_LAYOUT"


def test_valid_llm_and_exact_replay(tmp_path: Path, state: OptimizationState) -> None:
    client = ChatClient(ChatConfig(), SecretStr("test-secret-only"), tmp_path / "calls",
                        transport=lambda *args: answer("SWITCH_LAYOUT", state))
    policy = LLMPolicy(client, tmp_path / "decisions")
    decision = policy.choose(state)
    assert decision.action == "SWITCH_LAYOUT" and client.total_tokens == 20
    assert ReplayPolicy(tmp_path / "decisions").choose(state) == decision
    with pytest.raises(ValueError, match="Replay state"):
        ReplayPolicy(tmp_path / "decisions").choose(state.model_copy(update={"stagnation_steps": 3}))


@pytest.mark.parametrize('thinking',['enabled','disabled'])
def test_feasible_design_finishes_with_empty_arguments_and_no_review(tmp_path: Path, thinking: str) -> None:
    from tests.unit.test_optimization_env import local_env
    env=local_env(tmp_path/'env',design_review=True)
    state=env.observe()
    def transport(url,headers,payload,timeout):
        visible=json.loads(payload['messages'][1]['content'])
        assert 'layout' not in visible['design_evidence'] and 'member_checks' not in visible['design_evidence']
        assert visible['design_evidence']['raw_response']['max_beam_shear_ratio']==.196
        assert payload['tool_choice']=='required' and payload['parallel_tool_calls'] is False
        assert payload['thinking']=={'type':thinking}
        assert payload['reasoning_effort']==('high' if thinking=='enabled' else 'none')
        assert not any(t['function']['name']=='set_design_parameters' for t in payload['tools'])
        return tool_response('finish_design')
    client=ChatClient(ChatConfig(thinking=thinking),SecretStr('test-only'),tmp_path/'api',transport=transport)
    decision=LLMPolicy(client,tmp_path/'decisions').choose(state)
    assert decision.action=='FINALIZE' and decision.review is None and decision.reason=='tool:finish_design'
    env.step(decision)
    assert env.status=='COMPLETED' and len(env.evaluator.records)==1
    assert ReplayPolicy(tmp_path/'decisions').choose(state)==decision


def test_llm_receives_queries_parameter_trial_and_makes_explicit_adoption(tmp_path: Path) -> None:
    from tests.unit.test_optimization_env import local_env
    env = local_env(tmp_path/'env', design_review=True, allow_parameter_edits=True)
    requests = []
    def transport(url, headers, payload, timeout):
        visible = json.loads(payload['messages'][-1]['content'])
        requests.append(visible)
        n = len(requests)
        if n>1:
            assert payload['messages'][-1]['role']=='tool'
            assert payload['messages'][-1]['tool_call_id']==payload['messages'][-2]['tool_calls'][0]['id']
        # No tool accepts free-form engineering prose or asks the model to copy evidence hashes.
        assert not any(key in json.dumps(payload['tools']) for key in ('expected_effect','diagnosis','cause_hypothesis','evidence_refs'))
        if n in (1,3):
            return tool_response('inspect_member',{'member_id':'b','source':'current' if n==1 else 'trial'})
        if n==2:
            actual = visible['design_query_results'][-1]['result']
            assert actual['members'][0]['member_id']=='b' and actual['endpoint_connections']
            return tool_response('set_design_parameters',{'parameter_updates':{'conc_bot':'C35'},'inspected_member_ids':['b']})
        if n==4:
            feedback = visible['modification_feedback']
            assert feedback['changed_parameters']=={'conc_bot':{'before':'C30','after':'C35'}}
            assert visible['design_query_results'][-1]['query']['source']=='trial'
            assert visible['design_query_results'][-1]['result']['checks'][0]['concrete_grade']=='C35'
            assert feedback['after']['raw_response']['max_beam_shear_ratio']==.13
            return tool_response('accept_modification')
        assert visible['design_evidence']['design']['values']['conc_bot']=='C35'
        assert not visible['design_query_results']
        return tool_response('finish_design')
    client = ChatClient(ChatConfig(), SecretStr('synthetic-only'), tmp_path/'api', transport=transport)
    policy = LLMPolicy(client, tmp_path/'decisions')
    states = []
    for _ in range(5):
        state = env.observe();decision = policy.choose(state)
        assert decision.review is None and decision.tool_call_id
        if decision.modification:assert decision.modification.expected_effect is None
        states.append((state, decision));env.step(decision)
    replay = ReplayPolicy(tmp_path/'decisions')
    assert all(replay.choose(state)==decision for state, decision in states)
    assert env.status=='COMPLETED' and len(env.evaluator.records)==2 and len(requests)==5
    assert [p['action_history'][-1] for p in requests[1:]]==[
        'QUERY_DESIGN','PROPOSE_MODIFICATION','QUERY_DESIGN','ACCEPT_MODIFICATION']


@pytest.mark.parametrize('bad', ['extra','missing','wrong_type'])
def test_bad_tool_arguments_are_returned_as_tool_errors_without_fea(tmp_path: Path, state: OptimizationState, bad: str) -> None:
    args={'target_layout_id':'b'}
    if bad=='extra':args['reason']='Unrequested prose'
    elif bad=='missing':args={}
    else:args={'target_layout_id':42}
    requests=[]
    def transport(url,headers,payload,timeout):
        requests.append(payload)
        return tool_response('switch_layout',args) if len(requests)==1 else tool_response('request_human_review')
    client=ChatClient(ChatConfig(),SecretStr('synthetic-only'),tmp_path/'api',transport=transport)
    decision=LLMPolicy(client,tmp_path/'decisions').choose(state)
    assert decision.action=='REQUEST_HUMAN_REVIEW' and decision.review is None
    assert len(requests)==2 and requests[1]['messages'][-1]['role']=='tool'
    assert 'error' in json.loads(requests[1]['messages'][-1]['content'])


@pytest.mark.parametrize('mode',['text','multiple','missing','unknown','truncated'])
def test_gateway_rejects_non_tool_and_ambiguous_output(tmp_path: Path, state: OptimizationState, mode: str) -> None:
    response=tool_response('continue_optimization')
    msg=response['choices'][0]['message']
    if mode=='text':msg['content']='An unsolicited explanation'
    elif mode=='multiple':msg['tool_calls']*=2
    elif mode=='missing':msg['tool_calls']=[]
    elif mode=='unknown':msg['tool_calls'][0]['function']['name']='execute_shell'
    else:response['choices'][0]['finish_reason']='length'
    client=ChatClient(ChatConfig(),SecretStr('synthetic-only'),tmp_path/'api',transport=lambda *a:response)
    decision=LLMPolicy(client,tmp_path/'decisions').choose(state)
    assert decision.action=='REQUEST_HUMAN_REVIEW' and client.calls==1
    assert json.loads((tmp_path/'decisions/decision_00001.json').read_text())['origin']=='failure_review'


def test_infeasible_design_cannot_finish_and_proposal_needs_current_inspection(tmp_path: Path) -> None:
    from tests.unit.test_optimization_env import local_env
    from struct_agent.agents.policies import decision_tools,decision_from_tool_call
    env=local_env(tmp_path,design_review=True,allow_parameter_edits=True)
    state=env.observe().model_copy(update={'current_best_feasible':False})
    names={t['function']['name'] for t in decision_tools(state)}
    assert 'finish_design' not in names and 'set_design_parameters' not in names and 'move_wall_tip' not in names
    for name in ('finish_design','set_design_parameters'):
        call=tool_response(name)['choices'][0]['message']['tool_calls'][0]
        with pytest.raises(ValueError,match='unavailable'):decision_from_tool_call(call,state)
    assert len(env.evaluator.records)==1


def test_wall_tool_reuses_geometry_and_adoption_gates_without_review_text(tmp_path: Path) -> None:
    from tests.unit.test_optimization_env import local_env
    from struct_agent.agents.policies import decision_from_tool_call
    env=local_env(tmp_path,design_review=True)
    def apply(name,args):
        call=tool_response(name,args)['choices'][0]['message']['tool_calls'][0]
        return env.step(decision_from_tool_call(call,env.observe()))
    apply('inspect_member',{'member_id':'b'})
    state=apply('move_wall_tip',{'target_member_id':'wr','connected_member_id':'b','endpoint':'start','delta_length_m':-.1})
    assert state.modification_feedback['eligible_for_adoption']
    parent=env.layout_id
    apply('reject_modification',{})
    assert env.layout_id==parent and len(env.evaluator.records)==2


@pytest.mark.parametrize('mode',['reject','fail'])
def test_native_tools_cannot_adopt_a_worse_or_failed_trial(tmp_path: Path, mode: str) -> None:
    from tests.unit.test_optimization_env import local_env
    from struct_agent.agents.policies import decision_from_tool_call,decision_tools
    env=local_env(tmp_path,design_review=True,mode=mode)
    parent=env.layout_id
    for name,args in [('inspect_member',{'member_id':'b'}),
        ('move_wall_tip',{'target_member_id':'wr','connected_member_id':'b','endpoint':'start','delta_length_m':-.1})]:
        call=tool_response(name,args)['choices'][0]['message']['tool_calls'][0]
        env.step(decision_from_tool_call(call,env.observe()))
    state=env.observe()
    assert not state.modification_feedback['eligible_for_adoption']
    assert 'accept_modification' not in {t['function']['name'] for t in decision_tools(state)}
    call=tool_response('accept_modification')['choices'][0]['message']['tool_calls'][0]
    with pytest.raises(ValueError,match='unavailable'):decision_from_tool_call(call,state)
    assert env.layout_id==parent and len(env.evaluator.records)==2


def test_nontext_truncated_response_preserves_known_token_usage(tmp_path: Path) -> None:
    from struct_agent.agents.chat_client import GatewayError
    response = {'choices':[{'message':{'content':None},'finish_reason':'length'}],
        'usage':{'prompt_tokens':12,'completion_tokens':18,'total_tokens':30}}
    client = ChatClient(ChatConfig(), SecretStr('synthetic-only'), tmp_path/'api',
        transport=lambda *args: response)
    with pytest.raises(GatewayError,match='not text'):
        client.complete([{'role':'user','content':'Synthetic request'}])
    assert client.total_tokens==30 and client.calls==1
    audit = json.loads((tmp_path/'api/call_00001.json').read_text())
    assert audit['response_metadata']['usage']['total_tokens']==30


@pytest.mark.parametrize("bad", ["not JSON", '{"action":"SHELL","command":"anything"}',
    '{"action":"SWITCH_LAYOUT","reason":"invalid target","evidence_refs":[],"target_layout_id":"invented"}'])
def test_invalid_outputs_fail_closed(tmp_path: Path, state: OptimizationState, bad: str) -> None:
    client = ChatClient(ChatConfig(), SecretStr("test-secret-only"), tmp_path / "calls",
                        transport=lambda *args: {"choices": [{"message": {"content": bad}}]})
    decision = LLMPolicy(client, tmp_path / "decisions").choose(state)
    assert decision.action == "REQUEST_HUMAN_REVIEW" and client.calls == 1
    audit = json.loads((tmp_path / "decisions/decision_00001.json").read_text())
    assert audit["origin"] == "failure_review" and len(audit["errors"]) == 1


def test_transient_retry_and_secret_redaction(tmp_path: Path, state: OptimizationState) -> None:
    secret = "unit-test-private-value"
    attempts = []
    def transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
        assert headers["Authorization"] == "Bearer " + secret
        attempts.append(1)
        if len(attempts) == 1:
            raise GatewayError("Echoed credential " + secret, status=503)
        response = answer("CONTINUE_OPTIMIZATION", state)
        response["id"] = secret
        return response
    client = ChatClient(ChatConfig(), SecretStr(secret), tmp_path / "calls", transport=transport)
    assert LLMPolicy(client, tmp_path / "decisions").choose(state).action == "CONTINUE_OPTIMIZATION"
    assert client.calls == 2
    for path in tmp_path.rglob("*.json"):
        assert secret not in path.read_text(encoding="utf-8")
    audit = json.loads((tmp_path / "calls/call_00001.json").read_text())
    assert audit["error"]["status"] == 503 and audit["error"]["traceback"]


def test_403_is_not_retried_or_disguised(tmp_path: Path, state: OptimizationState) -> None:
    def blocked(*args: object) -> dict:
        raise GatewayError("network not supported", status=403)
    client = ChatClient(ChatConfig(), SecretStr("test-secret-only"), tmp_path / "calls", transport=blocked)
    assert LLMPolicy(client, tmp_path / "decisions").choose(state).action == "REQUEST_HUMAN_REVIEW"
    assert client.calls == 1
    assert json.loads((tmp_path / "decisions/decision_00001.json").read_text())["errors"][0]["status"] == 403


def test_credentials_are_literal_and_never_loaded_into_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("apikey", raising=False)
    path = tmp_path / ".env"
    path.write_text("# comment\napikey='literal-test-only'\n", encoding="utf-8")
    assert read_api_key(path, "apikey").get_secret_value() == "literal-test-only"
    import os
    assert "apikey" not in os.environ
    monkeypatch.setenv("apikey", "explicit-env-value")
    assert read_api_key(path, "apikey").get_secret_value() == "explicit-env-value"


@pytest.mark.parametrize("url", ["http://example.org/v1", "https://user:password@example.org/v1", "https://example.org/v1?key=secret"])
def test_gateway_rejects_unsafe_configuration(url: str) -> None:
    with pytest.raises(ValidationError):
        ChatConfig(base_url=url)


def test_llm_selects_only_generated_local_candidate_and_replays_exact_state(tmp_path: Path) -> None:
    from tests.unit.test_optimization_env import local_env
    env=local_env(tmp_path/'env')
    state=env.observe();candidate=state.local_layout_choices[0].candidate_id
    def transport(*args):
        return tool_response('adjust_local_layout',{'target_layout_id':candidate})
    client=ChatClient(ChatConfig(),SecretStr('synthetic-key-only'),tmp_path/'calls',transport=transport)
    decision=LLMPolicy(client,tmp_path/'decisions').choose(state)
    assert decision.target_layout_id==candidate
    assert ReplayPolicy(tmp_path/'decisions').choose(state)==decision
    after=env.step(decision)
    assert after.local_adjustment_history[-1].accepted and after.fidelity=='mock'


@pytest.mark.parametrize('extra',[{'coordinates':[[0.,0.],[1.,1.]]},{'target_layout_id':'invented_candidate'}])
def test_llm_cannot_supply_coordinates_or_invent_local_candidates(tmp_path: Path,extra: dict) -> None:
    from tests.unit.test_optimization_env import local_env
    env=local_env(tmp_path/'env');state=env.observe()
    arguments={'target_layout_id':state.local_layout_choices[0].candidate_id,**extra}
    client=ChatClient(ChatConfig(),SecretStr('synthetic-key-only'),tmp_path/'calls',
        transport=lambda *args:tool_response('adjust_local_layout',arguments))
    decision=LLMPolicy(client,tmp_path/'decisions').choose(state)
    assert decision.action=='REQUEST_HUMAN_REVIEW' and len(env.evaluator.records)==1
