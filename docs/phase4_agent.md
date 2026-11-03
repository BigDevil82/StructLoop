# Phase 4：受控决策与真实优化反馈

本阶段把固定策略、规则策略和学校 LLM 接入同一个 `OptimizationEnvironment`。
决策动作包括继续当前 CASINO 会话、选择受建筑约束的局部候选、提出切换预置布局、请求人工检查或结束运行。
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
启用局部调整且存在合法候选时，规则策略先试一个局部候选；否则在停滞两步或当前会话完成时提议切换预置布局。固定策略只做固定布局参数优化。
停滞按“可行性→总违反量→目标值”严格比较：改善则清零，否则加一，不使用数值容差；这是公开的启发式，
不是已验证的科学优势。LLM 接收确定性状态、历史动作、预算及证据；尚未将其命名为论文 Ours。

切换后立即进入 `WAITING_APPROVAL`，不新增 FEA、不创建目标会话。
受信任应用必须调用 `approve_layout(layout_id, reviewer=..., expected_sha256=...)` 才能继续；
摘要提供待审批布局及其规范 JSON 哈希。新会话重新构建布局缓存和局部校准器。
此版本支持同进程审批与续作。CLI 可通过重复 `--layout-approval <json>` 指定操作方已有批准；
批准必须同时匹配布局、设计条件规范 JSON 哈希及用途，在实际切换提议后才应用，并记录事件。
没有匹配批准时 CLI 在待审批处退出；**不支持从磁盘恢复**，交互界面属下一阶段。

## 局部布局调整

运行入口显式增加`--enable-local-adjustment`，授权当前输入与预算内的局部试验。
该授权绑定根布局、房间图、设计条件和移动规则，写入`local/authorization.json`；LLM不能生成或修改授权。
候选只沿原轴线移动墙梁共同端点，保持全部构件类别，受门窗禁布区、相邻房间限制、支路连接、残余长度和指定保护构件约束。
墙梁类别转换继续只用于前处理修错，不进入动作空间。

参数：`--local-step-m 0.1 0.2`指定移动量（m）；`--local-max-candidates 4`限制每份反馈的候选数；
`--local-max-trials 4`限制本次运行的局部试验次数；`--protect-member <ID>`可重复指定禁止调整的构件。
默认`--local-target-utilization 1.0`只处理受剪超限/墙配筋失败；低于1时尝试增加余量，不改变验算限值。
所有试验还受总`--budget-fea`约束，失败也计数；相同几何和参数不因更换布局ID而重复试算。

`ADJUST_LOCAL_LAYOUT`必须将`target_layout_id`指向状态中`local_layout_choices`的一个`candidate_id`。
策略看到控制构件、楼层、指标利用率、移动量、候选理由、当前整体指标与历次试验效果，不接收可执行代码或坐标编辑接口。
执行前重新校验布局/房间图哈希、建筑约束和连接；每次只试一个候选，完成真实FEA后才返回策略重新决策。
按现有“整体可行性→违反量→材料成本”排序，严格改善才采纳；变差或失败保留当前方案，候选结果与原始错误照常记录。
局部改善可能转移控制位置，状态中的`local_adjustment_history`保留控制构件及全结构梁最大利用率前后值，策略可据新反馈继续选择。

传入`--initial-design`时，先单独复算该设计一次，让策略先读真实反馈，避免必须先完成一代GA才能考虑布局调整。
需要继续CASINO时，为当前新布局创建独立会话，以该布局自己已验算的设计作为起点；不复制其他布局的种群、缓存或局部校准器。
已有预置布局的`SWITCH_LAYOUT`仍按上节进入审批；本节的受控局部试验由入口开关和确定性检查授权，不产生工程签审结论。

局部轨迹保存在`local/proposals_eval_*.json`、`local/trial_*.json`及`events/`；每步记录是否采纳、真实预算增量、整体指标变化和材料成本。
未启用该开关时维持原工作流。规则与LLM可选择局部动作；固定策略不选择该动作。

`FINALIZE`只结束优化计算并保存结果，工程审查状态仍为Pending；已有可行设计且预算耗尽时可以直接结束计算。
真实试验中模型曾把两者混淆而请求复核，现已明确收尾含义，并用相同末态的真实API复判验证，保留原始轨迹。

运行文件：`manifest.json`、`events/`、`analyses/`、`solver_logs/`、`sessions/`、
`api/`、`decisions/`、`summary.json`。事件记录动作前后状态、实际 FEA 增量和目标变化。
输出目录和各 JSON 不可覆盖。LLM 决策可用 `ReplayPolicy` 离线回放，要求状态哈希完全一致；
它是决策回放，不是物理会话的磁盘恢复。

## 对照及验证

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_llm_policy.py tests/unit/test_optimization_env.py tests/unit/test_comparison.py
.venv/Scripts/python.exe -m pytest -q --run-real
.venv/Scripts/python.exe -m struct_agent.evaluation.compare --run outputs/current/fixed_run --run outputs/current/llm_run --out outputs/comparison.json
```

比较器要求案例、候选顺序、种子、预算、停止上限、优化配置、软件与代码哈希一致；
策略名和 LLM 配置是允许差异。失败案例保留，无可行解的成本为 `null`，不填零或代理估值。
相同预算上限不要求各策略实际耗尽预算。开发过程中代码版本不同的基本流程测试不能混作严格对照。

普通单元测试使用 stub；显式 FuseGNN 集成测试使用真实权重但合成 FEA，标记 `mock`。
真正工程证据只来自 `fidelity=full` 的 OpenSees 记录。基本流程测试仅验证调用与决策路径，不证明工程可行或策略优越。

## 2026-11-02：自主设计审查模式

`agent_cli`增加`--design-review`，要求`--policy llm --enable-local-adjustment --initial-design <设计>`。
沿用现有`--layout --rooms --spec --run --case-id --purpose --seed --budget-fea --max-steps`。
当前仍先调用生成入口得到布局与房间图，再进入审查；不要求人工编辑两次决策之间的数据。
默认住宅平面使用`python -m struct_agent.cli generate --seed 42 --run <新目录>`生成。

- 初版曾一次性传入完整平面与验算；当前采用下节的全局摘要与按需专业查询。`api/call_*.json`保留摘要、实际查询结果和反馈正文，不是仅传路径。
- 目前是坐标和结构化平面输入，没有向学校LLM发送图片；房间用途标签缺失，不能声称已判断全部建筑使用要求。
- `Decision.review`包含一句诊断、原因假设、涉及构件、效果评议及未解决事项。`Decision.modification`为绑定源分析/布局的类型化指令，支持`move_wall_tip`和`set_design_parameters`，不允许任意源数据修改。
- `PROPOSE_MODIFICATION`指定墙、相连梁、端点及带符号墙长变化量（m，整毫米），编译后调用已有建筑/连接审查；非法建议返回原因且不调用FEA。
- 参数指令使用`{operation:"set_design_parameters",source_evaluation_id,source_layout_sha256,parameter_updates:{变量名:新值},expected_effect}`。仅能部分更新设计条件声明的8个变量，长度单位m且需为原生后端支持的整毫米；不能改变层数、设防、场地或参数域。`conc_bot`实际同步三个楼层分区的混凝土；主次梁参数按角色全体应用，墙厚按现有楼层分区。影响保护构件的共享参数更新拒绝执行。
- 提出任何修改前，必须有当前分析ID/布局哈希匹配的`inspect_member`或`inspect_region`结果，且评议引用其中受影响构件。只有全局摘要、过期查询或其他试算查询不满足该要求；已合理可行时允许直接结束。
- 合法建议真实试算，当前方案保持不动。下一轮Agent收到修改前后验算、全部试算构件检查及改变的几何，再选择`ACCEPT_MODIFICATION`或`REJECT_MODIFICATION`。
- 参数试算的`changed_parameters`记录实际前后值；查询`source=trial`可读取新截面/材料下的真实构件检查。采纳参数时保持布局不变，切换到已验算的新参数并清除旧查询上下文；拒绝时保留原参数。重复组合不再消耗FEA。
- 采纳还要求无新增全局失败、失败计数上升、构件—楼层失败及几何审查问题，且总违反量不恶化。允许增加材料成本；程序不按成本评分替代Agent采纳判断。新布局不复用旧CASINO会话。
- 原方案合理时允许直接`FINALIZE`；无法解决时报告未解决问题并`REQUEST_HUMAN_REVIEW`。工程审核始终`PENDING`，试算采纳不等于工程批准。
- 本模式使用任务总FEA预算与步骤上限，不应用旧候选步长、候选数或每种动作试算次数。请求额度与超时严格读取`--llm-config`，不再由审查模式隐式覆盖；当前学校推理模型配置为16384 token、240秒，实际配置写入manifest。推理占满额度也可能没有正式指令，不能当作有效决策；网关失败保留原方案，不伪造Agent结论。已返回的用量即使伴随空文本也计入统计；超时未返回用量时费用未知。
- 输出`selected_layout.json`、`selected_design.json`、`design_result.json`及原始事件；求解失败或步骤用尽时同样保留状态与未采纳试算。只支持同进程运行，不是磁盘恢复。

## 当前交互：专业查询与来源调查

当前设计审查交互已调整为全局摘要与只读专业查询，替代上节一次性发送完整平面和验算数组的方式。
`get_design_overview(evidence)`输出全局条件、数量、指标与有限异常入口；
`inspect_member(evidence, member_id, provenance=...)`计算轴线几何、端点连接、墙实体轴线覆盖、邻接房间、验算与生成来源；
`inspect_region(evidence, bounds_m, offset=0, limit=12)`按全局XY米制矩形分页返回构件和异常。
Agent以`QUERY_DESIGN`加`query`指令主动调用，结果及来源绑定写入`queries/query_*.json`，实际正文进入后续请求；查询不调用FEA。
`source=current/trial`明确区分保留方案和最近试算，采纳新布局后清除旧查询上下文，原始查询审计仍保留。

调查运行添加`--investigation-only --generation-run <生成目录>`：前者由状态机禁止结构修改，后者读取保存的房间图与`ratios.npy`，回放生成各阶段，只有最终布局完全匹配才允许引用来源。
2026-11-02曾先调查`beam_199`的56mm轴线段并暂停试调墙端；只读调查是可选模式，自主修改运行不传`--investigation-only`。`physical_span_m`不是已核实净跨；墙覆盖的是梁轴线，不能据此直接删除梁或批准建模修改。
短构件前处理的共线梁链与FEA支承跨度可能不同，工具分别提供二者，避免把FE分段或支承轴线距离当作独立物理梁与真实洞口。

2026-11-03已按用户要求撤回昂贵的刚域/净跨实现，恢复原有分析模型。生成入口新增确定性墙端交接补齐：已知原始门窗时，核对不超过180mm的唯一共线墙端与正交墙端，延墙并移除中间短梁，拒绝开口邻近、复杂连接或建筑边界不匹配。`junction_preprocessing.json`与来源回放记录原几何、新几何及mask差异；这项例外仅属于前处理，不放宽Agent局部修改审查。旧房间图缺少原始门窗数据时不执行该新规则。住宅真实验证仅补齐beam_199所在56mm间隙；剩余梁超限仍保留，详见进度文档。

## 尚未完成的研究验收

- 新图正式工程条件及规范口径尚待工程师确定；现有条件仅获准基本流程测试。
- 用户已批准 `outputs/archive/evidence_20261029.zip::residential_001_symmetry_02/` 的上游 union 对称化候选仅作基本流程测试，
  批准文件为该目录 `user_approval.json`；历史轨迹保存在同一归档，验证命令见上文。
- 论文 Ours 的动作收益模型、对比假设、消融口径与多种子实验尚未定义并验证。
- 人工审批界面、磁盘恢复、DWG/报告输出分别按后续阶段推进。
