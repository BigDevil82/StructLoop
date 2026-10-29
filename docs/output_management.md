# 本地输出管理

默认建筑始终是 `configs/test_case.json` 指定的residential_001；
图纸、权重、`.env`、`.venv`及用户提供的API指南不属于结果清理范围。

## 常用入口

| 用途 | 保留位置 |
|---|---|
| 当前布局/房间图/几何审查 | `outputs/residential_001_rcgnn_03/` |
| 当前12层条件与参数 | `configs/etabs_12_story_spec.json`、`outputs/residential_12_inputs_01/design.json` |
| 实现一致性回归与构件覆盖 | `configs/real_fea_reference.json`，绑定layout与详细分析文件哈希 |
| X向/网格诊断汇总 | `outputs/x_displacement_diagnosis_01/report.md` |
| ETABS粗模型与OpenSees独立比较 | `outputs/etabs_comparison_12_02/report.md` |
| 单梁/单墙解析验证 | `outputs/etabs_cantilever_04/`、`outputs/x_displacement_substructures_02/` |
| 真实LLM与跨布局调用历史 | `outputs/phase4_real_llm_01/`、`outputs/phase4_real_switch_01/` |
| 批准过的备选布局 | `outputs/residential_001_symmetry_02/`，仅用于原跨布局冒烟 |
| 软件能力及失败证据 | `configs/solver_inventory.json` 及其引用的YJK目录 |

RC-GNN `_02` 仍用于对照上游行为的集成测试，`_01` 是历史LLM/跨布局证据的输入；
它们不能混作当前生成规则。旧28层优化/Agent轨迹仅保留调用及算法历史，不作为当前物理标签。
当前单元及整体分析尚未获得工程验收，尤其整栋网格未收敛，不因清理改变结论。

## 保留与删除规则

- 保留当前回归文件、关键对照的原始模型/求解日志/结果、用户批准记录和来源审计；
  检查manifest中本项目outputs内的输入依赖，依赖目录一并保留。
- 完整保留当前网格敏感性试验及对照组，包括不收敛结果；YJK原生失败保留代表性证据。
- 可删除已替代的开发重试、旧指纹详细诊断、可重建的mock演示和重复验证目录。
  删除依据是用途及依赖关系，不是结果是否成功或是否有利。
- 清理以整个运行目录为单位；不在保留运行内挑删求解结果、修改manifest或回写旧数值。
- 新运行使用新目录。重要证据在研究结论冻结前不得自动按日期/编号删除。
  该说明不设置自动清理任务。

2026-10-29清理清单见 `cleanup_2026-10-29.json`：记录保留理由、删除目录字节数/文件数、
树SHA256及主要审计文件哈希。删除的原始工件不在Git中，哈希不能恢复文件；
历史文档和代码可通过 `git show ef2c915:<path>` 查看。
进度文档只保留当前状态和最近任务，较早的逐轮开发日志由Git保存。
