"""Independent load equilibrium and strict displacement result validation."""
from __future__ import annotations

import math
from typing import Any


def roof_equilibrium(reaction: dict[str,Any], reference: tuple[float,...], point: tuple[float,float,float],
                     force_n: float, direction: str) -> dict[str,bool]:
    if direction not in ('X','Y') or len(reference)!=3:
        raise ValueError('A 3D reference point and X/Y direction are required')
    x,y,z = (a-b for a,b in zip(point,reference))
    fx,fy = (force_n,0.) if direction=='X' else (0.,force_n)
    expected = dict(fx=-fx,fy=-fy,fz=0.,mx=z*fy,my=-z*fx,mz=y*fx-x*fy)
    tolerance = force_n*max(1.,abs(x),abs(y),abs(z))*1e-7
    return {key:math.isfinite(reaction[key]) and math.isclose(reaction[key],value,rel_tol=1e-6,abs_tol=tolerance)
            for key,value in expected.items()}
