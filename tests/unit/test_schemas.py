import pytest
from pydantic import ValidationError

from struct_agent.schemas import Member, LayoutCandidate, AnalysisRecord
from struct_agent.schemas.state import Decision


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


@pytest.mark.parametrize("action", [
    "CONTINUE_OPTIMIZATION", "SWITCH_LAYOUT", "REQUEST_HUMAN_REVIEW", "FINALIZE",
])
def test_real_decisions_keep_target_validation(action: str) -> None:
    target = "alternative_layout" if action == "SWITCH_LAYOUT" else None
    decision = Decision(action=action, reason="unit test", evidence_refs=("analyses/eval_00001.json",),
                        target_layout_id=target)
    assert Decision.model_validate_json(decision.model_dump_json()) == decision
    with pytest.raises(ValidationError, match="Only SWITCH_LAYOUT requires a target layout"):
        Decision(action=action, reason="unit test",
                 target_layout_id=None if target else "unexpected_layout")
