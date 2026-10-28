import pytest
from pydantic import ValidationError

from struct_agent.schemas import Member, LayoutCandidate, AnalysisRecord


def test_geometry_units_and_roundtrip() -> None:
    member = Member(member_id="w1", start=(0., 0.), end=(1., 0.), role="wall")
    layout = LayoutCandidate(layout_id="a", source="synthetic", length_unit="m",
        coordinate_system="global_xy", members=(member,), slabs=(((0.,0.),(1.,0.),(1.,1.)),))
    assert LayoutCandidate.model_validate_json(layout.model_dump_json()) == layout
    with pytest.raises(ValidationError):
        LayoutCandidate.model_validate_json(layout.model_dump_json().replace('"m"', '"mm"'))
    with pytest.raises(ValidationError):
        Member(member_id="w", start=(0.,0.), end=(0.,0.), role="wall")


def test_failure_cannot_be_structural_infeasibility() -> None:
    with pytest.raises(ValidationError):
        AnalysisRecord(evaluation_id="e", layout_id="l", condition_id="c", design_id="d",
            fidelity="full", status="SOLVER_ERROR", solver="x", solver_version="x",
            elapsed_s=0., feasible=False, raw={}, error=None)


def test_full_success_requires_complete_native_response() -> None:
    with pytest.raises(ValidationError):
        AnalysisRecord(evaluation_id="e", layout_id="l", condition_id="c", design_id="d",
            fidelity="full", status="SUCCESS", solver="x", solver_version="x",
            elapsed_s=0., feasible=True, raw={}, error=None)
