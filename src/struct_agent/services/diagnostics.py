"""Read-only member diagnostics and numerical replay comparisons."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
from typing import Any

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
            "empty_native_shear_control_count": sum(not m.control_combo_available for m in items),
            "absolute_combo_shear_exceeds_native_count": sum(m.absolute_combo_shear_n > m.shear_n + 1e-8 for m in items),
            "reinforcement_messages": dict(Counter(msg for m in items for msg in m.reinforcement_messages)),
            "members_below_rcgnn_topology_min_0_1m": sorted({m.member_id for m in items if m.length_m < .1-1e-8}),
            "worst_shear": None if worst is None else {**worst.model_dump(), "utilization": worst.utilization}}
    return result


def load_members(path: Path) -> tuple[MemberDiagnostic, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["fidelity"] != "full" or payload["units"] != {"length": "m", "force": "N", "stress": "Pa"}:
        raise ValueError("Diagnostic report requires real FEA with explicit native units")
    return tuple(MemberDiagnostic.model_validate_json(json.dumps(row)) for row in payload["members"])


def write_report(path: Path, members: tuple[MemberDiagnostic, ...], *, parity_passed: bool) -> None:
    lines = ["# 构件级有限元诊断（冒烟条件）", "",
        f"与原记录的全部汇总字段复算一致：{parity_passed}。结果与原始工件分别保留。", "",
        "指标按上游定义为 V/(βc·fc·b·h0)，利用率为该指标/原有限值。力 N，尺寸 m，应力 Pa。",
        "其中上游 ULS 的 h0：墙取肢长，梁取截面总高；配筋设计对梁另扣保护层。此处原样记录，不混为同一口径。",
        "原 ULS 对全部墙肢校核；配筋设计仅对长度 >0.5 m 的墙肢执行。此处保留该差异。", "",
        "另记录全部组合的有符号剪力；绝对值包络只供诊断比较，未替换上游校核值。空控制组合按原零包络保留。", "",
        "本报告用于定位控制构件，未改变几何、荷载、限值或原算法，不是工程签审。", ""]
    for kind, title in (("wall", "墙肢"), ("beam", "梁")):
        items = tuple(m for m in members if (m.role == "wall") == (kind == "wall"))
        lines += [f"## {title}控制项（利用率前 15 个构件-楼层）", "",
            "| 构件ID | 层 | 长度 m | b m | h0 m | V kN | 指标 | 限值 | 利用率 | 配筋检查 | 控制组合 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
        for m in sorted(items, key=lambda m: m.utilization, reverse=True)[:15]:
            design = "未执行" if not m.reinforcement_checked else ("通过" if m.reinforcement_passed else "不通过")
            lines.append(f"| {m.member_id} | {m.story} | {m.length_m:.6f} | {m.width_m:.3f} | {m.depth_m:.6f} | "
                f"{m.shear_n/1000:.3f} | {m.shear_ratio:.6f} | {m.shear_limit:g} | {m.utilization:.3f} | {design} | {m.control_combo} |")
        messages = Counter(msg for m in items for msg in m.reinforcement_messages)
        lines += ["", f"配筋设计消息（构件-楼层计数）：{dict(messages)}", ""]
    with path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
