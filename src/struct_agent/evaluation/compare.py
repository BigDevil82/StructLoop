"""Compare matched runs without hiding failures or treating missing costs as zero."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from struct_agent.io.artifacts import write_json


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def comparison(runs: tuple[Path, ...]) -> dict:
    if len(runs) < 2:
        raise ValueError("At least two runs required")
    signature = None
    rows = []
    for run in runs:
        manifest, summary = load(run / "manifest.json"), load(run / "summary.json")
        config = manifest["config"]
        current = {"seed": manifest["seed"], "software": manifest["software"],
            "code_sha256": manifest["code_sha256"],
            "config": {k: v for k, v in config.items() if k != "policy"},
            "inputs": {k: v["sha256"] for k, v in manifest["inputs"].items() if k != "llm_config"}}
        if signature is not None and current != signature:
            raise ValueError("Runs differ in case/candidates/budget/seed/optimizer/software/code; comparison rejected")
        signature = current
        records = [load(p)["analysis"] for p in sorted((run / "analyses").glob("eval_*.json"))]
        state = summary["state"]
        if len(records) != state["fea_calls_used"] or len(records) > config["budget"]:
            raise ValueError("Recorded analysis counts do not match budget/summary")
        if any(r["fidelity"] != state["fidelity"] for r in records):
            raise ValueError("Mixed evaluator fidelities")
        events = [load(p) for p in sorted((run / "events").glob("event_*.json"))]
        rows.append({"run": str(run), "policy": config["policy"], "status": summary["status"],
            "fidelity": state["fidelity"], "purpose": config["purpose"],
            "fea_attempts": len(records), "fea_failures": sum(r["status"] != "SUCCESS" for r in records),
            "has_feasible_analysis": any(r["status"] == "SUCCESS" and r["feasible"] for r in records),
            "best_feasible_cost": state["best_feasible_cost"],
            "solver_elapsed_s": sum(r["elapsed_s"] for r in records), "total_elapsed_s": summary["elapsed_s"],
            "api_calls": summary["api_calls"], "api_total_tokens": summary["api_total_tokens"],
            "review_requests": sum(e.get("decision", {}).get("action") == "REQUEST_HUMAN_REVIEW" for e in events),
            "switch_proposals": sum(e.get("decision", {}).get("action") == "SWITCH_LAYOUT" for e in events),
            "approved_switches": sum(e.get("approval") == "APPROVED" for e in events)})
    return {"matched_conditions": signature, "runs": rows,
            "interpretation": "Equal configured budget, not necessarily equal consumption. Smoke runs are not efficacy evidence."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write_json(args.out, comparison(tuple(args.run)))


if __name__ == "__main__":
    main()
