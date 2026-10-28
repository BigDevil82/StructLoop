"""Explicit legacy mm topology <-> public global-XY m conversion."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from struct_agent.schemas import LayoutCandidate, Member


def read_legacy_layout(path: Path, *, unit: Literal["m", "mm"], layout_id: str) -> LayoutCandidate:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return layout_from_legacy(raw, unit=unit, layout_id=layout_id, source=str(path.resolve()))


def layout_from_legacy(raw: dict[str, Any], *, unit: Literal["m", "mm"], layout_id: str,
                       source: str) -> LayoutCandidate:
    if unit not in ("m", "mm"):
        raise ValueError("Explicit m or mm unit required")
    scale = 0.001 if unit == "mm" else 1.
    def point(value: Any) -> tuple[float, float]:
        if len(value) != 2:
            raise ValueError("Expected XY point")
        return float(value[0])*scale, float(value[1])*scale
    members = []
    for key in ("shearwalls", "beams"):
        for i, item in enumerate(raw.get(key, [])):
            role = "wall" if key == "shearwalls" else item.get("beam_role", "primary")
            members.append(Member(member_id=item.get("member_id",f"{key}_{i}"), role=role,
                                  start=point(item["start"]), end=point(item["end"])))
    return LayoutCandidate(layout_id=layout_id, source=source, length_unit="m",
        coordinate_system="global_xy", members=tuple(members),
        slabs=tuple(tuple(point(p) for p in poly) for poly in raw["slabs"]))


def legacy_topology(layout: LayoutCandidate) -> dict[str, Any]:
    """Legacy structural JSON geometry in m; caller must set scale_to_m=1."""
    def member(m: Member) -> dict[str, Any]:
        result: dict[str, Any] = {"member_id":m.member_id,"start": list(m.start), "end": list(m.end)}
        if m.role != "wall":
            result["beam_role"] = m.role
        return result
    return {"shearwalls": [member(m) for m in layout.members if m.role == "wall"],
            "beams": [member(m) for m in layout.members if m.role != "wall"],
            "slabs": [[list(p) for p in poly] for poly in layout.slabs]}
