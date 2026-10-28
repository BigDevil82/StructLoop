"""Auditable execution of a synthetic case, independent of weights and real FEA."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from struct_agent.adapters.mock import MockSolver
from struct_agent.io.artifacts import create_run, write_json
from struct_agent.schemas.state import DesignState, MockCase
from struct_agent.services.analysis import AnalysisService
from .environment import MockDesignEnv
from .policy import choose_decision


def run_mock_case(case_path: Path, directory: Path, *, seed: int, budget: int,
                  policy: Literal["scripted", "fixed"] = "scripted",
                  approved_mock_layouts: tuple[str, ...] = ()) -> DesignState:
    case = MockCase.model_validate_json(case_path.read_text(encoding="utf-8"))
    if budget < 1 or policy not in ("scripted", "fixed"):
        raise ValueError("Positive budget and scripted/fixed policy required")
    if not set(approved_mock_layouts) <= {item.layout_id for item in case.layouts}:
        raise ValueError("Unknown mock approval target")
    create_run(directory, seed=seed, inputs={"case": case_path}, config={
        "fidelity": "mock", "scenario": case.scenario, "policy": policy, "budget": budget,
        "approved_mock_layouts": approved_mock_layouts,
        "seed_usage": "recorded; fixture and policies are deterministic without random sampling"})
    write_json(directory / "case.json", case.model_dump())
    service = AnalysisService(MockSolver(failure_design_ids=case.failure_design_ids),
                              budget=budget, directory=directory / "analyses")
    env = MockDesignEnv(case, service, directory)
    # Each iteration consumes a candidate, changes layout once, or terminates.
    while env.state.status == "RUNNING":
        env.step(choose_decision(env, allow_switch=policy == "scripted"))
        if env.state.status == "WAITING_APPROVAL" and env.state.pending_layout_id in approved_mock_layouts:
            env.approve_mock_layout(env.state.pending_layout_id, reviewer="explicit_mock_run_configuration")
    write_json(directory / "summary.json", {"fidelity": "mock", "engineering_review": "NOT_PERFORMED",
        "notice": "SYNTHETIC TEST DATA; NOT STRUCTURAL ANALYSIS", "state": env.state.model_dump()})
    return env.state
