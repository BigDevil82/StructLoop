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
