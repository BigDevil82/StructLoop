from pathlib import Path
from types import SimpleNamespace

import pytest

from struct_agent.adapters.casino import CasinoConfig, create_optimizer
from struct_agent.schemas import AnalysisRecord, DesignCandidate, LayoutCandidate, ProjectSpec, RoomGraph
from struct_agent.services.analysis import AnalysisService


class VersionedTestSolver:
    fidelity = 'mock'
    analysis_signature = 'corrected-test-a'

    def evaluate(self, layout: LayoutCandidate, design: DesignCandidate, spec: ProjectSpec, *, evaluation_id: str) -> AnalysisRecord:
        return AnalysisRecord(evaluation_id=evaluation_id, layout_id=layout.layout_id, condition_id=spec.condition_id,
            design_id=design.design_id, fidelity='mock', status='SUCCESS', feasible=False, raw={}, error=None,
            solver='TEST_ONLY', solver_version='1', elapsed_s=0.)


def test_cache_is_bound_to_analysis_implementation(tmp_path: Path, layout: LayoutCandidate, design: DesignCandidate, spec: ProjectSpec) -> None:
    solver = VersionedTestSolver()
    service = AnalysisService(solver, budget=2, directory=tmp_path/'analyses')
    first = service.evaluate(layout, design, spec)
    assert service.evaluate(layout, design, spec) is first
    solver.analysis_signature = 'corrected-test-b'
    second = service.evaluate(layout, design, spec)
    assert second.input_hash != first.input_hash and len(service.records) == 2


def test_mismatched_surrogate_cannot_filter_real_analysis(tmp_path: Path, layout: LayoutCandidate, rooms: RoomGraph, spec: ProjectSpec) -> None:
    service = AnalysisService(SimpleNamespace(fidelity='full', analysis_signature='current'), budget=1, directory=tmp_path/'analyses')
    cfg = CasinoConfig(seed=42, use_surrogate=True, surrogate_analysis_signature='old')
    with pytest.raises(ValueError, match='surrogate training physics'):
        create_optimizer(layout, rooms, spec, service, cfg, directory=tmp_path/'optimizer')


def test_default_optimization_has_no_unverified_surrogate(tmp_path: Path, layout: LayoutCandidate, rooms: RoomGraph, spec: ProjectSpec) -> None:
    service = AnalysisService(VersionedTestSolver(), budget=1, directory=tmp_path/'analyses')
    optimizer = create_optimizer(layout, rooms, spec, service, CasinoConfig(seed=42), directory=tmp_path/'optimizer')
    assert optimizer.evaluator.screener is None and optimizer.evaluator.cost_estimator is None
    assert not optimizer.evaluator.enabled
