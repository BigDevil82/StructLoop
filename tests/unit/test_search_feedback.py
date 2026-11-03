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


def test_failed_beam_feedback_includes_shallower_sections_within_domain() -> None:
    p = problem()
    x = {v.name: v.domain[-1] for v in p.variables}
    result = EvaluationResult(1., {}, False, {}, {'normalized_violations': {'beam_shear_ratio': .3}})
    proposed = p.feedback_candidates(x, result)
    assert any(c['hb_sec'] < x['hb_sec'] for c in proposed)
    assert any(c['hb_main'] < x['hb_main'] for c in proposed)
    assert all(c[v.name] in v.domain for c in proposed for v in p.variables)


def test_parameter_modification_preserves_geometry_and_checks_scope_domains_and_protection() -> None:
    import hashlib
    from struct_agent.schemas.state import ParameterModification, Decision
    from struct_agent.adapters.design_search import apply_parameter_modification
    layout, _, design, _ = local_case()
    spec = ProjectSpec.model_validate_json(Path('configs/reference_spec.json').read_text(encoding='utf-8'))
    spec = spec.model_copy(update={'condition_id':design.condition_id})
    before = design.model_dump_json(), layout.model_dump_json()
    instruction = ParameterModification(operation='set_design_parameters',source_evaluation_id='synthetic_eval',
        source_layout_sha256=hashlib.sha256(layout.model_dump_json().encode()).hexdigest(),
        parameter_updates={'conc_bot':'C35'},expected_effect='Synthetic trial only')
    candidate = apply_parameter_modification(layout,design,spec,instruction)
    assert candidate.values == {**design.values,'conc_bot':'C35'}
    assert candidate.layout_id == design.layout_id and candidate.condition_id == design.condition_id
    assert before == (design.model_dump_json(),layout.model_dump_json())
    parsed = Decision.model_validate_json(Decision(action='PROPOSE_MODIFICATION',reason='test',modification=instruction).model_dump_json())
    assert parsed.modification == instruction
    for updates in ({'stories':18.}, {'intensity':9.}, {}):
        with pytest.raises(ValueError):
            ParameterModification.model_validate({**instruction.model_dump(),'parameter_updates':updates})
    for updates in ({'bb_sec':.123}, {'tw_mid':.25}, {'conc_bot':'C30'}):
        with pytest.raises(ValueError):
            apply_parameter_modification(layout,design,spec,instruction.model_copy(update={'parameter_updates':updates}))
    with pytest.raises(ValueError,match='protected'):
        apply_parameter_modification(layout,design,spec,instruction,protected_member_ids=frozenset({'b'}))
    with pytest.raises(ValueError,match='Stale source'):
        apply_parameter_modification(layout,design,spec,instruction.model_copy(update={'source_layout_sha256':'stale'}))


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


def local_case() -> tuple:
    """Synthetic architecture and traceable member evidence, metres/N/Pa."""
    from struct_agent.schemas import Member, RoomGraph, DesignCandidate
    from struct_agent.schemas.diagnostics import MemberDiagnostic
    layout=LayoutCandidate(layout_id='local_test',source='synthetic_test',length_unit='m',coordinate_system='global_xy',
        members=(Member(member_id='wl',start=(0.,3.),end=(1.,3.),role='wall'),
            Member(member_id='b',start=(1.,3.),end=(3.,3.),role='secondary'),
            Member(member_id='wr',start=(3.,3.),end=(4.,3.),role='wall'),
            Member(member_id='root_l',start=(0.,3.),end=(0.,0.),role='wall'),
            Member(member_id='root_r',start=(4.,3.),end=(4.,0.),role='wall')),
        slabs=(((0.,0.),(4.,0.),(4.,3.),(0.,3.)),))
    rooms=RoomGraph(feature_version='rcgnn_25_8_v1',length_unit='m',native_feature_length_unit='mm',coordinate_system='global_xy',
        x=((0.,)*25,),edge_index=((),()),edge_attr=(),room_polygons=layout.slabs,
        masks=(tuple((((0.,1.),)) for _ in range(8)),),category=2)
    design=DesignCandidate(design_id='test',layout_id=layout.layout_id,condition_id='test',
        values={'tw_bot':.2,'tw_mid':.2,'tw_top':.2,'bb_main':.25,'hb_main':.5,'bb_sec':.3,'hb_sec':.4,'conc_bot':'C30'})
    def diagnostic(index: int) -> MemberDiagnostic:
        import math
        m=layout.members[index];denom=14.3e6*.3*.36
        return MemberDiagnostic(native_id=index,member_id=m.member_id,source_member_ids=(m.member_id,),role=m.role,story=1,
            start_m=m.start,end_m=m.end,length_m=math.dist(m.start,m.end),width_m=.3,depth_m=.4,effective_depth_m=.36,
            physical_span_m=math.dist(m.start,m.end),coupling=True,concrete_grade='C30',fc_pa=14.3e6,beta_c=1.,
            shear_n=.24*denom,denominator_n=denom,shear_ratio=.24,shear_limit=.2,control_combo='test',control_combo_type='Seismic',
            combo_shear_n={'test':.24*denom},combo_design_shear_n={'test':.24*denom},combo_shear_limits={'test':.2},
            shear_passed=False,reinforcement_checked=True,reinforcement_passed=False)
    return layout,rooms,design,diagnostic


def test_local_beam_shear_candidates_move_joint_without_retyping_members() -> None:
    from struct_agent.adapters.design_search import local_layout_candidates
    import math
    layout,rooms,design,diagnostic=local_case()
    before=layout.model_dump_json()
    first=local_layout_candidates(layout,rooms,design,(diagnostic(1),),steps_m=(.1,))
    second=local_layout_candidates(layout,rooms,design,(diagnostic(1),),steps_m=(.1,))
    assert first==second and len(first.proposals)==2
    assert layout.model_dump_json()==before
    for proposal in first.proposals:
        assert proposal.operation=='retract_wall_tip'
        assert [(m.member_id,m.role) for m in proposal.layout.members]==[(m.member_id,m.role) for m in layout.members]
        assert math.dist(proposal.layout.members[1].start,proposal.layout.members[1].end)==pytest.approx(2.1)
        assert proposal.layout.slabs==layout.slabs
        assert len({proposal.move.after_m for m in proposal.layout.members if proposal.move.after_m in (m.start,m.end)})==1


def test_local_wall_extension_respects_opening_masks_and_protected_members() -> None:
    from struct_agent.adapters.design_search import local_layout_candidates
    layout,rooms,design,diagnostic=local_case()
    permitted=local_layout_candidates(layout,rooms,design,(diagnostic(0),),steps_m=(.1,))
    assert len(permitted.proposals)==1 and permitted.proposals[0].operation=='extend_wall_tip'
    mask=list(rooms.masks[0]);mask[0]=((0.,.5),)
    blocked=rooms.model_copy(update={'masks':(tuple(mask),)})
    result=local_layout_candidates(layout,blocked,design,(diagnostic(0),),steps_m=(.1,))
    assert not result.proposals and any('door_window' in x for x in result.rejected)
    protected=local_layout_candidates(layout,rooms,design,(diagnostic(1),),protected_member_ids=frozenset({'wl','wr'}))
    assert not protected.proposals and any('protected' in x for x in protected.rejected)


def test_local_move_cannot_disconnect_a_branch_or_leave_a_tiny_wall() -> None:
    from struct_agent.adapters.design_search import local_layout_candidates
    from struct_agent.schemas import Member
    layout,rooms,design,diagnostic=local_case()
    branched=layout.model_copy(update={'members':layout.members+(
        Member(member_id='branch',start=(1.,3.),end=(1.,1.),role='primary'),)})
    result=local_layout_candidates(branched,rooms,design,(diagnostic(1),),steps_m=(.1,))
    assert len(result.proposals)==1
    assert result.proposals[0].move.wall_member_id=='wr'
    assert any('branch_or_support' in x for x in result.rejected)
    tiny=local_layout_candidates(layout,rooms,design,(diagnostic(1),),steps_m=(.9,))
    assert not tiny.proposals and any('residual_wall_too_short' in x for x in tiny.rejected)


def test_short_coupling_beam_may_lengthen_but_cannot_be_shortened_further() -> None:
    from struct_agent.adapters.design_search import local_layout_candidates
    layout,rooms,design,diagnostic=local_case()
    members=list(layout.members)
    members[1]=members[1].model_copy(update={'end':(1.4,3.)})
    members[2]=members[2].model_copy(update={'start':(1.4,3.)})
    short=layout.model_copy(update={'members':tuple(members)})
    evidence=diagnostic(1).model_copy(update={'end_m':(1.4,3.),'length_m':.4,'physical_span_m':.4})
    longer=local_layout_candidates(short,rooms,design,(evidence,),steps_m=(.1,))
    assert longer.proposals
    assert not local_layout_candidates(short,rooms,design,(diagnostic(0),),steps_m=(.1,)).proposals


def test_local_feedback_rejects_other_layout_geometry_and_does_not_invent_failed_checks() -> None:
    from struct_agent.adapters.design_search import local_layout_candidates
    layout,rooms,design,diagnostic=local_case()
    wrong=diagnostic(1).model_copy(update={'start_m':(1.1,3.)})
    with pytest.raises(ValueError,match='Diagnostic geometry'):
        local_layout_candidates(layout,rooms,design,(wrong,))
    passed=diagnostic(1).model_copy(update={'reinforcement_passed':True,'shear_ratio':.196,'shear_limit':.2,
        'shear_passed':True,'shear_n':.196*diagnostic(1).denominator_n,
        'combo_shear_n':{'test':.196*diagnostic(1).denominator_n},'combo_design_shear_n':{'test':.196*diagnostic(1).denominator_n}})
    assert not local_layout_candidates(layout,rooms,design,(passed,)).proposals
    assert local_layout_candidates(layout,rooms,design,(passed,),target_utilization=.95).proposals


def test_local_evaluation_preserves_failed_attempts_budget_and_input_sections(tmp_path: Path, spec: ProjectSpec) -> None:
    from dataclasses import fields,asdict
    from struct_agent.schemas import AnalysisRecord
    from struct_agent.services.analysis import AnalysisService
    from struct_agent.services.diagnostics import evaluate_local_layout_candidates
    from struct_agent._vendor.shearwall_modeling.parametric.types import ParametricAnalysisResult
    layout,rooms,design,diagnostic=local_case()
    design=design.model_copy(update={'condition_id':spec.condition_id,'values':{v.name:v.values[0] for v in spec.design_variables}})
    class SyntheticSolver:
        fidelity='mock'
        def evaluate(self, candidate, parameters, conditions, *, evaluation_id):
            assert parameters.values==design.values
            if evaluation_id=='eval_00003':raise ArithmeticError('synthetic local trial failure')
            passed=evaluation_id!='eval_00001'
            raw={f.name:True if f.type is bool else 0 if f.type is int else 1. if f.type is float else ''
                 for f in fields(ParametricAnalysisResult)}
            raw.update(feasible=passed,design_passed=passed,beam_shear_passed=passed,
                design_failed_beam_count=0 if passed else 1,torsion_ratio=1.2,period_ratio=.8,max_drift_ratio=.0005,
                max_wall_axial_ratio=.2,max_wall_axial_limit=.5,max_wall_shear_ratio=.1,max_wall_shear_limit=.2,
                max_beam_shear_ratio=.1 if passed else .3,max_beam_shear_limit=.2)
            return AnalysisRecord(evaluation_id=evaluation_id,layout_id=candidate.layout_id,design_id=parameters.design_id,
                condition_id=conditions.condition_id,fidelity='mock',status='SUCCESS',solver='synthetic_test',solver_version='test',
                elapsed_s=0.,feasible=passed,raw=asdict(ParametricAnalysisResult(**raw)),error=None)
    service=AnalysisService(SyntheticSolver(),budget=3,directory=tmp_path/'analyses')
    summary=evaluate_local_layout_candidates(service,layout,design,spec,rooms,(diagnostic(1),),max_candidates=4)
    assert summary['termination']=='budget_exhausted' and summary['fea_attempts']==3
    assert summary['evaluated_candidate_count']==2
    assert summary['candidates'][0]['feasible'] and summary['candidates'][0]['ranking_improved']
    assert summary['candidates'][1]['analysis']['status']=='SOLVER_ERROR'
    assert summary['candidates'][1]['error']['error_type']=='ArithmeticError'
    assert all(r.fidelity=='mock' for r in service.records)
    assert len(list((tmp_path/'analyses').glob('eval_*.json')))==3
