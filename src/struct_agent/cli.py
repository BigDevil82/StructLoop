"""Thin local tool CLI. No training or arbitrary command execution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from struct_agent.io.artifacts import create_run, sha256, write_json
from struct_agent.schemas import LayoutCandidate, ProjectSpec, RoomGraph


def load_assets(path: Path, *, names: tuple[str, ...]) -> dict[str, Path]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    paths = {}
    for name in names:
        if name not in payload:
            raise ValueError(f"BLOCKED: asset manifest is missing {name}")
        row = payload[name]
        target = Path(row["path"])
        if not target.is_file() or sha256(target) != row["sha256"]:
            raise ValueError(f"BLOCKED: missing/changed local asset {name}: {target}")
        paths[name] = target
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="StructLoop inference and fixed-layout optimization")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--dxf", type=Path, help="Explicit prepared DXF override, mm; requires --category")
    generate.add_argument("--category", type=int, choices=(0,1,2))
    generate.add_argument("--case-config", type=Path, default=Path("configs/test_case.json"),
                          help="Default engineering drawing and RC-GNN condition")
    optimization = sub.add_parser("optimize")
    optimization.add_argument("--layout", type=Path, required=True)
    optimization.add_argument("--rooms", type=Path, required=True)
    optimization.add_argument("--spec", type=Path, required=True)
    optimization.add_argument("--budget-fea", type=int, required=True)
    optimization.add_argument("--population", type=int, default=24)
    optimization.add_argument("--generations", type=int, default=20)
    optimization.add_argument("--screening-threshold", type=float, default=None)
    mock = sub.add_parser("run-case", help="Synthetic state-machine verification only; no real FEA")
    mock.add_argument("--case", type=Path, required=True)
    mock.add_argument("--run", type=Path, required=True)
    mock.add_argument("--seed", type=int, required=True)
    mock.add_argument("--budget-fea", type=int, required=True, help="Mock evaluation budget")
    mock.add_argument("--policy", choices=("scripted", "fixed"), default="scripted")
    mock.add_argument("--approve-mock-layout", action="append", default=[],
                      help="Explicit simulation approval of a named layout; not engineering approval")
    for cmd in (generate,optimization):
        cmd.add_argument("--assets", type=Path, default=Path("configs/local_assets.json"))
        cmd.add_argument("--run", type=Path, required=True)
        cmd.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    if args.command == "run-case":
        from struct_agent.workflows.runner import run_mock_case
        state = run_mock_case(args.case, args.run, seed=args.seed, budget=args.budget_fea,
                             policy=args.policy, approved_mock_layouts=tuple(args.approve_mock_layout))
        print(f"MOCK ONLY: {state.status}; mock evaluations={state.fea_calls_used}; artifacts: {args.run}")
        return
    names = tuple(f"rc_fold_{i}" for i in range(5)) if args.command == "generate" else ("feasibility", "steel")
    assets = load_assets(args.assets, names=names)
    if args.command == "generate":
        import numpy as np
        import torch
        from struct_agent.adapters.rcgnn import RCGNNAdapter, graph_from_dxf, layout_from_prediction
        case = None
        if args.dxf is None:
            from struct_agent.io.case import load_generation_case
            case, args.dxf = load_generation_case(args.case_config)
            if args.category is not None and args.category != case.category:
                parser.error("Default case category is fixed; use an explicit --dxf with --category for a different condition")
            args.category = case.category
        elif args.category is None:
            parser.error("An explicit --dxf requires --category")
        torch.manual_seed(args.seed)
        inputs = {k:p for k,p in assets.items() if k.startswith("rc_fold_")}
        inputs["dxf"] = args.dxf
        if case is not None:
            inputs["case_config"] = args.case_config
        create_run(args.run,seed=args.seed,inputs=inputs,config={"command":"generate", "category":args.category,
            "case_id": case.case_id if case is not None else None, "native_coordinate_unit": "mm", "symmetry_mode": "none"})
        rooms = graph_from_dxf(args.dxf,category=args.category)
        model = RCGNNAdapter(tuple(inputs[k] for k in sorted(inputs) if k.startswith("rc_fold_")))
        ratios = model.predict(rooms)
        np.save(args.run/"ratios.npy", ratios)
        layout = layout_from_prediction(rooms, ratios, layout_id=args.run.name)
        write_json(args.run/"room_graph.json",rooms.model_dump())
        write_json(args.run/"layout.json",layout.model_dump())
        print(f"Generated {len(layout.members)} members; artifacts: {args.run}")
    else:
        from struct_agent.adapters.casino import CasinoConfig, optimize
        from struct_agent.adapters.fea import OpenSeesAdapter
        from struct_agent.services.analysis import AnalysisService
        spec = ProjectSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
        rooms = RoomGraph.model_validate_json(args.rooms.read_text(encoding="utf-8"))
        layout = LayoutCandidate.model_validate_json(args.layout.read_text(encoding="utf-8"))
        cfg = CasinoConfig(feasibility_weights=assets["feasibility"], steel_weights=assets["steel"],
            seed=args.seed,population_size=args.population,generations=args.generations,
            screening_threshold=args.screening_threshold)
        inputs = {"spec":args.spec,"rooms":args.rooms,"layout":args.layout,
                  "feasibility":assets["feasibility"],"steel":assets["steel"]}
        create_run(args.run,seed=args.seed,inputs=inputs,config={**cfg.model_dump(mode="json"),"budget":args.budget_fea})
        evaluator = AnalysisService(OpenSeesAdapter(log_directory=args.run/"solver_logs"),
            budget=args.budget_fea,directory=args.run/"analyses")
        summary = optimize(layout,rooms,spec,evaluator,cfg,directory=args.run/"optimization")
        print(json.dumps(summary,ensure_ascii=False,default=str))


if __name__ == "__main__":
    main()
