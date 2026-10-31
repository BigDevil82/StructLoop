"""Read-only member diagnostics and numerical replay comparisons."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
from typing import Any
from struct_agent.schemas import DesignCandidate, LayoutCandidate, ProjectSpec, RoomGraph
from struct_agent.services.analysis import AnalysisService

from struct_agent.schemas.diagnostics import MemberDiagnostic


def compare_responses(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Use the pre-existing upstream regression tolerance; never alter either record."""
    rows = {}
    for name in sorted(actual.keys() | expected.keys()):
        a, e = actual.get(name), expected.get(name)
        present = name in actual and name in expected
        if type(a) in (int, float) and type(e) in (int, float):
            passed = present and math.isclose(a, e, rel_tol=1e-5, abs_tol=1e-8)
        else:
            passed = present and type(a) is type(e) and a == e
        rows[name] = {"actual": a, "expected": e, "passed": passed}
    return rows


def member_summary(members: tuple[MemberDiagnostic, ...]) -> dict[str, Any]:
    """Counts are member-story checks; unique_member_count is plan members."""
    groups = {"wall": tuple(m for m in members if m.role == "wall"),
              "beam": tuple(m for m in members if m.role != "wall")}
    result = {}
    for kind, items in groups.items():
        worst = max(items, key=lambda m: m.utilization, default=None)
        failed = tuple(m for m in items if not m.shear_passed)
        result[kind] = {"member_story_count": len(items), "unique_member_count": len({m.member_id for m in items}),
            "shear_failed_count": len(failed), "reinforcement_unchecked_count": sum(not m.reinforcement_checked for m in items),
            "shear_failed_and_reinforcement_unchecked_count": sum(not m.reinforcement_checked for m in failed),
            "reinforcement_failed_count": sum(m.reinforcement_passed is False for m in items),
            "reinforcement_messages": dict(Counter(msg for m in items for msg in m.reinforcement_messages)),
            "members_below_rcgnn_topology_min_0_1m": sorted({m.member_id for m in items if m.length_m < .1-1e-8}),
            "worst_shear": None if worst is None else {**worst.model_dump(), "utilization": worst.utilization}}
    return result


def load_members(path: Path) -> tuple[MemberDiagnostic, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["fidelity"] != "full" or payload["units"] != {"length": "m", "force": "N", "stress": "Pa"}:
        raise ValueError("Diagnostic report requires real FEA with explicit native units")
    return tuple(MemberDiagnostic.model_validate_json(json.dumps(row)) for row in payload["members"])


def evaluate_local_layout_candidates(service: 'AnalysisService', layout: 'LayoutCandidate',
        design: 'DesignCandidate', spec: 'ProjectSpec', rooms: 'RoomGraph',
        members: tuple[MemberDiagnostic, ...], *, steps_m: tuple[float,...]=(.1,.2),
        target_utilization: float=1., max_candidates: int=4) -> dict[str, Any]:
    """Evaluate bounded local proposals with unchanged sections and shared FEA budget.

    Reuse the existing constraint/cost ranking; solver failures stay in the record.
    Each layout has a fresh problem and no surrogate or calibration state.
    """
    from struct_agent.adapters.casino import CasinoProblem
    from struct_agent.adapters.design_search import local_layout_candidates
    from struct_agent.services.analysis import AnalysisFailed, BudgetExhausted
    from struct_agent._vendor.shearwall_optimization.surrogate_candidate import SurrogateCandidateEvaluator

    native={k:round(float(v)*1000) if k!='conc_bot' else v for k,v in design.values.items()}
    baseline_problem=CasinoProblem(layout,spec,service,layout_path=Path('unused'),seed=42)
    baseline=baseline_problem.evaluate(native)
    best_key=SurrogateCandidateEvaluator.rank_key(baseline)
    best_layout_id=layout.layout_id
    search=local_layout_candidates(layout,rooms,design,members,steps_m=steps_m,
        target_utilization=target_utilization,max_candidates=max_candidates)
    rows=[];termination='completed'
    for proposal in search.proposals:
        problem=CasinoProblem(proposal.layout,spec,service,layout_path=Path('unused'),seed=42)
        try:
            result=problem.evaluate(native)
        except BudgetExhausted:
            termination='budget_exhausted';break
        except AnalysisFailed as exc:
            rows.append({'proposal':proposal.model_dump(),'analysis':exc.record.model_dump(),
                'ranking_improved':False,'error':exc.record.error.model_dump()})
            continue
        key=SurrogateCandidateEvaluator.rank_key(result)
        improves=key<SurrogateCandidateEvaluator.rank_key(baseline)
        if key<best_key:best_key,best_layout_id=key,proposal.layout.layout_id
        rows.append({'proposal':proposal.model_dump(),'feasible':result.feasible,
            'objectives':result.objectives,'normalized_violations':result.metrics['normalized_violations'],
            'raw':next(r.raw for r in service.records if r.layout_id==proposal.layout.layout_id),
            'ranking_improved':improves})
    return {'termination':termination,'baseline_layout_id':layout.layout_id,
        'baseline_feasible':baseline.feasible,'baseline_objectives':baseline.objectives,
        'target_utilization':target_utilization,'target_is_search_trigger_not_code_limit':True,
        'generated_candidate_count':len(search.proposals),'evaluated_candidate_count':len(rows),
        'fea_attempts':len(service.records),'best_layout_id':best_layout_id,
        'candidates':rows,'rejected':search.rejected,
        'architectural_checks':'room masks, fixed axes, member roles, branch nodes, residual lengths',
        'scope':'repeated standard floor; continuous-steel section checks, not bar detailing',
        'agent_action_added':False,'member_role_changes_allowed':False}


def write_report(path: Path, members: tuple[MemberDiagnostic, ...], *, parity_passed: bool | None = None) -> None:
    lines = ["# 构件级有限元诊断（冒烟条件）", "",
        f"当前正确实现的独立计算。可选同协议复算对照：{parity_passed}。", "",
        "指标按上游定义为 V/(βc·fc·b·h0)，利用率为该指标/原有限值。力 N，尺寸 m，应力 Pa。",
        "h0采用截面尺寸扣除40mm纵筋合力点距离；梁跨按墙支座间共线构件识别，保留中间接入节点。",
        "基本组合剪力与调整后的设计剪力分别保存，按设计剪力/对应限值选择控制组合；全部墙肢逐组合设计。", "",
        "本报告用于定位控制构件，未改变几何、荷载、限值或原算法，不是工程签审。", ""]
    for kind, title in (("wall", "墙肢"), ("beam", "梁")):
        items = tuple(m for m in members if (m.role == "wall") == (kind == "wall"))
        lines += [f"## {title}控制项（利用率前 15 个构件-楼层）", "",
            "| 构件ID | 层 | 长度 m | b m | h0 m | V kN | 指标 | 限值 | 利用率 | 配筋检查 | 控制组合 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
        for m in sorted(items, key=lambda m: m.utilization, reverse=True)[:15]:
            design = "未执行" if not m.reinforcement_checked else ("通过" if m.reinforcement_passed else "不通过")
            lines.append(f"| {m.member_id} | {m.story} | {m.length_m:.6f} | {m.width_m:.3f} | {m.effective_depth_m:.6f} | "
                f"{m.shear_n/1000:.3f} | {m.shear_ratio:.6f} | {m.shear_limit:g} | {m.utilization:.3f} | {design} | {m.control_combo} |")
        messages = Counter(msg for m in items for msg in m.reinforcement_messages)
        lines += ["", f"配筋设计消息（构件-楼层计数）：{dict(messages)}", ""]
    with path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
