"""Real FuseGNN weights/current engineering geometry, explicitly SYNTHETIC FEA.

These tests validate continuation mechanics only, never engineering feasibility.
"""
from dataclasses import asdict
import json
from pathlib import Path

import pytest
import torch

from struct_agent.adapters.casino import CasinoConfig, create_optimizer
from struct_agent.adapters.casino_session import CasinoSession
from struct_agent.cli import load_assets
from struct_agent.io.artifacts import create_run, json_safe, write_json
from struct_agent.io.case import load_generation_case
from struct_agent.schemas import AnalysisRecord, DesignCandidate, LayoutCandidate, ProjectSpec, RoomGraph
from struct_agent.services.analysis import AnalysisService
from struct_agent._vendor.shearwall_modeling.parametric.types import ParametricAnalysisResult

pytestmark = pytest.mark.real


class SyntheticNativeResponseSolver:
    """Fabricated responses with native field names; confined to tests."""
    fidelity = "mock"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def evaluate(self, layout: LayoutCandidate, design: DesignCandidate, spec: ProjectSpec,
                 *, evaluation_id: str) -> AnalysisRecord:
        if self.fail:
            raise RuntimeError("Injected mock solver failure")
        thickness = float(design.values["tw_bot"])
        passed = thickness >= 0.3
        steel = 1000. * sum(float(v) for k, v in design.values.items() if k != "conc_bot")
        raw = ParametricAnalysisResult(converged=True, feasible=passed, design_passed=passed,
            design_failed_beam_count=0, design_failed_wall_count=0 if passed else 1,
            material_concrete_kg=100000. + steel * 5., material_steel_kg=steel, mass_total_t=1000.,
            T1=1.0, T2=0.9, T3=0.8, T4=0.7, T5=0.6, T6=0.5, period_ratio=0.8, torsion_ratio=1.0,
            min_shear_weight_ratio=0.1, max_drift_ratio=0.0005 if passed else 0.002,
            min_stiffness_ratio=1.0, max_wall_axial_ratio=0.3, max_wall_axial_limit=0.6,
            max_wall_shear_ratio=0.2, max_wall_shear_limit=1.0, max_beam_shear_ratio=0.2,
            max_beam_shear_limit=1.0, drift_passed=passed)
        return AnalysisRecord(evaluation_id=evaluation_id, layout_id=layout.layout_id,
            condition_id=spec.condition_id, design_id=design.design_id, fidelity="mock",
            status="SUCCESS", solver="synthetic_native_response_TEST_ONLY", solver_version="1",
            elapsed_s=0.0, feasible=passed, raw=asdict(raw), error=None)


@pytest.fixture
def case_inputs() -> tuple[LayoutCandidate, RoomGraph, ProjectSpec, CasinoConfig]:
    case, _ = load_generation_case(Path("configs/test_case.json"))
    run = Path("outputs/residential_001_rcgnn_01")
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["inputs"]["dxf"]["sha256"] == case.sha256
    layout = LayoutCandidate.model_validate_json((run / "layout.json").read_text(encoding="utf-8"))
    rooms = RoomGraph.model_validate_json((run / "room_graph.json").read_text(encoding="utf-8"))
    spec = ProjectSpec.model_validate_json(Path("configs/reference_spec.json").read_text(encoding="utf-8"))
    weights = load_assets(Path("configs/local_assets.json"), names=("feasibility", "steel"))
    cfg = CasinoConfig(feasibility_weights=weights["feasibility"], steel_weights=weights["steel"],
        seed=42, population_size=8, generations=3, min_eval_count=4, screening_threshold=0.0,
        calibration_min_samples=4)
    return layout, rooms, spec, cfg


def make_service(directory: Path, cfg: CasinoConfig, *, budget: int = 100, fail: bool = False) -> AnalysisService:
    create_run(directory, seed=cfg.seed, inputs={"case": Path("configs/test_case.json"),
        "layout": Path("outputs/residential_001_rcgnn_01/layout.json"),
        "rooms": Path("outputs/residential_001_rcgnn_01/room_graph.json"),
        "spec": Path("configs/reference_spec.json"), "feasibility": cfg.feasibility_weights,
        "steel": cfg.steel_weights}, config={"fidelity": "mock", "test": "CASINO continuation only",
        "notice": "SYNTHETIC FEA; NOT ENGINEERING RESULTS", "casino": cfg.model_dump(mode="json"),
        "budget": budget, "injected_solver_failure": fail})
    return AnalysisService(SyntheticNativeResponseSolver(fail=fail), budget=budget, directory=directory / "analyses")


def test_real_surrogates_chunked_match_native(case_inputs: tuple, tmp_path: Path) -> None:
    layout, rooms, spec, cfg = case_inputs
    native_service = make_service(tmp_path / "native", cfg)
    before_rng = torch.random.get_rng_state().clone()
    native = create_optimizer(layout, rooms, spec, native_service, cfg, directory=tmp_path / "native/optimization")
    assert torch.equal(before_rng, torch.random.get_rng_state())
    expected = native.optimize()
    write_json(tmp_path / "native/result.json", {"fidelity": "mock", "result": asdict(expected)})
    for name, chunks in (("continuous", (3,)), ("chunked", (1, 1, 1))):
        root = tmp_path / name
        service = make_service(root, cfg)
        session = CasinoSession(layout, rooms, spec, service, cfg, directory=root / "optimization")
        calibrator = session.optimizer.evaluator.local_calibrator
        previous_calls = 0
        for n in chunks:
            summary = session.advance(n)
            assert session.optimizer.evaluator.local_calibrator is calibrator
            snapshot = json.loads((root / f"optimization/steps/advance_{session.advance_count:05d}.json").read_text())
            assert snapshot["fea_attempts_delta"] == len(service.records) - previous_calls
            previous_calls = len(service.records)
        assert summary["termination"] == "completed" and summary["fidelity"] == "mock"
        assert json_safe(asdict(session.engine.result)) == json_safe(asdict(expected))
        assert [r.model_dump() for r in service.records] == [r.model_dump() for r in native_service.records]
        assert session.optimizer.rng.getstate() == native.rng.getstate()
        assert calibrator._records == native.evaluator.local_calibrator._records
        assert session.optimizer.evaluator.local_summary() == native.evaluator.local_summary()
        assert calibrator._feas_model is not None and calibrator._steel_model is not None
        with pytest.raises(RuntimeError, match="completed"):
            session.advance(1)


@pytest.mark.parametrize("failure", [False, True])
def test_session_failure_and_budget_are_terminal(case_inputs: tuple, tmp_path: Path, failure: bool) -> None:
    layout, rooms, spec, cfg = case_inputs
    service = make_service(tmp_path / "run", cfg, budget=1, fail=failure)
    session = CasinoSession(layout, rooms, spec, service, cfg, directory=tmp_path / "run/optimization")
    summary = session.advance(1)
    assert summary["termination"] == ("analysis_failed" if failure else "budget_exhausted")
    assert summary["fea_attempts"] == 1 and not summary["history_complete"]
    assert summary["error"]["traceback"] and summary["error"]["attempt"] == 1
    assert session.optimizer.evaluator.local_calibrator.sample_count == 0
    if failure:
        assert service.records[0].feasible is None and summary["best_feasible"] is None
        assert summary["error"]["error_type"] == "RuntimeError"
    with pytest.raises(RuntimeError):
        session.advance(1)
    assert len(service.records) == 1


def test_layout_sessions_keep_calibration_separate(case_inputs: tuple, tmp_path: Path) -> None:
    layout, rooms, spec, cfg = case_inputs
    service = make_service(tmp_path / "run", cfg)
    first = CasinoSession(layout, rooms, spec, service, cfg, directory=tmp_path / "run/first")
    first.advance(1)
    old_records = dict(first.optimizer.evaluator.local_calibrator._records)
    assert old_records
    # Predefined geometry perturbation for isolation only; NOT an approved candidate.
    wall = next(member for member in layout.members if member.role == "wall")
    shortened = wall.model_copy(update={"end": tuple((a + b) / 2 for a, b in zip(wall.start, wall.end))})
    alternate = LayoutCandidate.model_validate({**layout.model_dump(), "layout_id": "isolation_test_only",
        "members": tuple(shortened if member.member_id == wall.member_id else member for member in layout.members)})
    second = CasinoSession(alternate, rooms, spec, service, cfg, directory=tmp_path / "run/second")
    assert first.binding["layout_sha256"] != second.binding["layout_sha256"]
    assert second.optimizer.evaluator.local_calibrator.sample_count == 0
    assert second.summary()["fea_attempts"] == 0
    assert second.summary()["global_fea_attempts"] == len(service.records)
    second.advance(1)
    assert first.optimizer.evaluator.local_calibrator._records == old_records
    assert second.optimizer.evaluator.local_calibrator is not first.optimizer.evaluator.local_calibrator
    with pytest.raises(FileExistsError):
        CasinoSession(layout, rooms, spec, service, cfg, directory=tmp_path / "run/first")
