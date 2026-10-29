from types import SimpleNamespace
from typing import Any

import pytest

from struct_agent.adapters.etabs.area_mesh_audit import inspect_area_mesh


class AreaClient:
    def __init__(self, *, split: bool=False) -> None:
        self.operations: list[str] = []
        self.split = split
        self.model = SimpleNamespace(Analyze=SimpleNamespace(CreateAnalysisModel=None),
            AreaObj=SimpleNamespace(GetNameList=None,GetPoints=None,GetElm=None,GetEdgeConstraint=None),
            PointObj=SimpleNamespace(GetCoordCartesian=None),AreaElm=SimpleNamespace(GetPoints=None),
            PointElm=SimpleNamespace(GetCoordCartesian=None))

    def call(self, operation: str, method: Any,*args: Any) -> tuple[Any,...]:
        self.operations.append(operation)
        coords = {'1':(0.,0.,0.),'2':(4.,0.,0.),'3':(4.,0.,3.),'4':(0.,0.,3.)}
        values = {'AuditAreaNames':(1,['W1']),'AuditAreaObjectPoints':(4,list(coords)),
            'AuditGeneratedAreaElements':(2,['E1','E2']) if self.split else (1,['E1']),
            'AuditAreaElementPoints':(4,list(coords)),'AuditAreaEdgeConstraint':(False,)}
        if 'Coord' in operation:
            return coords[args[0]]
        return values.get(operation,())


@pytest.mark.parametrize('split',[False,True])
def test_actual_area_topology_audit_reports_extra_native_mesh_without_solving(split: bool) -> None:
    client = AreaClient(split=split)
    result = inspect_area_mesh(client,generate=False)
    assert result['verified']
    assert result['all_one_to_one_corner_match'] is (not split)
    assert result['analysis_elements']==(2 if split else 1)
    assert result['edge_constraints_enabled']==0
    assert not result['solver_run_called'] and not result['save_called']
    assert 'GenerateCopiedAreaAnalysisGraph' not in client.operations
    assert not any('RunAnalysis' in op or 'Save' in op for op in client.operations)
