"""ETABS cantilever checked against independent Timoshenko closed forms."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from struct_agent.io.artifacts import write_json

from .client import ETABSClient, rows
from .contracts import CantileverSpec


def expected(spec: CantileverSpec) -> dict[str, float]:
    a, h, e = spec.side_m, spec.height_m, spec.elastic_modulus_pa
    g, area, inertia = e/(2*(1+spec.poisson)), a*a, a**4/12
    compliance = h**3/(3*e*inertia)+h/(g*(5/6)*area)
    return {'tip_x_m':spec.tip_force_n*compliance,
        'base_fx_n':-spec.tip_force_n, 'base_my_nm':-spec.tip_force_n*h,
        'first_period_s':2*math.pi*math.sqrt(spec.tip_mass_kg*compliance)}


def build_and_analyze(client: ETABSClient, spec: CantileverSpec, directory: Path) -> dict[str, Any]:
    m, call = client.model, client.call
    call('InitializeNewModel', m.InitializeNewModel, 10)  # N, m, Celsius
    call('NewBlank', m.File.NewBlank)
    call('SetPresentUnits', m.SetPresentUnits, 10)
    # NewBlank creates a default story unrelated to our benchmark height.
    # ETABS lumps masses to story levels by default: define the actual level.
    call('SetBenchmarkStory',m.Story.SetStories_2,0.,1,['BenchmarkTop'],[spec.height_m],
        [True],[''],[False],[0.],[0])
    call('SetMaterial', m.PropMaterial.SetMaterial, 'BENCH_ELASTIC', 2)
    call('SetMPIsotropic', m.PropMaterial.SetMPIsotropic, 'BENCH_ELASTIC', spec.elastic_modulus_pa, spec.poisson, 0.)
    call('ZeroDensity', m.PropMaterial.SetWeightAndMass, 'BENCH_ELASTIC', 2, 0.)
    call('SetRectangle', m.PropFrame.SetRectangle, 'BENCH_SQUARE', 'BENCH_ELASTIC', spec.side_m, spec.side_m)
    frame, = call('AddCantilever', m.FrameObj.AddByCoord, 0.,0.,0.,0.,0.,spec.height_m,'','BENCH_SQUARE')
    base, top = call('GetPoints', m.FrameObj.GetPoints, frame)
    call('BaseRestraint', m.PointObj.SetRestraint, base, [True]*6)
    call('TipMass', m.PointObj.SetMass, top, [spec.tip_mass_kg]*3+[0.]*3, 0, False, True)
    call('AddedMassOnly', m.PropMaterial.SetMassSource_1, False, True, False, 0, [], [])
    source = call('MassSourceReadback',m.PropMaterial.GetMassSource_1)
    mass = call('PointMassReadback',m.PointObj.GetMass,top)
    tables = call('AvailableTables',m.DatabaseTables.GetAvailableTables)
    mass_tables = {}
    for key in tables[1]:
        if 'Mass Source' in key:
            mass_tables[key] = call('Table '+key,m.DatabaseTables.GetTableForDisplayArray,key,[],'')
    write_json(directory/'mass_readback.json',{'source':source,'point_mass':mass,'tables':mass_tables})
    call('AddTipPattern', m.LoadPatterns.Add, 'TIP_X', 8, 0., True)
    call('TipLoad', m.PointObj.SetLoadForce, top, 'TIP_X', [spec.tip_force_n,0.,0.,0.,0.,0.], True)
    call('ModalCase', m.LoadCases.ModalEigen.SetCase, 'MODAL_CHECK')
    call('DisableDefaultCases', m.Analyze.SetRunCaseFlag, '', False, True)
    for case in ('TIP_X','MODAL_CHECK'):
        call('EnableCase '+case, m.Analyze.SetRunCaseFlag, case, True)
    call('SaveBeforeAnalysis', m.File.Save, str(directory/'model.EDB'))
    call('RunAnalysis', m.Analyze.RunAnalysis)
    statuses = call('GetCaseStatus', m.Analyze.GetCaseStatus)
    state = dict(zip(statuses[1], statuses[2]))
    if any(state.get(case) != 4 for case in ('TIP_X','MODAL_CHECK')):
        raise RuntimeError(f'Cases did not finish: {state}')
    call('DeselectOutput', m.Results.Setup.DeselectAllCasesAndCombosForOutput)
    call('SelectTip', m.Results.Setup.SetCaseSelectedForOutput, 'TIP_X')
    disp = rows(call('JointDispl', m.Results.JointDispl, top, 0),
        ('object','element','case','step_type','step','u1','u2','u3','r1','r2','r3'), operation='JointDispl')
    reaction = rows(call('BaseReact', m.Results.BaseReact)[:-3],
        ('case','step_type','step','fx','fy','fz','mx','my','mz'), operation='BaseReact')
    call('DeselectOutput', m.Results.Setup.DeselectAllCasesAndCombosForOutput)
    call('SelectModal', m.Results.Setup.SetCaseSelectedForOutput, 'MODAL_CHECK')
    modal = rows(call('ModalPeriod', m.Results.ModalPeriod),
        ('case','step_type','mode','period','frequency','omega','eigenvalue'), operation='ModalPeriod')
    if len(disp) != 1 or len(reaction) != 1 or any(r['case'] != 'MODAL_CHECK' for r in modal):
        raise ValueError('Unexpected benchmark result case/count')
    actual = {'tip_x_m':disp[0]['u1'], 'base_fx_n':reaction[0]['fx'],
        'base_my_nm':reaction[0]['my'], 'first_period_s':max(r['period'] for r in modal)}
    theory = expected(spec)
    # Tight verification tolerance for this linear, single-member benchmark;
    # not a universal tolerance for shell-vs-MVLEM building comparisons.
    checks = {key:math.isfinite(actual[key]) and math.isclose(actual[key], val, rel_tol=1e-4, abs_tol=1e-9)
              for key,val in theory.items()}
    return {'purpose':'SYNTHETIC_MECHANICS_VERIFICATION', 'units':'N_m_kg_s',
        'expected':theory,'actual':actual,'checks':checks,'verified':all(checks.values()),
        'case_status':state,'displacements':disp,'reactions':reaction,'modes':modal,
        'section_properties':call('GetSectProps',m.PropFrame.GetSectProps,'BENCH_SQUARE'),
        'engineering_feasibility':'NOT_EVALUATED'}
