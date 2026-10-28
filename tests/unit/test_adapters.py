from pathlib import Path

import pytest
from pydantic import ValidationError

from struct_agent.adapters.fea import native_params, native_topology
from struct_agent.adapters.geometry import layout_from_legacy, legacy_topology
from struct_agent.io.artifacts import create_run, write_json
from struct_agent.schemas import AnalysisRecord, DesignCandidate, LayoutCandidate, ProjectSpec, RoomGraph
from struct_agent.services.analysis import AnalysisService, BudgetExhausted


def test_mm_conversion_preserves_geometry_and_beam_roles(layout: LayoutCandidate) -> None:
    raw = legacy_topology(layout)
    for item in raw['shearwalls']:
        item['start'] = [v*1000. for v in item['start']]
        item['end'] = [v*1000. for v in item['end']]
    raw['slabs'] = [[[v*1000. for v in p] for p in poly] for poly in raw['slabs']]
    restored = layout_from_legacy(raw,unit="mm",layout_id=layout.layout_id,source=layout.source)
    assert restored == layout
    assert native_topology(restored).walls[0].length == 4.


def test_strict_graph_indices_and_dimensions(rooms: RoomGraph) -> None:
    assert RoomGraph.model_validate_json(rooms.model_dump_json()) == rooms
    with pytest.raises(ValidationError,match="edge_index"):
        RoomGraph(**{**rooms.model_dump(),"edge_index":((3,),(0,)),"edge_attr":((0.,)*8,)})
    with pytest.raises(ValidationError,match="x"):
        RoomGraph(**{**rooms.model_dump(),"x":((0.,)*24,)})


def test_no_silent_unsupported_conditions(spec: ProjectSpec,design: DesignCandidate) -> None:
    with pytest.raises(ValidationError):
        ProjectSpec(**{**spec.model_dump(),"story_height_m":3.})
    params = native_params(design,spec)
    assert params.tw_bot == 200 and params.hs == 120 and params.h_story == 2.9


class FailingSolver:
    fidelity = "mock"
    def evaluate(self, *args: object, **kwargs: object) -> AnalysisRecord:
        raise ArithmeticError("synthetic solver failure")


def test_failed_attempts_consume_budget_and_keep_type(tmp_path: Path,layout: LayoutCandidate,
                                                     design: DesignCandidate,spec: ProjectSpec) -> None:
    service = AnalysisService(FailingSolver(),budget=1,directory=tmp_path/'analyses')
    record = service.evaluate(layout,design,spec)
    assert record.status == "SOLVER_ERROR" and record.feasible is None and record.fidelity == "mock"
    assert record.error.error_type == "ArithmeticError" and "Traceback" in record.error.traceback
    assert service.evaluate(layout,design,spec) == record  # cache does not spend twice
    changed = design.model_copy(update={"values":{**design.values,"tw_bot":0.25}})
    with pytest.raises(BudgetExhausted):
        service.evaluate(layout,changed,spec)
    assert len(service.records) == 1
    assert (tmp_path/'analyses/eval_00001.json').exists()


def test_run_and_json_never_overwrite(tmp_path: Path) -> None:
    source = tmp_path/'input.json'
    write_json(source,{"x":1})
    run = tmp_path/'run'
    create_run(run,seed=42,inputs={"source":source},config={})
    with pytest.raises(FileExistsError):
        create_run(run,seed=42,inputs={},config={})
    with pytest.raises(FileExistsError):
        write_json(source,{"x":2})
