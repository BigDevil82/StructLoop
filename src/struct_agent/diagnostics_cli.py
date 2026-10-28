"""Repeat one explicitly supplied real record, retaining member-level evidence."""
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
    for name in ("layout", "record", "spec", "run"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    layout = LayoutCandidate.model_validate_json(args.layout.read_text(encoding="utf-8"))
    spec = ProjectSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
    source = json.loads(args.record.read_text(encoding="utf-8"))
    reference = AnalysisRecord.model_validate_json(json.dumps(source["analysis"]))
    design = DesignCandidate.model_validate_json(json.dumps(source["design"]))
    design.validate_against(spec)
    if (reference.status != "SUCCESS" or reference.fidelity != "full" or reference.layout_id != layout.layout_id
            or reference.condition_id != spec.condition_id or reference.design_id != design.design_id
            or design.layout_id != layout.layout_id):
        raise ValueError("Diagnostic reference must be a matching successful real analysis")
    # AnalysisService's cache key binds the full geometry, conditions and parameters.
    import hashlib
    binding = hashlib.sha256((layout.model_dump_json()+spec.model_dump_json()+str(sorted(design.values.items()))).encode()).hexdigest()
    if reference.input_hash != binding:
        raise ValueError("Diagnostic source geometry/conditions differ from the original analysis hash")
    create_run(args.run, seed=0, inputs={"layout": args.layout, "spec": args.spec, "reference": args.record},
        config={"purpose": "member_diagnostics_smoke_only", "fidelity": "full", "budget": 1,
                "reference_input_hash": reference.input_hash})
    solver = OpenSeesAdapter(log_directory=args.run / "solver_logs", diagnostics_directory=args.run / "diagnostics")
    service = AnalysisService(solver, budget=1, directory=args.run / "analyses")
    record = service.evaluate(layout, design, spec)
    if record.status != "SUCCESS":
        write_json(args.run / "summary.json", {"status": "FAILED", "fea_attempts": len(service.records),
            "error": record.error.model_dump(), "engineering_review": "PENDING"})
        raise RuntimeError(f"Diagnostic analysis failed: {record.status}: {record.error.message}")
    comparison = compare_responses(record.raw, reference.raw)
    passed = all(row["passed"] for row in comparison.values())
    write_json(args.run / "comparison.json", comparison)
    members = load_members(args.run / "diagnostics/eval_00001/members.json")
    write_json(args.run / "summary.json", {"status": "COMPLETED" if passed else "PARITY_FAILED",
        "fea_attempts": len(service.records), "feasible": record.feasible, "reference_parity_passed": passed,
        "members": member_summary(members), "engineering_review": "PENDING"})
    write_report(args.run / "report.md", members, parity_passed=passed)
    print(f"Real FEA attempts={len(service.records)}; fields={len(comparison)}; parity={passed}; artifacts={args.run}")
    if not passed:
        raise AssertionError("Detailed diagnostic replay differs from the original summary; inspect comparison.json")


if __name__ == "__main__":
    main()
