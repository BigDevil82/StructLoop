"""Explicit local-reference regressions, not a scientific benchmark."""
import ast
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from struct_agent.adapters.rcgnn import RCGNNAdapter, graph_from_dxf, layout_from_prediction
from struct_agent.io.case import load_generation_case
from struct_agent.schemas import AnalysisRecord, DesignCandidate, LayoutCandidate, ProjectSpec, RoomGraph

pytestmark = pytest.mark.real
UPSTREAM = Path("E:/Common/Desktop/Research/deepLearning/codes/Png2Dxf")


def test_rcgnn_matches_original_model_on_current_case() -> None:
    case, dxf = load_generation_case(Path('configs/test_case.json'))
    from struct_agent._vendor.shearwall_pred.utils import extract_dxf_geometry
    raw_rooms, _, _ = extract_dxf_geometry(str(dxf))
    np.testing.assert_allclose([
        (max(room.bounds[2] for room in raw_rooms) - min(room.bounds[0] for room in raw_rooms)) / 1000.,
        (max(room.bounds[3] for room in raw_rooms) - min(room.bounds[1] for room in raw_rooms)) / 1000.],
        [27.1, 12.5], atol=1e-6)
    graph = graph_from_dxf(dxf, category=case.category)
    assert len(graph.x) == 43
    points = [point for polygon in graph.room_polygons for point in polygon]
    np.testing.assert_allclose([max(p[0] for p in points) - min(p[0] for p in points),
                               max(p[1] for p in points) - min(p[1] for p in points)],
                              [27.1, 12.3], atol=1e-6)
    # Original 200 mm coordinate clustering snaps the highest boundary down by 200 mm.
    # Raw drawing dimensions and model-preprocessed dimensions are deliberately tested separately.
    checkpoints = tuple(sorted(Path('checkpoints/rcgnn').glob('*.pth')))
    migrated = RCGNNAdapter(checkpoints,device='cpu').predict(graph)
    # Compile only the original trusted model definitions, with their own unchanged imports.
    # This avoids importing the upstream training/plot framework into the test process.
    import torch.nn as nn
    import torch.nn.functional as F
    from torch_geometric.data import Batch, Data
    from torch_geometric.nn import BatchNorm, GATv2Conv
    from struct_agent._vendor.shearwall_pred.config import model_config
    raw = UPSTREAM/'src/shearwall_pred/model.py'
    tree = ast.parse(raw.read_text(encoding='utf-8-sig'))
    classes = [n for n in tree.body if isinstance(n,ast.ClassDef)]
    namespace = dict(torch=torch,nn=nn,F=F,Data=Data,BatchNorm=BatchNorm,GATv2Conv=GATv2Conv,model_config=model_config)
    exec(compile(ast.Module(body=classes,type_ignores=[]),str(raw),'exec'),namespace)
    data = Batch.from_data_list([Data(x=torch.tensor(graph.x,dtype=torch.float32),
        edge_index=torch.tensor(graph.edge_index,dtype=torch.long),edge_attr=torch.tensor(graph.edge_attr,dtype=torch.float32),
        condition=torch.nn.functional.one_hot(torch.tensor([graph.category]),3).float())])
    outputs = []
    for path in checkpoints:
        model = namespace['ShearWallGNN']().eval()
        model.load_state_dict(torch.load(path,map_location='cpu',weights_only=True))
        with torch.no_grad():
            outputs.append(model(data))
    prob = torch.stack([v[0] for v in outputs]).mean(0)
    ratio = torch.stack([v[1] for v in outputs]).mean(0)
    expected = ((prob > .5)*ratio).numpy()
    expected[expected < .1] = 0.
    np.testing.assert_allclose(migrated,expected,rtol=1e-6,atol=1e-7)
    layout = layout_from_prediction(graph, migrated, layout_id=case.case_id)
    assert len(layout.slabs) == len(graph.x)
    assert any(member.role == 'wall' for member in layout.members)


@pytest.mark.parametrize('relative,class_name',[
    ('shearwall_optimization/algorithms/genetic.py','GeneticAlgorithmOptimizer'),
    ('shearwall_optimization/local_calibration.py','OnlineLocalCalibrator'),
    ('surrogate/gnn/model.py','LayoutParamGNN'),
    ('shearwall_modeling/builders/mvlem_frame.py','MVLEMFrameBuilder'),
])
def test_scientific_algorithm_bodies_unchanged(relative: str,class_name: str) -> None:
    def body(path: Path) -> str:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        node = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name == class_name)
        # Import namespace is the only difference in method bodies.
        return ast.dump(node,include_attributes=False).replace('struct_agent._vendor.','src.')
    assert body(Path('src/struct_agent/_vendor')/relative) == body(UPSTREAM/'src'/relative)


def test_real_fea_matches_original_reference(tmp_path: Path) -> None:
    # Frozen historical L17_101 parity regression; new engineering tests use configs/test_case.json.
    from struct_agent.adapters.fea import OpenSeesAdapter
    layout = LayoutCandidate.model_validate_json(Path('outputs/migration_rcgnn_01/layout.json').read_text(encoding='utf-8'))
    spec = ProjectSpec.model_validate_json(Path('configs/reference_spec.json').read_text(encoding='utf-8'))
    data = json.loads(Path('outputs/migration_casino_calibration_01/analyses/eval_00001.json').read_text(encoding='utf-8'))
    design = DesignCandidate.model_validate_json(json.dumps(data['design']))
    record = OpenSeesAdapter(log_directory=tmp_path/'logs').evaluate(layout,design,spec,evaluation_id='regression_01')
    assert record.status == 'SUCCESS', record.error
    reference = json.loads(Path('outputs/upstream_fea_regression_01/comparison.json').read_text(encoding='utf-8'))
    for name,row in reference.items():
        actual, expected = record.raw[name], row['actual']
        if isinstance(expected,(str,bool)) or expected is None:
            assert actual == expected
        else:
            np.testing.assert_allclose(actual,expected,rtol=1e-5,atol=1e-8,err_msg=name)
    assert record.feasible is False  # real analyzed example fails checks; not a solver failure
    assert Path(record.solver_log).is_file()


def test_objective_formula_preserved() -> None:
    path = 'shearwall_optimization/problems/shearwall_problem.py'
    original = ast.parse((UPSTREAM/'src'/path).read_text(encoding='utf-8-sig'))
    fn = next(n for n in original.body if isinstance(n,ast.FunctionDef) and n.name == '_evaluate_decision')
    start = next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id == 'cost' for t in n.targets))
    expected = ast.unparse(ast.Module(body=fn.body[start:],type_ignores=[])).replace("float(merged['intensity'])","float(params.intensity)")
    migrated = ast.parse((Path('src/struct_agent/_vendor')/path).read_text(encoding='utf-8'))
    fn = next(n for n in migrated.body if isinstance(n,ast.FunctionDef) and n.name == 'summarize_analysis')
    assert ast.dump(ast.parse(expected)) == ast.dump(ast.Module(body=fn.body,type_ignores=[]))
