# 当前进度

更新：2026-10-29。当前处于Phase 4：已有Agent决策与真实调用闭环，先解决结构分析可靠性，再推进有效优化实验。
最新用户规则：跨软件同条件差异小于5%即通过，停止核查校准；相关任务合并批量推进，已进入结构层面比对。
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

## 本批任务：结构超限原因检查

起点31a5160，工作区干净。仅检查原超限项，原通过项不重开；没有修改生产参数或重训模型。

- 扩展 `reference_mesh.py` 的诊断选项，新增 `exceedance_causes.py`，复用真实ETABS工件完成8组成组OpenSees反事实，
  另补1组墙梁壳替换。改变的是积分/单元假设，不改E、墙厚、荷载和源图，不生成生产标签。
- 重要原因已量化：c=0.4的独立离散积分对首层偏差+19.31%、屋顶仅+2.35%；
  T形墙中点诊断使首层X/Y差9.42%/22.63%→0.36%/3.85%，屋顶5.64%/5.81%→3.60%/3.21%。
  原86项超限中76项在探针里进入5%，剩余10项为耦合量；不能据此直接修改生产c（官方仍推荐0.4）。
- 整栋粗网格首层X/Y差21.35%/22.44%→8.23%/8.04%，说明积分效应解释大部分低层偏差，但不是全部原因。
  细网格中点、面外nu对齐都不能解释原13%–15%的屋顶差；T纤维×4也只改变很小幅度。
- 壳替换在无梁T形墙接近ETABS，在有梁组合首层Y差0.52%、X却110.15%，整栋同样未改善；
  支持将梁端弯矩—墙节点转角耦合作为首要剩余嫌疑，尚未定位到具体钻转刚度/端区项。
  全部不利反事实保留，未以“换壳”宣称修复。近零耦合分母解释极大百分比，但仍保留5%超限判定。
- 新增类型化 `connection_audit.py`，在专用实例只读检查12根梁：形心插入、零显式偏移、无释放、局部轴角0；
  AutoOffset开启，输入读回的0值不能等同已解析端区，后续仍需核实该项。
  无求解/保存，源EDB及第二轮源缓存哈希不变。完整平面审查未见未共节点交叉或正长度重叠。
- 初次补充脚本默认GBK读取JSON失败，求解前已停止，改UTF-8后成功；首次连接审查因缺少副本Y_缓存出现原生提示，
  补复制Y*后在新目录复查成功、stderr为空。首轮日志与处理记录保留，不混作结构求解失败。
- 工件/报告为 `outputs/{current,reports}/exceedance_causes_01/`、`exceedance_wall_beam_shell_01/`，
  只读证据 `outputs/current/connection_audit_{01,02}/`；索引 `configs/exceedance_causes_evidence.json`。
  结论与适用范围见 `docs/exceedance_causes.md`。生产物理指纹仍e49011b22005316c54e0bfcc858207ddaeb65a0935ddf3430631badae595ac62。

验证命令：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_exceedance_causes.py tests/unit/test_connection_audit.py tests/integration/test_structural_subsystem.py tests/integration/test_substructure_convergence.py --run-real
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.exceedance_causes --run outputs/current/exceedance_causes_01 --report outputs/reports/exceedance_causes_01
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.connection_audit --model outputs/current/structural_comparison_01/etabs/wall_beam/model.EDB --run outputs/current/connection_audit_02
.venv/Scripts/python.exe -m pytest -q
git diff --check
```

目标14 passed（0.67s）；默认152 passed、30 skipped、1个既有PyG弃用提示（23.25s）。
真实探针及只读审查完成；未调用学校LLM、GA、训练或YJK。
18个证据索引、142个主探针执行快照及143个只读审查执行/当前源码哈希核验通过；暂存差异检查通过。

## 上一批：5%规则及结构层面批量比对（31a5160）

起点d0e17ed，工作区干净。用户要求加快进度，取消单墙水平离散/泊松补查，采用小于5%即通过并关闭的原则。
AGENTS第6/11条、PLAN及ROADMAP已同步该明确授权，不再逐个小任务交付。

- 新增 `adapters/etabs/{tolerance,structural_batch}.py`、严格批量配置/请求及固定worker分支；
  复用现有两端建模器，在同一ETABS专用实例完成原图抽取的L形墙、T形墙、墙梁组合，均沿用12层条件。
- 整栋1/2/4片已有真实结果经归档SHA256核验后直接重评，无重复求解；每模型完整比较12阶周期、
  72项逐层位移/扭转、48项层间位移角。保留小量、超限项及绝对差异，不挑选有利网格。
- 已有单墙10/10项通过并关闭；3个新子系统的12阶周期全部小于5%，不再检查校准。
  L形墙屋顶X/Y差4.87%/4.52%、墙梁组合4.62%/4.47%，均通过；T形墙5.64%/5.81%超限。
- 整栋原粗网格屋顶X/Y差3.08%/4.26%，通过并关闭；但首层Y位移差22.44%，第10–12阶周期约5.10%–6.03%，
  以及细化网格部分层间响应仍超限。6个模型792项中288项通过、504项超限，结构比对完成但不能标为全部通过。
- 两端三组新子系统均实际求解成功、整体平衡/有限性通过，ETABS合计96.14s；
  无负刚度特征值或warning/error条目。子系统保留父楼板多边形仅供双方一致的规定质量协议，不作实际分担面积确认。
- 源码/配置/测试、README及结构说明、输出管理已更新；证据索引 `configs/structural_comparison_evidence.json`。
  工件 `outputs/current/structural_comparison_01/`，报告 `outputs/reports/structural_comparison_01/`，
  详细结果与范围见 `docs/structural_comparison.md`。生产建模器、物理指纹、布局、权重不变；无GA/训练/YJK重试。

验证命令：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_structural_tolerance.py tests/unit/test_etabs.py tests/integration/test_structural_subsystem.py --run-real
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.structural_batch --run outputs/current/structural_comparison_01 --report outputs/reports/structural_comparison_01
.venv/Scripts/python.exe -m pytest -q
git diff --check
```

目标27 passed（0.52s）；默认全量146 passed、29 skipped、1个既有PyG弃用提示（8.92s）。
商业真实运行状态STRUCTURAL_COMPARISON_COMPLETED，超限逐项保留；“测试通过/完成比对”不替代跨软件全部响应通过。
18个证据索引哈希复验通过，141个执行源码/当前源码哈希一致；暂存差异检查通过，仅提交源码、测试、文档和配置/哈希。

## 上一批：单片墙解析与竖向网格对照（d0e17ed）

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

## 后续批次

保持原质量、加载点和截面，成组隔离梁墙节点的弯矩/转角传递，核查分析线单元实际端区或显式关闭自动端区作对照。
据此定位整栋细网格超限的剩余原因；不直接用中点或换壳反事实替换生产方案。
已通过单墙、子系统周期及主响应不再核查校准；不再进行单墙水平离散/泊松补查。
之后补重力/地震谱/组合和规范配筋独立复核。
分析基础与几何受理问题解决后，才进入正式优化、代理兼容性验证及等预算策略比较。
人工审批界面、磁盘恢复、DWG和工程成果输出仍属于后续阶段。
