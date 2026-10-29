"""Translation-compatible single-wall MVLEM diagnostic; no production changes."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from struct_agent.io.artifacts import write_json
from .wall_input import WallCase, beam_reference, response_checks


def solve_wall(case: WallCase, directory: Path) -> dict[str, Any]:
    import openseespy.opensees as ops
    from struct_agent._vendor.shearwall_modeling.builders.mvlem_frame import wall_shear_stiffness
    directory.mkdir(exist_ok=False, parents=True)
    write_json(directory/'input.json', case.model_dump())
    ops.wipe()
    try:
        ops.logFile(str(directory/'opensees.log'))
        ops.model('basic', '-ndm', 3, '-ndf', 6)
        dz = case.height_m/case.panels
        ops.uniaxialMaterial('Elastic', 1, case.elastic_modulus_pa)
        ops.uniaxialMaterial('Elastic', 2, wall_shear_stiffness(
            case.length_m, case.thickness_m, dz, case.shear_modulus_pa))
        for level in range(case.panels+1):
            for side in range(2):
                tag = 2*level+side+1
                ops.node(tag, (side-.5)*case.length_m, 0., level*dz)
                ops.fix(tag, *([1]*6 if level == 0 else [0, 1, 0, 1, 0, 1]))
            if level and level % case.subdivisions == 0 and case.diaphragm == 'physical_floors':
                # In XZ with UY/RZ restrained, a horizontal rigid diaphragm is
                # exactly equal UX. UZ and in-plane RY remain independent.
                ops.equalDOF(2*level+1, 2*level+2, 1)
            if level:
                m = case.fibers
                ops.element('MVLEM_3D', level, 2*level-1, 2*level, 2*level+2, 2*level+1, m,
                    '-thick', *([case.thickness_m]*m), '-width', *([case.length_m/m]*m),
                    '-rho', *([0.]*m), '-matConcrete', *([1]*m), '-matSteel', *([1]*m),
                    '-matShear', 2, '-CoR', .4, '-Poisson', case.poisson)
        ops.timeSeries('Linear', 1)
        ops.pattern('Plain', 1, 1)
        for tag in (2*case.panels+1, 2*case.panels+2):
            ops.load(tag, case.tip_force_n/2, 0., 0., 0., 0., 0.)
        ops.constraints('Transformation')
        ops.numberer('RCM')
        ops.system('UmfPack')
        ops.algorithm('Linear')
        ops.integrator('LoadControl', 1.)
        ops.analysis('Static')
        code = ops.analyze(1)
        if code != 0:
            raise RuntimeError(f'Single-wall solve failed: {case.case_id}, returncode={code}')
        displacement = [[list(ops.nodeDisp(2*level+side+1)) for side in range(2)]
            for level in range(case.panels+1)]
        ops.reactions()
        # Include nodal moment and lever-arm force couple about global origin.
        base = [ops.nodeReaction(tag) for tag in (1, 2)]
        total = [sum(r[i] for r in base) for i in range(6)]
        for side in range(2):
            total[4] -= (side-.5)*case.length_m*base[side][2]
            total[5] += (side-.5)*case.length_m*base[side][1]
        reaction = dict(zip(('fx', 'fy', 'fz', 'mx', 'my', 'mz'), total))
        checks = response_checks(case, displacement, reaction, (0., 0., 0.))
        tip = sum(node[0] for node in displacement[-1])/2
        theory = beam_reference(case)
        discrete_verified = math.isclose(tip, theory['mvlem_discrete_m'], rel_tol=1e-7, abs_tol=1e-10)
        result = {'case':case.model_dump(), 'solver_version':ops.version(), 'checks':checks,
            'verified':all(checks.values()), 'displacement':displacement, 'base_reaction':reaction,
            'tip_x_m':tip, 'beam_reference':theory, 'discrete_verified':discrete_verified,
            'beam_relative_difference':tip/theory['timoshenko_m']-1,
            'nodes':len(ops.getNodeTags()), 'elements':len(ops.getEleTags()),
            'engineering_feasibility':'NOT_EVALUATED'}
        write_json(directory/'result.json', result)
        return result
    finally:
        ops.wipe()
