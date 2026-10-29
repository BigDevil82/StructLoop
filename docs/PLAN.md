# PLAN.md — 住宅建筑结构智能设计 Agent：本地工程执行规范

> 2026-10-29用户更新：相关验证按批次推进，尽快进入结构层面；跨软件同条件响应的相对差异小于5%即通过，
> 不再对通过项追加核查或校准。统一分母为ETABS响应绝对值，等于5%及以上单列处理。
> 本条替代早期“逐小任务交付”和“不设统一跨软件阈值”的执行口径；已保存的历史数值和当时结论保留原样。

> 2026-10-28 用户执行规则更新：已发现的实现 bug 直接按正确逻辑修复，无需重复确认，不保留错误算法的旧版运行分支。
> 仍须记录依据与验证、区分真实/mock，工程最终审查及未提供的工程条件独立处理。详见 AGENTS.md 第 7 条。

> 状态：v0.1 / 探索性设计。本文是本地 Codex 的项目级执行契约，不是已经验证的论文结论。与 `RESEARCH_ROADMAP.md` 配合使用：前者管**怎么实现与验证**，后者管**为什么研究与如何演进**。  
> 优先级：**真实物理闭环 > 可复现实验 > Agent 决策研究 > DWG/报告等产品能力**。任何未核实的现有算法接口不得假定为事实。

## 1. 研究目标与问题数学定义

### 1.1 一句话核心任务

给定住宅建筑空间信息与工程设计条件，使用 **RC-GNN 生成剪力墙布置、CASINO 辅助固定布置下的参数优化、FEA 提供真实反馈**，由上层决策 Agent 判断继续参数优化还是切换布置方案，在有限分析预算内找到可验证的高质量可行设计，并支持工程师确认和成果交付。

**研究范围**：聚焦住宅建筑剪力墙结构的布置—参数协同；建筑平面本身不生成。优先以单个标准层、与现有 RC-GNN/CASINO 数据分布一致的算例验证；完整多层、DWG、跨软件、施工图为扩展。不得将图像/文本评价冒充结构验算。

### 1.2 数学定义及约束

- 建筑/房间图：$G=(V,E,X,P)$；$N=|V|$，$E$ 为房间关系边数，$X\in\mathbb{R}^{N\times F_R}$ 为节点特征，$P\in\mathbb{R}^{N\times2}$ 为平面位置（m），`edge_index` 形状 `[2,E]`。**$F_R$、边特征、图构建口径必须从现有 RC-GNN checkpoint/代码核实**。`[TODO: 待确认]`
- 设计条件：$c$，包括楼层/层高、结构体系、材料、荷载/设防参数、规范版本、允许的参数范围及目标；缺项标记为 `MISSING`，不得由 LLM 悄悄补齐。
- 布置方案：$L\in\mathcal L(G,c)$。统一几何表示可采用墙线端点 `wall_segments: [M,2,2]`（m）及墙体属性/楼层索引；**此为系统交换格式，并非断言 RC-GNN 的原生输出形态**。
- 参数向量：$x\in\mathcal X(L,c)$，长度 $D$ 随算例/参数分组变化，例如墙厚、截面与已有模型支持的配筋参数；必须以带名称、单位、上下界、离散选项的 `design_variables` 定义，不硬编码 $D$。`[TODO: 待确认：CASINO 当前可优化的真实变量及编码]`
- 分析器：$y=\mathcal F(L,x,c)$，返回结构响应、校核指标与求解状态。各上限型工程约束统一为 $g_j=y_j/y_{j,\lim}-1\leq0$；下限/双侧约束在校核适配器中显式转换，保留原始数值、单位、限值及规范来源。不得把 `SOLVER_ERROR` 当成结构不满足约束。
- 优化目标：在所有必要约束满足时，最小化 $J(L,x;c)$（优先材料量或造价，口径统一）；在预算 $B_{FEA}$ 内获得可行方案：

  $$\min_{L,x}\ J(L,x;c),\quad \mathrm{s.t.}\ g_j(L,x;c)\leq0\ (\forall j),\ N_{FEA}\leq B_{FEA}.$$

- 不满足强制几何、构造或规范规则的候选不得被标注为 `FEASIBLE`。最终交付须有真实分析结果和人工审查状态；工程师对最终工程成果负责。

### 1.3 Agent 状态与动作

- 最小状态：`s_t = {case_id, current_layout_id, current_design_id, constraint_ratios, solver_status, best_feasible_cost, optimization_progress, action_history, fea_calls_used, fea_budget_remaining, approvals}`。保留具体受控版本，不靠聊天历史重建。
- MVP 动作：`CONTINUE_OPTIMIZATION`（固定布置继续 CASINO+优化器）、`SWITCH_LAYOUT`（切换/重新生成候选 RC-GNN 布置）、`REPAIR_MODEL`（仅处理建模/求解异常）、`REQUEST_HUMAN_REVIEW`、`FINALIZE`。
- `SWITCH_LAYOUT` 不隐含“LLM可以精确移动某片墙”。局部墙体编辑为后续扩展动作，须具备确定性几何操作与合法性校核。
- 每个动作产生 `{action, reason, evidence_refs, cost_estimate, approval_required}`；执行后写入**真实**性能变化与分析资源消耗。有限预算、动作可行条件和人工确认由确定性状态机强制执行。
- **待验证的候选决策原型**：先用规则过滤不合法动作，再按 `score(a)=α·预计约束改善 + β·预计可行概率提升 − γ·预计材料增量 − λ·预计FEA成本` 排序；预期量由历史同类动作、小规模试探或保守默认值估计，并记录不确定性。它只是第一版可复现的工程启发式，**不预先宣称为创新算法**。`[TODO: 待确认：收益估计方法和权重标定]`

### 1.4 输入/输出与成功判据

- **MVP 输入**：已清洗的建筑房间图、设计条件、现有 RC-GNN/CASINO 权重与配置、一个真实 FEA 后端；不要求先处理 DWG。
- **最终输入**：建筑 `.dwg`、工程师自然语言需求、经确认的建筑/结构设计约束与必要补充资料。
- **核心输出**：可行的布置 $L^*$ 与参数 $x^*$、分析模型、真实 FEA 和约束验算结果、完整执行轨迹、优化比较结果；后期增加结构 DWG、设计报告与可选施工图导出。
- **最小科研成功**：至少跑通一个**真实** RC-GNN→CASINO→FEA→状态更新→二次决策→再次评价的闭环，并能在等预算条件下与固定工作流比较。Mock 闭环只证明工程软件链路无误，不证明研究假设成立。

## 2. 本地仓库目录结构设计

```text
project_root/
├── PLAN.md                         # 本文件：接口、阶段、验收纪律
├── RESEARCH_ROADMAP.md             # 研究故事线、长期路线
├── pyproject.toml                   # Python 包、开发依赖和 CLI 入口
├── README.md                        # 安装、环境、复现实验说明
├── .env.example                     # 仅字段名；不提交密钥
├── configs/
│   ├── base.yaml                    # 单位、路径、日志、预算及公共设置
│   ├── models.yaml                  # RC-GNN / CASINO 路径与原始参数映射
│   ├── solvers/                     # mock / 主 FEA / 其他适配器
│   ├── policies/                    # fixed / rules / llm / proposed / ablations
│   └── experiments/                 # 数据划分、种子、预算、指标
├── data/
│   ├── raw/                         # 原始 DWG/模型/数据；只读，默认 Git 忽略
│   ├── interim/                     # 建筑语义解析及图预处理
│   ├── processed/                   # 标准化 graph、设计条件、候选库
│   └── examples/toy_01/            # 无商业软件依赖的最小测试算例
├── checkpoints/                     # 外部模型权重：记录版本，不提交大文件
├── src/struct_agent/
│   ├── schemas/                     # project.py, graph.py, layout.py, analysis.py, state.py
│   ├── io/                          # load_case.py, cad_parser.py, normalize.py, artifact_store.py
│   ├── models/                      # RC-GNN / CASINO 封装；不复制训练工程
│   ├── adapters/                    # rcgnn.py, casino.py, fea/{base,mock,real}.py
│   ├── services/                    # layout.py, optimization.py, analysis.py, reporting.py
│   ├── envs/design_env.py           # 状态转移、动作合法性、预算/审批控制
│   ├── agents/                      # scripted_policy.py, fixed_policy.py, rule_policy.py, llm_policy.py, proposed.py
│   ├── workflows/                   # runner.py, approval.py, state_machine.py
│   ├── evaluation/                  # metrics.py, compare.py, ablation.py
│   └── cli.py                       # run-case, evaluate, report 等 CLI
├── scripts/
│   ├── audit_upstream.py            # 盘点现有 RC-GNN/CASINO/FEA 实际接口
│   ├── make_dummy_case.py           # 最小合成数据，不用于论文性能结论
│   ├── run_case.py                  # CLI 的薄封装（可选）
│   ├── run_benchmark.py             # 多案例/多种子批量实验
│   └── make_figures.py              # 从原始实验结果生成论文图表
├── tests/
│   ├── unit/                        # schema、约束、预算、状态机
│   ├── integration/                 # adapters + workflow；mock 可在 CI 跑
│   ├── regression/                  # 已知案例与真实求解结果快照
│   └── fixtures/                    # 小图、小布局、mock FEA 响应
├── outputs/                         # 每次运行独立目录：工件、日志、表格、图片
└── docs/                            # 字段字典、模型契约审计、软件能力矩阵
```

**管理原则**：`data/raw` 与上游模型仓库保持只读；研究代码只通过 Adapter 调用它们。一次运行一个 `run_id`，将输入哈希、Git commit、配置快照、模型权重版本、软件版本、随机种子写入 `outputs/<run_id>/manifest.json`。大型权重和商业数据不进 Git。

## 3. 数据流与核心模块接口规范

### 3.1 数据契约（先定交换格式，再写业务代码）

| 数据对象 | 建议文件 | 必需内容及形状 / 约束 |
|---|---|---|
| `ProjectSpec` | `case.json` | `case_id`、条件 `c`、工程单位、设计目标、所有约束的数值/单位/依据、楼层信息、必要人工确认字段 |
| `RoomGraph` | `room_graph.pt` + `graph_meta.json` | `x:[N,F_R]`、`edge_index:[2,E]`、`pos:[N,2]`（m）；可选 `edge_attr:[E,F_E]`、mask；特征列顺序和来源写入元数据 |
| `LayoutCandidate` | `layouts/<layout_id>.json` | `layout_id`、`source`、`wall_segments:[M,2,2]`、楼层/墙类型/构造属性、几何检查、原始模型输出引用 |
| `DesignCandidate` | `designs/<design_id>.json` | `layout_id`、有名称和单位的设计变量字典、设计材料量/造价、对应分析记录 ID |
| `FEAResult` | `analyses/<eval_id>.json` | `status`、`solver`、`solver_version`、`model_hash`、工况、原始响应、`checks:{name,value,limit,ratio,passed}`、耗时、错误说明 |
| `DecisionEvent` | `events.jsonl` | 决策前状态摘要、候选动作、选中动作、理由、证据、审批、实际效果、预算前后值 |
| `RunSummary` | `summary.json` + `metrics.csv` | 最终可行性、最优可行成本、FEA数、总耗时、LLM消耗、人工介入、失败分类、文件引用 |

- **内部规范单位**：长度 `m`，力 `kN`，应力 `MPa`，材料体积 `m³`；金额明确币种。DWG常见 `mm` 与软件自有单位在适配边界转换，所有转换写测试。
- **图 Batch**：单样本 `x:[N,F_R]`、`edge_index:[2,E]`；若模型依赖 PyG，则多图 `Batch.x:[ΣN,F_R]`、`Batch.edge_index:[2,ΣE]`、`Batch.batch:[ΣN]`。具体额外字段以现有 RC-GNN 为准；若不是 PyG 模型，Adapter 内转换，不强制修改上游。
- **CASINO 输入**：遵守现有 FuseGNN/优化管线真实契约（房间图、布置统计、设计参数与设计条件）；`F_C` 和 $D$ 均从现有实现读取。不得凭空假定可跨布局复用在线局部校准器。**每个 `(layout_id, condition_id)` 使用隔离的校准缓冲区**。
- **FEA 语义**：`status∈{SUCCESS, MODEL_ERROR, SOLVER_ERROR, TIMEOUT, INVALID_RESULT}`；仅 `SUCCESS` 且必要检查齐全时可计算 `feasible`。预估/代理结果必须标为 `PREDICTED`，不能冒充真实 FEA。
- **输入安全**：`*.pt`/checkpoint 只加载受信任的本地文件；不信任的外部文件不做任意反序列化或执行。所有 Agent 生成的脚本必须经过许可清单和受控执行环境。

### 3.2 五个核心模块及接口（Python 伪签名，供实现时落为类型化 Schema）

```python
from pathlib import Path
from typing import Literal, Protocol

class ProjectIO(Protocol):
    def load_case(self, case_dir: Path) -> ProjectSpec: ...
    def preprocess_dwg(self, dwg: Path, spec: ProjectSpec) -> RoomGraph: ...
    # 第二个接口在 DWG 扩展阶段才实现；前期使用已准备的 graph。

class LayoutService(Protocol):
    def generate(self, graph: RoomGraph, spec: ProjectSpec,
                 n_candidates: int, seed: int) -> list[LayoutCandidate]: ...
    def validate(self, layout: LayoutCandidate, spec: ProjectSpec) -> LayoutValidation: ...

class AnalysisService(Protocol):
    def evaluate(self, layout: LayoutCandidate, design: DesignCandidate,
                 spec: ProjectSpec, fidelity: Literal['mock', 'full']) -> FEAResult: ...
    # 负责统一调用记账、校验结果及缓存；分析失败单独记录。

class OptimizationService(Protocol):
    def optimize(self, layout: LayoutCandidate, spec: ProjectSpec,
                 evaluator: AnalysisService, fea_budget: int,
                 seed: int, previous: OptimizationState | None = None
                 ) -> OptimizationResult: ...
    # 封装现有优化器 + CASINO 筛选/排序/在线校准；真实 FEA 全部经 evaluator 记账。

class DecisionPolicy(Protocol):
    def choose_action(self, state: DesignState,
                      allowed_actions: list[str]) -> Decision: ...
    # 无权直接调用 FEA、改数据库或越过人工确认；仅返回决策提案。
```

**编排责任**：`DesignEnv` 验证决策合法性、消耗预算、执行审批门控并更新状态；`WorkflowRunner` 串联上述五个模块，支持暂停/恢复和失败重试。`ReportingService` 读取不可变工件生成报告，不参与力学计算。

### 3.3 单次状态转移与数据流

```text
ProjectSpec + RoomGraph
  └─ LayoutService → LayoutPool (候选/有效性/工程师批准)
       └─ OptimizationService(CASINO + 优化器)
            └─ AnalysisService(FEA / 工程约束 / 计算记账)
                 └─ DesignState 更新（性能、失败类型、历史、预算）
                      └─ DecisionPolicy → 提议动作
                           └─ DesignEnv 校验/审批 → 执行/回退/终止
                                └─ artifacts + summary + report
```

**重要约束**：如果 RC-GNN 只有确定性单方案预测能力，不得伪造“多候选采样”；先使用可重现的候选布局库、已有模型支持的不同有效条件，或工程师提交的备选方案。`[TODO: 待确认：RC-GNN 的候选多样化能力]`。优化阶段产生的所有 FEA 调用（含CASINO校准与复核）统一计费；最终独立验证另行标记，并在实验中对所有方法采用同一口径。

## 4. 渐进式开发里程碑（Codex 必须逐 Phase 验收）

> 以下命令定义**待实现的项目 CLI 和测试入口**，不是声称现在已经可运行。每个 Phase 先提交最小代码，再实现对应测试；不能因商业软件缺席而伪造真实通过。阶段结束记录 `docs/progress.md`（完成项、运行命令、测试结果、阻塞项）。

### Phase 0 — 上游能力审计与环境基线

- **任务**：创建 `pyproject.toml`、`README.md`、`configs/base.yaml`、`scripts/audit_upstream.py`、`docs/upstream_contracts.md`。核实 RC-GNN 的输入输出/特征、候选生成方式、checkpoint；CASINO 的设计变量、优化器、FEA校准调用；现有FEA接口及授权。**只读取现有仓库，不更改论文算法或权重。**
- **验证命令**：`python scripts/audit_upstream.py --output docs/upstream_contracts.md`；`python -m pytest -q tests/unit/test_upstream_contracts.py`。
- **通过标准**：能生成接口盘点表和明确的 `KNOWN/UNKNOWN/BLOCKED` 清单；被发现的维度/接口均有代码路径或模型配置证据。缺乏权重或软件时标为阻塞，不填写虚构值。

### Phase 1 — 统一 Schema、单位与最小数据集

- **任务**：实现 `schemas/{project,graph,layout,analysis,state}.py`、`io/{load_case,artifact_store}.py`、`scripts/make_dummy_case.py`；建立 `toy_01`（例如4房间、2种合法候选布置、少量设计变量及约束），与真实模型维度分开标注。
- **验证命令**：`python scripts/make_dummy_case.py --out data/examples/toy_01`；`python -m pytest -q tests/unit/test_schemas.py tests/unit/test_units.py`。
- **通过标准**：JSON/graph 保存—加载一致；缺失单位、非法 `edge_index`、不合法墙线/校核结果被拒绝；无真实模型也可运行。

### Phase 2 — Mock 物理闭环与状态机

- **任务**：实现 `adapters/fea/mock.py`、`envs/design_env.py`、`workflows/{runner,state_machine,approval}.py`、`agents/{scripted_policy,fixed_policy}.py`；Mock FEA 为确定性函数，设置可预测的“某布局不可行、切换后可行”场景。
- **验证命令**：`python -m struct_agent.cli run-case --case data/examples/toy_01 --solver mock --policy scripted --budget-fea 10`；`python -m pytest -q tests/integration/test_mock_workflow.py`。
- **通过标准**：生成 `manifest.json`、`events.jsonl`、`summary.json`；可模拟“优化→评价→继续/切换→终止”；预算不超支；求解错误不会被计作结构不安全；重跑同一种子轨迹一致。

### Phase 3 — 真实 RC-GNN / CASINO / FEA 适配与最小实证闭环

- **任务**：实现 `adapters/{rcgnn,casino}.py`、`adapters/fea/real.py`、`services/{layout,optimization,analysis}.py`；复用上游模型与现有分析程序，建立一套**已知正确的单算例回归基准**。优化器和CASINO的FEA调用统一穿过 `AnalysisService`。
- **验证命令**：`python -m pytest -q tests/integration/test_real_adapters.py -m real`；`python -m struct_agent.cli run-case --case data/processed/case_001 --solver real --policy scripted --budget-fea 20`。
- **通过标准**：在具备权重/求解器的机器上，RC-GNN输出能转换为合法候选，CASINO调用真实FEA并取得有效校核数据；存在**一次真实评价后的明确续作（继续优化或更换预置布局）与二次真实评价**；关键结构计算与上游已验证脚本一致。若未接入真实FEA，则 **Phase 3 未完成**。
- **待确认**：`[TODO: 待确认：真实 solver 首选、许可证/接口、一次求解耗时、FEA覆盖的校核项、优化预算最小规模]`。

### Phase 4 — 决策策略与双层协同实验

- **任务**：实现 `agents/{rule_policy,llm_policy,proposed}.py`、`evaluation/metrics.py`；先用规则策略跑通 `CONTINUE_OPTIMIZATION` 与 `SWITCH_LAYOUT`，再接入基础LLM策略与拟研究的状态/历史/预算感知策略。加入动作后实际收益记录和状态回放。
- **验证命令**：`python -m pytest -q tests/unit/test_policy.py tests/integration/test_decision_loop.py`；`python -m struct_agent.cli run-case --case data/processed/case_001 --solver real --policy rules --budget-fea 20`。
- **通过标准**：各策略共享相同候选集、评价器和预算；能复现一次“固定布置继续优化”和一次“切换布局”路径，决策证据可追踪；`REPAIR_MODEL` 与 `SWITCH_LAYOUT` 不混淆。

### Phase 5 — Agent 交互与 Human-in-the-Loop

- **任务**：实现 `agents/llm_policy.py` 的结构化输入/输出和拒绝非法动作机制，`workflows/approval.py` 的暂停/批准/拒绝/恢复；将人工修改作为新版本 `LayoutCandidate` 写回状态。LLM只提出策略，不直接修改分析器的结果。
- **验证命令**：`python -m pytest -q tests/unit/test_approval.py tests/integration/test_llm_stub.py`；用固定的 Fake LLM 响应测试非法JSON、空指令、越权操作、审批拒绝和恢复。
- **通过标准**：不依赖在线LLM也能测试；待审批时不会继续调用真实求解器；批准后可恢复；人改方案/Agent结果都有完整审计记录。

### Phase 6 — 基线、消融与规模化复现实验

- **任务**：实现 `scripts/run_benchmark.py`、`evaluation/{compare,ablation}.py`、`scripts/make_figures.py`、`configs/experiments/*.yaml`。统一案例清单、预算、种子、停止准则与可行性判定，生成失败案例分析。
- **验证命令**：`python scripts/run_benchmark.py --config configs/experiments/pilot.yaml --dry-run`；`python scripts/run_benchmark.py --config configs/experiments/pilot.yaml`；`python -m pytest -q tests/unit/test_metrics.py tests/integration/test_replay.py`。
- **通过标准**：可从运行原始记录重算每个指标，重跑同配置可复现（含明确记录的LLM随机波动）；同预算下基线与Ours得到可比结果；至少完成小规模 pilot 后再扩大样本。

### Phase 7 — DWG、完整分析模型与成果交付（后置扩展）

- **任务**：实现 `io/{cad_parser,normalize}.py`、`services/reporting.py`、基础结构DWG导出；增加 `docs/solver_capability_matrix.md`，评估 ETABS/SAP2000/YJK/PKPM/OpenSees 的实际可用接口，先接通一个后端再扩展。
- **验证命令**：`python -m pytest -q tests/integration/test_dwg_roundtrip.py tests/integration/test_report.py`；`python -m struct_agent.cli report --run outputs/<run_id>`。
- **通过标准**：可核对几何尺寸、楼层与墙体数量的 DWG→标准模型→DWG 往返一致性；报告每个关键数值可追溯至真实 `FEAResult`；无法自动出具的配筋/施工图内容明确标记未覆盖，不伪装完成。

## 5. 实验设计与评估矩阵

### 5.1 对比方法（共用输入、候选能力、分析器与预算）

| ID | 方法 | 作用 |
|---|---|---|
| B0 | 固定流程：一个RC-GNN布置 + 预设CASINO优化 | 基础下限；不允许切换布局 |
| B1 | 固定预算重启：等预算探索预定数量的候选布局 | 排除“只是尝试更多布局”的收益 |
| B2 | 工程规则驱动：按预设停滞/约束阈值切换层级 | 检验LLM是否真优于合理规则 |
| B3 | 基础LLM Agent：相同工具/状态，直接Prompt决策 | 检验显式工程状态/历史机制的增益 |
| Ours | 工程状态 + 历史效果 + 预算感知的分层决策 | 待提出/待验证的研究方法 |

**公平性**：同案例、输入、候选布局池、设计变量上下界、求解器版本、停止准则、FEA预算；按案例配对和多种子统计。所有高保真FEA（含代理校准及最终复核）均明确记账，若某环节独立计费须在各方法一致处理。不得仅对成功算例取均值而忽略失败案例。

### 5.2 主要指标与计算口径

- **可行成功率**：`SR = #在预算内获得全部必要约束通过且真实FEA成功的案例 / #全部案例`。
- **最优可行目标**：`J_best(b)=min{J_i | 第i个真实FEA可行, FEAs_used_i≤b}`；无可行解记 `NA`，单独统计成功率，不能偷偷替换为代理预测值。
- **约束违反程度**：`V = Σ_j w_j * max(0, g_j)`（仅对计算成功且有完整结果者）；模型/求解失败单列错误指标。
- **FEA与总成本**：真实调用次数（含失败尝试单列）、计算墙钟时间、Agent token/API费用、人工操作耗时；比较时优先绘制 `J_best` / `SR` 对累计FEA预算的曲线。
- **决策效率**：无效动作比例（动作后未改善可行性/目标且没有信息增益的比例；判定规则须预先固定）、重复切换次数、恢复成功率、人工确认次数。
- **统计展示**：每种策略/案例至少多次随机试验，报告中位数、四分位区间或置信区间；试验次数由 pilot 与算力决定。`[TODO: 待确认：正式案例数、预算档位、随机种子数]`

### 5.3 消融配置开关（YAML，不准硬编码）

```yaml
policy:
  name: proposed   # scripted(仅测试) | fixed | fixed_restart | rules | llm | proposed
  use_engineering_features: true
  use_action_history: true
  use_budget_awareness: true
  allow_layout_switch: true
  use_action_value_estimate: false  # 如后续提出收益估计器再开启
  llm_enabled: false                # 无网络可跑离线策略
experiment:
  fea_budget: 20
  candidate_pool_mode: predefined  # predefined | rcgnn_generated
  seed: 42
  final_validation_counted: true
human_review:
  required_for_layout_change: true # 正式工程模式强制；模拟消融不得绕过安全门控
```

最小消融：`-engineering_features`、`-history`、`-budget_awareness`、`-layout_switch`；如增加候选动作收益估计器，再比较 `±action_value_estimate`。`human_review` 属于系统安全策略，不以关闭审批换取“效率提升”。

**论文图表预留**：框架总览图；状态—动作反馈图；典型剪力墙布局/截面前后对比；`SR/J_best`—FEA预算曲线；基线统计表；消融表；典型成功与失败轨迹图。所有图由 `outputs/` 原始记录重建。

## 6. 给 AI 编码代理（Codex）的全局规范


---

**当前第一任务（交给 Codex）**：执行 **Phase 0**。盘点本地 RC-GNN、CASINO、FEA 仓库的真实输入输出及依赖，产出 `docs/upstream_contracts.md`；只完成必要环境和接口骨架，不要立即开发DWG、多Agent对话UI或跨软件适配。**验证后再进入 Phase 1。**
