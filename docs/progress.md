# 当前进度

更新：2026-10-29。当前处于Phase 4：已有Agent决策与真实调用闭环，先解决结构分析可靠性，再推进有效优化实验。
本文件只保留现状和最近任务。早期逐轮日志见 `git show ef2c915:docs/progress.md`；代码及文档历史由Git保留。
默认案例和工程条件是不同的确认事项：建筑固定为residential_001；现有条件仅获准冒烟，12层用于当前软件对照。

## 已实现与适用边界

| 模块 | 现状 |
|---|---|
| 审计/迁移与Schema | 最小RC-GNN、CASINO、MVLEM代码已独立迁入；单位、公共Schema、来源/权重哈希和不可变运行目录已实现 |
| 布置生成 | 预处理DXF/房间图→RC-GNN→墙/主次梁/楼板拓扑；原生DWG及任意图层识别尚未实现 |
| 参数搜索 | GA共用单次/分段引擎，按可行性→违反量→材料成本排序；给定初值与反馈邻域已接入 |
| CASINO | 会话、局部校准与筛选接口已接入；旧权重未经修正后标签兼容性验证，真实优化默认禁用代理 |
| Agent | 固定/规则/学校LLM、预算、候选切换、审批和决策回放；真实LLM与跨布局调用仅作冒烟 |
| OpenSees | 建模、反应谱/组合与本地简化校核可运行；修复了已发现的物理/材料计算错误，工程正确性尚未完整验证 |
| ETABS 18.1 | 独立后台实例建模、保存、弹性静力/模态及提取已实测；重力/谱/组合/设计配筋尚未对照 |
| YJK 2025 | 官方API导入及部分几何导出成功；ReadYdb原生崩溃、隐藏宿主脚本回调未打通，已停止重试 |

关键说明：求解成功、回归测试通过及软件间数值接近，都不能代替网格收敛、规范校核和工程签审。
当前尚未得到通过全部要求的设计，也未证明Agent策略收益。

## 当前基准与未解决问题

- 建筑：`configs/test_case.json`，用户提供archi_comp.dxf本地副本。图纸、7个权重、环境和密钥保留原样。
- 当前布局：`outputs/current/residential_001/`；12层条件 `configs/etabs_12_story_spec.json`；参数 `outputs/current/design_12_story/design.json`。
- 同实现数值回归：`configs/real_fea_reference.json`，按哈希绑定布局、条件及 `opensees_residential_12_diagnostics_02` 分析记录。
- 当前生产物理指纹：`e49011b22005316c54e0bfcc858207ddaeb65a0935ddf3430631badae595ac62`。
- 本地详细诊断仍不可行：墙配筋55项失败、墙剪压3项、梁剪压16项，按构件-楼层计；这些不是ETABS配筋结果。
- 极短物理墙肢尚未消解，当前真实GA在受控前处理门槛处阻断。数值网格加密不能替代物理构件治理。
- RC-GNN `_02` 仍用于上游/会话对照测试；`_01` 与批准过的symmetry_02保留为历史真实决策轨迹的输入，不冒充当前生成规则。

此前ETABS悬臂模型通过含剪切变形解析解验证。12层原粗网格X/Y位移差约9.43%/1.13%，只适用于该粗网格。
后续保持楼层、材料、质量、荷载及物理几何不变，墙高度细分1/2/4片，X向位移实测：

| 模型 | 1片/mm | 2片/mm | 4片/mm |
|---|---:|---:|---:|
| ETABS，近似抑制梁剪切 | 2.374560 | 4.061073 | 5.124680 |
| OpenSees，Euler梁 | 2.447730 | 3.684367 | 4.357638 |

2→4片仍变化26.2%/18.3%，整栋尚未收敛。原网格重建等价、纤维单独加密和小构件解析检查通过，仍未定位整栋原因。
完整负面发现、控制组和两端原始结果均保留，见 `x_displacement_checks.md` 与 `outputs/reports/x_displacement/report.md`。
不得把细网格某次结果指定为真值或直接写入GA/代理标签。

## 本次任务：进一步整理outputs

上一轮已删除48个过期运行并清理文档，清单见 `cleanup_2026-10-29.json`，提交8ea5d8b。
用户要求继续清理outputs，本轮将剩余38个独立运行压缩归档，只直接展开当前输入、回归文件及两份主要报告。

```text
outputs/
├── current/       # residential_001布局/房间图与12层参数
├── reference/     # 当前FEA回归与RC-GNN上游对照文件
├── reports/       # X向/网格诊断和ETABS对照报告
└── archive/       # evidence_20261029.zip，原38个完整运行
```

- 38个原目录整体入ZIP，1246个原文件逐一校验SHA256后删除松散原件；ZIP约77.4 MiB。
- outputs直接展开的文件及ZIP/说明共32个，总占用196924658→86879640字节，即187.80→82.85 MiB，另释放104.95 MiB。
- 当前输入、两个回归视图及两个报告视图为原件逐字节副本，共6个子目录；它们不是新求解记录。
- 所有原模型、日志、运行源码、失败及不收敛结果、批准记录均保存在ZIP中，没有筛除不利结果。
- 归档验证：38棵原目录树哈希、6个当前副本树哈希及61项outputs内输入依赖哈希通过。
- 原manifest中的执行时绝对路径原样保留，旧outputs/<run>/...映射至ZIP内<run>/...；查 `outputs_archive_index.json`，不能当成仍存在的磁盘路径。
- `real_fea_reference.json`只更新路径，数据哈希不变；solver_inventory使用明确的archive/member引用或当前报告路径。
- 两处集成测试改读reference目录；README及相关说明同步新入口。生产代码、物理指纹、权重、原图、环境与密钥未修改。
- 安全删除只针对校验过的叶文件和空目录，未使用递归删除；归档创建和核验成功后才删除原目录。
- 树哈希复验按原Windows Path顺序排序；首次用字符串排序导致验证拒绝，纠正排序后38项全部吻合。未改动归档数据。

验证命令：

```powershell
.venv/Scripts/python.exe -m pytest -q --run-real tests/integration/test_real_adapters.py tests/integration/test_member_diagnostics.py tests/integration/test_symmetry_reference.py tests/integration/test_casino_session.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest -q --run-real
git diff --check
```

结果：目标12 passed、8 warnings（27.23s）；默认129 passed、25 skipped、1 warning（11.51s）；
完整真实154 passed、0 skipped、8 warnings（29.97s）。提示均为既有PyG/ezdxf弃用提示；diff检查通过。
本轮没有新建真实住宅运行、学校API调用或GA；测试在临时目录复算回归。
当前单元/整栋可靠性边界未改变，网格未收敛与短物理墙肢问题仍待解决。

## 下一最小任务

两端一致的单片墙→L/T形墙→墙梁子结构，分开检查有/无刚性楼板、共节点和高度细分的影响，
定位粗网格过硬及细化后差异，确定生产单元/网格策略。之后再补重力/地震谱/组合和规范配筋独立复核。
分析基础与几何受理问题解决后，才进入正式优化、代理兼容性验证及等预算策略比较。
人工审批界面、磁盘恢复、DWG和工程成果输出仍属于后续阶段。
