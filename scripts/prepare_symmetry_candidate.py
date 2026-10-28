"""Prepare an unapproved union-symmetry candidate using existing RC-GNN predictions."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from struct_agent.adapters.rcgnn import layout_from_prediction
from struct_agent.adapters.symmetry import detect_axis
from struct_agent.io.artifacts import create_run, write_json
from struct_agent.io.case import load_generation_case
from struct_agent.schemas import LayoutCandidate, RoomGraph


def draw(layouts: tuple[LayoutCandidate, ...], output: Path) -> None:
    from html import escape
    width, height = 1500, 580
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<text x="750" y="30" text-anchor="middle" font-family="sans-serif" font-size="20">RC-GNN / union symmetry candidate — NOT APPROVED</text>']
    points = [p for layout in layouts for m in layout.members for p in (m.start, m.end)]
    minx, maxx = min(p[0] for p in points), max(p[0] for p in points)
    miny, maxy = min(p[1] for p in points), max(p[1] for p in points)
    scale = min(650. / (maxx-minx), 380. / (maxy-miny))
    for index, layout in enumerate(layouts):
        left = index * 750 + 50
        walls = sum(m.role == "wall" for m in layout.members)
        parts.append(f'<text x="{left}" y="75" font-family="sans-serif" font-size="18">{escape(layout.layout_id)} ({walls} wall segments)</text>')
        for m in layout.members:
            x1, y1 = left + (m.start[0]-minx)*scale, 480-(m.start[1]-miny)*scale
            x2, y2 = left + (m.end[0]-minx)*scale, 480-(m.end[1]-miny)*scale
            color, stroke = ("#b91c1c", 3) if m.role == "wall" else ("#64748b", 1)
            parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{stroke}"/>')
        parts.append(f'<text x="{left}" y="530" font-family="sans-serif" font-size="15">Red: walls; gray: beams. Same scale, XY metres; review only.</text>')
    parts.append('</svg>')
    with output.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--case-config", type=Path, default=Path("configs/test_case.json"))
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    case, dxf = load_generation_case(args.case_config)
    source = args.source_run
    rooms = RoomGraph.model_validate_json((source / "room_graph.json").read_text(encoding="utf-8"))
    original = LayoutCandidate.model_validate_json((source / "layout.json").read_text(encoding="utf-8"))
    ratios = np.load(source / "ratios.npy", allow_pickle=False)
    rebuilt = layout_from_prediction(rooms, ratios, layout_id=original.layout_id)
    if rebuilt != original:
        raise ValueError("Source layout does not match stored room graph/predictions")
    from struct_agent.io.artifacts import sha256
    import json
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest["inputs"]["dxf"]["sha256"] != sha256(dxf):
        raise ValueError("Source drawing differs from current case")
    axis, confidence = detect_axis(dxf)
    create_run(args.run, seed=args.seed, inputs={"dxf": dxf, "case_config": args.case_config,
        "rooms": source / "room_graph.json", "ratios": source / "ratios.npy", "baseline": source / "layout.json"},
        config={"case_id": case.case_id, "symmetry_mode": "union", "axis_mm": axis,
                "room_union_iou": confidence, "threshold": .85, "approval": "PENDING", "fea_executed": False})
    candidate = layout_from_prediction(rooms, ratios, layout_id=args.run.name, symmetry_axis_mm=axis)
    write_json(args.run / "layout.json", candidate.model_dump())
    write_json(args.run / "room_graph.json", rooms.model_dump())
    draw((original, candidate), args.run / "comparison.svg")
    print(f"Unapproved candidate: {args.run}; room IoU={confidence:.6f}")


if __name__ == "__main__":
    main()
