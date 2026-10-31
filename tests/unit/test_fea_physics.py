import math
from types import SimpleNamespace as NS

import pytest

from struct_agent._vendor.shearwall_modeling.analysis.combinations import cqc
from struct_agent._vendor.shearwall_modeling.analysis.uls_combinations import LoadCombinationDef, ULSCombinationAnalyzer
from struct_agent._vendor.shearwall_modeling.analysis import member_forces


def test_signed_combinations_and_negative_shear_envelope() -> None:
    combos = [LoadCombinationDef('plus', 'Seismic', {'Dead': 1., 'EqX': 1.}),
              LoadCombinationDef('minus', 'Seismic', {'Dead': 1., 'EqX': -1.})]
    analyzer = ULSCombinationAnalyzer(NS(), combos)
    forces = {'Dead': {(1, 1): (5., -2., -10.)}, 'EqX': {(1, 1): (2., 4., 30.)}}
    plus = analyzer._combine_one_force((1, 1), combos[0], forces)
    minus = analyzer._combine_one_force((1, 1), combos[1], forces)
    assert plus == (7., 2., 20.) and minus == (3., -6., -40.)
    envelope = analyzer._build_envelope({'plus': {(1, 1): plus}, 'minus': {(1, 1): minus}})[1, 1]
    assert envelope.max_shear_n == 40. and envelope.max_shear_combo == 'minus'
    assert envelope.max_moment_n_m == 6.


def test_zero_force_has_control_combo_and_missing_case_fails() -> None:
    combo = LoadCombinationDef('zero', 'NonSeismic', {'Dead': 1.})
    analyzer = ULSCombinationAnalyzer(NS(), [combo])
    assert analyzer._build_envelope({'zero': {(1, 1): (0., 0., 0.)}})[1, 1].max_shear_combo == 'zero'
    with pytest.raises(ValueError, match='Missing member effect'):
        analyzer._combine_one_force((1, 1), combo, {})


def test_governing_combination_uses_utilization_not_largest_shear() -> None:
    analyzer = ULSCombinationAnalyzer(NS(), [LoadCombinationDef('gravity', 'NonSeismic', {'Dead':1.}),
                                           LoadCombinationDef('earthquake', 'Seismic', {'EqX':1.})])
    envelope = analyzer._build_envelope({'gravity':{(1,1):(0.,0.,180.)},'earthquake':{(1,1):(0.,0.,-170.)}})[1,1]
    assert envelope.max_shear_n == 170. and envelope.max_shear_combo == 'earthquake'


@pytest.mark.parametrize('angle', [0., math.pi/2, math.pi/4])
def test_wall_section_force_uses_wall_axis(angle: float, monkeypatch: pytest.MonkeyPatch) -> None:
    x, y = math.cos(angle), math.sin(angle)
    # In-plane 30 N per node, plus transverse 100 N that must not enter V_in_plane.
    node = [30*x-100*y, 30*y+100*x, 1000., 0., 0., 0.]
    monkeypatch.setattr(member_forces.ops, 'eleResponse', lambda *args: node+node+[0.]*12)
    monkeypatch.setattr(member_forces.ops, 'eleNodes', lambda *args: [1, 2, 3, 4])
    unit = NS(wall_id=1, element_tags=[1], bottom_nodes=[1, 2],
        member=NS(start=NS(x=0., y=0.), end=NS(x=2*x, y=2*y)), node_coords={1:(0.,0.,0.), 2:(2*x,2*y,0.)})
    axial, moment, shear = member_forces.extract_wall_force_tuple(unit)
    assert axial == 2000. and moment == pytest.approx(0.) and shear == pytest.approx(60.)


def test_cqc_matches_ansys_one_percent_close_mode_example() -> None:
    # ANSYS Technology Showcase 12.7: f=4.857/5.017 Hz, damping=1%, rho=0.276.
    eigenvalues = [(2*math.pi*f)**2 for f in (4.857, 5.017)]
    response = cqc([1., 1.], eigenvalues, [.01, .01], [1., 1.])
    rho = (response**2-2.)/2.
    assert rho == pytest.approx(.276, abs=.001)
    assert cqc([3., -4.], [1., 4.], [0., 0.], [1., 1.]) == 5.


@pytest.mark.parametrize('eigenvalues', [[0.], [-1.], [float('nan')]])
def test_invalid_cqc_inputs_fail(eigenvalues: list[float]) -> None:
    with pytest.raises(ValueError):
        cqc([1.], eigenvalues, [.05], [1.])


def test_reinforcement_pipeline_checks_every_modeled_wall() -> None:
    import logging
    from struct_agent._vendor.shearwall_modeling.design.pipeline import ReinforcementDesignPipeline
    checked = []
    pipeline = ReinforcementDesignPipeline(NS(), NS(wall_uls_metrics=[]), NS(resolve_story_profiles=lambda: [NS(story=1, material=NS())]), logging.getLogger('test'))
    demands = [NS(wall_id=1,story=1, length_m=.1), NS(wall_id=2,story=1, length_m=1.)]
    pipeline.extractor = NS(extract=lambda result: ([], demands),compound_demands=[])
    def design(demand: NS, material: NS) -> NS:
        checked.append(demand.length_m)
        return NS(wall_id=demand.wall_id,story=1,is_passed=False)
    pipeline.wall_designer = NS(design=design)
    result = pipeline.run()
    assert checked == [.1, 1.] and len(result.wall_results) == 2


def test_section_limits_use_effective_height_physical_span_and_seismic_factor() -> None:
    from struct_agent._vendor.shearwall_modeling.design.constants import beam_shear_limit,effective_depth_m
    assert effective_depth_m(.4)==pytest.approx(.36)
    assert beam_shear_limit(.3,.4,1.,True)==pytest.approx(.15/.85)
    assert beam_shear_limit(.3,.4,1.001,True)==pytest.approx(.20/.85)
    assert beam_shear_limit(.3,.4,1.,False)==.25
    assert beam_shear_limit(.1,.64,2.,False)==pytest.approx(.20)
    with pytest.raises(ValueError,match='effective depth'):
        effective_depth_m(.04)


def test_beam_design_matches_section_check_and_gravity_is_not_reduced() -> None:
    from struct_agent._vendor.shearwall_modeling.design.beam import BeamReinforcementDesigner
    from struct_agent._vendor.shearwall_modeling.design.results import BeamDesignDemand
    from struct_agent._vendor.shearwall_modeling.core.config import MaterialConfig
    from dataclasses import replace
    designer=BeamReinforcementDesigner()
    demand=BeamDesignDemand(1,1,.3,.4,1.,0.,0.,400000.,shear_cases=((400000.,.15/.85,True),))
    failed=designer.design(demand,MaterialConfig('C40'))
    assert failed.is_section_insufficient == (400000/(19.1e6*.3*.36)>.15/.85)
    passed=designer.design(replace(demand,shear_cases=((400000.,.20/.85,True),)),MaterialConfig('C40'))
    assert not passed.is_section_insufficient
    gravity=designer._design_flexural_steel(100000.,300.,460.,19.1,seismic=False)
    seismic=designer._design_flexural_steel(100000.,300.,460.,19.1,seismic=True)
    assert gravity[0]>seismic[0]
    large=designer._design_flexural_steel(.4*19.1*300*460**2/.75/1000,300.,460.,19.1)
    assert 'compression_zone_limit_exceeded' in large[2]


@pytest.mark.parametrize('x_mm,area_mm2',[(200.,1000.),(20.,1000.),(800.,2000.)])
def test_wall_boundary_area_recovers_independent_force_equilibrium(x_mm: float,area_mm2: float) -> None:
    from struct_agent._vendor.shearwall_modeling.design.wall import symmetric_boundary_area
    b,h,a,fc,fy=200.,2000.,40.,19.1,400.
    # Generate N and M directly from concrete block and compatible bar strains.
    stress=[max(-fy,min(fy,200000*.0033*(1-y/(x_mm/.8)))) for y in (a,h-a)]
    concrete=fc*b*x_mm
    axial=concrete+area_mm2*sum(stress)
    moment=concrete*(h-x_mm)/2+area_mm2*(stress[0]-stress[1])*(h/2-a)
    assert symmetric_boundary_area(axial,moment,b,h,a,fc,fy)==pytest.approx(area_mm2,rel=1e-6)
    assert symmetric_boundary_area(-800000.,0.,b,h,a,fc,fy)==1000.
    assert symmetric_boundary_area(840000.,2500000.,b,h,a,fc,fy)==0.


def test_hrb400_design_strength_and_wall_adjustment_are_distinct() -> None:
    from struct_agent._vendor.shearwall_modeling.design.constants import ReinforcementDesignConstants
    c=ReinforcementDesignConstants()
    assert c.fy_mpa==360. and c.fyv_mpa==360.
    assert c.gamma_re_wall==.85 and c.gamma_re_bending==.75


def test_wall_axial_compression_does_not_count_tension() -> None:
    analyzer=ULSCombinationAnalyzer(NS(),[LoadCombinationDef('compression','Seismic',{}),LoadCombinationDef('tension','Seismic',{})])
    assert analyzer._select_axial_for_wall((1,1),{'compression':{(1,1):(100.,0.,0.)},'tension':{(1,1):(-1000.,0.,0.)}})==(100.,'compression')


def test_missing_members_and_nonfinite_forces_are_rejected() -> None:
    analyzer=ULSCombinationAnalyzer(NS(beam_element_units=[NS(beam_id=1,story=1)],wall_story_element_units=[]))
    with pytest.raises(ValueError,match='Incomplete/extra'):
        analyzer.run({'Dead':{}},{'Dead':{}})
    combo=LoadCombinationDef('bad','NonSeismic',{'Dead':1.})
    with pytest.raises(ValueError,match='Nonfinite'):
        analyzer._combine_one_force((1,1),combo,{'Dead':{(1,1):(0.,0.,float('nan'))}})


def test_empty_member_checks_do_not_pass() -> None:
    from struct_agent._vendor.shearwall_modeling.analysis.checkers import WallULSChecker,BeamShearPressureChecker
    result=NS()
    WallULSChecker().apply([],result);BeamShearPressureChecker().apply([],result)
    assert not result.is_wall_axial_passed and not result.is_wall_shear_pressure_passed and not result.is_beam_shear_pressure_passed


def test_low_damping_spectrum_increases_and_invalid_spectra_fail() -> None:
    from struct_agent._vendor.shearwall_modeling.core.config import SeismicConfig,_gb50011_spectrum_shape_params,_calculate_gb50011_alpha
    assert _gb50011_spectrum_shape_params(.02)[2]==pytest.approx(1+(.05-.02)/(.08+1.6*.02))
    with pytest.raises(ValueError,match='ordered finite'):
        SeismicConfig(periods=[1.,0.],sa=[.1,.2])
    with pytest.raises(ValueError,match='6 s'):
        _calculate_gb50011_alpha(7.,.16,.35,.05)


def test_rsa_averages_signed_modes_and_stiffness_uses_metres(monkeypatch: pytest.MonkeyPatch) -> None:
    from struct_agent._vendor.shearwall_modeling.analysis.response_spectrum import ResponseSpectrumAnalyzer
    context=NS(bbox=(0.,1.,0.,1.),wall_story_element_units=[],num_stories=1,story_heights=[3.],config=NS(seismic=NS(damping_ratio=.05,combination_method='CQC')))
    analyzer=ResponseSpectrumAnalyzer(context)
    def one_mode(**kw: object) -> None:
        kw['modal_drift_center'][0].append(.1)
        kw['modal_story_shear'][0].append(100.)
        for c,value in enumerate((.3,-.1,-.1,.3)):
            kw['modal_drift_corners'][c][0].append(value)
    monkeypatch.setattr(analyzer,'_analyze_mode',one_mode)
    response,_,_=analyzer._run_rsa_analysis(1,'X',[1.],[1000.])
    m=response.metrics[0]
    assert m.drift_max==pytest.approx(.3) and m.drift_avg==pytest.approx(.1)
    assert m.torsion_ratio==pytest.approx(3.) and m.stiffness_k==pytest.approx(100/.3)


def test_physical_span_and_capacity_design_are_shared_across_beam_subdivisions() -> None:
    from struct_agent._vendor.shearwall_modeling.core.domain import BeamMember,BeamRole,PlanMember,Point2D
    def p(x: float,y: float=0.) -> Point2D:return Point2D(x,y)
    beams=[BeamMember(1,'beam',p(0.),p(.8),BeamRole.SECONDARY),BeamMember(2,'beam',p(.8),p(1.),BeamRole.SECONDARY)]
    walls=[PlanMember(3,'shearwall',p(-2.),p(0.)),PlanMember(4,'shearwall',p(1.),p(3.))]
    units=[NS(beam_id=b.m_id,story=1,member=b,width=.3,depth=.4,length=b.length) for b in beams]
    wall_units=[NS(wall_id=w.m_id,story=1,member=w,thickness=.2) for w in walls]
    context=NS(beam_element_units=units,wall_story_element_units=wall_units,story_profiles=[NS(story=1,material=NS(concrete_grade='C40'))],config=NS(seismic=NS(axial_compression_ratio_limit=.5)))
    combos=[LoadCombinationDef('G','NonSeismic',{'Dead':1.}),LoadCombinationDef('E','Seismic',{'EqX':1.})]
    analyzer=ULSCombinationAnalyzer(context,combos)
    zeros={key:(0.,0.,0.) for key in ((1,1),(2,1))}
    result=analyzer.run({'Dead':zeros,'Live':zeros,'EqX':{(1,1):(120000.,60000.,100000.),(2,1):(60000.,-120000.,100000.)}},
        {c:{(3,1):(0.,0.,0.),(4,1):(0.,0.,0.)} for c in ('Dead','Live','EqX')})
    assert all(m.physical_span_m==1. and m.coupling for m in result.beam_metrics)
    assert all(m.shear_checks['E'][0]==pytest.approx(288000.) for m in result.beam_metrics)
    assert all(m.shear_pressure_ratio_limit==pytest.approx(.15/.85) for m in result.beam_metrics)


def test_insufficient_modal_mass_cannot_produce_a_pass() -> None:
    from struct_agent._vendor.shearwall_modeling.analysis.response_spectrum import ResponseSpectrumAnalyzer
    analyzer=ResponseSpectrumAnalyzer(NS(bbox=(0.,1.,0.,1.),wall_story_element_units=[]))
    props={'partiMassRatiosMX':[40.,40.],'partiMassRatiosMY':[50.,45.],'partiMassRatiosRMZ':[1.,1.]}
    with pytest.raises(ValueError,match='90 percent'):
        analyzer.extract_modal_summary([1.,.5],props)


def test_mode_extraction_increases_until_both_directions_have_enough_mass(monkeypatch: pytest.MonkeyPatch) -> None:
    from struct_agent._vendor.shearwall_modeling.analysis.response_spectrum import ResponseSpectrumAnalyzer
    from struct_agent._vendor.shearwall_modeling.analysis import response_spectrum
    calls=[]
    for name in ('constraints','numberer','system','test','algorithm','integrator','analysis'):
        monkeypatch.setattr(response_spectrum.ops,name,lambda *args:None)
    def eigen(method: str,count: int) -> list[float]:
        calls.append(count);return [10.+i for i in range(count)]
    def properties(*args: object) -> dict:
        n=calls[-1]
        return {'eigenLambda':[10.+i for i in range(n)],'partiMassRatiosMX':[40. if n==2 else 20.]*n,
            'partiMassRatiosMY':[45. if n==2 else 20.]*n,'partiMassRatiosRMZ':[.1]*n}
    monkeypatch.setattr(response_spectrum.ops,'eigen',eigen)
    monkeypatch.setattr(response_spectrum.ops,'modalProperties',properties)
    context=NS(bbox=(0.,1.,0.,1.),wall_story_element_units=[],num_stories=3,config=NS(num_modes=2,seismic=NS(periods=[0.,6.])),logger=NS(info=lambda *args:None))
    values,_,summary=ResponseSpectrumAnalyzer(context).run_modal_case()
    assert calls==[2,5] and len(values)==5
    assert summary.mass_participation_x_pct==100. and summary.mass_participation_y_pct==100.


def test_torsion_checks_floor_displacement_in_addition_to_story_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    from struct_agent._vendor.shearwall_modeling.analysis.response_spectrum import ResponseSpectrumAnalyzer
    context=NS(bbox=(0.,1.,0.,1.),wall_story_element_units=[],num_stories=2,story_heights=[3.,3.],config=NS(seismic=NS(damping_ratio=.05,combination_method='CQC')))
    analyzer=ResponseSpectrumAnalyzer(context)
    def one_mode(**kw: object) -> None:
        for story,values in enumerate(((.3,.12,.12,.3),(-.1,-.3,-.3,-.1))):
            kw['modal_drift_center'][story].append(sum(values)/4)
            kw['modal_story_shear'][story].append(100.)
            for c,value in enumerate(values):kw['modal_drift_corners'][c][story].append(value)
    monkeypatch.setattr(analyzer,'_analyze_mode',one_mode)
    response,_,_=analyzer._run_rsa_analysis(1,'X',[1.],[1000.,1000.])
    assert response.metrics[1].torsion_ratio==pytest.approx(20.)


@pytest.mark.parametrize('strain',[.001,-.001])
def test_section_equilibrium_matches_uniform_compression_and_tension(strain: float) -> None:
    import numpy as np
    from struct_agent._vendor.shearwall_modeling.design.wall import section_equilibrium
    concrete=np.array([[-50.,-100.,20000.],[50.,-100.,20000.],[-50.,100.,20000.],[50.,100.,20000.]])
    bars=np.array([[-60.,-160.,0.],[60.,-160.,0.],[-60.,160.,0.],[60.,160.,0.]])
    area=np.full(4,400.)
    fc=19.1
    expected_n=(.75*fc*(80000.-1600.) if strain>0 else 0.)+200000*strain*1600.
    check=section_equilibrium(concrete,bars,area,(expected_n,0.,0.),fc,360.,'uniform')
    assert check.passed and check.relative_error<1e-7
    assert check.resultant_n_mx_my==pytest.approx((expected_n,0.,0.),abs=.01)


def test_section_equilibrium_rejects_demand_above_axial_capacity() -> None:
    import numpy as np
    from struct_agent._vendor.shearwall_modeling.design.wall import section_equilibrium
    concrete=np.array([[-50.,-100.,20000.],[50.,-100.,20000.],[-50.,100.,20000.],[50.,100.,20000.]])
    bars=concrete.copy();area=np.full(4,400.)
    capacity=19.1*(80000-1600)+360*1600
    assert not section_equilibrium(concrete,bars,area,(1.1*capacity,0.,0.),19.1,360.,'over_capacity').passed


def test_biaxial_equilibrium_is_rotation_invariant() -> None:
    import numpy as np
    from struct_agent._vendor.shearwall_modeling.design.wall import section_equilibrium
    concrete=np.array([[-50.,-100.,20000.],[50.,-100.,20000.],[-50.,100.,20000.],[50.,100.,20000.]])
    bars=np.array([[-60.,-160.,0.],[60.,-160.,0.],[-60.,160.,0.],[60.,160.,0.]])
    area=np.full(4,400.);fc=19.1
    def strain(points: np.ndarray) -> np.ndarray:return .0004+.0005*points[:,1]/400-.0003*points[:,0]/400
    def stress(e: np.ndarray) -> np.ndarray:return fc*(2*(e/.002)-(e/.002)**2)
    stress_c=stress(strain(concrete));stress_s=200000*strain(bars)-stress(strain(bars))
    n=sum(stress_c*concrete[:,2])+sum(stress_s*area)
    mx=(sum(stress_c*concrete[:,2]*concrete[:,1])+sum(stress_s*area*bars[:,1]))/1000
    my=-(sum(stress_c*concrete[:,2]*concrete[:,0])+sum(stress_s*area*bars[:,0]))/1000
    first=section_equilibrium(concrete,bars,area,(n,mx,my),fc,360.,'biaxial')
    rotation=np.array([[0.,1.],[-1.,0.]])
    rotated_c=concrete.copy();rotated_b=bars.copy()
    rotated_c[:,:2]=concrete[:,:2]@rotation;rotated_b[:,:2]=bars[:,:2]@rotation
    second=section_equilibrium(rotated_c,rotated_b,area,(n,-my,mx),fc,360.,'rotated')
    assert first.passed and second.passed
    assert first.max_concrete_strain==pytest.approx(second.max_concrete_strain,abs=1e-7)
