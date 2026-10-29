"""Synthetic search/quantity checks; these are not engineering benchmarks."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from struct_agent.adapters.casino import CasinoProblem
from struct_agent.schemas import LayoutCandidate, ProjectSpec
from struct_agent._vendor.shearwall_optimization.core.contracts import EvaluationResult
from struct_agent._vendor.shearwall_optimization.cost_estimation import material_cost
from struct_agent._vendor.shearwall_modeling.core.config import MaterialConfig
from struct_agent._vendor.shearwall_modeling.design.beam import BeamReinforcementDesigner
from struct_agent._vendor.shearwall_modeling.design.wall import WallReinforcementDesigner
from struct_agent._vendor.shearwall_modeling.design.results import BeamDesignDemand, WallDesignDemand


def problem() -> CasinoProblem:
    spec = ProjectSpec.model_validate_json(Path('configs/reference_spec.json').read_text(encoding='utf-8'))
    layout = LayoutCandidate(layout_id='synthetic', source='synthetic_test', length_unit='m',
        coordinate_system='global_xy', members=(dict(member_id='w', start=(0.,0.), end=(2.,0.), role='wall'),),
        slabs=(((0.,0.), (2.,0.), (0.,2.)),))
    return CasinoProblem(layout, spec, NS(), layout_path=Path('unused'), seed=42)


def test_seed_is_checked_and_preserved_before_exploratory_corner() -> None:
    p = problem()
    seed = {v.name: v.values[0] for v in p.spec.design_variables}
    p.initial_values = seed
    native = p.initial_candidates()
    assert native[0]['tw_bot'] == 200 and native[1]['tw_bot'] == 400
    assert native[1]['conc_bot'] == 'C50'
    seed['tw_bot'] = .123
    with pytest.raises(ValueError, match='Out-of-domain'):
        CasinoProblem(p.layout, p.spec, NS(), layout_path=Path('unused'), seed=42, initial_values=seed)


def test_feedback_repairs_active_wall_and_beam_checks_without_assuming_depth_helps() -> None:
    p = problem()
    x = {v.name: v.domain[0] for v in p.variables}
    result = EvaluationResult(1., {}, False, {}, {'normalized_violations': {'wall_shear_ratio': 1., 'beam_shear_ratio': .5}})
    proposed = p.feedback_candidates(x, result)
    assert proposed[0]['tw_bot'] > x['tw_bot'] and proposed[0]['bb_main'] > x['bb_main']
    assert proposed[0]['conc_bot'] == 'C35'
    assert proposed[0]['hb_main'] == x['hb_main']
    assert p.repair(proposed[0]) == proposed[0]


def test_feasible_feedback_seeks_lower_cost_and_excludes_evaluated_designs() -> None:
    p = problem()
    x = {v.name: v.domain[-1] for v in p.variables}
    result = EvaluationResult(1., {}, True, {}, {})
    proposed = p.feedback_candidates(x, result)
    assert proposed and proposed[0]['tw_bot'] < x['tw_bot']
    assert all(p.repair(item) == item for item in proposed)
    from struct_agent.schemas import DesignCandidate
    values = {k: v/1000. if k != 'conc_bot' else v for k, v in proposed[0].items()}
    p.results.append((DesignCandidate(design_id='seen', layout_id=p.layout.layout_id,
        condition_id=p.spec.condition_id, values=values), result))
    assert proposed[0] not in p.feedback_candidates(x, result)


def test_concrete_cost_recovers_volume_without_density_mismatch() -> None:
    row = dict(conc_bot='C30', tw_bot=200, tw_mid=200, tw_top=200)
    cost = material_cost(concrete_kg=2500., steel_kg=10., row=row, steel_price_per_kg=5.)
    assert cost.concrete_cost == 500. and cost.material_cost == 550.


def test_wall_boundary_quantity_scales_with_story_height() -> None:
    demand = WallDesignDemand(1, 1, .2, 2., 2.9, 0., 0., 0., 0., True)
    designer = WallReinforcementDesigner()
    first = designer.design(demand, MaterialConfig())
    taller = designer.design(replace(demand, story_height_m=5.8), MaterialConfig())
    assert taller.material_usage.steel_kg == pytest.approx(2*first.material_usage.steel_kg)
    expected = (2*.002*.2*2.*2.9 + 2*.005*.2*.4*2.9 + 2*.004*.2*.4*2.9)*7850.
    assert first.material_usage.steel_kg == pytest.approx(expected)


def test_beam_stirrups_include_width_and_depth() -> None:
    demand = BeamDesignDemand(1, 1, .3, .6, 4., 0., 0., 0.)
    result = BeamReinforcementDesigner().design(demand, MaterialConfig())
    longitudinal = (result.top_steel_area_mm2+result.bottom_steel_area_mm2)*1e-6*4.*7850.
    expected_hoops = 50.3e-6*2*(.3+.6-4*.04)*(4000/result.stirrup_spacing_mm)*7850.
    assert result.material_usage.steel_kg-longitudinal == pytest.approx(expected_hoops)


def test_design_failure_feedback_has_resolution_below_binary_failure() -> None:
    from dataclasses import fields
    from struct_agent.adapters.fea import native_params
    from struct_agent.schemas import DesignCandidate
    from struct_agent._vendor.shearwall_modeling.parametric.types import ParametricAnalysisResult
    from struct_agent._vendor.shearwall_optimization.problems.shearwall_problem import summarize_analysis
    p = problem()
    design = DesignCandidate(design_id='synthetic', layout_id=p.layout.layout_id,
        condition_id=p.spec.condition_id, values={v.name: v.values[0] for v in p.spec.design_variables})
    values = {f.name: True if f.type is bool else 0 if f.type is int else 1.0 if f.type is float else ''
              for f in fields(ParametricAnalysisResult)}
    values.update(max_drift_ratio=.0005, period_ratio=.8, min_shear_weight_ratio=.1,
                  design_passed=False, design_failed_wall_count=2)
    raw = ParametricAnalysisResult(**values)
    def summarize(raw: ParametricAnalysisResult) -> EvaluationResult:
        return summarize_analysis(analysis_result=raw, params=native_params(design, p.spec), geom_scale=1.,
            objective_cfg=p.objective_cfg, constraint_cfg=p.constraint_cfg, limit_cfg=p.limit_cfg,
            member_counts={'wall': 10, 'beam': 0})
    initial = summarize(raw)
    improved = summarize(replace(raw, design_failed_wall_count=1, material_concrete_kg=1000.))
    assert not initial.feasible and not improved.feasible
    assert initial.objectives['violation_score']-improved.objectives['violation_score'] == pytest.approx(.1)
    from struct_agent._vendor.shearwall_optimization.surrogate_candidate import SurrogateCandidateEvaluator as E
    assert E.rank_key(improved) < E.rank_key(initial)
    with pytest.raises(ValueError, match='failure count'):
        summarize(replace(raw, design_failed_wall_count=11))
