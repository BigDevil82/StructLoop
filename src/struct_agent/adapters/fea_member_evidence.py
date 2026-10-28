"""Translate already-computed native member checks without changing their scope."""
from __future__ import annotations

from struct_agent._vendor.shearwall_modeling.analysis.results import AnalysisResult
from struct_agent._vendor.shearwall_modeling.builders.base import AnalysisModelContext
from struct_agent._vendor.shearwall_modeling.core.constants import concrete_fc_pa
from struct_agent._vendor.shearwall_modeling.design.results import ReinforcementDesignSummary
from struct_agent.schemas import LayoutCandidate
from struct_agent.schemas.diagnostics import MemberDiagnostic


def collect_members(layout: LayoutCandidate, context: AnalysisModelContext, analysis: AnalysisResult,
                    design: ReinforcementDesignSummary, *, beta_c: float) -> tuple[MemberDiagnostic, ...]:
    profiles = {p.story: p for p in context.story_profiles}
    rows = []
    groups = (("wall", analysis.wall_uls_metrics, context.wall_story_element_units,
               analysis.wall_forces_by_combo, design.wall_results),
              ("beam", analysis.beam_uls_metrics, context.beam_element_units,
               analysis.beam_forces_by_combo, design.beam_results))
    for kind, metrics, units, forces, designs in groups:
        id_field = "wall_id" if kind == "wall" else "beam_id"
        by_key = {(getattr(u, id_field), u.story): u for u in units}
        design_by_key = {(getattr(d, id_field), d.story): d for d in designs}
        for metric in metrics:
            native_id, story = getattr(metric, id_field), metric.story
            unit = by_key[native_id, story]
            member = layout.members[native_id]
            if (member.role == "wall") != (kind == "wall"):
                raise ValueError("Native member ID does not map to the layout role")
            grade = profiles[story].material.concrete_grade
            fc = concrete_fc_pa(grade)
            width = unit.thickness if kind == "wall" else unit.width
            depth = unit.member.length if kind == "wall" else unit.depth
            denominator = max(beta_c * fc * max(width, 1e-9) * max(depth, 1e-9), 1e-9)
            combo_shear = {name: float(values[native_id, story][2]) for name, values in forces.items()}
            combo_available = metric.shear_control_combo in combo_shear
            if combo_available:
                shear = max(0., combo_shear[metric.shear_control_combo])
            elif metric.shear_control_combo == "" and metric.shear_pressure_ratio == 0.:
                # Native envelope initializes at -1 N, clips its maximum to zero,
                # and can leave combo='' when every signed shear is below -1 N.
                if not combo_shear or any(v > -1. for v in combo_shear.values()):
                    raise ValueError("Empty native control combination is inconsistent with signed forces")
                shear = 0.
            else:
                raise ValueError("Native shear control combination is missing from force data")
            result = design_by_key.get((native_id, story))
            rows.append(MemberDiagnostic(native_id=native_id, member_id=member.member_id, role=member.role,
                story=story, start_m=(unit.member.start.x, unit.member.start.y),
                end_m=(unit.member.end.x, unit.member.end.y), length_m=metric.length,
                width_m=width, depth_m=depth, concrete_grade=grade, fc_pa=fc, beta_c=beta_c,
                shear_n=shear, denominator_n=denominator, shear_ratio=metric.shear_pressure_ratio,
                shear_limit=metric.shear_pressure_ratio_limit, control_combo=metric.shear_control_combo,
                control_combo_available=combo_available, combo_shear_n=combo_shear,
                control_combo_type=metric.shear_control_combo_type, shear_passed=metric.is_shear_pressure_passed,
                reinforcement_checked=result is not None, reinforcement_passed=result.is_passed if result else None,
                reinforcement_messages=tuple(result.messages) if result else ()))
    return tuple(rows)
