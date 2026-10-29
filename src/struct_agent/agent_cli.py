"""Real CASINO/FEA feedback runner; all engineering releases remain pending review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from struct_agent.adapters.casino import CasinoConfig
from struct_agent.adapters.casino_session import CasinoSession
from struct_agent.adapters.fea import OpenSeesAdapter
from struct_agent.agents.chat_client import ChatClient, ChatConfig, read_api_key
from struct_agent.agents.policies import FixedPolicy, RulePolicy, LLMPolicy, DecisionPolicy
from struct_agent.cli import load_assets
from struct_agent.io.artifacts import create_run, write_json
from struct_agent.schemas import DesignCandidate, LayoutCandidate, ProjectSpec, RoomGraph
from struct_agent.services.analysis import AnalysisService
from struct_agent.workflows.optimization_env import OptimizationEnvironment
from struct_agent.workflows.layout_approval import LayoutApproval


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path, action="append", required=True, help="Ordered, pre-defined candidate pool")
    parser.add_argument("--rooms", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--purpose", choices=("smoke_only", "research"), required=True)
    parser.add_argument("--policy", choices=("fixed", "rules", "llm"), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--initial-design", type=Path, help="Evaluate this design first, then iterate from real feedback")
    parser.add_argument("--budget-fea", type=int, required=True)
    parser.add_argument("--population", type=int, default=24)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--screening-threshold", type=float)
    parser.add_argument("--use-surrogate", action="store_true", help="Only use physics-compatible trained weights")
    parser.add_argument("--assets", type=Path, default=Path("configs/local_assets.json"))
    parser.add_argument("--llm-config", type=Path, default=Path("configs/llm.json"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--layout-approval", type=Path, action="append", default=[],
                        help="Operator approval bound to exact candidate, conditions and run purpose")
    args = parser.parse_args()
    if args.budget_fea < 1 or args.max_steps < 1:
        parser.error("Budget and max-steps must be positive")
    assets = load_assets(args.assets, names=("feasibility", "steel") if args.use_surrogate else ())
    layouts = tuple(LayoutCandidate.model_validate_json(p.read_text(encoding="utf-8")) for p in args.layout)
    rooms = RoomGraph.model_validate_json(args.rooms.read_text(encoding="utf-8"))
    spec = ProjectSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
    initial = DesignCandidate.model_validate_json(args.initial_design.read_text(encoding="utf-8")) if args.initial_design else None
    if initial is not None:
        initial.validate_against(spec)
        if initial.layout_id != layouts[0].layout_id:
            raise ValueError("Initial design must belong to the first layout")
    metadata = json.loads(args.assets.read_text(encoding="utf-8")) if args.use_surrogate else {}
    signatures = {metadata[k].get("analysis_signature") for k in assets}
    cfg = CasinoConfig(feasibility_weights=assets.get("feasibility"), steel_weights=assets.get("steel"), seed=args.seed,
                       use_surrogate=args.use_surrogate, surrogate_analysis_signature=next(iter(signatures)) if len(signatures) == 1 else None,
                       initial_values=initial.values if initial else None,
                       population_size=args.population, generations=args.generations, screening_threshold=args.screening_threshold)
    inputs = {**assets, "rooms": args.rooms, "spec": args.spec,
              **{f"layout_{i}": p for i, p in enumerate(args.layout)}}
    if args.initial_design:
        inputs["initial_design"] = args.initial_design
    approvals: dict[str, LayoutApproval] = {}
    for i, path in enumerate(args.layout_approval):
        approval = LayoutApproval.model_validate_json(path.read_text(encoding="utf-8"))
        candidate = next((x for x in layouts if x.layout_id == approval.layout_id), None)
        if candidate is None or approval.layout_id in approvals:
            raise ValueError("Approval must name one unique candidate in the input pool")
        approval.check(candidate, spec, args.purpose)
        approvals[approval.layout_id] = approval
        inputs[f"approval_{i}"] = path
    chat_cfg = None
    if args.policy == "llm":
        chat_cfg = ChatConfig.model_validate_json(args.llm_config.read_text(encoding="utf-8"))
        key = read_api_key(args.env_file, chat_cfg.api_key_env)
        inputs["llm_config"] = args.llm_config
    create_run(args.run, seed=args.seed, inputs=inputs, config={"casino": cfg.model_dump(mode="json"),
        "budget": args.budget_fea, "max_steps": args.max_steps, "policy": args.policy,
        "purpose": args.purpose, "case_id": args.case_id, "fidelity": "full"})
    start = time.monotonic()
    evaluator = AnalysisService(OpenSeesAdapter(log_directory=args.run / "solver_logs"),
                                budget=args.budget_fea, directory=args.run / "analyses")
    def factory(layout: LayoutCandidate, directory: Path) -> CasinoSession:
        return CasinoSession(layout, rooms, spec, evaluator, cfg, directory=directory)
    env = OptimizationEnvironment(args.case_id, layouts, evaluator, factory, args.run)
    client = ChatClient(chat_cfg, key, args.run / "api") if chat_cfg else None
    policy: DecisionPolicy = LLMPolicy(client, args.run / "decisions") if client else (
        FixedPolicy() if args.policy == "fixed" else RulePolicy())
    for _ in range(args.max_steps):
        if env.status != "RUNNING":
            break
        decision = policy.choose(env.observe())
        print(f"action={decision.action}; evaluations={len(evaluator.records)}/{evaluator.budget}", flush=True)
        env.step(decision)
        if env.status == "WAITING_APPROVAL" and env.pending in approvals:
            approval = approvals[env.pending]
            env.approve_layout(approval.layout_id, reviewer=approval.reviewer, expected_sha256=approval.layout_sha256)
    if env.status == "RUNNING":
        env.status = "STEP_LIMIT"
    summary = {**env.summary(), "elapsed_s": time.monotonic() - start, "purpose": args.purpose,
               "policy": args.policy, "api_calls": client.calls if client else 0,
               "api_total_tokens": client.total_tokens if client else 0,
               "api_usage_missing_calls": client.usage_missing_calls if client else 0}
    write_json(args.run / "summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("status", "purpose", "policy", "api_calls", "api_total_tokens")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
