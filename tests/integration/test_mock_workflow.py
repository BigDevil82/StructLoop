import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from struct_agent.adapters.mock import MockSolver
from struct_agent.io.artifacts import write_json
from struct_agent.schemas.state import Decision, DecisionEvent, MockCase
from struct_agent.services.analysis import AnalysisService
from struct_agent.workflows.environment import MockDesignEnv
from struct_agent.workflows.mock_case import make_mock_case
from struct_agent.workflows.policy import choose_decision
from struct_agent.workflows.runner import run_mock_case


@pytest.fixture
def case_path(tmp_path: Path) -> Path:
    path = tmp_path / "case.json"
    write_json(path, make_mock_case().model_dump())
    return path


def events(directory: Path) -> list[DecisionEvent]:
    return [DecisionEvent.model_validate_json(line)
            for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def test_switch_trace_budget_and_deterministic_replay(case_path: Path, tmp_path: Path) -> None:
    original = case_path.read_bytes()
    runs = [tmp_path / name for name in ("first", "replay")]
    for directory in runs:
        state = run_mock_case(case_path, directory, seed=42, budget=4,
                              approved_mock_layouts=("layout_b",))
        assert state.status == "COMPLETED"
        assert state.fidelity == "mock" and state.feasible is True
        assert state.fea_calls_used == 4 and state.fea_budget_remaining == 0
        assert state.best_feasible_design_id == "layout_b_1"
        assert state.best_feasible_objective == pytest.approx(4.8)
        trace = events(directory)
        assert [event.decision.action if event.decision else event.kind for event in trace] == [
            "CONTINUE_OPTIMIZATION", "CONTINUE_OPTIMIZATION", "SWITCH_LAYOUT", "mock_approval",
            "CONTINUE_OPTIMIZATION", "CONTINUE_OPTIMIZATION", "FINALIZE"]
        assert sum(event.fea_calls_delta for event in trace) == 4
        assert trace[3].after.feasible is None and trace[3].after.constraint_ratios == {}
        assert trace[3].after.candidate_cursors == {"layout_a": 2, "layout_b": 0}
        for event in trace:
            for ref in event.decision.evidence_refs if event.decision else ():
                assert (directory / ref).is_file()
            if event.analysis_ref:
                record = json.loads((directory / event.analysis_ref).read_text(encoding="utf-8"))["analysis"]
                assert record["fidelity"] == "mock"
        assert len(list((directory / "states").glob("*.json"))) == len(trace) + 1
    assert (runs[0] / "events.jsonl").read_bytes() == (runs[1] / "events.jsonl").read_bytes()
    assert case_path.read_bytes() == original
    with pytest.raises(FileExistsError):
        run_mock_case(case_path, runs[0], seed=42, budget=4)


def test_default_runner_pauses_for_approval(case_path: Path, tmp_path: Path) -> None:
    state = run_mock_case(case_path, tmp_path / "paused", seed=42, budget=4)
    assert state.status == "WAITING_APPROVAL" and state.pending_layout_id == "layout_b"
    assert state.current_layout_id == "layout_a" and state.fea_calls_used == 2


def test_illegal_actions_and_in_process_approval(tmp_path: Path) -> None:
    service = AnalysisService(MockSolver(), budget=4, directory=tmp_path / "analyses")
    env = MockDesignEnv(make_mock_case(), service, tmp_path)
    with pytest.raises(ValueError, match="stopping condition"):
        env.step(Decision(action="FINALIZE", reason="premature"))
    for _ in range(2):
        env.step(choose_decision(env, allow_switch=True))
    before = env.state.model_dump_json()
    with pytest.raises(ValueError, match="evidence"):
        env.step(Decision(action="SWITCH_LAYOUT", target_layout_id="layout_b", reason="no evidence"))
    with pytest.raises(ValueError, match="Unknown/visited"):
        env.step(Decision(action="SWITCH_LAYOUT", target_layout_id="missing", reason="invalid",
                          evidence_refs=(env.state.latest_analysis_ref,)))
    assert before == env.state.model_dump_json() and len(service.records) == 2
    env.step(choose_decision(env, allow_switch=True))
    with pytest.raises(ValueError, match="WAITING_APPROVAL"):
        env.step(Decision(action="CONTINUE_OPTIMIZATION", reason="bypass gate"))
    with pytest.raises(ValueError, match="pending layout"):
        env.approve_mock_layout("layout_a", reviewer="test")
    assert len(service.records) == 2
    env.approve_mock_layout("layout_b", reviewer="test_simulation_only")
    env.step(choose_decision(env, allow_switch=True))
    assert env.state.current_design_id == "layout_b_0" and len(service.records) == 3


@pytest.mark.parametrize("budget", [1, 2, 3])
def test_budget_is_shared_across_layouts(case_path: Path, tmp_path: Path, budget: int) -> None:
    directory = tmp_path / "limited"
    state = run_mock_case(case_path, directory, seed=42, budget=budget,
                          approved_mock_layouts=("layout_b",))
    assert state.status == "BUDGET_EXHAUSTED" and state.feasible is False
    assert state.fea_calls_used == budget
    assert len(list((directory / "analyses").glob("*.json"))) == budget


def test_solver_failure_is_unknown_and_requires_review(tmp_path: Path) -> None:
    case = MockCase.model_validate({**make_mock_case().model_dump(),
                                    "failure_design_ids": ("layout_a_0",)})
    path = tmp_path / "failure_case.json"
    write_json(path, case.model_dump())
    directory = tmp_path / "failed_run"
    state = run_mock_case(path, directory, seed=42, budget=4, approved_mock_layouts=("layout_b",))
    assert state.status == "AWAITING_REVIEW" and state.solver_status == "SOLVER_ERROR"
    assert state.feasible is None and state.fea_calls_used == 1
    assert state.current_layout_id == "layout_a" and state.constraint_ratios == {}
    record = json.loads((directory / state.latest_analysis_ref).read_text(encoding="utf-8"))["analysis"]
    assert record["error"]["error_type"] == "MockSolverError"
    assert "Explicit synthetic failure" in record["error"]["message"]
    assert record["error"]["traceback"] and record["error"]["attempt"] == 1
    assert events(directory)[-1].decision.action == "REQUEST_HUMAN_REVIEW"


def test_fixed_policy_remains_in_original_layout(case_path: Path, tmp_path: Path) -> None:
    state = run_mock_case(case_path, tmp_path / "fixed", seed=42, budget=4, policy="fixed")
    assert state.status == "NO_MORE_CANDIDATES" and state.feasible is False
    assert state.current_layout_id == "layout_a" and state.fea_calls_used == 2


def test_real_fidelity_is_rejected_before_creating_run(tmp_path: Path) -> None:
    path = tmp_path / "not_mock.json"
    write_json(path, {**make_mock_case().model_dump(), "fidelity": "full"})
    directory = tmp_path / "invalid"
    with pytest.raises(ValidationError):
        run_mock_case(path, directory, seed=42, budget=4)
    assert not directory.exists()
