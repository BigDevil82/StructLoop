# 上游接口审计

只读来源：`E:/Common/Desktop/Research/deepLearning/codes/Png2Dxf`。静态存在性不等于运行验证。

| 能力 | 状态 | 证据 | SHA256 |
|---|---|---|---|
| RC-GNN architecture / dimensions | KNOWN | `src/shearwall_pred/model.py` | `cc9cc908d3fcba7f7590f7ad0c8f5c18ac2023504500c3e3c303743f7a5b0033` |
| RC-GNN configuration | KNOWN | `src/shearwall_pred/config.py` | `d2bd3ece4ab77ac65802deedcf677d07a3302a71c1a3deb6153d21d58872443e` |
| Room graph / DXF preprocessing | KNOWN | `src/shearwall_pred/utils.py` | `04c4273fd8250bfd4367e3ddc4c1e9d2310223f40bd21ad1c623bc672fcff125` |
| RC-GNN native inference | KNOWN | `src/shearwall_pred/inference.py` | `67f8c08a50ef680d58fbe6e9fa9ded2cb9329cd4010b9d9856f9b9adc9a3f22e` |
| Prediction to structural topology | KNOWN | `src/data_engine/postprocess/fem_builder.py` | `79cfa4b4e2507c29fc0f9a29016d8c1f7045396b4f958ebbb737e4afdad996d2` |
| CASINO design variables / objective | KNOWN | `src/shearwall_optimization/problems/shearwall_problem.py` | `7f356705b7b301424f57480bfeee2bf3fb012d69ede2fa41f8168b720312ee89` |
| CASINO GA | KNOWN | `src/shearwall_optimization/algorithms/genetic.py` | `8aa1a9f8ff84578d8e331afb500ae2d2d6acf5a98110c27673da3abde35bf7eb` |
| CASINO screening / selection | KNOWN | `src/shearwall_optimization/surrogate_candidate.py` | `33c7173d55faceaaf5a0fd288a4b4c0c6f0d8d22f565de9fc959ba5541d179c7` |
| CASINO local calibration | KNOWN | `src/shearwall_optimization/local_calibration.py` | `ad82db6fc1ce9949d81baf07e1d065634fdb8a79271e1c487595294fbf803099` |
| FuseGNN architecture | KNOWN | `src/surrogate/gnn/model.py` | `69b5123ee24daaf2730f92d6a94f5ebc696339b83dd87d7e2c111c3cb31b0899` |
| FuseGNN preprocessing | KNOWN | `src/surrogate/gnn/dataset.py` | `d543e7099a71a8f191f64c4c399ac448eb52a427e4b64feb3d78443e671f8eef` |
| FEA parameter types | KNOWN | `src/shearwall_modeling/parametric/types.py` | `1c231be04240dba4227608214f944f101009d42380ac2354792f482638087b65` |
| FEA modeling / analysis | KNOWN | `src/shearwall_modeling/parametric/analysis.py` | `fe2a9f9e0d94d62d700dbcc82eaa6907b3f7ee5ef76afeae21d2e5c6383e7365` |
| FEA topology schema | KNOWN | `src/shearwall_modeling/core/domain.py` | `5153f9319d6863e2e38b51b6b4b5bc29859aab53a2eda2d525d225b6afffa3cf` |

## 已核实契约

- RC-GNN：float32 x[N,25]、edge_attr[E,8]；int64 edge_index[2,E]；condition[1,3]。输出 probability/ratio[N,16]。预处理原生平面坐标为 mm；公共几何为 m。
- 单一条件、eval 模式是确定性预测，不能把重复调用当成不同候选。房间边顺序/掩码必须保留上游编码。
- CASINO：默认 tw_bot/tw_mid/tw_top、hb_main/bb_main/hb_sec/bb_sec（mm），conc_bot（等级）。优化后的配筋为 FEA 设计输出，非直接决策变量。
- FuseGNN 依赖布局 room_v2 图缓存、layout_features 和权重中的 preprocess/model_cfg。新布局必须重新构建这些输入，不能复用另一布局缓存或局部校准器。
- FEA：FEMInput 含墙、主次梁和板。OpenSees 模型/校核/配筋链可复用。原结果含 converged/feasible/design_passed、指标及材料 kg。

## 差异与最小变更

- 用户提供的 axis_engine 是 CAD/规则布置；RC-GNN 位于本次审计的 shearwall_pred。迁移模型推理依赖，不搬 CAD 插件或训练框架。
- 上游 parametric/analysis.py 固定层高 2.9m、板厚 0.12m、各区混凝土均为 conc_bot；Adapter 拒绝不匹配输入，不改变既有科学口径。
- 上游会自动放大几何；公共 m 几何禁止 auto_scale，否则建筑尺寸改变。
- 上游异常仅 error=str(exc) 且优化器转为不可行；迁移版须保留异常类型/traceback，并把求解失败与结构不通过分开。

## 资产存在性

- RC five folds: KNOWN (5 files)
- Feasibility weights: KNOWN (1 files)
- Steel weights: KNOWN (1 files)
- Known layout: KNOWN (1 files)

## 待确认与验收边界

- [TODO: 待确认] RC-GNN 五折模型及 CASINO 默认工件是否为论文最终指定版本；本次只按现有默认入口复用并记录哈希。
- 默认工程图已由用户指定为 `archi_comp.dxf`，本地命名为 `residential_001/architecture_preprocessed.dxf`。
  旧 README 对此图采用 `category=2`；本项目配置见 `configs/test_case.json`。
- 图纸头单位 m 与坐标/旧处理链 mm 不一致；显式按 mm 解释并保留原文件哈希。
  原图 27.1 × 12.5 m，旧 200 mm 房间坐标对齐后 27.1 × 12.3 m，未改变对齐算法。
- 旧案例 README 使用 `symmetry_mode=union`，当前最小 Adapter 为 `none`；对称化后处理尚未迁入。
- [TODO: 待确认] 此工程的层数、荷载、规范版本及真实已验证 FEA 回归基准。图纸确认不等于工程条件确认。
- DWG 原生读取、任意图层自动语义识别及 Agent 决策不属于本轮最小代码迁移。
- UNKNOWN：模型跨布局泛化有效性；需要实验验证，不由迁移推断。
