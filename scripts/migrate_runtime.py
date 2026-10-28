"""One-time, explicit allowlist extraction; sources read-only, destination must be new.

AST removes training/demo/plot entry points and unused imports, then follows only
the remaining runtime imports. Core numerical class/function bodies stay intact.
All deviations and both file hashes are recorded in migration_manifest.json.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

from scripts.audit_upstream import DEFAULT_SOURCE

PREFIX = "struct_agent._vendor"
SEEDS = [
    "src.shearwall_pred.model", "src.shearwall_pred.utils",
    "src.data_engine.postprocess.fem_builder",
    "src.shearwall_optimization.algorithms.genetic",
    "src.shearwall_optimization.problems.shearwall_problem",
    "src.surrogate.gnn.model", "src.surrogate.gnn.dataset",
    "src.surrogate.features.layout_features",
    "src.surrogate.gnn.graph_data",
    "src.shearwall_modeling.parametric.analysis",
]
KEEP = {
    "src.surrogate.gnn.dataset": {"ParamPreprocessor", "SurrogateGNNDataset"},
    "src.surrogate.gnn.graph_data": {"_build_room_graph_data"},
    "src.shearwall_modeling.parametric.space": {"normalize_params", "split_stories", "_normalize_conc"},
    "src.shearwall_pred.config": {"ModelConfig", "DataConfig", "VisualizationConfig"},
    "src.shearwall_pred.utils": {"compute_anchor_ratios", "mask_to_constraint_vector", "extract_dxf_geometry", "build_graph_from_dxf", "get_file_category"},
    "src.shearwall_pred.augmentor": {"GeometryAugmentor"},
    "src.data_engine.postprocess.fem_builder": {"FEMTopologyBuilder"},
    "src.data_engine.preprocess.dxf_extractor": {"Point", "Wall", "LineSegment", "Room", "DXFExtractor"},
    "src.data_engine.preprocess.layout_graph": {"LayoutGraphBuilder"},
    "src.data_engine.preprocess.room_analyzer": {"RoomAnalyzer", "get_room_edges", "_walls_from_vector"},
    "src.data_engine.preprocess.room_calibrator": {"RoomCalibrator", "calibrate_rooms"},
    "src.shearwall_optimization.problems.shearwall_problem": {
        "ShearWallObjectiveConfig", "ShearWallConstraintConfig", "ShearWallLimitConfig",
        "_evaluate_decision", "_failed", "_shear_weight_limit"},
}


class Trim(ast.NodeTransformer):
    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        node.body = [n for n in node.body if not isinstance(n, ast.FunctionDef)
                     or not any(s in n.name for s in ("visualiz", "plot", "export_to_dxf"))]
        return self.generic_visit(node)


def transform(module: str, raw: str) -> str:
    tree = ast.parse(raw)
    body = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if module in KEEP and node.name not in KEEP[module]:
                continue
            if node.name == "main" or node.name.startswith(("plot_", "visualize_")):
                continue
        if isinstance(node, (ast.If, ast.Expr)):
            # Drop __main__ and import-time effects; retain module docstrings.
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant):
                continue
        if module == "src.shearwall_pred.config" and isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "training_config" for t in node.targets):
                continue
        body.append(node)
    tree.body = body
    tree = Trim().visit(tree)
    source = ast.unparse(tree)
    if module == "src.surrogate.gnn.dataset":
        source = source.replace("from src.surrogate.training.lightgbm_baseline import CLASS_TASK", "CLASS_TASK = 'final_pass'")
    if module == "src.shearwall_modeling.parametric.analysis":
        source = source.replace("from ..builders import DetailedShellBuilder, EquivalentFrameBuilder, MVLEMFrameBuilder", "from ..builders.mvlem_frame import MVLEMFrameBuilder")
        source = source.replace("from ..design import ReinforcementDesignPipeline", "from ..design.pipeline import ReinforcementDesignPipeline")
        tree = ast.parse(source)
        for n in tree.body:
            if isinstance(n, ast.FunctionDef) and n.name == "analyze_parametric_model":
                for t in ast.walk(n):
                    if isinstance(t, ast.ExceptHandler):
                        t.body = [ast.Raise()]
            if isinstance(n, ast.FunctionDef) and n.name == "_create_builder":
                n.body = ast.parse("if name == 'mvlem_frame':\n    return MVLEMFrameBuilder(logger, fiber_width=0.2)\nraise ValueError(f'Only migrated builder mvlem_frame is supported: {name}')").body
        source = ast.unparse(tree)
    if module == "src.shearwall_optimization.problems.shearwall_problem":
        tree = ast.parse(source)
        for n in tree.body:
            if isinstance(n, ast.FunctionDef) and n.name == "_evaluate_decision":
                n.name = "summarize_analysis"
                n.args = ast.parse("def f(*, analysis_result, params, geom_scale, objective_cfg, constraint_cfg, limit_cfg): pass").body[0].args
                start = next(i for i, s in enumerate(n.body) if isinstance(s, ast.Assign)
                             and any(isinstance(t, ast.Name) and t.id == "cost" for t in s.targets))
                n.body = n.body[start:]
        source = ast.unparse(tree).replace("float(merged['intensity'])", "float(params.intensity)")
    # Remove unused imports after trimming (including lazy imports in removed methods).
    tree = ast.parse(source)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    class Imports(ast.NodeTransformer):
        def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom | None:
            if node.module == '__future__':
                return node
            node.names = [a for a in node.names if (a.asname or a.name) in used or a.name == '*']
            return node if node.names else None
        def visit_Import(self, node: ast.Import) -> ast.Import | None:
            node.names = [a for a in node.names if (a.asname or a.name.split('.')[0]) in used]
            return node if node.names else None
    tree = Imports().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def migrate(source: Path, destination: Path, *, refresh: bool = False) -> None:
    """Copy the verified runtime dependency closure into an isolated namespace."""
    if destination.exists():
        if not refresh:
            raise FileExistsError(destination)
        old = json.loads((destination / 'migration_manifest.json').read_text(encoding='utf-8'))
        for row in old['files']:
            path = Path(row['destination'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != row['destination_sha256']:
                raise ValueError(f'Refusing to overwrite edited migration: {path}')
    destination.mkdir(parents=True, exist_ok=refresh)
    queue = list(SEEDS)
    seen: set[str] = set()
    records = []
    while queue:
        module = queue.pop(0)
        if module in seen:
            continue
        seen.add(module)
        path = source.joinpath(*module.split('.')).with_suffix('.py')
        if not path.is_file():
            raise FileNotFoundError(f"Unresolved runtime module: {module}")
        raw = path.read_text(encoding="utf-8-sig")
        text = transform(module, raw)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            target = node.module or ""
            if node.level:
                target = importlib.util.resolve_name('.' * node.level + target, module.rsplit('.', 1)[0])
            if not target.startswith('src.'):
                continue
            target_path = source.joinpath(*target.split('.'))
            if target_path.with_suffix('.py').is_file():
                queue.append(target)
            else:
                # Package symbol imports must resolve explicitly, never import a huge __init__.
                for alias in node.names:
                    candidate = target_path / (alias.name + '.py')
                    if candidate.is_file():
                        queue.append(target + '.' + alias.name)
                    else:
                        raise ValueError(f"Resolve package symbol explicitly: {module}: {target}.{alias.name}")
        text = text.replace('from src.', f'from {PREFIX}.')
        target = destination.joinpath(*module.split('.')[1:]).with_suffix('.py')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        parent = target.parent
        while parent != destination.parent:
            (parent / '__init__.py').touch(exist_ok=True)
            parent = parent.parent
        records.append({"source": str(path), "destination": str(target),
                        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "destination_sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    (destination / 'migration_manifest.json').write_text(json.dumps({
        "source_root": str(source),
        "changes": ["AST extraction and namespace rewrite", "Drop training/demo/plot/import effects",
                    "Inference dataset CLASS_TASK constant replaces training import",
                    "Only MVLEM builder retained", "FEA exceptions re-raised for typed Adapter error records",
                    "Objective summarization separated from FEA execution; formula unchanged"],
        "files": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Migrated {len(records)} runtime modules into {destination}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--destination', type=Path, default=Path('src/struct_agent/_vendor'))
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    migrate(args.source, args.destination, refresh=args.refresh)


if __name__ == '__main__':
    main()
