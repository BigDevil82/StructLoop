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
