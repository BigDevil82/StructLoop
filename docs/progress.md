# 当前状态与验证索引

更新：2026-11-04。详细步骤与失败保留在原始运行目录；本文件只保留交接所需结论。

## 已具备

- RC-GNN生成住宅布局，前处理修正短构件/墙端交接，保留几何审查与生成来源记录。
- 真实OpenSees分析、整体与构件校核、相连墙联合截面配筋、材料用量计算；建模假定见[final_model.md](final_model.md)。
- 受建筑、门窗、连接和保护构件约束的墙端调整，以及已有8个设计变量的部分更新。
- 纯工具Agent闭环：连续调查会话、全局摘要与按需查询、受约束的生成布局修复和参数组合试算、显式采纳/拒绝、回退与停止；不生成文字审查报告。
- 确定性`--policy feedback`入口，另保留CASINO会话与固定/规则策略；这些运行不冒充LLM自主决策。

## 关键证据

下表链接均为被Git忽略的本地运行记录。

| 验证 | 结论 | 原始记录 |
|---|---|---|
| 墙端交接前处理 | 补齐beam_199所在56mm间隙；撤回昂贵刚域实现，其他剩余超限继续保留 | [junction_validation_20261103_01](../outputs/current/junction_validation_20261103_01/comparison.json) |
| 数值修正及12/18/24层复验 | 原K/M与验收阈值不变；只对原模态验收失败做一次残差修正；不同层数真实复验通过 | [modal_refinement_20261103_01](../outputs/current/modal_refinement_20261103_01/validation_summary.json) |
| 纯工具LLM完整任务 | 24层、8度自然超限案例；7次工具调用、3次真实FEA；不利增高梁候选被拒绝，随后C35→C40并采纳、结束 | [工具轨迹审计](../outputs/current/tool_only_design_20261103_01/audit.json) |
| 开关思考的同状态比较 | 7状态×2模式×2重复；14组仅10组实际动作效果一致，关闭思考不能视为无损提速 | [配对记录](../outputs/current/tool_routing_20261103_01/thinking_pair_20261104_comparison.json) |
| 分段耗时核对 | 同布局/截面/设防：12层约25.80秒，24层约107.69秒；主要增量在分析阶段，包含配筋但未计少量几何导出 | [分段计时](../outputs/current/tool_routing_20261103_01/timing_20261104_comparison.json) |
| TOD自主审查与修复 | 从原始生成布局及C35初设开始；61次工具决策、5次真实FEA，自主完成小墙组、梁链与开口修复并结束；独立复算一致，全部现有力学检查通过 | [执行轨迹与参数](../outputs/current/tod_autonomous_layout_20261104_09/trajectory_audit.json)、[核查](../outputs/current/tod_autonomous_layout_20261104_09/audit.json) |

纯工具任务的最大梁利用率1.035441→0.916072，梁/墙失败条目均为0，全部已实现检查通过。
最终几何和其他截面参数不变，材料模型成本165.26→170.30万元；[参数配置](../outputs/current/tool_only_design_20261103_01/parameter_configuration.json)绑定实际eval_00003。
该案例仍有46条几何筛查未逐项核实，工程审核为PENDING，不证明正式工程安全或经济最优。

当前默认开启思考已完成TOD整任务验证；关闭思考的配对请求没有执行设计建议，不能当作完整优化轨迹比较。
当前重点见[PLAN.md](PLAN.md)，运行设置见[phase4_agent.md](phase4_agent.md)。

## 验收与追溯

最近代码验收：`pytest -q --run-real -p no:cacheprovider`，**253通过**、8条第三方弃用警告，40.06秒。
[验收日志](../outputs/current/tod_autonomous_layout_20261104_09/acceptance_final.log)与同目录XML保留；这是整套测试耗时。

已提交基础：`3aaf850`（统一反馈入口与模态残差修正）、`72483b0`（Agent参数修改与真实反馈）。
更早决策、已撤回实现及临时探索查Git历史和原始输出，不作为默认规则。
本次精简前尚未提交的长文快照为`outputs/current/tool_routing_20261103_01/documentation_before_cleanup_20261104.zip`。
