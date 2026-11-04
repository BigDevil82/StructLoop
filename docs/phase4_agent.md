# Agent运行与工具协议

目标见[PLAN.md](PLAN.md)，最新结果见[progress.md](progress.md)，物理模型见[final_model.md](final_model.md)。

## 运行

已有本地住宅输入的示例；布局、房间图、条件和初始设计必须匹配，输出目录必须是新的：

```powershell
.venv/Scripts/python.exe -m struct_agent.agent_cli `
  --layout outputs/current/feasible_design_20261103_01/selected_layout.json `
  --rooms outputs/current/feasible_design_20261103_01/room_graph.json `
  --spec outputs/current/robustness_20261103_01/case_C_spec.json `
  --initial-design outputs/current/robustness_20261103_01/case_C_initial.json `
  --run outputs/current/new_agent_design `
  --case-id residential_001 --purpose smoke_only --seed 42 `
  --policy llm --design-review --enable-local-adjustment `
  --budget-fea 16 --max-steps 30
```

输入为本地证据文件，不随Git分发；新生成方式见[README](../README.md#入口)。预算与步骤上限按任务设置，失败FEA也计数，不要求耗尽。
`--investigation-only`可选，仅查询、不改结构；`--generation-run`只有来源回放与布局完全匹配时才提供生成证据。
`--protect-member <ID>`可重复指定；保护构件受到共享参数影响时同样拒绝修改。

## 模型与请求

设置统一读取[configs/llm.json](../configs/llm.json)。学校网关模型ID为`DeepSeek-V4.1-Flash`，默认开启思考；对外仍只允许一个原生`tool_calls`，正文必须为空。
`thinking`可选`enabled/disabled`。urllib直接发送顶层thinking，等价于SDK的`extra_body`扩展；学校网关还需同向的`reasoning_effort=high/none`。
实际开关效果以返回usage核对；切换模式会改变设计决策，不能只比较延迟。

请求强制工具选择、禁止并行工具；普通正文、空/多调用、不可用工具及截断调用均不执行，不降级到文字JSON。
模型不填写reason、review、expected_effect或最终总结；内部`tool:<名称>`是程序路由标签。
`.env`的apikey或同名环境变量提供凭据；默认直连、禁重定向、审计脱敏，不记录私有推理文本。
网络/部分服务错误按配置重试，参数语义错误最多纠正一次；仍失败则保留方案并停止交人工处理。

## 工具与执行顺序

| 工具 | 输入与用途 |
|---|---|
| get_design_overview | 读取current/trial全局摘要 |
| inspect_member | 构件ID；查询实际坐标、属性、连接、墙轴线覆盖、相邻房间、验算与来源 |
| inspect_region | 全局XY米制矩形、分页参数；查询区域构件/异常，按需读取后续页 |
| set_design_parameters | parameter_updates与inspected_member_ids；部分更新既有8变量 |
| move_wall_tip | 墙ID、相连梁ID、端点与带符号整毫米长度变化（单位m） |
| accept_modification / reject_modification | 明确处理最近试算；拒绝保留原方案 |
| finish_design / request_human_review | 已通过则结束，未解或故障交人工处理；均不批准工程安全 |

初次提供全局摘要，查询结果实际进入后续请求，不仅传文件路径。current是保留方案，trial是最近试算。
当前源分析的构件/区域查询完成后才开放修改；程序绑定分析ID、布局哈希和证据引用。
每次工具执行后，以同一tool_call_id的role=tool消息返回真实状态。

合法修改调用真实FEA，候选暂不替换当前方案。待决试算期间只允许查询、采纳/拒绝或人工处理。
只有无新增全局失败、失败计数上升、构件—楼层失败或几何问题，且总违反量不恶化，才开放采纳；允许为可行性增加成本。
非法/重复指令不消耗FEA；失败或不利候选不替换方案。参数采纳清除旧查询，新布局另建会话与局部校准状态。
墙端受建筑、开口、连接和保护约束；类别转换只属于前处理。
主/次梁参数作用于对应角色全部梁，conc_bot同步全楼混凝土，墙厚按既有分区；不能改变设计条件。

本模式受总FEA预算与步骤上限约束，不按每类动作固定试算次数；旧候选模式的步长/候选数限制不应用于类型化修改。

## 输出与其他入口

自动保存manifest、analyses、solver_logs、diagnostics、queries、api、decisions和events。
审查模式另存selected_layout.json、selected_design.json、design_result.json与summary.json；未解时也保留状态，不标为校核通过。
工程审核始终PENDING。返回用量缺失时费用未知；模型/求解失败不能解释为工程无解。

`--policy feedback --initial-design ...`是独立的确定性反馈搜索，不使用LLM、不加design-review；它还自动导出parameter_configuration.json，并在找到新可行解后共享预算独立复算。
fixed/rules及普通LLM模式保留CASINO代际继续、局部候选和预置布局切换；切换预置布局仍须匹配的外部批准。
CASINO advance(1)是一代，不是一次FEA。当前仅支持同进程续行；ReplayPolicy是精确状态哈希下的决策回放，不是磁盘恢复。
其余开关直接查agent_cli --help；测试命令统一见README。
