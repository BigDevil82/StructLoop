"""Physical global bending tensors, independent of solver local-axis names."""
from __future__ import annotations

from typing import Any

import numpy as np

from .contracts import ResidentialSpec


def review_axes(audit: dict[str, Any], spec: ResidentialSpec) -> dict[str, Any]:
    """CSI row-major local-to-global matrix; columns are global local axes.

    Tensors have Shape (3,3), float64, global XYZ, units m^4. OpenSees'
    vecxz=(0,0,1) implies y=Z cross x and z=Z for these horizontal beams.
    """
    values = spec.design.values
    rows = []
    for name, frame in audit['frames'].items():
        coords = np.asarray(frame['coordinates_m'],dtype=np.float64)
        x = coords[1]-coords[0]
        x /= np.linalg.norm(x)
        if abs(x[2]) > 1e-10:
            raise ValueError('Only source horizontal beams are supported')
        transform = np.asarray(frame['transformation'],dtype=np.float64).reshape(3,3)
        if not np.allclose(transform.T@transform,np.eye(3),atol=1e-10,rtol=0.) or not np.allclose(transform[:,0],x,atol=1e-10,rtol=0.):
            raise ValueError('CSI transformation does not confirm the documented local-to-global convention')
        role = frame['section'][0]
        if role not in ('primary','secondary'):
            raise ValueError('Unexpected beam section')
        suffix = 'main' if role == 'primary' else 'sec'
        width, depth = float(values['bb_'+suffix]),float(values['hb_'+suffix])
        iy, iz = width*depth**3/12,depth*width**3/12
        section = audit['section_properties'][role]
        etabs = section[4]*np.outer(transform[:,1],transform[:,1])+section[5]*np.outer(transform[:,2],transform[:,2])
        y, z = np.cross([0.,0.,1.],x), np.array([0.,0.,1.])
        opensees = iy*np.outer(y,y)+iz*np.outer(z,z)
        relative = float(np.linalg.norm(etabs-opensees)/np.linalg.norm(opensees))
        rows.append({'frame':name,'section':role,'relative_bending_tensor_difference':relative,
            'area_relative_difference':abs(section[0]-width*depth)/(width*depth),
            'etabs_global_inertia_m4':etabs.tolist(),'opensees_global_inertia_m4':opensees.tolist()})
    if not rows:
        raise ValueError('No beam axes reviewed')
    return {'verified':all(r['relative_bending_tensor_difference']<1e-9 and r['area_relative_difference']<1e-9 for r in rows),
        'beams_reviewed':len(rows),'matrix_convention':'row-major local-to-global; local axes are columns',
        'frames':rows}
