# YJK API接入与分层交叉验证

2026-10-29，Phase 4 接口核查与验证计划。用户已确认加密狗正常、盈建科可以使用；
这与本项目的自动求解链是否跑通分别记录，不再把授权状态简单写成未知。

## 已核实的接口与实测范围

原厂[开发者平台](https://open.yjk.cn/)提供结构自动化建模与优化方向的二次开发。
本机SDK声明位于 `D:/Softwares/YJKS_8_0_0/python310/site-packages/YJKAPI/`，对应安装版本V8.0.0。
下面的“存在”表示本机公开接口声明可查，不等于真实计算返回已通过核验。

| 环节 | 本机接口依据 | 当前状态 |
|---|---|---|
| 建模 | `DataFunc` 的标准层、楼层、节点、网格、梁墙截面及布置、板创建接口 | 节点/网格/楼层持久化已实测；完整梁墙板模型待实现 |
| YDB写入 | `DbModel_Assign`、`Hi_AddToAndReadYjk.SetDbmodel/CreateYDB` | 先提交内存模型再创建文件，已验证几何数据实际落盘 |
| 模型读回 | `Hi_AddToAndReadYjk.ReadYdb` | 驱动更新后独立进程仍以0xC0000005退出；目前用SQLite只读方式核对自建文件 |
| 前处理和求解控制 | `YJKSControl`、`YJKSUIPy.QRunCommandEx`、`YJKSCommandPy.RunCommand` | 旧脚本提供了命令序列；独立宿主初始化、完成判据尚未验证 |
| 分析与配筋结果 | `YJKSDsnDataPy` 的质量、周期、位移、墙柱标准内力与配筋等查询 | 声明存在；尚无本轮商业求解结果，不能宣称读取已成功 |

明确查到的结果接口示例：`dsnGetTolMass`、`dsnGetFirstPeriod`、`dsnGetNodeDis`、
`dsnGetWallColumnStdForce`、`dsnGetWallColumnAs`、`dsnGetBeamAsWithCal`。
有些返回类型为Any，必须核实数组/对象字段、单位、组合号和失败标记后才能归一化。
不能将空返回当零，不能从接口名称推定它给出的是标准内力、调整后内力还是实配。

主工程保留Python 3.12，外部SDK使用软件随附的Python 3.10独立进程；不把不同版本的CLR/Python依赖塞入主环境。
正式Adapter只接受结构化请求，固定可执行文件和方法白名单，串行管理商业实例，设置超时并采集stdout/stderr/退出码。
原生库可能直接退出而不给Python异常，因此父进程必须负责错误分类与记录；LLM不能直接执行任意RunCmd或shell。

## 本轮探针记录

使用当前 `residential_001_rcgnn_03` 的真实平面节点和243条构件中心线，建立一个标准层的几何骨架。
为避免大地坐标的单精度损失，先记录平面原点，再将m显式转换为局部整数mm。
这是接口测试，不是将工程简化为一层后验证结构安全，也不是完整YJK工程模型。

- `outputs/yjk_api_roundtrip_01/`：内存中有201节点/243网格，但直接CreateYDB得到的是空库。
  API返回true不能证明构件写入；首次读回两种路径方式原生退出1，无Python traceback。
- `outputs/yjk_api_roundtrip_02/`：检查发现提交前PreModel为空，`DbModel_Assign`后DbModel有数据。
  误将PreModel交给ReflectAndCreateYDB，返回false，没有生成模型；保留失败工件。
- `outputs/yjk_api_roundtrip_03/`：提交后使用DbModel和CreateYDB，实际写入201节点、243网格、1标准层、1楼层。
  `database_verification.json` 用只读数据库核对全部节点坐标、网格连接、2900 mm层高、输入/文件哈希及完整性。
  梁、墙、板对象均为0；还没有赋真实构件截面、组装28层、补齐规范参数或启动求解。
  对有效文件及项目目录再次尝试ReadYdb，均原生退出1，记录在 `readback_failures.json`。

本轮商业求解=0，学校LLM API调用=0。没有操作现有用户工程或自动关闭盈建科实例。
探针脚本与日志是不可变运行工件，不是正式可复用Adapter；复验需创建新目录，不重跑覆盖既有目录。

## 交叉验证顺序

### 1. 对齐实际模型与计算假定

由统一 `LayoutCandidate + DesignCandidate + ProjectSpec` 分别生成两套模型，并保留源ID到软件ID的映射。
先核对输入几何，再读取YJK前处理后的实际分析几何/设计截面；其自动归并、刚域或壳元转换必须进入差异表。
不能把OpenSees原始分段模型直接与YJK已归并模型的差异都归结为程序误差。

需要逐项核对：单位与局部坐标、楼层与约束、梁墙板截面、材料E/G/容重、质量源与自重、
恒活载与传荷、刚性楼板、刚域、梁墙刚度折减、P-Delta、地震谱/阻尼/振型数/参与质量、
偶然偏心、风荷载、地震剪力调整、作用组合及抗震等级。
采用实际导出值核对，不能只确认发送的配置相同。工程条件仍沿用已获准的冒烟条件，不悄悄套YJK默认值。

### 2. 验证基础力学与传力

先用明确标记的软件验证子模型或从本例提取的构件，检查解析解、反力平衡、轴力/剪力/弯矩与坐标符号。
整楼先比恒载和明确的静力水平荷载，再比反应谱。逐层检查总荷载、总质量、反力、层剪力与位移，
定位漏荷载、单位或约束错误后才进入下一层比较。

### 3. 比较整楼动力与构件响应

比较周期、振型形状与方向、参与质量、层位移和层间位移角、层剪力及扭转指标。
振型可能交换顺序，不能仅按“第1阶对第1阶”机械比较。
墙比较同一物理墙肢/组合截面及形心处的合力；梁核对真正跨度、支座面/刚域边的取力位置。
分开比较基本工况、组合前后与规范调整前后；不把不同来源的包络混作同一数值。

### 4. 最后比较设计与材料

先比较相同截面、同一组N/M/V下的所需钢筋、构造要求、控制组合与超限原因，再比较实配和全楼工程量。
墙柱、组合墙、连梁和边缘构件分别检查。计算所需面积、施工图实配与含锚固搭接的吨位不能混用。
自编简化检查未覆盖的项目明确列出，以成熟后端完成复核；不为了数值接近而放宽限值或删除失败项。
YJK是工程参照，解析和平衡检查也要独立保留；两软件相近本身不是完整规范认证。

误差按分项口径预先记录，近零响应设置与单位匹配的绝对误差尺度。阈值须依据解析/收敛验证和模型差异确定，
不预设“所有结果小于5%”或强行让MVLEM与壳元逐值一致。

## 接入Agent的顺序与下一最小任务

先打通一个完整模型的 `导出→前处理→求解→结果查询/官方报告→归一化`，验证后再接GA循环。
若某项没有稳定API，使用可核验的官方输出作为读取路径，并记录出处与单位，不臆造数值。
每次分析采用新目录、输入/配置哈希、版本、日志和完成判据，拒绝误读上一轮结果。
当前AnalysisRecord的真实raw契约偏OpenSees，接入YJK时应显式区分后端响应并统一必要校核，不能填零凑齐字段。
CASINO标签和局部校准仍绑定布局、条件与分析协议，不直接把原权重当成已适配YJK。

下一小任务：解决SDK模型读回/初始化问题，完成当前住宅的梁墙板截面和28层模型导出，核对YDB实际内容。
随后确认一个固定计算任务及结果读取，才进行上述数值交叉验证。所有修复直接推进，不要求用户重复确认。

## 后台方式、驱动复测与旧脚本审查（2026-10-29）

用户确认：独立脚本直接导入YJKAPI，软件内脚本通过 `yjks_pyload` 选择运行。
独立Python写YDB、无界面求解、外部进程控制隐藏的软件宿主是三种不同能力。
目前只验证了第一种的几何骨架持久化，不能承诺全链条无需宿主。
已安装SDK公开 `ControlConfig.Version/Invisible/Pid`，默认null/false/-1；
`YJKSControl`提供initConfig、RunYJK、init、RunCmd和exit等方法。
这些声明说明可继续调查隐藏宿主方式，不能证明能非交互加载脚本或后台完成分析。
Version参数含义、独立实例的所有权和项目路径传入方式需要核实；不能猜参数连接用户当前实例。

新的 `adapters/yjk_runtime.py` 只开放固定模型读探针：一致性SQLite快照→固定SDK worker→检查返回计数。
请求通过stdin传入，避免YJKAPI将命令行第二参数误当SDK加载模式；主项目不导入CLR。
worker无任意脚本/命令入口，校验只能读取运行目录内快照；父进程保留超时、退出码、日志和错误类型。
成功状态仅为SDK_READ_COUNTS_MATCH，不代表完整几何一致、规范合规或商业求解通过。
计数相等的单元测试使用明确标记的合成进程响应，不是实际SDK成功记录。

驱动更新后的真实只读探针：

- `outputs/yjk_background_probe_01`：对有效的几何骨架YDB调用ReadYdb，原生退出0xC0000005。
- `_02`：改为使用DataFunc提供的DbModel初始化读取桥，仍是相同退出码。
- `_03`：经新增受控Adapter复测，SDK打印Environment initialized successfully，
  随后在worker的ReadYdb处发生access violation；保存outcome.json、stdout/stderr、native_fault.log及模型快照。

上述结果不能判定加密狗驱动是之前失败的原因，也不能判定正常GUI启动等于独立SDK上下文正常。
原因仍未解决；完整模型、真实前处理/求解与结果提取标记为BLOCKED/未验证。商业求解次数为0。
没有启动、关闭或操作用户已打开的工程。

用户提供的上游脚本位于 `Png2Dxf/pipelines/structural/yjk_pipeline/`，只读审查：

- `analysis_runner.py`（SHA256 `f990ead9e043b1c3566ac2726b87a1e40fe08201747963c03351ab0a5442589c`）
  使用YJKSUIPy和YJKSCommandPy，属于宿主脚本。已有命令序列为
  yjk_repairex、yjk_save、yjk_setlayersupport、yjkspre_genmodrel、
  yjktransload_tlplan、yjktransload_tlvert、yjkdesign_dsncalculating_all；
  可作为后续固定白名单的来源，尚未在本项目实测。原脚本忽略RunCommand返回值，
  没有新鲜结果和完成状态判据，不能以“未抛异常”当计算完成。
- `result_extractor.py`（SHA256 `af0f88997d59a87d00f2e145069f978cbc7de0aa673cd0b3af506e61b3074176`）
  将缺失/转换错误替为0、按数值大小猜质量字段、去重接近的周期、猜位移角字段；
  这些逻辑可能误读结果，不迁移。后续按官方返回契约、单位、状态及模态序号严格解析，缺失显式失败。
- 旧model_builder包含硬编码工程参数和刷新当前软件的操作；pipeline允许清理旧文件，
  run_analysis=False也可能标记analysis_success=True。不整体复制旧流程。

下一最小任务是核对独立宿主的官方初始化和非交互脚本加载方式。
只对本项目专用实例进行启动、加载、命令执行和退出；先验证模型读回与完整导出，
再实现“分析完成且输出属于本次运行”的检查，最后接严格结果解析。已有活动实例不参与探测。
