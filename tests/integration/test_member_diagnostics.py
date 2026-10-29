"""Validate persisted real diagnostic replays; does not launch extra FEA calls."""
import json
from pathlib import Path

import pytest

from struct_agent.schemas import AnalysisRecord, LayoutCandidate, ProjectSpec
from struct_agent.services.diagnostics import load_members, member_summary

pytestmark = pytest.mark.real


def test_real_diagnostic_replay_evidence() -> None:
    from struct_agent.io.artifacts import sha256
    reference = json.loads(Path('configs/real_fea_reference.json').read_text(encoding='utf-8'))
    for asset in reference['inputs'].values():
        assert sha256(Path(asset['path'])) == asset['sha256']
    run = Path(reference['inputs']['analysis']['path']).parents[1]
    if not (run / "summary.json").is_file():
        pytest.fail(f"BLOCKED: missing real diagnostic artifacts {run}")
    payload = json.loads((run / "analyses/eval_00001.json").read_text(encoding="utf-8"))
    record = AnalysisRecord.model_validate_json(json.dumps(payload["analysis"]))
    from struct_agent.adapters.physics import analysis_signature
    assert record.status == "SUCCESS" and record.fidelity == "full"
    assert record.analysis_signature == analysis_signature()
    layout = LayoutCandidate.model_validate_json(Path(reference['inputs']['layout']['path']).read_text(encoding='utf-8'))
    spec = ProjectSpec.model_validate_json(Path(reference['inputs']['spec']['path']).read_text(encoding='utf-8'))
    members = load_members(run / "diagnostics/eval_00001/members.json")
    from struct_agent.adapters.fea import native_topology
    from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import wall_piers
    assert len(members) == (len(wall_piers(native_topology(layout).walls)) + sum(m.role != 'wall' for m in layout.members)) * spec.stories
    assert len({(m.native_id, m.story) for m in members}) == len(members)
    for story in range(1,spec.stories+1):
        source_ids = [source for m in members if m.story == story for source in m.source_member_ids]
        assert len(source_ids) == len(set(source_ids)) == len(layout.members)
        assert set(source_ids) == {m.member_id for m in layout.members}
    for member in members:
        assert layout.members[member.native_id].member_id in member.source_member_ids
        if member.role == "wall":
            assert member.reinforcement_checked
    summary = member_summary(members)
    for kind in ("wall", "beam"):
        native = record.raw[f"max_{kind}_shear_ratio"] / record.raw[f"max_{kind}_shear_limit"]
        assert summary[kind]["worst_shear"]["utilization"] == pytest.approx(native, rel=1e-9)
    assert summary["beam"]["reinforcement_failed_count"] == record.raw["design_failed_beam_count"]
    assert summary["wall"]["reinforcement_failed_count"] == record.raw["design_failed_wall_count"]
