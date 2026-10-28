import json
from pathlib import Path

import pytest

from struct_agent.evaluation.compare import comparison
from struct_agent.io.artifacts import write_json


def make_run(root: Path, policy: str, *, budget: int = 2) -> Path:
    root.mkdir()
    (root / "analyses").mkdir()
    (root / "events").mkdir()
    write_json(root / "manifest.json", {"seed": 42, "software": {}, "code_sha256": "same",
        "inputs": {"layout_0": {"sha256": "same"}},
        "config": {"policy": policy, "budget": budget, "purpose": "smoke_only"}})
    write_json(root / "analyses/eval_00001.json", {"analysis": {"fidelity": "mock",
        "status": "SOLVER_ERROR", "feasible": None, "elapsed_s": 1.}})
    write_json(root / "summary.json", {"status": "AWAITING_REVIEW", "elapsed_s": 2.,
        "api_calls": 0, "api_total_tokens": 0, "state": {"fidelity": "mock", "fea_calls_used": 1,
        "best_feasible_cost": None}})
    return root


def test_retains_failed_runs_and_missing_cost(tmp_path: Path) -> None:
    rows = comparison((make_run(tmp_path / "a", "fixed"), make_run(tmp_path / "b", "rules")))["runs"]
    assert len(rows) == 2
    assert all(r["fea_failures"] == 1 and r["best_feasible_cost"] is None for r in rows)


def test_rejects_unequal_conditions(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="differ"):
        comparison((make_run(tmp_path / "a", "fixed"), make_run(tmp_path / "b", "rules", budget=3)))
