"""Read-only upstream capability inventory; never import/execute upstream code."""
from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path

DEFAULT_SOURCE = Path("E:/Common/Desktop/Research/deepLearning/codes/Png2Dxf")
EVIDENCE = {
    "RC-GNN architecture / dimensions": "src/shearwall_pred/model.py",
    "RC-GNN configuration": "src/shearwall_pred/config.py",
    "Room graph / DXF preprocessing": "src/shearwall_pred/utils.py",
    "RC-GNN native inference": "src/shearwall_pred/inference.py",
    "Prediction to structural topology": "src/data_engine/postprocess/fem_builder.py",
    "CASINO design variables / objective": "src/shearwall_optimization/problems/shearwall_problem.py",
    "CASINO GA": "src/shearwall_optimization/algorithms/genetic.py",
    "CASINO screening / selection": "src/shearwall_optimization/surrogate_candidate.py",
    "CASINO local calibration": "src/shearwall_optimization/local_calibration.py",
    "FuseGNN architecture": "src/surrogate/gnn/model.py",
    "FuseGNN preprocessing": "src/surrogate/gnn/dataset.py",
    "FEA parameter types": "src/shearwall_modeling/parametric/types.py",
    "FEA modeling / analysis": "src/shearwall_modeling/parametric/analysis.py",
    "FEA topology schema": "src/shearwall_modeling/core/domain.py",
}


def inspect_source(root: Path) -> list[dict[str, object]]:
    """Return file hashes and top-level symbols without executing source files."""
    rows = []
    for capability, relative in EVIDENCE.items():
        path = root / relative
        row: dict[str, object] = {"capability": capability, "path": relative, "status": "BLOCKED"}
        if path.is_file():
            raw = path.read_bytes()
            tree = ast.parse(raw.decode("utf-8-sig"))
            row.update(status="KNOWN", sha256=hashlib.sha256(raw).hexdigest(),
                       symbols=[n.name for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))])
        rows.append(row)
    return rows


def report(root: Path) -> str:
    """Generate reproducible evidence inventory; scientific verification is separate."""
    rows = inspect_source(root)
    lines = ["# 上游接口审计", "", f"只读来源：`{root.as_posix()}`。静态存在性不等于运行验证。", "",
             "| 能力 | 状态 | 证据 | SHA256 |", "|---|---|---|---|"]
    lines += [f"| {r['capability']} | {r['status']} | `{r['path']}` | `{r.get('sha256', '')}` |" for r in rows]
    lines += ["", "## 已核实契约", "",
              "- RC-GNN：float32 x[N,25]、edge_attr[E,8]；int64 edge_index[2,E]；condition[1,3]。输出 probability/ratio[N,16]。预处理原生平面坐标为 mm；公共几何为 m。",
              "- 单一条件、eval 模式是确定性预测，不能把重复调用当成不同候选。房间边顺序/掩码必须保留上游编码。",
              "- CASINO：默认 tw_bot/tw_mid/tw_top、hb_main/bb_main/hb_sec/bb_sec（mm），conc_bot（等级）。优化后的配筋为 FEA 设计输出，非直接决策变量。",
              "- FuseGNN 依赖布局 room_v2 图缓存、layout_features 和权重中的 preprocess/model_cfg。新布局必须重新构建这些输入，不能复用另一布局缓存或局部校准器。",
              "- FEA：FEMInput 含墙、主次梁和板。OpenSees 模型/校核/配筋链可复用。原结果含 converged/feasible/design_passed、指标及材料 kg。",
              "", "## 差异与最小变更", "",
              "- 用户提供的 axis_engine 是 CAD/规则布置；RC-GNN 位于本次审计的 shearwall_pred。迁移模型推理依赖，不搬 CAD 插件或训练框架。",
              "- 上游 parametric/analysis.py 固定层高 2.9m、板厚 0.12m、各区混凝土均为 conc_bot；Adapter 拒绝不匹配输入，不改变既有科学口径。",
              "- 上游会自动放大几何；公共 m 几何禁止 auto_scale，否则建筑尺寸改变。",
              "- 上游异常仅 error=str(exc) 且优化器转为不可行；迁移版须保留异常类型/traceback，并把求解失败与结构不通过分开。",
              "", "## 资产存在性", ""]
    assets = {
        "RC five folds": list((root / "outputs/result/shearwall_pred/0126_cond_kfold").glob("fold_*/best_model.pth")),
        "Feasibility weights": list((root / "data/parametric/ckpt/baseline_gnn_room_hybrid_h256_screen995_v1").glob("*.pt")),
        "Steel weights": list((root / "data/parametric/ckpt/steel_gnn_room_lr5e4_b512").glob("*.pt")),
        "Known layout": list((root / "data/dxf/cad_json_data/fem_raw").glob("L17_101.json")),
    }
    for name, paths in assets.items():
        lines.append(f"- {name}: {'KNOWN' if paths else 'BLOCKED'} ({len(paths)} files)")
    lines += ["", "## 待确认与验收边界", "",
              "- [TODO: 待确认] RC-GNN 五折模型及 CASINO 默认工件是否为论文最终指定版本；本次只按现有默认入口复用并记录哈希。",
              "- [TODO: 待确认] 正式算例、规范版本/荷载及真实已验证回归基准。冒烟调用不能替代工程验收。",
              "- DWG 原生读取、任意图层自动语义识别及 Agent 决策不属于本轮最小代码迁移。",
              "- UNKNOWN：模型跨布局泛化有效性；需要实验验证，不由迁移推断。", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=Path("outputs/reports/upstream_audit.md"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report(args.source), encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
