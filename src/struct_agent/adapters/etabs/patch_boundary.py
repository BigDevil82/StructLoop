"""Apply complete prescribed fields through a real static increment."""
from __future__ import annotations

import numpy as np


def prescribe_field(values: dict[int,np.ndarray], equation_scale: float) -> None:
    """Exact Lagrange SP equations; no fictitious spring or auxiliary member.

    values[node]: float64 Shape (6,), global XYZ translations (m), rotations
    about global XYZ (rad). equation_scale is a positive numerical scale.

    Updating and committing nodes before an incremental macro element updates
    can erase its deformation increment. A static step commits node/material
    states in solver order and checks all measured nodal DOFs afterwards.
    """
    import openseespy.opensees as ops
    ops.timeSeries('Linear',900001)
    ops.pattern('Plain',900001,900001)
    for node,vector in values.items():
        for dof,value in enumerate(vector,1):
            ops.sp(node,dof,float(value))
    ops.constraints('Lagrange',equation_scale,equation_scale)
    ops.numberer('Plain')
    ops.system('FullGeneral')
    ops.algorithm('Linear')
    ops.integrator('LoadControl',1.)
    ops.analysis('Static')
    if ops.analyze(1)!=0:
        raise RuntimeError('Prescribed-field native static step failed')
    for node,vector in values.items():
        if not np.allclose(ops.nodeDisp(node),vector,atol=1e-12,rtol=1e-9):
            raise ValueError('Prescribed-field native displacement readback mismatch')
