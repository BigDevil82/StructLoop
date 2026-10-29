"""Read actual generated shell topology, rather than infer it from objects."""
from __future__ import annotations

from typing import Any

from .client import ETABSClient


def inspect_area_mesh(client: ETABSClient, *, generate: bool=True) -> dict[str,Any]:
    m,call = client.model,client.call
    if generate:
        call('GenerateCopiedAreaAnalysisGraph',m.Analyze.CreateAnalysisModel)
    count,names = call('AuditAreaNames',m.AreaObj.GetNameList)
    if count<=0 or len(names)!=count:
        raise ValueError('No area objects available for topology audit')
    object_coords,element_coords = {},{}
    records = {}
    for name in names:
        n,points = call('AuditAreaObjectPoints',m.AreaObj.GetPoints,name)
        if n!=4 or len(points)!=n:
            raise ValueError('The controlled wall audit requires four-corner objects')
        for point in points:
            if point not in object_coords:
                object_coords[point] = call('AuditObjectPointCoord',m.PointObj.GetCoordCartesian,point)
        ne,elements = call('AuditGeneratedAreaElements',m.AreaObj.GetElm,name)
        if ne<=0 or len(elements)!=ne:
            raise ValueError('Missing generated area elements')
        mesh = []
        for element in elements:
            nn,nodes = call('AuditAreaElementPoints',m.AreaElm.GetPoints,element)
            if len(nodes)!=nn:
                raise ValueError('Invalid generated area connectivity')
            for node in nodes:
                if node not in element_coords:
                    element_coords[node] = call('AuditElementPointCoord',m.PointElm.GetCoordCartesian,node)
            mesh.append({'element':element,'nodes':nodes,'coordinates_m':[element_coords[p] for p in nodes]})
        corners = sorted(tuple(round(v,7) for v in object_coords[p]) for p in points)
        matched = ne==1 and sorted(tuple(round(v,7) for v in p) for p in mesh[0]['coordinates_m'])==corners
        edge, = call('AuditAreaEdgeConstraint',m.AreaObj.GetEdgeConstraint,name)
        records[name] = {'edge_constraint':edge,'one_to_one_corner_match':matched,'elements':mesh}
    return {'purpose':'COPIED_MODEL_ACTUAL_AREA_MESH_AUDIT','verified':True,'area_objects':count,
        'analysis_elements':sum(len(r['elements']) for r in records.values()),
        'all_one_to_one_corner_match':all(r['one_to_one_corner_match'] for r in records.values()),
        'edge_constraints_enabled':sum(bool(r['edge_constraint']) for r in records.values()),'areas':records,
        'solver_run_called':False,'save_called':False,'analysis_model_generated_on_copy':generate}
