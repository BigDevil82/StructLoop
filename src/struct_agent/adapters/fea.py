"""Controlled in-process OpenSees MVLEM boundary; no arbitrary script execution."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from time import perf_counter
import traceback
from typing import Any, Protocol

from struct_agent.io.artifacts import json_safe
from struct_agent.schemas import AnalysisRecord, DesignCandidate, ErrorRecord, LayoutCandidate, ProjectSpec


class Solver(Protocol):
    def evaluate(self, layout: LayoutCandidate, design: DesignCandidate,
                 spec: ProjectSpec, *, evaluation_id: str) -> AnalysisRecord: ...


def native_params(design: DesignCandidate, spec: ProjectSpec) -> Any:
    """Public dimensions m -> upstream integer mm, without silent rounding."""
    from struct_agent._vendor.shearwall_modeling.parametric.types import ParametricModelParams
    design.validate_against(spec)
    values = dict(design.values)
    for name in values:
        if name == "conc_bot":
            continue
        value = float(values[name]) * 1000.
        if abs(value-round(value)) > 1e-7:
            raise ValueError(f"Legacy parameter requires whole mm: {name}")
        values[name] = round(value)
    return ParametricModelParams(**values, N=spec.stories, hs=120, h_story=spec.story_height_m,
        intensity=spec.intensity, site_class=spec.site_class, seismic_group=spec.seismic_group,
        conc_mid=values["conc_bot"], conc_top=values["conc_bot"])


def native_topology(layout: LayoutCandidate) -> Any:
    from struct_agent._vendor.shearwall_modeling.core.domain import BeamMember, BeamRole, FEMInput, PlanMember, Point2D
    walls, beams = [], []
    for i, m in enumerate(layout.members):
        kwargs = dict(m_id=i, start=Point2D(*m.start), end=Point2D(*m.end))
        if m.role == "wall":
            walls.append(PlanMember(cate="shearwall", **kwargs))
        else:
            beams.append(BeamMember(cate="beam", role=BeamRole(m.role), **kwargs))
    return FEMInput(walls=walls, beams=beams, slabs=[[Point2D(*p) for p in poly] for poly in layout.slabs])


class OpenSeesAdapter:
    """Serial process use only: OpenSees owns process-global native state."""
    fidelity = "full"

    def __init__(self, *, log_directory: Path) -> None:
        log_directory.mkdir(parents=True,exist_ok=False)
        self.log_directory = log_directory

    def evaluate(self, layout: LayoutCandidate, design: DesignCandidate,
                 spec: ProjectSpec, *, evaluation_id: str) -> AnalysisRecord:
        import math
        import openseespy.opensees as ops
        from struct_agent._vendor.shearwall_modeling.parametric.analysis import analyze_parametric_model
        from struct_agent._vendor.shearwall_modeling.parametric.types import DatasetGenerationConfig
        started = perf_counter()
        context = dict(layout_id=layout.layout_id, design_id=design.design_id, condition_id=spec.condition_id)
        status = "MODEL_ERROR"
        log_path = self.log_directory / f"{evaluation_id}.log"
        if log_path.exists():
            raise FileExistsError(log_path)
        try:
            ops.logFile(str(log_path.resolve()),"-noEcho")
            if design.layout_id != layout.layout_id:
                raise ValueError("Design/layout mismatch")
            params = native_params(design, spec)
            topology = native_topology(layout)
            cfg = DatasetGenerationConfig(builder_name="mvlem_frame", input_unit_scale_to_m=1.,
                enable_auto_scale=False, seed=0, scale_seed=0)
            status = "SOLVER_ERROR"
            result = analyze_parametric_model(topology, params, cfg)
            raw = asdict(result)
            status = "INVALID_RESULT"
            required = ("material_concrete_kg", "material_steel_kg", "torsion_ratio", "max_drift_ratio",
                "period_ratio", "min_shear_weight_ratio", "min_stiffness_ratio",
                "max_wall_axial_ratio", "max_wall_axial_limit", "max_wall_shear_ratio",
                "max_wall_shear_limit", "max_beam_shear_ratio", "max_beam_shear_limit")
            if not result.converged or not result.period_ratio_available:
                raise ValueError("Incomplete/non-converged analysis, including missing period-ratio check")
            if any(not math.isfinite(raw[k]) for k in required):
                raise ValueError("Nonfinite required analysis metrics")
            return AnalysisRecord(evaluation_id=evaluation_id, **context, fidelity="full", status="SUCCESS",
                solver="OpenSees/MVLEM_3D", solver_version=str(ops.version()),
                elapsed_s=perf_counter()-started, feasible=bool(result.feasible and result.design_passed),
                raw=json_safe(raw), error=None,solver_log=str(log_path))
        except Exception as exc:
            return AnalysisRecord(evaluation_id=evaluation_id, **context, fidelity="full", status=status,
                solver="OpenSees/MVLEM_3D", solver_version=str(ops.version()), elapsed_s=perf_counter()-started,
                feasible=None, raw={}, solver_log=str(log_path),error=ErrorRecord(error_type=type(exc).__name__, message=str(exc),
                    traceback=traceback.format_exc(), context=context, attempt=1))
