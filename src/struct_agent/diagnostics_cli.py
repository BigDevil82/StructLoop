"""Analyze one explicit design with member-level evidence using current corrected physics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from struct_agent.adapters.fea import OpenSeesAdapter
from struct_agent.io.artifacts import create_run, write_json
from struct_agent.schemas import AnalysisRecord, DesignCandidate, LayoutCandidate, ProjectSpec
from struct_agent.services.analysis import AnalysisService
from struct_agent.services.diagnostics import compare_responses, load_members, member_summary, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("layout", "design", "spec", "run"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--reference", type=Path, help="Optional same-implementation analysis for numerical reproducibility")
    args = parser.parse_args()
    layout = LayoutCandidate.model_validate_json(args.layout.read_text(encoding="utf-8"))
    spec = ProjectSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
    design = DesignCandidate.model_validate_json(args.design.read_text(encoding="utf-8"))
    design.validate_against(spec)
    if design.layout_id != layout.layout_id:
        raise ValueError("Design/layout mismatch")
    from struct_agent.adapters.physics import analysis_signature
    reference = None
    inputs = {"layout": args.layout, "spec": args.spec, "design": args.design}
    if args.reference:
        data = json.loads(args.reference.read_text(encoding="utf-8"))
        reference = AnalysisRecord.model_validate_json(json.dumps(data["analysis"]))
        if (reference.status != "SUCCESS" or reference.fidelity != "full"
                or reference.analysis_signature != analysis_signature()
                or data["design"] != design.model_dump()):
            raise ValueError("Reference must match current physics and the exact design")
        inputs["reference"] = args.reference
    create_run(args.run, seed=0, inputs=inputs, config={"purpose": "member_diagnostics_smoke_only",
        "fidelity": "full", "budget": 1, "analysis_signature": analysis_signature()})
    solver = OpenSeesAdapter(log_directory=args.run / "solver_logs", diagnostics_directory=args.run / "diagnostics")
    service = AnalysisService(solver, budget=1, directory=args.run / "analyses")
    record = service.evaluate(layout, design, spec)
    if record.status != "SUCCESS":
        write_json(args.run / "summary.json", {"status": "FAILED", "fea_attempts": len(service.records),
            "error": record.error.model_dump(), "engineering_review": "PENDING"})
        raise RuntimeError(f"Diagnostic analysis failed: {record.status}: {record.error.message}")
    passed = None
    if reference is not None:
        if reference.input_hash != record.input_hash:
            raise ValueError("Reference geometry/conditions differ from current inputs")
        comparison = compare_responses(record.raw, reference.raw)
        passed = all(row["passed"] for row in comparison.values())
        write_json(args.run / "comparison.json", comparison)
    members = load_members(args.run / "diagnostics/eval_00001/members.json")
    write_json(args.run / "summary.json", {"status": "PARITY_FAILED" if passed is False else "COMPLETED",
        "fea_attempts": len(service.records), "feasible": record.feasible, "reference_parity_passed": passed,
        "members": member_summary(members), "engineering_review": "PENDING"})
    write_report(args.run / "report.md", members, parity_passed=passed)
    print(f"Real FEA attempts={len(service.records)}; same-physics replay parity={passed}; artifacts={args.run}")
    if passed is False:
        raise AssertionError("Detailed diagnostic replay differs from the original summary; inspect comparison.json")


if __name__ == "__main__":
    main()
