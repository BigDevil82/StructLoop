# 构件级诊断与正式实验前待确认事项

本轮只添加可选诊断输出，不修改 RC-GNN、CASINO、FEA 上游算法、限值或既有工件。
条件仍为用户获准的 28 层等冒烟设置，不能代替实际工程条件。

## 可复算证据

```powershell
.venv/Scripts/python.exe -m struct_agent.diagnostics_cli --layout outputs/residential_001_rcgnn_01/layout.json --spec configs/reference_spec.json --record outputs/phase4_real_switch_01/analyses/eval_00001.json --run outputs/member_diagnostics_baseline_02
.venv/Scripts/python.exe -m struct_agent.diagnostics_cli --layout outputs/residential_001_symmetry_02/layout.json --spec configs/reference_spec.json --record outputs/phase4_real_switch_01/analyses/eval_00003.json --run outputs/member_diagnostics_symmetry_02
```

目录已存在，复跑必须另取名称。每次只有 1 次真实求解，均通过 `AnalysisService` 记账。
诊断模式重用原构建、分析、校核和配筋组件，保存全部构件-楼层结果及实际模型配置。
两次成功复算的 35 个汇总字段均通过既有回归容差 `rtol=1e-5, atol=1e-8`，包括材料量及配筋失败计数。
这验证数值复现，不表示上游计算口径已获得工程确认。

主要工件：各目录 `report.md`、`summary.json`、`comparison.json`，以及
`diagnostics/eval_00001/{members,checks,model_config,native_summary}.json`。
`members.json` 中坐标/尺寸为 m，内力 N，强度 Pa，指标和利用率无量纲；原组合名与有符号剪力逐项保存。

## 发现一：1 mm 墙段控制原布局剪压指标

| 项目 | 原布局 | union 对称化布局 |
|---|---:|---:|
| 平面墙段 | 142 | 135 |
| 小于原请求最小长度 0.1 m 的墙段 | 15（均约 1 mm） | 0 |
| 墙肢剪压失败（构件-楼层） | 355 | 0 |
| 墙配筋未执行（构件-楼层） | 1092 | 644 |
| 梁剪压失败（构件-楼层） | 60 | 91 |
| 梁配筋截面不足（构件-楼层） | 5 | 19 |

原布局控制构件 `shearwalls_138`，首层，长约 0.001 m、厚 0.2 m：
`V=14290.817341 N`，`βc·fc·b·h0=2859.99999993 N`，指标 `4.99678928`，限值 `0.15`，利用率 `33.31193`。
355 项墙剪压失败由 341 项 1 mm 墙和 14 项 0.25 m 墙组成，不可全部归因于 1 mm 墙。
这些失败均属于上游未执行墙配筋设计的范围。

来源差异：`design/pipeline.py` 仅对墙长 `>0.5 m` 执行配筋设计；
`analysis/checkers.py` 的 ULS 墙剪压检查覆盖全部墙段。
因此 `design_failed_wall_count=0` 不等于所有墙段均完成并通过配筋设计。
`adapters/rcgnn.py` 请求 `min_length=100 mm`，但上游 `fem_builder.py` 仅存储此参数，
构建过程的合并/分段条件中存在 1 mm 阈值，最终拓扑校验没有剔除这些极短段。
诊断没有据此删除构件或跳过校核；改变这些墙段会同时改变模型刚度、连接和受力。

对称化布局控制梁为 `beams_49`，3 层，长 0.35 m、截面 0.3×0.4 m，
剪力约 604.838 kN，原 ULS 指标 0.352470，限值 0.15，利用率约 2.350。
其配筋失败消息是 `beam_shear_section_insufficient`。这项问题不能靠忽略短墙解决。
上游 ULS 对梁的分母使用截面总高；梁配筋设计另扣保护层，两种口径均原样保留。

## 发现二：有符号输入与包络处理契约不一致

`analysis/member_forces.py` 返回有符号静力内力；`ULSCombinationAnalyzer` 的注释却假定无符号效应。
`_combine_one_force()` 使用 `abs(factor)`，所以当前 +/− 同类组合得到相同效应。
`_build_envelope()` 取有符号最大值并截为非负；所有剪力低于 −1 N 时，可能返回剪力 0、空控制组合。
配筋提取器 `design/extractor.py` 又使用 `max(abs(v))`，与 ULS 剪压检查不一致。

实际例子：对称化布局 `shearwalls_92` 第 28 层，现有组合剪力绝对值最大约 113.557 kN，
原 ULS 包络为 0、控制组合为空；`beams_56` 第 27 层类似，绝对值最大约 85.359 kN，原包络为 0。
诊断只列出差异，没有将绝对值包络替换进既有校核或重新标记可行性。

| 诊断计数（构件-楼层） | 原墙 | 原梁 | 对称化墙 | 对称化梁 |
|---|---:|---:|---:|---:|
| 原包络控制组合为空 | 40 | 30 | 107 | 15 |
| 组合绝对剪力最大值大于原选取值 | 498 | 111 | 449 | 93 |

这些数值是当前组合输出的诊断比较，不能直接充当新的设计剪力或新的可行率。

## 最小修正边界（尚未执行）

- `[TODO: 待确认]` 先明确静力效应和反应谱效应的符号契约、正负组合与包络定义，再修正 Adapter。
  仅将剪力取绝对值，不能同时解决组合因子符号问题。
- `[TODO: 待确认]` 极短墙段在拓扑生成端进行邻接/共线关系追踪，形成新的候选版本供工程师检查；
  不直接删除原布局构件，不将短墙从校核集合静默排除。
- 计算口径变化需显式版本及新的分析缓存绑定；应保留旧结果和上游对照。
  现有 CASINO 权重对应旧标签/指标，新口径下的代理有效性需另行验证。
- 确认并复验上述问题后，再冻结代码、候选池、预算与停止条件，执行同版本 pilot。

重大计算/评价口径变化按项目 `AGENTS.md` 第 7 条需要人工确认。本轮只完成证据采集与复现。
