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
| ETABS 18.1 | 独立实例弹性静力/模态及两端单墙网格对照已实测；重力/谱/组合/设计配筋尚未对照 |
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

## 本次任务：同边界单片墙解析与竖向网格对照

起点399d8f3，工作区干净。上一轮38个运行已归档，入口仍按 `output_management.md`，未重复迁移或改写旧证据。
本轮仅完成Phase 4的单墙最小切片，未扩展L/T形墙、墙梁或开展正式优化。

- 新增 `adapters/etabs/wall_{input,etabs,opensees,study}.py`，扩展类型化请求、固定worker及CLI。
  无新依赖；两端共用几何/材料/荷载/边界定义，保存原生模型、逐节点位移、六分量平衡、源码和SHA256。
- 来源为当前布局 `shearwalls_3`（2.3m），12×2.9m；全高简化为底区200mm墙厚、E=30GPa、nu=0.2。
  无自重/质量/梁/显式楼板，单墙XZ平面化，两种真实楼层约束、每层1/2/4/8片。
  这些是显式诊断简化，不代替住宅完整分区或工程条件确认。
- ETABS 10个工况、OpenSees 10个配对及2个纤维控制全部通过平衡与有限响应检查；
  MVLEM全部与独立离散应变能解一致。实际结果和解析假设见 `x_displacement_checks.md`。
- 1→8片时ETABS位移22.917675→22.279994mm，OpenSees23.712495→23.241969mm，分别−2.7825%/−1.9843%。
  单墙未复现整栋显著变软；本平面单墙有/无楼层刚性楼板几乎相同，不能外推L/T形墙。
- 零泊松控制中两软件差从−4.1390%变为−0.3788%；提示泊松/面内离散约束值得排查，
  尚不能确认水平锁定机制或将任一软件/细网格视为真值。整栋仍未验证、网格仍未证明收敛。
- 初次ETABS运行因默认D1重名返回API码1；修正为独立名称后在新目录完整复跑。
  `_01`失败与部分结果、`_02`完整结果均保留；初步单次native probe不参与配对结论。
  `configs/single_wall_evidence.json`记录工件哈希及重试链，不能作为GA标签或生产回归真值。
- 工件：`outputs/current/single_wall_12_02/`；报告 `outputs/reports/single_wall_12_02/report.md`。
  `docs/output_management.md`及ETABS说明同步；生产建模器、物理指纹、RC-GNN/CASINO权重不变。

验证命令：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_single_wall.py tests/unit/test_etabs.py tests/integration/test_single_wall_mechanics.py tests/integration/test_substructure_convergence.py --run-real
.venv/Scripts/python.exe -m struct_agent.etabs_cli single-wall --layout outputs/current/residential_001/layout.json --spec configs/etabs_12_story_spec.json --design outputs/current/design_12_story/design.json --wall-member shearwalls_3 --timeout 600 --run outputs/current/single_wall_12_02 --comparison outputs/reports/single_wall_12_02
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest -q --run-real
git diff --check
```

结果：目标28 passed（0.33s）；默认134 passed、28 skipped、1 warning（10.54s）；
完整真实162 passed、0 skipped、8 warnings（31.00s）。提示均为既有PyG/ezdxf弃用提示。
ETABS正式复跑176.47s，状态SUCCESS仅指工况及响应检查，不是跨软件验收。
证据复验：11个索引哈希、437个原始工件哈希及139个执行源码/工作区源码哈希全部一致；
暂存内容仅含源码、测试、文档与证据索引，`git diff --cached --check`通过。
首次pytest因两个新测试文件同名产生收集错误，已将集成文件改为test_single_wall_mechanics.py后重跑通过。
本轮没有学校API、GA、模型训练或YJK重试。

## 下一最小任务

先固定本单墙物理条件增加ETABS水平离散/泊松伸缩控制，再扩展共边L/T形墙→墙梁连接，
分开检查真实楼层刚性楼板、共节点和高度细分，定位整栋粗网格过硬及两端差异。
之后确定生产单元/网格策略，补重力/地震谱/组合和规范配筋独立复核。
分析基础与几何受理问题解决后，才进入正式优化、代理兼容性验证及等预算策略比较。
人工审批界面、磁盘恢复、DWG和工程成果输出仍属于后续阶段。
