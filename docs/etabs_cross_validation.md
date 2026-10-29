# ETABS复核能力审计（2026-10-29）

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
