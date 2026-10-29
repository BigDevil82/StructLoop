# ETABS复核能力审计（2026-10-29）

> 最新验收规则：用户2026-10-29指定双软件同条件相对差异小于5%即在误差范围内，停止对通过项的核查校准。
> 后文“不以统一5%阈值验收”为历史调查口径，已由本条替代；历史证据不改写。
> 本轮批量覆盖L/T形墙、墙梁组合及12层整栋的周期/逐层位移/层间响应，不再要求逐小任务交付。

> 本文保留静态审计及后续实测记录。原运行已归档至 `outputs/archive/evidence_20261029.zip`；
> `ZIP::<run>/...` 为归档成员引用，恢复及当前报告入口见 `output_management.md`。
> 后台弹性诊断已实测，重力/配筋及整栋网格收敛尚未验证，初期“未启动”仅指当时静态审计。

本次为Phase 4的替代商业参照能力审计，不是建模、授权、求解或配筋结果验收。
未启动/附着ETABS、未操作用户模型；未引入依赖或迁移业务模块。
安装信息、API/文档与上游源码SHA256见 `configs/solver_inventory.json`。

## 能力与本机接口

ETABS提供混凝土框架设计与剪力墙设计/校核。墙设计需要先正确分配Pier/Spandrel标签、
选择规范和设计组合、完成分析，再执行设计，并可输出表格和报告。
设计截面与分析截面最终必须一致。见
[CSI墙设计流程](https://docs.csiamerica.com/help-files/etabs/Getting_Started/Shear_Wall_Design_Procedure.htm)。
中国2010墙设计技术报告列出墙肢与连梁的抗弯、抗剪设计，
但具体可用规范由本机版本、安装和授权确定，尚未实测，不将旧规范名称等同于当前完整规范覆盖。
见[中文技术报告](https://www.cisec.cn/support/files/混凝土剪力墙设计E-TN-SWD-CHINESE2010_cn.pdf)。

注册表确认ETABS 18.1.0，安装目录 `C:/Program Files/Computers and Structures/ETABS 18`。
只读取随软件安装的ETABSv1.dll公开.NET接口元数据（程序集版本1.0.0.0不等于软件产品版本），
没有构造cOAPI或启动应用。确认：

| 接口 | 已核实的公开方法/属性 | 尚未验证 |
|---|---|---|
| cSapModel | DesignConcrete、DesignShearWall、DatabaseTables等入口 | 实际实例调用 |
| cDesignConcrete | StartDesign、SetCode/GetCode、GetResultsAvailable、GetSummaryResultsBeam/Column；Chinese_2010属性 | 授权、指定规范选择、计算与结果含义 |
| cDesignShearWall | GetPierSummaryResults、GetSpandrelSummaryResults、GetRebar、GetRebarPrefsPier/Spandrel | 有效工程上的结果读取 |
| cDatabaseTables | GetAvailableTables、GetAllFieldsInTable、GetTableForDisplayArray/CSV等 | 表名、字段、单位、状态及实际返回 |
| cOAPI | ApplicationStart、Hide/Unhide、Visible、ApplicationExit | 实际专用实例生命周期 |

本机cDesignShearWall只有上述5个公开方法，没有StartDesign；cDesignResults也只有DesignForces属性。
因此不能照搬DesignConcrete.StartDesign来宣称墙设计可全后台触发，也不把新版API声明当18.1能力。
可行的首条验证路线是API建模/分析→工程师在GUI启动墙设计→API读取结果/官方表格。
若日后需要全自动，再单独核实该版本支持的触发途径，不以界面按钮存在推定API可用。

墙肢摘要字段含Story、PierLabel、Station、DCRatio、AsLeft/AsRight、ShearAv、边界区信息及WarnMsg/ErrMsg；
连梁摘要含上下部钢筋、剪切钢筋、对角钢筋、控制组合及警告/错误。
字段名不能替代单位、设计模式与物理含义校验，GetRebar也不能直接解释成全楼钢筋吨位。

## 上游复用边界

已找到用户之前的 `Png2Dxf/pipelines/structural/etabs/create_etabs_model.py`、`etabs_util.py`。
只读审查，不直接执行它们：

- 有创建梁墙板、刚性楼板、面荷载、保存模型和调用Analyze.RunAnalysis的基础逻辑，可最小提取。
- 默认ATTACH_TO_INSTANCE=True，会附着用户活动会话；新Adapter应只管理自己的独立实例。
- 旧脚本固定18层、3m、200mm墙等条件；新工程须从统一Spec/Design转换，不能照搬默认值。
- 源码明确质量源和工况需要人工预设；尚不构成可复现的自动分析链。
- StoryDrifts被当成X/Y两组数组，实际签名是Direction:string[]和Drift:double[]，必须按方向与工况逐行解析。
  [CSI公开签名](https://docs.csiamerica.com/help-files/etabs-api-2016/html/e55e16e2-b7b0-2864-f3dc-b781f4062325.htm)
  与本机18.1元数据一致。不能对Direction做数值比较，不能将缺失输出视为零漂移通过。
- 旧脚本提取模态时仅选择Modal输出，之后没有按注释选择全部工况就读取漂移；
  新适配必须显式选择目标基本工况/组合，检查求解状态与非空结果。
- 部分旧工具仅打印非零API返回值但继续执行；迁入时必须失败即保留错误并阻断，不能静默漏构件。
- 主环境尚无comtypes；本次仅借助现有SDK Python的CLR读取元数据，未把YJKAPI作为ETABS运行依赖。

## 对照顺序

1. 先用解析基准完成本地验证，再启动一个独立ETABS小模型，检查保存、求解状态、质量、反力与周期；
   对接回本例时默认案例仍为residential_001，沿用既有条件只能用于获准的冒烟。
2. 对齐材料E/G/容重、质量源、自重与附加恒载、刚度折减、边界和楼板约束、网格与截面。
   ETABS壳模型与MVLEM不是相同离散体系，不强求未经解释的逐单元相等。
3. 先比基本静力工况、模态和反应谱响应，再按物理墙肢/连梁的同一截面位置比较N/M/V。
   Pier/Spandrel标签需要物理含义，不直接将每片分析网格作为独立设计墙肢。
4. 通过分析对照后，固定设计规范/版本、组合、抗震等级、材料强度、设计覆盖项，比较所需配筋与失败原因。
   必须区分程序调整的设计内力与原始分析内力，以及所需面积、实配与工程量。
5. 保存官方报告、表格、全部错误/警告和源ID映射。只确认已覆盖的校核项；
   不能因为ETABS某摘要无错误就认定本项目全部规范检查通过。

下一最小任务为独立进程/专用实例的ETABS小模型API冒烟，验证实际授权与分析结果读取；
随后用一次界面墙设计确认结果接口和中国规范可用性，再迁入当前住宅的最小建模模块。
当前没有ETABS真实计算结果，不更新CASINO标签或声称交叉验证通过。

## 已执行：小模型与12层住宅弹性对照

用户批准先小模型、再使用residential_001，住宅对照改为12层。新配置
`configs/etabs_12_story_spec.json` 的condition_id独立，原28层配置不变；其他条件仅沿用已获准冒烟条件。
新增 `adapters/etabs/`，只接受类型化的cantilever/residential任务，没有任意脚本/命令入口。
专用COM实例通过固定worker执行，记录API返回值、进程退出/超时、完整错误与所有源ID映射。
每次运行复制源代码到不可覆盖的source目录，保留各文件SHA256，避免长计算期间工作区编辑改变故障栈或运行依据。
新增可选依赖comtypes==1.4.17；psutil==7.2.2已在原环境中。没有增加绘图或商业FEA Python库依赖。

### 悬臂解析解

`outputs/archive/evidence_20261029.zip::etabs_cantilever_04` 已经真实启动ETABS 18.1.0 Build 2117并完成计算。
3m高、0.4m正方形、E=30GPa、nu=0.2、柱顶质量10000kg，水平力10000N，材料自重置零。
理论包含5GA/6剪切变形；同一模型的两个水平振型具有相同周期，保留二者，不去重。

| 指标 | 解析解 | ETABS |
|---|---|---|
| 柱顶位移/mm | 1.424250000 | 1.424250003 |
| 支座剪力/N | -10000 | -10000 |
| 支座弯矩/Nm | -30000 | -30000.000000000007 |
| 首阶周期/s | 0.237122618645 | 0.237122618855 |

只对该确定线性例题使用1e-4相对容差；不是整楼不同离散模型的统一通过阈值。
首次worker请求Path的严格Python校验不接受JSON字符串，已改为嵌套Schema的model_validate_json；
`cantilever_01` 未启动软件。`_02/_03` 静力完成，但模态没有有效质量，被明确判失败。
读回发现质量及质量源本身正确，而NewBlank默认层不位于柱顶、软件默认向楼层集中质量。
显式定义正确柱顶楼层后 `_04` 通过。没有用API返回0掩盖模态失败。
日志保留“请求振型数降至有效质量自由度数”的提示，本例按质量源只有两个水平质量自由度，与两个重复周期一致。

### 12层住宅

使用 `outputs/current/residential_001/layout.json` 的162墙段、32主梁、49次梁，12层、层高2.9m。
墙厚分区及梁截面使用独立design.json；依现有楼层分区规则为3/5/4层，墙厚200/160/160mm，
主梁250×500mm，次梁300×400mm，混凝土C30。本次不是参数优化或工程可行解。
原极短墙/梁保留为诊断对象，完整记录；仍受真实GA前处理门槛约束，不允许以本次完成计算越过该门槛。

两边都采用弹性材料、固定底部和每层刚性楼板；无显式楼板弯曲刚度。
按现有质量协议指定相同逐层平动质量和转动惯量，ETABS元素密度置零以免重复计质量。
质量量值由新模块独立计算并与OpenSees建模器实际值核对：墙梁几何自重加6kPa/9.81楼面质量，
既有5kPa恒载已含板重，不再另加板自重。本次并不证明该简化质量协议的工程适用性：
转动惯量仍按平面端点分布估计，物理质量源和面荷载传递需要另行独立验证。
以楼层平均端点位置为共同参考，在屋顶分别施加X/Y方向1MN诊断力；这不是设计地震/风荷载。

ETABS墙使用ShellThin，面外弯曲修正为0.63³以对齐MVLEM默认面外厚度参数；
梁采用软件矩形截面，OpenSees仍为Euler梁，两种单元的剪切变形处理不同。
两者的壳面内泊松效应、网格/连接和墙肢离散也未先验等价，差异必须逐项检查。

最终 `outputs/archive/evidence_20261029.zip::etabs_residential_12_05` 用时91.42s：

- 1944墙片、972梁、2617节点；全部输入节点逐项读回，最大坐标差7.11e-15m。
- 上述2617为对象节点；原生求解日志为2629分析节点（含12个内部楼板控制节点）、1944壳单元、972杆单元。
- 逐层质量读回一致；目标两个静力工况和模态工况状态均为4（已完成）。
- X/Y各自六项整体力和力矩平衡及响应有限性通过，原生日志无负刚度特征值、没有warning/error条目。
- 完整提取12阶振型，并以官方模态表确认阶次；不能使用默认仅第一阶的ModeShape输出。
- 保留EDB、原生.LOG、.OUT、模型映射、API调用日志、请求与源代码快照。
  本机第二次File.Save会删除此前原生求解工件，因此保存模型在求解前进行，查询后不重复Save。

`opensees_residential_12_02` 用相同输入完成独立的MVLEM模态与两方向静力诊断；
全局平衡和独立计算的质量/转动惯量核对通过。
按质量加权MAC及一对一匹配比较12阶，而不是只按周期序号强配；最小MAC为0.9903865。
完整差异见 `outputs/reports/etabs_comparison/comparison.json` 与report.md：

| 指标 | ETABS | OpenSees | OpenSees相对ETABS差异 |
|---|---|---|---|
| 第1阶周期/s | 0.408360 | 0.392128 | -3.97% |
| 第2阶周期/s | 0.367374 | 0.365395 | -0.54% |
| 第3阶周期/s | 0.297920 | 0.289176 | -2.93% |
| X加载屋顶X位移/mm | 2.702472 | 2.447730 | -9.43% |
| Y加载屋顶Y位移/mm | 2.714278 | 2.683477 | -1.13% |

耦合方向位移与扭转差异同样保留；例如X加载屋顶Y位移两边分别约0.02353和0.04920mm，
其相对差异较大，不能只展示主方向或大响应而删除该项。
结果状态为DIFFERENCES_REPORTED_NOT_ACCEPTANCE，不以统一5%阈值宣布整楼通过。

### 核对中修正的本地物理错误

1. 矩形梁把Iy+Iz当成Saint-Venant扭转常数，现改为矩形截面级数解；
   单位正方形J约0.140577014955，而非1/6。验证尺寸四次方缩放与宽高互换不变量。
   公式依据[矩形杆扭转论文](https://link.springer.com/article/10.1186/s10033-018-0214-9)。
2. MVLEM_3D剪切材料接受的是位移并输出力，旧代码直接传G（Pa）作为弹簧刚度。
   改为逐分析墙片 K=5GA/(6h)（N/m），截面修正系数取当前弹性矩形梁的5/6假定；
   不是普遍适用的非线性墙剪切本构或规范强制系数。
   依据[官方源代码](https://github.com/OpenSees/OpenSees/blob/master/SRC/element/mvlem/MVLEM_3D.cpp)
   的setTrialStrain、getInitialTangent和getStress用法，并以本机实际单元的纯剪切加载验证单位和几何缩放。
3. 极短分析墙片可能仅有1条宏纤维，形心纤维无法表达面内弯曲惯性。
   每片截面至少8纤维；这修复离散表达，并不使极短物理墙肢变成工程合理构件。
   8纤维不等于已达到截面离散收敛，仍需后续纤维数/竖向网格收敛检查。

对应原生力学验证在 `tests/integration/test_mvlem_panel_mechanics.py`，
短墙分析截面覆盖检查在test_wall_pier_mechanics.py。
官方.cpp只读快照与SHA256位于 `outputs/archive/evidence_20261029.zip::etabs_mechanics_audit_01`，实测而非仅据master源码推定安装版本行为。
本轮新指纹 `e49011b22005316c54e0bfcc858207ddaeb65a0935ddf3430631badae595ac62`，
旧结果/代理标签不能作为当前筛选依据，没有重训或修改权重。

### 当前未完成与复现

恒活载传递、反应谱/组合、规范调整与配筋尚未在ETABS中验证。
目前EDB只有专门的水平诊断工况，材料只设置弹性参数；不可直接拿它点击配筋后声称工程设计通过。
需要先补齐混凝土/钢筋设计材料、重力工况、地震谱/组合和设计设置，再做墙设计及结果解释。
12层当前本地全管线诊断 `opensees_residential_12_diagnostics_02` 也仍不可行：墙配筋失败55项，
墙剪压失败3项、梁剪压失败16项（均按构件-楼层计数）。
此为本地简化检查结果，并非ETABS配筋结果，更不是成熟软件等价性验收。

当前真实数值回归基准改为用户批准的12层，并用 `configs/real_fea_reference.json` 绑定输入/结果哈希；
其正常入口与详细入口一致，只证明同实现的复算一致性，独立参照证据来自上述ETABS/解析解对照。
旧28层历史结果保留原样，不为新指纹补写标签。RC-GNN/CASINO权重不变。

复跑需新的运行目录：

```powershell
.venv/Scripts/python.exe -m struct_agent.etabs_cli cantilever --run outputs/current/new_cantilever
.venv/Scripts/python.exe -m struct_agent.etabs_cli residential --layout outputs/current/residential_001/layout.json --spec configs/etabs_12_story_spec.json --design outputs/current/design_12_story/design.json --run outputs/current/new_etabs_12 --opensees-reference outputs/current/new_opensees_12 --comparison outputs/current/new_comparison_12
```

下一最小任务：用可控墙/梁子结构和网格收敛检查定位X向约9.43%的位移差异，
特别核对墙片离散、梁剪切变形、连接及面外修正，再补恒活载和反应谱；设计结果读取放在分析输入对齐之后。

### 后续检查：粗模型接近不能作为收敛证据

详见 [X向位移与网格检查](x_displacement_checks.md)。实际1/2/4片高度细分显示，
ETABS与OpenSees均有显著整栋网格敏感性，尚未收敛；原先约9.43%/1.13%的差异只适用于原粗网格。
仅改变梁剪切变形也显著影响响应，但不足以完整解释差异。
本轮已通过解析梁/墙、原网格重建等价及交点共节点检查；未改正式建模器或将新结果作为GA标签。
后续已完成两端同边界单片墙的10个配对工况与OpenSees纤维控制，报告在
`outputs/reports/single_wall_12_02/`，输入/失败重试/结果哈希见 `configs/single_wall_evidence.json`。
该简化单墙随竖向细化略变硬，未复现整栋显著变软；零泊松控制显著缩小两端差异，
但未验证壳水平离散或L/T形墙连接机制。具体数值、解析假设与边界见上述子结构文档。
最新按用户5%规则关闭单墙，取消水平离散补查；L/T形墙、墙梁组合及整栋已完成
[批量结构对照](structural_comparison.md)。通过项不再核查校准，后续处理整栋逐层/层间响应及T形墙等超限项目。
