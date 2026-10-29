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

## 2026-10-28：Phase 3 CASINO 同进程增量会话

### 已完成范围

新增 `adapters/incremental_ga.py`、`adapters/casino_session.py`，修改 `adapters/casino.py` 复用构造过程，
原 `optimize()` 一次性入口保留为对照。新增 CLI 参数 `--generations-per-step`、`--device`；
未修改 `_vendor` 算法、权重、原数据，也未训练新的代理模型。

`advance(n)` 在预设总世代上限内推进 n 代，保留种群、独立随机状态、历史、预测缓存与局部校准器。
每次写不可覆盖的状态快照，保存评价增量和错误。预算耗尽、求解失败或其他执行错误均终止当前会话，
防止将部分执行过的代重跑；共享评价服务负责跨会话全局预算，新布局新建隔离校准器。
原 GA 最后一代末尾的额外种群评价和最终代理候选保底复核顺序均保持不变。

### 验证与问题定位

新增 `tests/unit/test_incremental_ga.py` 的 10 项测试：两个种子、有/无代理选择下的原生/连续/分段对照，
包括已拟合的 Platt/Ridge、逐项历史/结果/随机状态/调用顺序/校准样本一致性，以及最终复核只执行一次、
部分代预算耗尽不重复执行、非法步数不触发评价。

新增 `tests/integration/test_casino_session.py` 的 4 项测试：使用 residential_001 几何与真实 FuseGNN 权重，
**有限元响应全部由测试内的合成函数生成并标记 mock**。覆盖实际代理链的三路对照、预算、失败语义、
布局与校准隔离、共享预算及不可覆盖工件。

首轮集成测试 `1 failed, 3 passed`：原代理自动使用 CUDA，第二代一个候选的钢筋预测相差
`0.07087933392904233 kg`（对应代理成本差约 0.3544），严格比较失败。没有放宽容差；
在 Adapter 中显式设置 CPU 为回归默认设备并保留 CUDA 选项后，完整比较通过。
构造代理模型采用 `torch.random.fork_rng()`，避免覆盖调用方的全局随机状态。
首次失败工件也保留在 `outputs/casino_continuation_01/gpu_mismatch_initial/`。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_incremental_ga.py
# 10 passed in 2.55s（最终目标测试）
.venv/Scripts/python.exe -m pytest -q tests/integration/test_casino_session.py --run-real
# 4 passed, 1 warning in 12.90s
.venv/Scripts/python.exe -m struct_agent.cli optimize --help
# 包含 --generations-per-step、--device
.venv/Scripts/python.exe -m pytest -q
# 34 passed, 11 skipped, 1 warning in 9.44s
```

11 skipped = 原有 7 项显式真实测试 + 新增 4 项本地权重集成测试；新增 4 项已另行显式执行通过。
本次没有重跑旧真实 FEA，也没有执行新案例真实 FEA。唯一 warning 为既有 PyG 弃用提示。

### 工件与验证结果

已将完整测试工件从 pytest 临时目录复制到不可覆盖的 `outputs/casino_continuation_01/`，
逐文件检查复制哈希；摘要见 `verification.json`。

- `equivalence/{native,continuous,chunked}/`：原版 GA、一次推进 3 代、分三次各推进 1 代。
  三路评价记录、历史、结果和校准记录一致，各 15 次 mock 评价；continuous/chunked 均为 15 条局部样本。
- 测试专用最小校准样本阈值为 4（正式默认仍为 25），已验证拟合 Platt/Ridge 后的续行。
  所有这些拟合仅基于合成标签，不表示真实工程校准成功。最终 `fit_pending=true` 表示最后一批新样本
  尚待原生下次拟合时机；状态快照不为了展示额外触发拟合。
- `budget_limit/`、`solver_failure/`、`layout_isolation/`：预算/失败/隔离验证记录。
  隔离测试只做预定义几何扰动，不能视为获批的结构修改。

### 当前整体进度与下一步

Phase 0 工具审计/迁移及 Phase 1 公共契约已具备最小能力；Phase 2 mock 闭环通过。
Phase 3 已有真实工具适配与增量会话，但新工程的真实反馈二次决策闭环尚未完成。
下一小步是在确定设计条件后，将本会话接入真实 FEA 和确定性反馈状态机，记录真实评价后的第二次动作。
Phase 4 再接入 LLM API，用固定/规则策略作对照；Phase 5 完善人工交互和恢复，随后扩展 DWG/报告/图纸。

当前增量会话只支持同进程代际暂停，不支持磁盘恢复、代内暂停或终止后追加世代；
CLI 逐段自动执行，尚无 Agent 在段间决策。正式工程条件仍待确认，本次不宣称获得工程可行方案。

## 2026-10-28：Phase 4 基础决策闭环、学校 API 与获批跨布局冒烟

### 实现范围

- 新增 `schemas/agent.py`、`agents/chat_client.py`、`agents/policies.py`：固定、规则、受控 LLM 与状态哈希回放。
  学校 HTTPS 网关默认直连，读取 `.env` 的 `apikey`，严格检查动作/候选/证据，失败转人工检查。
  保留 API 请求、最终回答、usage、重试和脱敏错误；无 shell 工具、无模型审批权限。
- 新增 `workflows/optimization_env.py`、`layout_approval.py` 和 `agent_cli.py`：同布局续行、共享真实预算、
  跨布局会话/校准隔离、动作前后实际消耗、布局/条件/用途哈希绑定批准。创建会话失败也记录完整错误。
- 新增 `evaluation/compare.py`：相同条件/预算/代码/软件才允许汇总，失败保留，无可行成本为 null。
- 最小迁移 `adapters/symmetry.py` 并给 `rcgnn.layout_from_prediction` 增加可选镜像轴；默认行为不变。
  新增 `scripts/prepare_symmetry_candidate.py`，复用已有房间图和预测，不重训或重跑模型。
  对照图用标准库 SVG；没有新增 Matplotlib/Pillow 等依赖，未改 `_vendor`。
- 更新 README、`docs/phase4_agent.md`、上游契约、`.env.example`、网关配置与临时 Office 文件忽略规则。

### 授权及网络验证

用户明确授权“沿用现有条件，仅作冒烟验证”：28 层、8 度、II 类场地、第 1 组及现有荷载/材料口径。
校园网经系统代理返回 403；用户授权尝试绕过 Clash，直连后模型列表与对话均成功。
采用实测存在的 `DeepSeek-V4.1-Flash`，首次合成状态探针保留在 `outputs/phase4_api_probe_01/`。
首次回答误解暂停/待审查状态，提示词明确其语义后继续实际验证，未修改原始失败/探针记录。

用户查看对照后明确回复“批准，用于本轮跨布局冒烟”。批准保存在
`outputs/residential_001_symmetry_02/user_approval.json`，绑定布局规范 JSON SHA256
`e16a6dc51c5370a9e19a9913c99f20e9af068723b7c5011951dcd8a1fdfa38b4`
及条件 SHA256 `579ff7b4cc395dc4d957b3908cd2e33b9d066a63f33151d9eb0e760dfc23e685`。
它不是工程签审，也不适用于变更后的几何/条件/用途。

### 真实运行结果

| 工件目录（outputs 下） | 实际动作 | 真实 FEA | 求解失败 | 可行解 |
|---|---|---:|---:|---:|
| phase4_real_rules_01 | 继续→继续→结束 | 5 | 0 | 0 |
| phase4_real_llm_01 | 继续→继续→人工检查 | 5 | 0 | 0 |
| phase4_real_switch_01 | 继续→切换提议→用户批准→继续→结束 | 4（2+2） | 0 | 0 |

共 14 次真实求解成功，但所有候选均未通过既有结构校核，不得解释为工程可行。
LLM 在第 4 次 FEA 后依据墙抗剪违反与剩余预算选择继续，随后确实执行第 5 次 FEA；
共 3 次在线决策，API 返回 2303 tokens，无 JSON 修正或网络重试。预算用尽后请求人工检查。
规则/LLM 同布局冒烟得到相同评价轨迹，但开发期间代码哈希不同，比较器正确拒绝将其当正式配对实验。

跨布局运行当前布局和新布局各 2 次实际分析，批准事件不消耗 FEA；两个会话各保留 2 条局部样本。
同布局运行各有 5 条样本，均未达到正式默认最小校准样本数 25，不能声称真实局部模型已拟合。
`outputs/phase4_verification_01/verification.json` 核验评价计数、事件增量、证据文件和批准记录。

上述真实命令均使用：

```powershell
.venv/Scripts/python.exe -m struct_agent.agent_cli --layout outputs/residential_001_rcgnn_01/layout.json --rooms outputs/residential_001_rcgnn_01/room_graph.json --spec configs/reference_spec.json --run outputs/phase4_real_llm_01 --case-id residential_001 --purpose smoke_only --policy llm --seed 42 --budget-fea 5 --population 3 --generations 2 --screening-threshold 0
.venv/Scripts/python.exe -m struct_agent.agent_cli --layout outputs/residential_001_rcgnn_01/layout.json --layout outputs/residential_001_symmetry_02/layout.json --layout-approval outputs/residential_001_symmetry_02/user_approval.json --rooms outputs/residential_001_rcgnn_01/room_graph.json --spec configs/reference_spec.json --run outputs/phase4_real_switch_01 --case-id residential_001 --purpose smoke_only --policy rules --seed 42 --budget-fea 4 --population 2 --generations 1 --screening-threshold 0
```

规则单布局命令与第一条相同，但 `--policy rules --run outputs/phase4_real_rules_01`。
这些目录已存在，复跑必须改用新目录名；阈值 0 只作调用链冒烟，不表示正式 CASINO 效率设置。

### 测试与几何核验

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_optimization_env.py
# 7 passed in 2.63s（含构造异常与批准绑定）
.venv/Scripts/python.exe -m pytest -q tests/integration/test_casino_session.py tests/integration/test_symmetry_reference.py --run-real
# 7 passed, 1 warning in 15.74s
.venv/Scripts/python.exe -m pytest -q
# 57 passed, 14 skipped, 1 warning in 8.63s
```

14 skipped = 原 11 项 + 真实会话反馈集成、三策略配对集成、上游对称化参考各 1 项。
本次上述 7 项显式集成已通过；除几何参考外使用真实 FuseGNN 权重但**合成 FEA**，LLM 比较使用桩。
新增三策略测试共享候选/预算，固定策略不切换、规则与 LLM 桩均切换一次；全部标记 mock。
完整 104 个工件复制并逐文件校验哈希后保存于 `outputs/phase4_policy_comparison_mock_01/`。
原 7 项更早的真实回归未重复执行；唯一 warning 为既有 PyG 弃用提示。

候选生成命令：

```powershell
.venv/Scripts/python.exe scripts/prepare_symmetry_candidate.py --source-run outputs/residential_001_rcgnn_01 --run outputs/residential_001_symmetry_02 --seed 42
```

原始房间并集对称 IoU=0.9855676302564323，阈值 0.85；镜像轴为原坐标 x=728266 mm。
输出墙线与上游逐项 WKB 完全一致，最终拓扑校验通过，仍为 43 个楼板区域。
墙段 142→135（涉及合并，不等于墙量减少）。`comparison.svg` 与对应 PNG 已检查，用户已批准候选。
首次 `residential_001_symmetry_01` 几何生成成功，但绘图因缺 Matplotlib 失败；保留该目录，
随后改用无额外依赖的 SVG 并在新目录重新生成。PNG 是 Windows System.Drawing 对 SVG 的展示副本。
密钥扫描未发现源码、DOCX 内容及当前 JSON 工件泄漏，`.env` 确认被 Git 忽略。

### 完成边界与下一最小任务

Phase 4 的基础工程验收路径已打通：实际反馈后继续优化、获批后切换布局、学校 LLM 真调用。
这不等于本章研究完成：论文 Ours 的动作收益/分层决策机制、正式三策略配对、多种子与消融仍待设计验证。
下一最小任务：冻结当前代码和双布局候选池，确定正式 pilot 的预算/停止条件，做同版本固定/规则/LLM 对照；
同时诊断反复出现的墙/梁抗剪不通过，先核对上游输出及工程口径，不擅自改变约束限值。
工程条件仍仅获准冒烟；磁盘恢复、工程审批界面、DWG/成果输出继续留在后续阶段。

## 2026-10-28：构件级 FEA 诊断与抗剪失败定位

### 本轮最小任务与变更

在冻结正式 pilot 前，先核查反复出现的墙/梁抗剪不通过。新增可选的构件诊断路径：
`adapters/fea_diagnostics.py` 复用原生构建/分析/校核/配筋组件；`fea_summary.py` 保持原汇总逻辑，
`fea_member_evidence.py` 映射构件与实际组合内力；新增严格 `MemberDiagnostic`、报告服务及 `diagnostics_cli.py`。
`OpenSeesAdapter` 增加可选诊断目录，默认路径不变；未修改 `_vendor`、权重、限值、几何或历史结果。
未增加依赖、训练或调用 LLM API。

### 真实复算与失败保留

两个既有布局均使用上一轮相同参数复算，原布局和已批准的对称化布局各完成一次有效诊断。
成功目录为 `outputs/member_diagnostics_baseline_02/` 和 `outputs/member_diagnostics_symmetry_02/`。
每次经 `AnalysisService` 记 1 次真实 FEA；全部 35 个原汇总字段在原回归容差内通过，
两者仍是求解成功、结构不可行，不改变既有可行性结论。

此前各有一次采集失败，保留在 `member_diagnostics_baseline_01/`、`member_diagnostics_symmetry_01/`。
原因是新采集器假定控制组合非空，未处理上游全负剪力经零截断后保留空组合的情况。
原生分析/配筋已返回，随后采集抛出 `KeyError('')`；这两条早期记录状态为 SOLVER_ERROR，未改写。
修复后保留空组合、原零包络及全部有符号剪力；未来诊断采集异常归为 INVALID_RESULT，
保留原异常链，避免把后处理失败误报成结构不通过或求解器故障。
本轮实际新增 4 次 FEA（2 次采集失败 + 2 次成功复算），全部记账，未隐藏失败开销。
核验工件：`outputs/member_diagnostics_verification_01/verification.json`，该核验自身不新增求解。

真实命令见 `docs/member_diagnostics.md`；成功输出分别包含 `report.md`、`summary.json`、
`comparison.json` 和详细构件、配筋消息、实际模型配置。坐标/尺寸 m、力 N、强度 Pa。

### 关键发现

- 原布局含 15 条约 1 mm 墙段。控制墙 `shearwalls_138` 首层剪力约 14.291 kN，
  上游分母约 2860 N，剪压指标 4.996789、限值 0.15、利用率约 33.312。
  355 个墙剪压失败中，341 个来自 1 mm 墙，14 个来自 0.25 m 墙。
- 墙配筋只对长度 >0.5 m 执行，ULS 则检查全部墙段；355 个失败都位于未执行配筋的短墙范围。
  因而 `design_failed_wall_count=0` 不能理解为全部墙段完成且通过设计。
- 对称化布局无 1 mm 墙，原 ULS 墙剪压检查通过；控制梁 `beams_49` 第 3 层长 0.35 m，
  300×400 mm 截面，剪力约 604.838 kN，利用率约 2.350，配筋消息为截面抗剪不足。
- 上游有符号静力内力与无符号组合/包络假设不一致：组合因子用 abs，+/- 组合结果相同；
  有符号剪力最大值截为非负，可将全负效应归零。对称化墙 `shearwalls_92` 第 28 层的
  组合绝对剪力最大约 113.557 kN，原包络为零。诊断保留该值，没有代换校核或重标注历史数据。

完整差异、数量、来源及待确认的最小修正边界见 `docs/member_diagnostics.md`，已同步上游契约和 README。

### 验证命令与输出

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_fea_diagnostics.py tests/integration/test_member_diagnostics.py --run-real
# 11 passed in 0.93s：9 项合成单元测试 + 2 项真实工件核验（不新增 FEA）
.venv/Scripts/python.exe -m pytest -q
# 66 passed, 16 skipped, 1 warning in 8.88s
```

16 skipped 为原 14 项加两项需要本地真实诊断工件的显式核验；这两项已单独启用并通过。
单元测试覆盖原生汇总逐字段对照、空集合/周期比回退/并列利用率选择、短墙检查范围、
有符号零包络保留、证据单位一致性及采集异常分类/预算。唯一 warning 仍是 PyG 弃用提示。

### 下一最小任务

先确认并修正力效应符号、正负组合与包络契约，再追踪极短墙段的拓扑生成。
这些变化会影响 FEA 指标、可行性标签和 CASINO 权重适用性，按 AGENTS.md 第 7 条需人工确认；
须显式版本化分析协议与缓存绑定，保留旧路径和旧结果。新几何仍按版本供工程师检查。
由于本轮定位到上述真实问题，正式三策略对照配置/运行暂不扩大；修正并复验后再冻结 pilot。

## 2026-10-28：直接修正计算与拓扑实现，不保留错误分支

### 执行规则

用户明确要求“有问题就改……不需要保留旧版……确保逻辑正确……不需要经过我确认”。
已将此授权写入 AGENTS.md 第7条和 PLAN 顶部。实现 bug 直接修复；工程条件不编造、最终工程签审独立处理。
以下为实际修复，不再是待确认方案。原 Png2Dxf 仓库只读，本项目迁移副本按正确逻辑维护。

### 修复内容

- ULS：组合保留系数正负；负效应取绝对值参与控制包络，不再归零；不同限值下按利用率选控制组合。
  增加反例：非地震180/0.2与地震170/0.15，后者必须控制。缺失工况不能隐式补零。
- 力提取：梁改取 localForce 并统一 j 端截面图弯矩符号；墙剪力投影自身平面方向，不混入面外分量。
- CQC：输入是 omega²，相关系数用频率比 sqrt(lambda_i/lambda_j)，并正确处理零阻尼与无效输入。
  核对 OpenSees 坐标文档及 ANSYS 1%阻尼近频振型算例，资料链接见 `docs/physics_fixes.md`。
- 拓扑：零区间不生成墙；未预测间隙保留为梁；合并间隙用 mm 距离而非0.02比例；
  固定锚点2 mm吸附避免链式漂移，落实最小墙长，保留边界连接与T节点，删除旧短段翻转逻辑。
- 配筋：所有建模墙肢执行设计，取消 <=0.5 m 漏检。诊断采集要求每个构件有设计记录和真实控制组合。
- 普通/详细 FEA 共用 `parametric/summary.py`；删除重复 `adapters/fea_summary.py`。
  删除未使用且错误的重复组合方法，没有新增旧算法开关。
- 缓存/标签：记录与缓存键绑定当前分析实现指纹。旧代理权重缺少新标签兼容证据，真实优化默认直接FEA，
  只有训练指纹匹配的权重可启用代理；mock测试可验证旧权重的机械接口，不混入真实研究结论。
  没有重训模型或改动权重。迁移清单更新本地哈希及修正说明。

### 测试

针对性测试覆盖有符号组合、负/零包络、不同限值控制项、旋转墙投影、CQC数值例、
墙设计覆盖、几何连接/零区间/不链式吸附、缓存实现隔离和旧权重拒绝。
新增3个真实小型悬臂梁（X/Y/45°），逐项对照 M=PL、V=P、位移 PL³/(3EI)。
测试数据/参考均切换到修正后的当前实现，不再要求复现错误的历史数值。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_fea_physics.py tests/unit/test_fea_diagnostics.py tests/unit/test_topology_cleanup.py tests/unit/test_analysis_compatibility.py tests/integration/test_opensees_beam_mechanics.py --run-real
# 29 passed, 1 warning（随后单独增加的全墙设计覆盖测试也通过）
.venv/Scripts/python.exe -m pytest -q --run-real
# 103 passed, 8 warnings in 95.72s；0 failed，0 skipped
```

103项包含所有本地权重/真实求解显式测试。8个提示为 PyG 与 ezdxf/pyparsing 的弃用提示。
普通/详细真实入口独立计算的35字段对照通过，未通过放宽数值容差获得通过。

### 工件和真实计算

- `outputs/residential_001_rcgnn_02/`：149墙、81梁；`outputs/residential_001_symmetry_03/`：187墙、73梁。
  两布局均为43个楼板区域，最短墙均>=0.1 m，无1 mm墙段，拓扑验证通过。输入图和RC-GNN权重不变。
- 最终诊断 `outputs/member_diagnostics_{baseline,symmetry}_04/`：各1次真实建筑FEA，均 SUCCESS 但不可行。
  墙配筋检查分别4172/5236项，漏检均为0；墙设计失败133/506项，梁设计失败7/28项。
- 最终 Agent 冒烟 `outputs/physics_fix_agent_02/`：当前正确实现、预算1、代理禁用，实际FEA=1，正常结束。
- 核验 `outputs/physics_fixes_verification_01/verification.json`：检查实现指纹、几何最小长度、
  全构件设计覆盖、预算和代理禁用。核验自身不新增求解。
- 实现指纹 `981ea4234286f985cdfeb0fc4181c20bd245c26e82362dba6e7034344b625644`。

本轮还运行过 `_03` 诊断、`physics_fix_agent_01` 和一次中间默认入口对照；随后发现跨限值控制项问题，
重新生成 `_04` 最终结果并重跑全部测试。建筑规模真实计算本轮共9次：中间验证5次，最终诊断2次、
最终Agent1次、最终默认入口对照1次。都保留日志；中间结果不作为当前协议的论文标签。
小型解析梁测试另属软件验证，不计入设计优化的预算或性能结论。

真实命令：

```powershell
.venv/Scripts/python.exe -m struct_agent.cli generate --run outputs/residential_001_rcgnn_02 --seed 42
.venv/Scripts/python.exe scripts/prepare_symmetry_candidate.py --source-run outputs/residential_001_rcgnn_02 --run outputs/residential_001_symmetry_03 --seed 42
.venv/Scripts/python.exe -m struct_agent.diagnostics_cli --layout outputs/residential_001_rcgnn_02/layout.json --spec configs/reference_spec.json --design outputs/physics_fix_inputs_01/design_baseline.json --run outputs/member_diagnostics_baseline_04
.venv/Scripts/python.exe -m struct_agent.diagnostics_cli --layout outputs/residential_001_symmetry_03/layout.json --spec configs/reference_spec.json --design outputs/physics_fix_inputs_01/design_symmetry.json --run outputs/member_diagnostics_symmetry_04
.venv/Scripts/python.exe -m struct_agent.agent_cli --layout outputs/residential_001_rcgnn_02/layout.json --rooms outputs/residential_001_rcgnn_02/room_graph.json --spec configs/reference_spec.json --run outputs/physics_fix_agent_02 --case-id residential_001 --purpose smoke_only --policy rules --seed 42 --budget-fea 1 --population 2 --generations 1
```

以上目录已存在；复跑另取新名称。详细变更、使用方法及权重边界见 `docs/physics_fixes.md`。
下一最小任务：依据修正后的控制构件完善布局/参数策略，积累当前物理实现的可信样本，验证/更新代理标签兼容性。
目前尚无可行解，不宣称已完成工程设计或证明 Agent 优于基线。

## 2026-10-29：优化内核与反馈迭代修正

### 范围与实现

按用户本轮授权，围绕“给定结构→调整至可行→降低材料目标”修正现有流程，仍属于Phase 4。
先完成一个最小可验证任务：修复GA的种群更新/终代评价，统一可行性优先的排序，接通给定初值与参数反馈邻域。
没有重训或修改RC-GNN/FuseGNN权重，没有改变真实图纸或编造工程条件。

- `_vendor/shearwall_optimization/algorithms/{genetic,evolution}.py`：
  一个已评价种群算一代，终代参与最优解；小种群保留子代位置；单次与分段共用引擎。
  删除重复 `adapters/incremental_ga.py`，不保留原先错误的尾随评价分支。
- `surrogate_candidate.py`、`problems/shearwall_problem.py`、`casino.py`、`casino_session.py`：
  所有选择均按可行性/违反量/材料成本排序；真实结果优先于未评价代理占位值。
  连续约束不重复加同项二元惩罚；增加墙梁设计失败比例，保留无数值解释的失败标志。
- `adapters/design_search.py` 和两CLI：支持 `--initial-design`，验证参数域/布局归属；
  给定初值先评价，探索参数上界组合，再用真实超限项提出离散邻域候选。
  可行后提出降档候选；上界或局部邻域失败不是布局无解的证明。
- `schemas/agent.py`、`workflows/optimization_env.py`：状态保存最优违反量与可行性；
  停滞判断使用相同排序，事件记录违反量变化。
- 材料计算：混凝土价格按同一2500 kg/m³换算；梁箍筋计算完整理想矩形周长；
  墙边缘纵筋与体积配箍按层高计量。此处只修正量纲/几何错误，没有更换规范限值。
  当前目标仅为既有单价下梁墙的理想化材料成本，缺少锚固搭接、弯钩、节点扣重、楼板配筋等。
- 同步迁移清单、README、上游契约、`docs/optimization_iteration.md` 和旧物理修正记录的当前指向。

### 测试与失败处理

先跑目标测试再跑全套。初次运行旧预算测试失败，因为它仍假定 `advance(1)` 会评价两批种群；
根据已确认的新语义改为第二代触发部分种群预算耗尽，并保留“不重启失败会话”的检查。
新增最后一批真实参与最优选择、小种群多样性、成本不能掩盖约束违反、给定初值与反馈邻域、
设计失败比例分辨率、价格密度一致性和钢筋几何工程量测试。
合成离散算例独立验证“得到可行点→降低材料目标→拒绝降档后的不可行点”，不冒充建筑效果。

不再要求修正后的GA/目标函数AST与错误的上游逐字一致，改以行为和解析反例验证；
未更改的局部校准器、FuseGNN与MVLEM构建器仍保留上游实现对照。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_search_feedback.py tests/unit/test_incremental_ga.py tests/unit/test_optimization_env.py
# 28 passed in 2.52s
.venv/Scripts/python.exe -m pytest -q tests/integration/test_casino_session.py --run-real
# 6 passed, 1 warning in 15.15s；真实权重+明确合成FEA，只证明会话/预算/隔离
.venv/Scripts/python.exe -m pytest -q
# 95 passed, 17 skipped, 1 warning in 7.70s
.venv/Scripts/python.exe -m pytest -q --run-real
# 112 passed, 8 warnings in 93.47s；0 failed，0 skipped
```

17 skipped 是默认需显式启用的本地测试，已在后一条命令全部执行；没有通过跳过失败获取通过。
8项warning仍为PyG、ezdxf/pyparsing弃用提示。当前分析指纹为
`e9b700f9321c8805556b77842da8c4c2fd3c1c45f57d0640719846e0686a8976`。

### 真实迭代与工件

默认工程图仍为 `configs/test_case.json` 的 `residential_001`，采用修正后的 `residential_001_rcgnn_02`。
条件沿用用户批准的28层等冒烟条件；未将图纸确认等同于正式荷载、规范条件确认。

```powershell
.venv/Scripts/python.exe -m struct_agent.agent_cli --layout outputs/residential_001_rcgnn_02/layout.json --rooms outputs/residential_001_rcgnn_02/room_graph.json --spec configs/reference_spec.json --initial-design outputs/physics_fix_inputs_01/design_baseline.json --run outputs/feedback_search_agent_01 --case-id residential_001 --purpose smoke_only --policy rules --seed 42 --budget-fea 6 --population 2 --generations 5
```

实际5代、6次FEA、全部SUCCESS，Agent预算用完后正常结束；所有候选仍不可行。
无代理筛选、无LLM API调用。求解/事件/种群/随机状态和初值输入均保留在该目录。

| 评价 | 约束违反量 | 梁墙理想材料成本 元 | 墙设计失败数 | 梁设计失败数 |
|---|---:|---:|---:|---:|
| 1 给定初值 | 2.065384 | 2325514.14 | 133 | 7 |
| 2 参数域上界探索 | 1.012978 | 5283727.10 | 6 | 0 |
| 3 | 0.969482 | 4070733.54 | 56 | 0 |
| 4 | 1.071525 | 4691420.36 | 15 | 0 |
| 5 当前排序最佳 | 0.938128 | 4327980.63 | 39 | 0 |
| 6 | 1.040018 | 4973478.95 | 6 | 0 |

第4/6次反而变差，仍完整保留，第5次作为当前最优；不是每次参数增大都改善。
初值到最佳违反量下降54.58%；最佳成本相对上界探索点降低18.09%，但高于原始不可行初值，
不能宣称已实现可行设计的材料节约，更不能据此证明Agent优于其他策略。
新反馈违反量只用于搜索，未改变任何校核通过标准，也没有忽略配筋失败。

独立诊断及核验：

- `outputs/member_diagnostics_{baseline,symmetry}_05/`：各1次真实FEA，更新材料汇总后的当前参考；
  力学失败结论与既有 `_04` 相同。测试已切换当前指纹，没有拿旧材料标签作当前参考。
- `outputs/feedback_search_inputs_01/`：从Agent摘要提取的最佳设计及来源哈希。
- `outputs/feedback_search_best_diagnostics_01/`：搜索后额外1次独立真实FEA，全部35字段对照通过；
  该调用单独记账，不计入前述6次搜索预算。墙剪压失败9项、梁35项，墙配筋失败39项、梁0项。
  控制墙 `shearwalls_2` 首层长0.1 m、厚0.3 m，利用率1.4231；
  控制次梁 `beams_40` 第4层长0.755 m、截面0.3×0.5 m，利用率1.5057。
- `outputs/feedback_search_verification_01/`：`verification.json`、全6次 `evaluations.csv`、
  `independent_parity.json` 与输入哈希。核验自身0次求解。

本轮建筑规模真实FEA总数10：当前双布局诊断2、全套测试独立普通入口对照1、Agent搜索6、
最佳独立诊断1。小型解析梁与真实权重/合成FEA的软件测试不计作设计搜索效果。
无失败求解被隐藏；没有追加训练或调用学校API。

### 未解决与下一最小任务

尚无满足全部现有校核的结构，当前终止只代表预算内流程完成。材料估算仍不是完整施工工程量。
剩余控制集中于极短墙段与短梁，仅调整8个全局参数未能解决；局部邻域穷尽也不能证明布局无解。
下一小任务应把最佳方案的构件诊断接入受控修复，先核实短墙是否应作为组合墙肢/边缘段建模和校核，
再形成可验证的局部截面或墙段调整操作；不通过放宽限值、漏检或无依据改分类获得“可行”。
旧代理权重与当前材料标签仍缺少兼容证据，继续禁用于真实筛选。正式策略对照和论文结论仍待验证。

## 2026-10-29：物理墙肢、短构件前处理及盈建科接口核查

### 发现与处理

用户明确指出应先满足要求再优化材料，成本高于不可行初值可以接受，并要求参照成熟软件处理极短墙梁。
本轮先读计划、路线、README和上游契约，分步修正建模语义，未重训/改权重、改真实图纸或编造工程条件。

查阅原厂资料和本机YJK-A手册后确认：分析网格、物理墙肢和配筋设计截面不是同一对象；
YJK有短墙归并/MPC处理、组合截面/柱式配筋和小跨高比连梁转壳元等不同机制。
本机手册模型转换章（PDF408页、印刷397页）明确列出180 mm短墙/网格归并与相邻构件重接。
这些属于软件技术处理，不当作所有工程的统一规范长度要求。详见 `docs/model_semantics.md`。

- 新增 `_vendor/shearwall_modeling/geometry/wall_piers.py`：
  共线且端点相接的墙段组成直墙肢，允许保留中间T节点；不跨洞口，不任意合并正交翼缘。
  保留全部原始单元和节点，每个源墙段只归属一个设计墙肢。
- `builders/base.py`、`mvlem_frame.py`：保存原始网格单元和物理墙肢两套映射。
  各基本工况、各阶振型都先在墙肢形心积分合力，再CQC/组合；绝不事后相加绝对值包络。
  `fea_diagnostics.py`、`fea_member_evidence.py`、诊断Schema新增源构件映射及 `wall_piers.json`。
  CASINO设计失败比例的分母同步改为物理墙肢数，而不是分析片段数。
- 修正之前没有依据的短墙转梁行为：`fem_builder.py` 和 `topology_cleanup.py` 两处代码均撤掉；
  预测墙保留墙类别。2 mm数值近点吸附保留，不能替代180 mm工程前处理。
- 新增 `services/model_review.py`：按物理墙肢前置审查；真实GA若存在未处理的180 mm及以下物理墙肢，
  保存 `geometry_review.json` 并在任何FEA之前阻断。长度/厚度小于4与梁段长高比小于2另列专项审查提示；
  梁的2仅是本地优先排查启发式，不是YJK转换阈值或规范判废线，详见模型语义文档。
- 小型真实构建测试暴露3层时中间分区为0层仍送入ModelConfig的问题，已剔除空分区。
  自重测试初始误把楼板自重重复加入；回读上游注释确认板自重已包含在dead_kpa，修正测试，未改荷载。
  同时在迁移副本恢复这条原注释，避免再误读质量源。

### 验证与当前工件

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_model_review.py tests/unit/test_topology_cleanup.py tests/unit/test_wall_piers.py tests/unit/test_fea_diagnostics.py tests/unit/test_search_feedback.py tests/integration/test_wall_pier_mechanics.py --run-real
# 32 passed in 3.14s
.venv/Scripts/python.exe -m pytest -q
# 106 passed, 17 skipped, 1 warning in 7.43s
.venv/Scripts/python.exe -m pytest -q --run-real
# 123 passed, 8 warnings in 88.73s；0 failed，0 skipped
```

新增反例包括T节点0.1+2.3 m直墙肢、反向/旋转墙段、洞口不合并、重叠段拒绝、节点与单元完整保留、
轴力移至新形心的弯矩、相反振型内力先抵消再CQC，以及前置拒绝不消耗真实分析预算。
新的小型真实OpenSees构建核验保留全部MVLEM单元、T节点、共享节点和质量；不是商业软件设计对比。
删去已主动修改的MVLEM builder与上游AST逐字一致断言，保留未修改算法检查并以真实拓扑/质量守恒替代。
17项默认跳过已在全套显式真实测试全部运行，8项warning仍为原有依赖弃用提示。

当前分析指纹：`a76e2b6fe9f51d9c41c90d46ae0ca66bc692271ba89795a96dd9ee180a46dfcf`。
固定既有结构输入独立复算（不是新生成流程已通过工程验算）：

| 工件 | 墙分析段→直墙肢 | 墙配筋失败 前→后 | 墙剪压失败 前→后 | 结构可行 |
|---|---:|---:|---:|---|
| `member_diagnostics_baseline_06` | 149→97 | 133→21 | 64→25 | 否 |
| `member_diagnostics_symmetry_06` | 187→121 | 506→266 | 159→72 | 否 |
| `feedback_search_best_diagnostics_02` | 149→97 | 39→0 | 9→4 | 否 |

三者均保留原图、参数、全部有限元网格和质量。整体周期/位移/扭转、梁检查与混凝土量在原容差内一致；
变化是墙肢合力和配筋计量对象纠错，没有漏掉源墙段或改通过限值。
上一轮参数候选仍有4项墙、35项梁剪压失败；控制墙长0.188 m、利用率1.0712，梁分析段长0.755 m、利用率1.5057。
梁0.755 m是分析段长，尚不能直接当作实际净跨。墙配筋0失败也不等同于柱式/组合截面验算完整。

真实命令：

```powershell
.venv/Scripts/python.exe -m struct_agent.diagnostics_cli --layout outputs/residential_001_rcgnn_02/layout.json --spec configs/reference_spec.json --design outputs/physics_fix_inputs_01/design_baseline.json --run outputs/member_diagnostics_baseline_06
.venv/Scripts/python.exe -m struct_agent.diagnostics_cli --layout outputs/residential_001_symmetry_03/layout.json --spec configs/reference_spec.json --design outputs/physics_fix_inputs_01/design_symmetry.json --run outputs/member_diagnostics_symmetry_06
.venv/Scripts/python.exe -m struct_agent.diagnostics_cli --layout outputs/residential_001_rcgnn_02/layout.json --spec configs/reference_spec.json --design outputs/feedback_search_inputs_01/best_design.json --run outputs/feedback_search_best_diagnostics_02
.venv/Scripts/python.exe -m struct_agent.cli generate --seed 42 --run outputs/residential_001_rcgnn_03
.venv/Scripts/python.exe -m struct_agent.agent_cli --layout outputs/residential_001_rcgnn_03/layout.json --rooms outputs/residential_001_rcgnn_03/room_graph.json --spec configs/reference_spec.json --run outputs/model_preflight_agent_01 --case-id residential_001 --purpose smoke_only --policy rules --seed 42 --budget-fea 2 --population 2 --generations 2
```

新生成162墙段、81梁、43板区；102个直墙肢中12个进入180 mm审查，不再声称已满足100 mm或工程最小墙长。
`model_preflight_agent_01` 运行到审查阻断，状态 `AWAITING_REVIEW`，真实FEA=0、API调用=0。
此状态表示当前缺少自动前处理工具，不是要求用户重新批准bug修复；下一步应将其接到受控模型修复分支。

本轮建筑规模真实计算总计5次：3次独立诊断，加首次120项全套与最终123项全套中各1次普通入口独立对照。
未隐藏失败数值；3层小型构建测试没有执行结构求解，不计设计预算。没有调用学校LLM API或训练模型。
核验在 `outputs/wall_pier_verification_01/verification.json`，自身0次FEA；核对全部源构件逐层覆盖及全局不变量。
手册提取、原厂API探测和固定输入几何审查位于 `outputs/wall_pier_review_01/`。

### 成熟后端的实际可用性与下一任务

本机注册表与安装目录已确认YJK 2025 V8.0.0，还发现SAP2000/ETABS安装。
YJK自带Python 3.10.11执行 `import YJKAPI` 返回 `YJK_API_IMPORT_OK`、exit=0；
没有调用初始化控制、创建项目、启动商业求解或读取授权文件，不能宣称YJK真实计算通过。
原厂入口声明和本机手册路径/哈希保存在 `configs/solver_inventory.json`。

下一最小任务：建立隔离目录中的受控YJK模型导出/读取，核对单位、楼层、梁墙板、荷载和ID映射，
再验证前处理与真实求解/配筋返回，形成对本地简化检查的工程参照。
仍未实现YJK的MPC/短墙归并、完整组合墙/柱式配筋和小跨高比梁壳模型，不继续将本地检查包装成成熟软件等价结果。
旧CASINO标签/权重不得跨新设计单位、几何或求解后端未经验证使用；真实工程条件和最终签审边界保持明确。

## 2026-10-29：YJK API能力核查、几何持久化与交叉验证计划

用户确认有可用加密狗、盈建科可正常使用。本轮仍属Phase 4的接口核查；未改分析/优化算法或模型权重。
已核实本机DataFunc建模/YDB写入、YJKSControl/UI命令控制、YJKSDsnDataPy结果查询的公开接口声明。
结果查询覆盖质量、周期、位移、墙柱标准内力与配筋等，但未将接口存在冒充真实读取通过。

实际在隔离目录做了当前住宅平面的一层几何探测：

- `_01`：内存201节点/243网格，CreateYDB返回true但落盘空库。只读核验发现问题；未隐藏失败。
  两次ReadYdb调用导致原生进程退出1，没有Python异常，不能当作读取成功。
- `_02`：检查出DataFunc需要DbModel_Assign提交；提交后DbModel含201节点/243网格，而PreModel为空。
  以PreModel尝试ReflectAndCreateYDB返回false，没有模型文件，保留结果。
- `_03`：提交后SetDbmodel(GetDbModelData())并CreateYDB，实际生成有数据的 `project/dtlmodel.ydb`。
  只读SQLite核对完整性、全部坐标、243条网格的连接关系和2900 mm层高均通过；记录哈希与平面原点。
  有效文件/目录两种ReadYdb参数仍引发原生退出1；原因未定，后续需核对SDK初始化/调用上下文。

工件分别为 `outputs/yjk_api_roundtrip_{01,02,03}/`，保留脚本、内存计数、返回值及失败记录。
最终核验是 `_03/database_verification.json`，读回失败为 `_03/readback_failures.json`。
这只证明几何骨架可持久化：梁/墙/板对象0，标准层1、楼层1；不是28层住宅工程模型，更没有商业求解结果。
本轮商业求解=0、额外OpenSees求解=0、学校API调用=0；没有更改用户现有工程或关闭其软件实例。

具体探测命令（工作目录为对应全新运行目录，已有目录不要复跑覆盖）：

```powershell
& 'D:/Softwares/YJKS_8_0_0/python310/python.exe' -u probe_worker.py
& 'D:/Softwares/YJKS_8_0_0/python310/python.exe' -u readback_worker.py
& 'D:/Softwares/YJKS_8_0_0/python310/python.exe' -u readback_dir_worker.py
```

更新 `configs/solver_inventory.json`：授权状态为USER_CONFIRMED_USABLE；几何导出局部验证通过，
完整模型导出、商业计算与分析结果读取未验证，模型API读回原生退出问题明确保留。
新增 `docs/yjk_cross_validation.md`，确定分层对照：实际模型/假定→基础力学/平衡→动力与构件响应→配筋/材料。
必须核对YJK前处理后的实际模型与截面，区分标准/调整/组合内力，先比所需配筋再比实配工程量；不预设统一误差百分比。
计划通过固定白名单Adapter和外部SDK进程接入Agent，保持主项目Python环境，捕获原生进程退出、超时及旧结果误读。

本轮只提交文档、能力清单与来源/哈希，无新增业务代码；实际几何文件是对应验证工件，不能算完整API调用链验收。
仓库回归 `.venv/Scripts/python.exe -m pytest -q`：106 passed、17 skipped、1 warning，9.54s。
17项为默认关闭的本地真实测试；本轮没有改计算代码，不重复执行建筑FEA，YJK探针单独按上述真实工件核验。
下一最小任务：解决模型读回上下文，补齐当前住宅的梁墙板截面、楼层和明确计算参数，再验证一轮前处理/求解/结果读取。

## 2026-10-29：Phase 4受控SDK进程、驱动更新后复测与宿主脚本核查

本次小任务只处理商业SDK进程边界和模型读取诊断，不改RC-GNN、CASINO、GA、物理组合或权重。
用户提供了yjks_pyload入口和旧analysis_runner.py路径；只读检查旧pipeline，未更改上游文件。

新增 `adapters/yjk_runtime.py` 与独立Python 3.10兼容 `yjk_read_worker.py`：
固定read_model操作、stdin请求、只读源库的一致性快照、新建不可覆盖目录、固定worker及超时；
保留stdout/stderr、原生退出码、父进程错误及worker故障栈，返回成功还需计数严格匹配。
不使用shell，不启动/附着/关闭GUI实例，不开放任意SDK命令或脚本。
成功仅表示SDK读取计数相符，不是完整模型或求解验收。
新增9项测试覆盖有符号/无符号原生退出、超时日志、零退出但缺失/错误/布尔计数、
合法合成响应、越权请求及外部文件拒绝、源文件不变与运行目录不可覆盖。

真实复测工件 `outputs/yjk_background_probe_{01,02,03}/`：
前两次分别核查ReadYdb和DbModel初始化，第三次经正式受控读取Adapter；
均在ReadYdb附近以0xC0000005退出。第三次native_fault.log明确记录worker中ReadYdb的access violation，
stdout表明SDK环境初始化成功后进入model_read。模型来源为 `yjk_api_roundtrip_03` 的几何骨架，
仍不包含梁墙板工程对象。不可据此定位为驱动问题，也不可宣称后台分析或商业结果已验证。
真实模型读回链路BLOCKED，完整模型/求解/结果提取未验证；本轮商业求解=0、OpenSees求解=0、学校API=0。

旧分析脚本依赖软件运行时，提供可追溯命令序列；但忽略命令返回和完成状态。
旧提取器会把缺失值替零、猜质量/位移角字段、去重接近周期，不能迁入作数值标签。
具体来源哈希、API状态和后续处理见 `docs/yjk_cross_validation.md` 与 `configs/solver_inventory.json`。
公开SDK声明存在ControlConfig.Invisible，不等于已验证隐藏宿主全链条；当前用户活动工程未被操作。

验证命令：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_yjk_runtime.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -c "from pathlib import Path; from struct_agent.adapters.yjk_runtime import YJKRuntimeConfig, probe_model_read; result=probe_model_read(Path('outputs/yjk_api_roundtrip_03/project/dtlmodel.ydb'), Path('outputs/yjk_background_probe_03'), YJKRuntimeConfig(install_root=Path('D:/Softwares/YJKS_8_0_0'))); print(result.model_dump_json(indent=2))"
```

目标测试9 passed，1.28s；全套115 passed、17 skipped、1 warning，8.86s。
17项仍为默认关闭的本地真实测试；合成子进程测试与上述真实SDK失败记录分开保存。
实际探针命令父进程正常保存PROCESS_ERROR结果，不等于子进程成功；不覆盖既有运行目录复跑。
下一最小任务：核实专用独立宿主的初始化与非交互加载脚本方式，解决模型读回，
再补全本例梁墙板/28层模型并检查本次分析完成和结果契约，随后开展数值交叉验证。

## 2026-10-29：Phase 4盈建科后台链路有限重试，按用户要求暂停

用户要求“再尝试一下，实在无法打通就算了”。本次只做受限诊断，不增加未验证的生产接口。
读取项目约定并核对厂商Gitee 8.0分支，通过公开API获得指定示例源码、blob ID和SHA256。
官方control.py确认Version="8.0.0"、Invisible=True可配置；link.py确认RunCmd三参数可传脚本路径和函数名，
不需要弹出文件选择框。来源存于 `outputs/yjk_final_attempt_01/official_sources.json`。

本机实际结果：

- `_01`：启动了专用隐藏宿主并建立IPC，命令报告Success，但没有回传文件；
  首次探针过早读取文件报FileNotFoundError，失败原样保留。
- `_02`：修正探针的等待，并避免依赖宿主中的__file__，新增隔离UINew调用。
  再次确认隐藏宿主和IPC可用，UINew仅报告Success；未生成可验证的完整工程文件。
  软件内Python在yjks_pyload入口输出路径原始字符串未终止的SyntaxError，随后有UTF-8编码错误。
  回传脚本的导入/函数标记均不存在，75s总运行上限后清理；不能将接口报告成功当成实际脚本执行。
- 官方案例6的kj.ydb只用于SDK运行时诊断，来源SHA256
  `9ff8ee766b51a2912572a0099d96fdc6a7de6326b3d5a8fbeb61a7d784448138`。
  `outputs/yjk_vendor_sample_read_01` 经现有Adapter仍在ReadYdb处0xC0000005退出。
  再按官方默认构造顺序并将cwd设为安装目录读取，同样退出；
  保存于 `_02/official_read_exact_outcome.json`。官方样例最终哈希未变。

监督进程仅清理由本次worker启动、匹配exe路径/PID/创建时间的宿主57892和61196；
未操作用户工程或原有启动器，结束确认无yjks进程。没有修改软件安装文件或上游仓库。
本轮商业求解=0、OpenSees求解=0、学校LLM调用=0；不产生论文数值结果。
已确认能力仅为隐藏宿主启动与IPC连接，脚本执行/完整建模/分析/结果提取仍BLOCKED。
详细原始错误、来源与判据见 `docs/yjk_cross_validation.md`；更新 `configs/solver_inventory.json`。
没有新增业务源码/依赖，不把失败探针迁入生产控制链。

实际命令（仅在已有工件所在目录记录，不覆盖复跑）：

```powershell
.venv/Scripts/python.exe outputs/yjk_final_attempt_01/host_supervisor.py
.venv/Scripts/python.exe outputs/yjk_final_attempt_02/host_supervisor.py
.venv/Scripts/python.exe -c "from pathlib import Path; from struct_agent.adapters.yjk_runtime import YJKRuntimeConfig, probe_model_read; result=probe_model_read(Path('outputs/yjk_final_attempt_02/vendor_sample_kj.ydb'), Path('outputs/yjk_vendor_sample_read_01'), YJKRuntimeConfig(install_root=Path('D:/Softwares/YJKS_8_0_0'))); print(result.model_dump_json(indent=2))"
.venv/Scripts/python.exe -m pytest -q tests/unit/test_yjk_runtime.py
.venv/Scripts/python.exe -m pytest -q
```

默认构造顺序的额外读取由主环境subprocess.run调用SDK Python，脚本为
`outputs/yjk_final_attempt_02/official_read_exact_worker.py`，cwd=`D:/Softwares/YJKS_8_0_0`，超时20s。
工件完整性摘要在 `_02/verification.json`。目标9 passed，1.29s；全套115 passed、17 skipped、1 warning，9.38s。
17项仍是默认关闭的本地真实测试，不包含本轮实际商业接口失败诊断。
按用户要求暂停后台自动接入，避免继续为未打通路线增加代码。
下一最小任务回到短墙/短梁几何修复与现有后端的确定性验证；盈建科人工交叉复核尚未开展，
自动接入待厂商可工作的运行环境/基线明确后再恢复，不作为主线继续推进的前置条件。
