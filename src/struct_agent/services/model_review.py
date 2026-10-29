"""Preflight model semantics; software policies are not universal code limits."""
from __future__ import annotations

from typing import Literal
from pydantic import Field

from struct_agent.schemas import DesignCandidate, LayoutCandidate
from struct_agent.schemas.base import Contract
from struct_agent.adapters.fea import native_topology
from struct_agent._vendor.shearwall_modeling.geometry.wall_piers import wall_piers


class GeometryIssue(Contract):
    code: Literal['SHORT_WALL_PIER', 'COLUMN_OR_COMPOSITE_DESIGN_REQUIRED', 'BEAM_SPAN_REVIEW']
    source_member_ids: tuple[str, ...] = Field(min_length=1)
    length_m: float = Field(gt=0.)
    ratio: float | None = Field(default=None, gt=0.)


class ModelGeometryReview(Contract):
    wall_merge_review_threshold_m: float = Field(gt=0.)
    physical_wall_pier_count: int = Field(ge=1)
    mesh_wall_segment_count: int = Field(ge=1)
    requires_model_repair: bool
    issues: tuple[GeometryIssue, ...]
    interpretation: str = 'Model review only; absence of listed issues is not engineering validation.'


def review_geometry(layout: LayoutCandidate, *, design: DesignCandidate | None = None,
                    wall_merge_review_threshold_m: float = .18) -> ModelGeometryReview:
    """Flag short physical piers, rather than every short FE subdivision.

    The 180 mm review policy is sourced from the installed YJK-A manual's model
    conversion chapter. It is NOT a general minimum wall length from a code.
    Ratios below are routing indicators, not substitute capacity checks.
    """
    if wall_merge_review_threshold_m <= 0:
        raise ValueError('Positive model review threshold required')
    walls = native_topology(layout).walls
    piers = wall_piers(walls)
    issues = []
    thickness = max(float(design.values[k]) for k in ('tw_bot','tw_mid','tw_top')) if design else None
    for pier in piers:
        source = tuple(layout.members[i].member_id for i in pier.source_ids)
        length = pier.member.length
        if length <= wall_merge_review_threshold_m+1e-8:
            issues.append(GeometryIssue(code='SHORT_WALL_PIER', source_member_ids=source, length_m=length))
        if thickness is not None and length / thickness < 4.:
            issues.append(GeometryIssue(code='COLUMN_OR_COMPOSITE_DESIGN_REQUIRED', source_member_ids=source,
                length_m=length, ratio=length/thickness))
    if design:
        for member in layout.members:
            if member.role == 'wall':
                continue
            depth = float(design.values['hb_main' if member.role == 'primary' else 'hb_sec'])
            length = ((member.end[0]-member.start[0])**2+(member.end[1]-member.start[1])**2)**.5
            if length / depth < 2.:
                issues.append(GeometryIssue(code='BEAM_SPAN_REVIEW', source_member_ids=(member.member_id,),
                    length_m=length, ratio=length/depth))
    return ModelGeometryReview(wall_merge_review_threshold_m=wall_merge_review_threshold_m,
        physical_wall_pier_count=len(piers), mesh_wall_segment_count=len(walls),
        requires_model_repair=any(i.code=='SHORT_WALL_PIER' for i in issues), issues=tuple(issues))
