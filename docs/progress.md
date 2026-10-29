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
- 当前布局：`outputs/residential_001_rcgnn_03/`；12层条件 `configs/etabs_12_story_spec.json`；参数 `outputs/residential_12_inputs_01/design.json`。
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
完整负面发现、控制组和两端原始结果均保留，见 `x_displacement_checks.md` 与 `outputs/x_displacement_diagnosis_01/report.md`。
不得把细网格某次结果指定为真值或直接写入GA/代理标签。

## 本次任务：项目清理

已先读PLAN、RESEARCH_ROADMAP、README及upstream_contracts，只整理工件/文档，不修改计算源代码或训练模型。

- 输出86→38个目录，2626→1246个文件；368156306→196924658字节（351.10→187.80 MiB），删除163.30 MiB。
- 删除48个已替代的诊断、重复求解、开发重试和可重建mock运行；保留当前不收敛试验、代表性商业后端失败、真实决策历史及全部输入依赖。
- 保留38个运行目录的树SHA256均未变；61项outputs内manifest输入依赖的文件哈希通过；真实回归输入哈希及solver_inventory输出引用通过。
- 删除未被使用的 `configs/base.yaml` 和过期 `docs/member_diagnostics.md`；纠正README、物理修正/建模语义/优化/Phase 4说明中的旧状态与命令。
- 将78KB逐轮进度日志压缩为本文件；历史文档可从Git查看。删除的outputs从未入Git，目录树摘要仅能识别内容、不能恢复文件。
- 新增 `output_management.md` 与 `cleanup_2026-10-29.json`，记录保留理由、删除目录大小/数量和树哈希。
- 批量递归删除被自动安全检查拦截，未执行；改为校验后的逐文件、再空目录删除。实际保留运行未做内部删改。
- 仍被公共入口、测试及迁移来源审计使用的代码保留；没有为清理而删功能或改变物理指纹。
- 额外删除src/tests/scripts下字节码及根目录pytest缓存，共33个缓存目录、175个文件、1430155字节；环境及保留运行不清缓存。

验证命令：

```powershell
.venv/Scripts/python.exe -m pytest -q --run-real tests/integration/test_real_adapters.py tests/integration/test_member_diagnostics.py tests/integration/test_symmetry_reference.py tests/integration/test_casino_session.py tests/unit/test_upstream_contracts.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest -q --run-real
git diff --check
```

结果：目标14 passed、8 warnings（25.97s）；默认129 passed、25 skipped、1 warning（9.89s）；
完整真实154 passed、0 skipped、8 warnings（27.53s）。提示为现有PyG/ezdxf弃用提示；默认跳过项全部开启后通过。
diff检查通过，无新增测试/生产代码变更；只复用现有验证覆盖本次清理。
本次不调用学校API、不运行GA、不重新生成住宅工件；测试在临时目录复算当前回归。

## 下一最小任务

两端一致的单片墙→L/T形墙→墙梁子结构，分开检查有/无刚性楼板、共节点和高度细分的影响，
定位粗网格过硬及细化后差异，确定生产单元/网格策略。之后再补重力/地震谱/组合和规范配筋独立复核。
分析基础与几何受理问题解决后，才进入正式优化、代理兼容性验证及等预算策略比较。
人工审批界面、磁盘恢复、DWG和工程成果输出仍属于后续阶段。
