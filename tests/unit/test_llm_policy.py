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
