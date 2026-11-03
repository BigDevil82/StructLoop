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


def answer(action: str, state: OptimizationState) -> dict:
    return {"choices": [{"message": {"content": json.dumps({"action": action, "reason": "test evidence",
        "evidence_refs": list(state.evidence_refs), "target_layout_id": "b" if action == "SWITCH_LAYOUT" else None})},
        "finish_reason": "stop"}], "usage": {"total_tokens": 20}}


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


def test_design_review_sends_actual_evidence_and_requires_review(tmp_path: Path) -> None:
    from tests.unit.test_optimization_env import local_env
    env=local_env(tmp_path/'env',design_review=True)
    state=env.observe();requests=[]
    def transport(url,headers,payload,timeout):
        requests.append(payload)
        visible=json.loads(payload['messages'][1]['content'])
        assert 'layout' not in visible['design_evidence'] and 'member_checks' not in visible['design_evidence']
        assert visible['design_evidence']['query_tools']['inspect_member']
        assert visible['design_evidence']['raw_response']['max_beam_shear_ratio']==.196
        decision={'action':'FINALIZE','reason':'No modification needed in this synthetic test',
            'evidence_refs':list(state.evidence_refs),'target_layout_id':None,'modification':None,
            'review':{'diagnosis':'Test checks passed','cause_hypothesis':'No known problem',
                'affected_member_ids':[],'assessment':'Keep the evaluated design','unresolved':['Test only']}}
        if len(requests)==1:decision.pop('review')
        return {'choices':[{'message':{'content':json.dumps(decision)}}]}
    client=ChatClient(ChatConfig(),SecretStr('test-only'),tmp_path/'api',transport=transport)
    decision=LLMPolicy(client,tmp_path/'decisions').choose(state)
    assert len(requests)==2 and decision.review.diagnosis=='Test checks passed'
    assert 'requires diagnosis' in requests[-1]['messages'][-1]['content']
    assert ReplayPolicy(tmp_path/'decisions').choose(state)==decision


@pytest.mark.parametrize("bad", ["not JSON", '{"action":"SHELL","command":"anything"}',
    '{"action":"SWITCH_LAYOUT","reason":"invalid target","evidence_refs":[],"target_layout_id":"invented"}'])
def test_invalid_outputs_fail_closed(tmp_path: Path, state: OptimizationState, bad: str) -> None:
    client = ChatClient(ChatConfig(), SecretStr("test-secret-only"), tmp_path / "calls",
                        transport=lambda *args: {"choices": [{"message": {"content": bad}}]})
    decision = LLMPolicy(client, tmp_path / "decisions").choose(state)
    assert decision.action == "REQUEST_HUMAN_REVIEW" and client.calls == 2
    audit = json.loads((tmp_path / "decisions/decision_00001.json").read_text())
    assert audit["origin"] == "failure_review" and len(audit["errors"]) == 2


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
        return {'choices':[{'message':{'content':json.dumps({'action':'ADJUST_LOCAL_LAYOUT',
            'target_layout_id':candidate,'reason':'test bounded local candidate','evidence_refs':state.evidence_refs})}}]}
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
    content={'action':'ADJUST_LOCAL_LAYOUT','target_layout_id':state.local_layout_choices[0].candidate_id,
        'reason':'synthetic rejection test','evidence_refs':state.evidence_refs,**extra}
    client=ChatClient(ChatConfig(),SecretStr('synthetic-key-only'),tmp_path/'calls',
        transport=lambda *args:{'choices':[{'message':{'content':json.dumps(content)}}]})
    decision=LLMPolicy(client,tmp_path/'decisions').choose(state)
    assert decision.action=='REQUEST_HUMAN_REVIEW' and len(env.evaluator.records)==1
