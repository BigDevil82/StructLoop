"""Synthetic detailed records validate diagnostics only, never physical results."""
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from struct_agent.adapters.fea_member_evidence import collect_members
from struct_agent._vendor.shearwall_modeling.parametric.summary import summarize_native
from struct_agent.schemas import LayoutCandidate
from struct_agent.schemas.diagnostics import MemberDiagnostic
from struct_agent.services.diagnostics import compare_responses, member_summary, write_report
from struct_agent._vendor.shearwall_modeling.parametric.types import ParametricAnalysisResult


@pytest.mark.parametrize("empty,ratio", [(False, .7), (False, None), (True, .7), (True, 0.)])
def test_shared_summary_matches_explicit_expected_values(empty: bool, ratio: float | None) -> None:
    metric = NS(axial_ratio=.4, axial_ratio_limit=.6, shear_pressure_ratio=.3, shear_pressure_ratio_limit=.15)
    # Equal utilization with a different ratio/limit: native last-item tie rule.
    tied = NS(axial_ratio=.2, axial_ratio_limit=.3, shear_pressure_ratio=.4, shear_pressure_ratio_limit=.2)
    analysis = NS(modal_summary=NS(periods=[1., .9, .8, .7, .6, .5], period_ratio=ratio),
        wall_uls_metrics=[] if empty else [metric, tied], beam_uls_metrics=[] if empty else [metric, tied])
    build = NS(floor_load_masses=[1000., 1000.], floor_self_masses=[10., 10.])
    design = NS(is_passed=False, failed_beams=[1, 2], failed_walls=[], total_concrete_kg=500., total_steel_kg=50.)
    overall = NS(is_passed=False, is_torsion_passed=True, is_shear_weight_passed=True, is_stiffness_passed=True,
        is_interstory_drift_passed=True, is_period_ratio_passed=ratio is not None,
        is_wall_axial_passed=True, is_wall_shear_pressure_passed=False, is_beam_shear_pressure_passed=False)
    directions = {"X": NS(metrics=[NS(torsion_ratio=1., shear_weight_ratio=.1, stiffness_ratio_adjacent=.9)], max_interstory_drift_ratio=.0005)}
    actual = asdict(summarize_native(build, analysis, overall, directions, design))
    assert actual == dict(converged=True, feasible=False, design_passed=False,
        design_failed_beam_count=2, design_failed_wall_count=0, material_concrete_kg=500., material_steel_kg=50.,
        mass_total_t=2.02, T1=1., T2=.9, T3=.8, T4=.7, T5=.6, T6=.5,
        period_ratio=1.25 if ratio is None else ratio, period_ratio_available=ratio is not None,
        torsion_ratio=1., min_shear_weight_ratio=.1, max_drift_ratio=.0005, min_stiffness_ratio=.9,
        max_wall_axial_ratio=0. if empty else .2, max_wall_axial_limit=1. if empty else .3,
        max_wall_shear_ratio=0. if empty else .4, max_wall_shear_limit=1. if empty else .2,
        max_beam_shear_ratio=0. if empty else .4, max_beam_shear_limit=1. if empty else .2,
        torsion_passed=True, shear_weight_passed=True, stiffness_passed=True, drift_passed=True,
        period_ratio_passed=ratio is not None, wall_axial_passed=True, wall_shear_passed=False,
        beam_shear_passed=False, error='')


def evidence(*, negative_wall: bool = False) -> tuple[MemberDiagnostic, ...]:
    layout = LayoutCandidate.model_validate_json(json.dumps({"layout_id": "synthetic", "source": "test_only", "length_unit": "m",
        "coordinate_system": "global_xy", "members": [
            {"member_id": "w", "start": [0., 0.], "end": [.001, 0.], "role": "wall"},
            {"member_id": "b", "start": [0., 0.], "end": [0., 2.], "role": "primary"}],
        "slabs": [[[0., 0.], [1., 0.], [0., 2.]]]}))
    def member(index: int, length: float) -> NS:
        m = layout.members[index]
        return NS(length=length, start=NS(x=m.start[0], y=m.start[1]), end=NS(x=m.end[0], y=m.end[1]))
    wall = NS(wall_id=0, story=1, member=member(0, .001), thickness=.2)
    beam = NS(beam_id=1, story=1, member=member(1, 2.), width=.2, depth=.5)
    context = NS(story_profiles=[NS(story=1, material=NS(concrete_grade="C30"))],
                 wall_story_element_units=[wall], beam_element_units=[beam])
    def metric(native_id: int, length: float, ratio: float, wall: bool) -> NS:
        return NS(**({"wall_id": native_id} if wall else {"beam_id": native_id}), story=1, length=length,
            shear_pressure_ratio=ratio, shear_pressure_ratio_limit=.15, shear_control_combo="EQ",
            shear_control_combo_type="Seismic", is_shear_pressure_passed=False)
    analysis = NS(wall_uls_metrics=[metric(0, .001, 5., True)], beam_uls_metrics=[metric(1, 2., .3, False)],
        wall_forces_by_combo={"EQ": {(0, 1): (0., 0., 5.*14.3e6*.2*.001)}},
        beam_forces_by_combo={"EQ": {(1, 1): (0., 0., .3*14.3e6*.2*.5)}})
    if negative_wall:
        analysis.wall_forces_by_combo["EQ"][0, 1] = (0., 0., -14300.)
    design = NS(wall_results=[NS(wall_id=0, story=1, is_passed=False, messages=["section_insufficient"])],
        beam_results=[NS(beam_id=1, story=1, is_passed=False, messages=["beam_shear_section_insufficient"])])
    return collect_members(layout, context, analysis, design, beta_c=1., combination_types={"EQ": "Seismic"})


def test_short_wall_uls_and_reinforcement_are_both_recorded(tmp_path: Path) -> None:
    members = evidence()
    assert members[0].shear_passed is False and members[0].reinforcement_passed is False
    assert members[0].denominator_n == pytest.approx(2860.)
    summary = member_summary(members)
    assert summary["wall"]["shear_failed_and_reinforcement_unchecked_count"] == 0
    assert summary["wall"]["members_below_rcgnn_topology_min_0_1m"] == ["w"]
    assert summary["beam"]["reinforcement_messages"] == {"beam_shear_section_insufficient": 1}
    write_report(tmp_path / "report.md", members, parity_passed=True)
    with pytest.raises(FileExistsError):
        write_report(tmp_path / "report.md", members, parity_passed=True)


def test_inconsistent_force_evidence_rejected() -> None:
    row = evidence()[0].model_dump()
    row["shear_n"] *= 1000
    with pytest.raises(ValidationError, match="does not reproduce"):
        MemberDiagnostic.model_validate_json(json.dumps(row))


def test_negative_shear_is_captured_as_absolute_envelope() -> None:
    wall = evidence(negative_wall=True)[0]
    assert wall.shear_n == 14300. and wall.shear_ratio == 5. and not wall.shear_passed
    assert wall.control_combo == "EQ"
    assert wall.combo_shear_n == {"EQ": -14300.} and wall.absolute_combo_shear_n == 14300.


def test_replay_comparison_retains_missing_fields_and_failure_flags() -> None:
    result = compare_responses({"x": 1., "feasible": False, "extra": 2}, {"x": 1.0000001, "feasible": True, "missing": 3})
    assert result["x"]["passed"] is True
    assert not result["feasible"]["passed"] and not result["missing"]["passed"] and not result["extra"]["passed"]


def test_evidence_failure_is_invalid_result_and_consumes_budget(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import openseespy.opensees as ops
    from struct_agent.adapters import fea_diagnostics
    from struct_agent.adapters.fea import OpenSeesAdapter
    from struct_agent.schemas import DesignCandidate, ProjectSpec
    from struct_agent.services.analysis import AnalysisService
    layout = LayoutCandidate.model_validate_json(json.dumps({"layout_id": "synthetic", "source": "test_only",
        "length_unit": "m", "coordinate_system": "global_xy", "members": [
            {"member_id": "w", "start": [0., 0.], "end": [1., 0.], "role": "wall"}],
        "slabs": [[[0., 0.], [1., 0.], [0., 1.]]]}))
    spec = ProjectSpec.model_validate_json(Path("configs/reference_spec.json").read_text(encoding="utf-8"))
    design = DesignCandidate(design_id="test", layout_id=layout.layout_id, condition_id=spec.condition_id,
        values={v.name: v.values[0] for v in spec.design_variables})
    def broken(*args: object, **kwargs: object) -> None:
        try:
            raise KeyError("injected_capture_error")
        except KeyError as exc:
            raise fea_diagnostics.DiagnosticEvidenceError(f"KeyError: {exc}") from exc
    monkeypatch.setattr(fea_diagnostics, "analyze_detailed", broken)
    monkeypatch.setattr(ops, "logFile", lambda *args: None)
    solver = OpenSeesAdapter(log_directory=tmp_path / "logs", diagnostics_directory=tmp_path / "details")
    service = AnalysisService(solver, budget=1, directory=tmp_path / "analyses")
    record = service.evaluate(layout, design, spec)
    assert record.status == "INVALID_RESULT" and record.feasible is None
    assert record.error.error_type == "DiagnosticEvidenceError"
    assert "KeyError" in record.error.traceback and len(service.records) == 1
