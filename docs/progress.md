# 迁移进度

2026-10-28。本轮任务：先审计、统一公共数据结构，再独立迁移最小推理/优化/分析工具。
仓库初始仅有规划文件，未初始化 Git；本轮没有修改旧仓库或重新训练模型。

## 阶段状态

- Phase 0 审计已完成：创建 README、pyproject、base 配置、审计脚本和 upstream_contracts。
- Phase 1 的公共 Schema/单位/工件层已实现并验证；没有宣称完成规划中的完整 toy_01 教学数据集。
- 按本轮用户迁移范围，实现了 Phase 3 的专业工具切片；48 个运行模块、7 个权重和一个参考案例已独立迁入。
- **Phase 3 整体未完成**：尚无 Agent 决策后的真实续作闭环，当前真实两次分析是优化器内的候选评价。
- Phase 2 状态机和 Phase 4–7 不属于本轮迁移，尚未实现。原生 DWG 未接入。

## 已改文件

- `scripts/audit_upstream.py`、`migrate_runtime.py`、`import_local_assets.py`、`verify_upstream_fea.py`。
- `src/struct_agent/schemas/`：graph、layout、project、analysis、response 与严格公共配置。
- `src/struct_agent/adapters/`：RC-GNN、CASINO、布局特征、几何单位、OpenSees。
- `src/struct_agent/services/analysis.py`：统一缓存、预算、失败记录；`io/artifacts.py`：不可覆盖运行工件。
- `src/struct_agent/_vendor/`：来源可追溯的 48 个旧运行模块及迁移 manifest。
- `configs/`、`pyproject.toml`、`requirements.lock.txt`、README、测试及本目录接口/迁移文档。

## 环境与静态审计

本地 `.venv`：Python 3.12.12、torch 2.5.1+cu124、PyG 2.7.0、NumPy 1.26.4、
OpenSeesPy 3.8.0.0、Pydantic 2.12.3，完整版本见 requirements.lock.txt。
PyG 确为两个现有模型所需；未引入 LangGraph、HDF5 或商业 FEA 软件。
运行不再引用旧仓库代码路径；只有审计、初次导入、对照回归脚本读取上游。
源文件和资产 57 项哈希复核：`Upstream source/assets hash mismatches: []`。

## 命令与实际输出

均从项目根目录运行：

```powershell
.venv/Scripts/python.exe scripts/audit_upstream.py --output docs/upstream_contracts.md
# Wrote docs/upstream_contracts.md
.venv/Scripts/python.exe -m pytest -q tests/unit/test_upstream_contracts.py
# 2 passed（Phase 0）
.venv/Scripts/python.exe -m scripts.migrate_runtime
# Migrated 48 runtime modules（初次提取后补充一次受哈希保护的 --refresh）
.venv/Scripts/python.exe -m scripts.import_local_assets
# Imported 9 assets with matching SHA256
.venv/Scripts/python.exe -m pytest -q tests/unit/test_schemas.py tests/unit/test_adapters.py
# 8 passed
.venv/Scripts/python.exe -m pytest -q tests/integration/test_real_adapters.py -m real --run-real
# 7 passed, 1 warning
.venv/Scripts/python.exe -m pytest -q
# 12 passed, 7 skipped, 1 warning（真实测试显式启用后另行通过）
```

真实生成和优化：

```powershell
.venv/Scripts/python.exe -m struct_agent.cli generate --dxf data/local/L17_101.dxf --category 0 --seed 42 --run outputs/migration_rcgnn_01
# Generated 115 members；拓扑检查通过
.venv/Scripts/python.exe -m struct_agent.cli optimize --layout outputs/migration_rcgnn_01/layout.json --rooms outputs/migration_rcgnn_01/room_graph.json --spec configs/reference_spec.json --seed 42 --budget-fea 1 --population 2 --generations 1 --run outputs/migration_casino_01
# completed；1 次真实 FEA；best_feasible=false；局部样本 0（候选被默认筛选拒绝，最终保底复核）
.venv/Scripts/python.exe -m struct_agent.cli optimize --layout outputs/migration_rcgnn_01/layout.json --rooms outputs/migration_rcgnn_01/room_graph.json --spec configs/reference_spec.json --seed 42 --budget-fea 2 --population 2 --generations 1 --screening-threshold 0.0 --run outputs/migration_verified_01
# completed；2 次真实 FEA；best_feasible=false；local_calibration_samples=2；含逐次 solver_logs
```

另保留 `outputs/migration_casino_02`（12 候选、2 代、默认筛选、1 次保底 FEA）和
`outputs/migration_casino_calibration_01`（初次阈值 0 冒烟，2 次真实 FEA）以保留完整检查历史。
没有删除不满足校核的运行。最终 `migration_verified_01` 与其原生数值一致，增加了稳定设计 ID、响应校验与日志引用。

原工程数值对照（只读、禁止上游 bytecode 写入；其日志写在新的本项目回归目录）：

```powershell
& E:/Common/Desktop/Research/deepLearning/codes/Png2Dxf/.venv/Scripts/python.exe -B scripts/verify_upstream_fea.py --source E:/Common/Desktop/Research/deepLearning/codes/Png2Dxf --layout outputs/migration_rcgnn_01/layout.json --record outputs/migration_casino_calibration_01/analyses/eval_00001.json --spec configs/reference_spec.json --output outputs/upstream_fea_regression_01
# Original/migrated FEA fields: 35; failures: []
```

## 工件位置与已知边界

- 审计：`docs/upstream_contracts.md`；公共字段：`docs/data_contracts.md`；迁移范围：`docs/migration_notes.md`。
- 权重：`checkpoints/{rcgnn,casino}`；资产来源/哈希：`configs/local_assets.json`。
- 图与方案：`outputs/migration_rcgnn_01/{room_graph.json,ratios.npy,layout.json,manifest.json}`。
- 最新真实优化：`outputs/migration_verified_01/{manifest.json,analyses,solver_logs,optimization}`。
- 原 FEA 比较：`outputs/upstream_fea_regression_01/comparison.json`。
- 所有真实冒烟方案均**未通过结构校核**；不能作论文性能结果或工程成果。
- 阈值 0 的运行只检验真实数据进入局部缓冲区；2 条样本低于默认 25 条，**尚未拟合 Platt/Ridge 模型**。
- 默认阈值拒绝本轮候选，不能据此断言它们真实不可行；代理泛化与新布局适用性仍待实验。
- [TODO: 待确认] 正式模型工件版本、回归基准、荷载和规范版本。暂沿用显式标记的旧默认口径。
- 本地测试唯一 warning 来自 PyG 内部已弃用 distributed 模块导入；不涉及本项目分布式训练。
- 当前无 Git，因此未提交 Git commit，运行 manifest 使用源码 SHA256。

## 2026-10-28：Phase 2 模拟状态机最小切片

发现现有 `adapters/casino.py:optimize()` 每次创建新 GA、问题实例和校准器。
重复调用不能称为“继续优化”；本次先完成独立的 mock 状态机验证，未改动模型、优化算法或真实 FEA。
正式工程条件仍待确认，不将既有冒烟条件升级为工程师确认基准。

新增文件：`schemas/state.py`、`adapters/mock.py`、`workflows/{mock_case,environment,policy,runner}.py`、
`scripts/make_dummy_case.py`、`tests/integration/test_mock_workflow.py`；修改 CLI、README 和公共契约说明。
为减少分散的小模块，环境和策略暂放在同一 `workflows/` 包。

实现范围：预置候选评价、保持共享预算、请求切换布局、显式模拟审批、失败转待检查、
不可覆盖运行目录、逐步状态和事件证据。`fixed` 策略不换布局；`scripted` 策略在当前队列用尽后请求切换。
没有 LLM，也没有把预置候选遍历当作 CASINO 增量优化。

### 验证命令及实际结果

```powershell
.venv/Scripts/python.exe -m pytest -q tests/integration/test_mock_workflow.py
# 9 passed in 1.56s
.venv/Scripts/python.exe -m pytest -q
# 21 passed, 7 skipped, 1 warning in 6.36s
.venv/Scripts/python.exe scripts/make_dummy_case.py --out data/examples/toy_01
# Created MOCK ONLY case: data/examples/toy_01/case.json
.venv/Scripts/python.exe -m struct_agent.cli run-case --case data/examples/toy_01/case.json --run outputs/phase2_mock_01 --seed 42 --budget-fea 4 --approve-mock-layout layout_b
# MOCK ONLY: COMPLETED; mock evaluations=4
.venv/Scripts/python.exe -m struct_agent.cli run-case --case data/examples/toy_01/case.json --run outputs/phase2_mock_replay_01 --seed 42 --budget-fea 4 --approve-mock-layout layout_b
# MOCK ONLY: COMPLETED; mock evaluations=4
.venv/Scripts/python.exe -m struct_agent.cli run-case --case data/examples/toy_01/case.json --run outputs/phase2_approval_gate_01 --seed 42 --budget-fea 4
# MOCK ONLY: WAITING_APPROVAL; mock evaluations=2
.venv/Scripts/python.exe -m struct_agent.cli run-case --case data/examples/toy_01/case.json --run outputs/phase2_fixed_01 --seed 42 --budget-fea 4 --policy fixed
# MOCK ONLY: NO_MORE_CANDIDATES; mock evaluations=2
Get-FileHash outputs/phase2_mock_01/events.jsonl, outputs/phase2_mock_replay_01/events.jsonl -Algorithm SHA256
# Both: 28C0A0B5C7B35D36EC973F0B893AF458AFEBA45A7DE60301408E324255C92A4D
```

9 项新增测试覆盖：完整决策链及同种子回放、默认审批暂停、非法动作/证据/目标拒绝和进程内审批续行、
3 种预算边界、失败注入、固定流程、真实 fidelity 拒绝；也核查输入未改动、输出不可覆盖、证据引用存在。
7 skipped 仍是显式 `--run-real` 才启用的旧模型/求解器回归，本次没有重跑，也不声称新增真实验证。
唯一 warning 仍来自 PyG 弃用模块导入。

### 当前边界及下一步最小任务

上述 `outputs/phase2_*` **全部是合成数据，不用于论文性能结果**。
模拟闭环成功仅证明状态、预算、门控与轨迹记录行为；不能证明跨层级决策提升了结构设计效果。
仅支持同进程内审批续行，磁盘恢复、真实审批界面、自动修模尚未实现。
种子显式记录，当前 mock 计算和策略均无随机采样。

下一步为 CASINO 增加可保留种群、随机状态、历史和局部校准的增量会话：
同布局继续时复用该会话，切换布局时新建独立会话；以不中断/分段运行的数值一致性验证真实“继续”。
先审计原 GA 的代际边界，优先改 Adapter，保留原算法作为对照；随后接入真实二次评价。
[TODO: 待确认] 正式参考案例的完整设计条件、荷载和规范版本，仍需工程师确认。

## 2026-10-28：测试布局核对图

按用户要求绘制两组核对图，未修改输入布局或业务代码：

- `outputs/layout_review_01/L17_101_comparison.png`：左为 `data/local/reference_layout.json`
  （50 段墙、19 段主梁、44 段次梁），右为 `outputs/migration_rcgnn_01/layout.json`
  （54 段墙、19 段主梁、42 段次梁）。此前真实 CASINO/FEA 冒烟使用右图，建筑输入为 `L17_101.dxf`。
- `outputs/layout_review_01/toy_01_mock.png`：当前 Phase 2 的合成 A/B 布局，来源为
  `outputs/phase2_mock_01/case.json`，不是实际住宅布局。

复现脚本与输入 SHA256 保存在同目录 `render.py`、`sources.json`。
本项目环境没有 matplotlib，使用旧项目已有绘图库，只读加载 JSON；不添加项目运行依赖。
命令：`& E:/Common/Desktop/Research/deepLearning/codes/Png2Dxf/.venv/Scripts/python.exe -B outputs/layout_review_01/render.py`。
输出：`Created L17_101_comparison.png, toy_01_mock.png and sources.json`。
验证：两个住宅布局通过现有 Schema 校验；核对构件数量及 m 坐标、等比例、方向和图例，逐张查看 PNG。
本次为静态核对图，未重跑模型、FEA 或 pytest。下一步等待用户识别是否为常用布局，再继续参考案例选择。

## 2026-10-28：指定工程案例 residential_001 与 Git 基线

用户指定 `Png2Dxf/data/dxf/cad_json_data/archi_comp.dxf` 为以后统一的真实测试建筑图。
已逐字节复制到 `data/local/residential_001/architecture_preprocessed.dxf`（172479 bytes），未改动源文件。
源文件/副本 SHA256 均为 `4c9f637390669573e259cdb459c787ab573de0989dd275a48c4fa193f15dcc31`。
本任务为 Phase 3 案例基线准备，不涉及训练、优化算法重构或新 FEA 验证。

### 配置、接口和文件

- 新增 `configs/test_case.json`、`schemas/case.py`、`io/case.py`：案例来源、哈希、类别和单位解释；
  读取前验证哈希，拒绝文件缺失或变更。
- 修改 `cli.py`：`generate` 默认读取该案例；自定义 DXF 必须显式提供类别。
  仅验证当前命令需要的权重，生成和优化入口不再依赖历史 L17_101 资产存在。
- 新增 `tests/unit/test_case.py`；真实 RC-GNN 数值对照改用 residential_001，覆盖原图与预处理尺寸、
  模型预测一致性和生成拓扑；旧 FEA 回归仍保留被冻结的历史数值，不用新案例伪替旧参考。
- 更新 README、上游差异记录、AGENTS.md；后续真实生成/优化/闭环统一采用此图，toy_01 仍作为 mock fixture。
- 初始化本地 Git `main`，沿用已有用户身份；新增 `.gitattributes`，扩充 `.gitignore`。
  工程数据、DXF/DWG、权重、环境、缓存、日志、输出和密钥不提交；记录来源与哈希的配置提交。
  `_vendor` 禁止 Git 自动转换换行，保证迁移清单记录的文件字节哈希在检出后仍有效。
  每次完成任务并验证后检查并本地提交，未经指示不推送。

### 实际发现与处理

旧项目 README 中 `archi_comp.dxf` 的正式示例采用 `--category 2`，据此显式设置条件。
图纸有 43 个 ROOM 多段线，无已有 SHEAR_WALLS 实体；解析得到 43 节点、182 条有向边。
DXF 头 `INSUNITS=6`（m），但房间边长 3600/3200 等及旧处理链均按 mm；保留原字节并显式记录单位解释。
原图包围范围 27.1 × 12.5 m；旧 200 mm 坐标聚类使最高边界下降 200 mm，模型图为 27.1 × 12.3 m。
首轮目标测试误把原图尺寸作为预处理后尺寸，出现 `1 failed`；定位至原有坐标对齐后，改为分别
校验原图/模型图尺寸并通过。没有更改对齐算法或扩大容差掩盖差异。
旧案例文档示例还使用 `symmetry_mode=union`；当前最小 Adapter 保持 `none`，未声称复制了完整后处理方案。

### 命令和验证输出

```powershell
git init -b main
# Initialized empty Git repository .../StructLoop/.git/
.venv/Scripts/python.exe -m pytest -q tests/unit/test_case.py
# 3 passed in 0.08s
.venv/Scripts/python.exe -m pytest -q tests/integration/test_real_adapters.py -k rcgnn --run-real
# 1 passed, 6 deselected, 8 warnings in 5.82s
.venv/Scripts/python.exe -m pytest -q
# 24 passed, 7 skipped, 1 warning in 6.77s
.venv/Scripts/python.exe -m struct_agent.cli generate --seed 42 --run outputs/residential_001_rcgnn_01
# Generated 217 members；拓扑校验通过
git check-ignore .venv/pyvenv.cfg data/local/residential_001/architecture_preprocessed.dxf checkpoints/rcgnn/fold_0.pth outputs/residential_001_rcgnn_01/layout.json .env
# 上述五类路径均命中忽略规则
```

新工件：`outputs/residential_001_rcgnn_01/{manifest.json,room_graph.json,ratios.npy,layout.json}`。
生成 142 段墙、27 段主梁、48 段次梁、43 块楼板；段数不是工程墙肢数量或合规性结论。
manifest 保存图纸、案例配置、5 份权重哈希及源码 SHA256；生成发生于初次 Git 提交之前，`git_commit=null`。
本次真实验证仅为 RC-GNN 推理/生成及其与原模型的数值对照，新图尚未运行 FEA。
普通测试的 7 skipped 仍是显式启用的真实测试；此次其中 RC-GNN 项已单独执行。
warnings 为 ezdxf/PyParsing 和 PyG 的弃用提醒。

### 下一步最小任务

在该案例上开发并验证 CASINO 增量会话，保留种群/随机状态/优化历史/本布局局部校准；
先验证分段运行与连续运行一致，再接入真实反馈状态机。
[TODO: 待确认] 新工程的层数、荷载、设防及规范条件；现有 `reference_spec.json` 仍为冒烟示例。
本任务只确认建筑图，不自动把旧 28 层/8 度示例条件套作新工程条件。
