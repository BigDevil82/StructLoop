# Phase 4：受控决策与真实优化反馈

本阶段把固定策略、规则策略和学校 LLM 接入同一个 `OptimizationEnvironment`。
决策动作只能是继续当前 CASINO 会话、提出切换预置布局、请求人工检查或结束运行。
LLM 不接收 shell 工具，不修改几何、预算、求解结果或审批记录。

## 学校 API

依据本地《人工智能服务平台使用指南.docx》，网关为 `https://agi.tongji.edu.cn/v1`。
2026-10-28 实测：使用系统代理返回 HTTP 403“当前网络环境不支持”；
通过 `urllib.request.ProxyHandler({})` 直连后模型列表与对话均成功。
实测可用模型包含 `DeepSeek-V4.1-Flash`，配置见 `configs/llm.json`。

`.env` 的 `apikey` 字段仅在请求内存中读取，不进入 manifest、请求审计或 Git。
同名进程环境变量优先；读取器不执行变量插值或 shell 命令。
默认 `use_system_proxy=false`，如确需代理可显式修改配置。
不跟随 HTTP 重定向；日志对密钥做脱敏。新增能力仅用 Python 标准库，无新依赖。

每次响应必须通过严格 JSON schema、动作白名单、候选 ID 和证据引用检查。
429/部分 5xx/网络超时最多按配置重试；403 不自动重试。
语义错误最多要求一次改正；仍失败则显式 `REQUEST_HUMAN_REVIEW`，不伪装成模型成功决策。
审计保留请求、最终回答、usage、错误类型/信息/traceback 和每次尝试，不保存模型私有推理文本。
token 为服务返回值；缺失 usage 单列，不能据此推定费用为零。

首次真实API探针使用明确标记的合成状态；该开发探针已清理，历史记录见Git提交ef2c915。实际LLM/FEA轨迹保留于 `outputs/archive/evidence_20261029.zip::phase4_real_llm_01/`。
模型合法返回人工检查，但把 `paused` 与 `engineering_review=PENDING` 误解为续作审批缺失。
提示词已明确：前者是正常代际边界；后者指最终工程交付审查，不阻止已授权的优化。
该问题及提示修正保存在Git历史中，原试算文件本次已清理。

## 真实运行

```powershell
.venv/Scripts/python.exe -m struct_agent.agent_cli --layout outputs/current/residential_001/layout.json --rooms outputs/current/residential_001/room_graph.json --spec configs/residential_12_story.json --run outputs/current/new_agent_run --case-id residential_001 --purpose smoke_only --policy llm --seed 42 --budget-fea 5 --population 3 --generations 2
```

上例使用当前12层输入；极短物理墙肢尚未消解时会在前置检查处阻断，不应切换旧布局跳过检查。
建模配置已固定，软件差异排查结束，见 `docs/final_model.md`。此处展示接口，历史调用流程测试不代表工程设计通过。

`--policy fixed|rules|llm` 使用相同评价服务、候选池与 CASINO 配置。
`--layout` 可重复指定有顺序的预置候选池；当前默认工程图只有一个既有 RC-GNN 方案。
`--purpose` 强制说明用途；旧28层条件只获准基本流程测试，后续另获准12层用于软件诊断；均非正式工程条件确认。
早期筛选阈值0用于暴露真实调用链，不表示CASINO效率设置；当前真实优化默认禁用未验证的代理权重。
一次决策推进一代，可能产生多次 FEA；共享服务在每次实际求解前检查总预算，含失败尝试。

继续动作保留同一会话。仅成功但不可行的反馈允许提出切换；求解/执行错误只能请求人工检查。
规则策略在停滞两步或当前会话完成时优先提议切换，固定策略永不切换。
停滞按“可行性→总违反量→目标值”严格比较：改善则清零，否则加一，不使用数值容差；这是公开的启发式，
不是已验证的科学优势。LLM 接收确定性状态、历史动作、预算及证据；尚未将其命名为论文 Ours。

切换后立即进入 `WAITING_APPROVAL`，不新增 FEA、不创建目标会话。
受信任应用必须调用 `approve_layout(layout_id, reviewer=..., expected_sha256=...)` 才能继续；
摘要提供待审批布局及其规范 JSON 哈希。新会话重新构建布局缓存和局部校准器。
此版本支持同进程审批与续作。CLI 可通过重复 `--layout-approval <json>` 指定操作方已有批准；
批准必须同时匹配布局、设计条件规范 JSON 哈希及用途，在实际切换提议后才应用，并记录事件。
没有匹配批准时 CLI 在待审批处退出；**不支持从磁盘恢复**，交互界面属下一阶段。

运行文件：`manifest.json`、`events/`、`analyses/`、`solver_logs/`、`sessions/`、
`api/`、`decisions/`、`summary.json`。事件记录动作前后状态、实际 FEA 增量和目标变化。
输出目录和各 JSON 不可覆盖。LLM 决策可用 `ReplayPolicy` 离线回放，要求状态哈希完全一致；
它是决策回放，不是物理会话的磁盘恢复。

## 对照及验证

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_llm_policy.py tests/unit/test_optimization_env.py tests/unit/test_comparison.py
.venv/Scripts/python.exe -m pytest -q tests/integration/test_casino_session.py --run-real
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m struct_agent.evaluation.compare --run outputs/current/fixed_run --run outputs/current/llm_run --out outputs/comparison.json
```

比较器要求案例、候选顺序、种子、预算、停止上限、优化配置、软件与代码哈希一致；
策略名和 LLM 配置是允许差异。失败案例保留，无可行解的成本为 `null`，不填零或代理估值。
相同预算上限不要求各策略实际耗尽预算。开发过程中代码版本不同的基本流程测试不能混作严格对照。

普通单元测试使用 stub；显式 FuseGNN 集成测试使用真实权重但合成 FEA，标记 `mock`。
真正工程证据只来自 `fidelity=full` 的 OpenSees 记录。基本流程测试仅验证调用与决策路径，不证明工程可行或策略优越。

## 尚未完成的研究验收

- 新图正式工程条件及规范口径尚待工程师确定；现有条件仅获准基本流程测试。
- 用户已批准 `outputs/archive/evidence_20261029.zip::residential_001_symmetry_02/` 的上游 union 对称化候选仅作基本流程测试，
  批准文件为该目录 `user_approval.json`；历史轨迹保存在同一归档，验证命令见上文。
- 论文 Ours 的动作收益模型、对比假设、消融口径与多种子实验尚未定义并验证。
- 人工审批界面、磁盘恢复、DWG/报告输出分别按后续阶段推进。
