"""Synthetic dimensional test function. Never use its scores as engineering data."""
from __future__ import annotations

import math

from struct_agent.schemas import AnalysisRecord, DesignCandidate, LayoutCandidate, ProjectSpec


class MockSolverError(RuntimeError):
    pass


class MockSolver:
    fidelity = "mock"

    def __init__(self, *, failure_design_ids: tuple[str, ...] = ()) -> None:
        self.failure_design_ids = frozenset(failure_design_ids)

    def evaluate(self, layout: LayoutCandidate, design: DesignCandidate,
                 spec: ProjectSpec, *, evaluation_id: str) -> AnalysisRecord:
        design.validate_against(spec)
        if design.design_id in self.failure_design_ids:
            raise MockSolverError(f"Explicit synthetic failure: {design.design_id}")
        if design.layout_id != layout.layout_id:
            raise ValueError("Design/layout mismatch")
        horizontal = vertical = length = 0.0
        for wall in layout.members:
            if wall.role != "wall":
                continue
            dx, dy = wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]
            horizontal += abs(dx)
            vertical += abs(dy)
            length += math.hypot(dx, dy)
        thickness = float(design.values["tw_bot"])
        # 2.0 m² is a fabricated demand for state-machine tests, not a mechanics law.
        ratios = {"synthetic_x": 2.0 / max(horizontal * thickness, 0.01),
                  "synthetic_y": 2.0 / max(vertical * thickness, 0.01)}
        score = length * thickness
        return AnalysisRecord(evaluation_id=evaluation_id, layout_id=layout.layout_id,
            condition_id=spec.condition_id, design_id=design.design_id, fidelity="mock",
            status="SUCCESS", solver="synthetic_directional_capacity", solver_version="1",
            elapsed_s=0.0, feasible=all(ratio <= 1.0 for ratio in ratios.values()),
            raw={"mock_score": score, "constraint_ratios": ratios,
                 "notice": "SYNTHETIC TEST DATA; NOT STRUCTURAL ANALYSIS"}, error=None)
