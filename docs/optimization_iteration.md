# 优化迭代修正（2026-10-29）

本轮仍为 Phase 4 的优化内核修正。目标是从给定结构参数开始，以真实反馈寻找可行解，再降低材料目标。
这是一种待验证的混合搜索实现，不预设 Agent 或新搜索策略优于基线。
用户已授权直接修正 GA、仿真及旧实现；没有重训、改动权重或修改原始工程图。

## 已修正的流程

- 小种群必须留出至少一个子代位置。原 population=2、elite=2 会使种群完全不更新。
- 一代定义为一个完成评价并参与排序的种群。最后一代不再额外计算一批随后被忽略的候选。
- 单次执行与分段执行共用 `_vendor/shearwall_optimization/algorithms/evolution.py`；
  删除重复的 `adapters/incremental_ga.py`，不保留错误行为的对照运行开关。
- 所有选择点（锦标赛、精英、全局最优、会话摘要、Agent状态）均按
  **可行性 → 约束违反量 → 材料成本** 排序。成本更低不能抵消更严重的约束违反。
  未执行 FEA 的代理拒绝/跳过结果不能超越真实评价结果。
- 连续超限量不再重复叠加同一项的二元失败惩罚；保留缺少连续解释的失败标志。
  墙/梁设计失败使用失败构件-楼层占各自总数的比例，使“133项失败降到6项”能被观察到。
  这些只是搜索反馈量，不改变任何通过标准，也不把求解失败当成结构不可行。
- 支持 `--initial-design`。先评价给定参数，再探索参数域上界组合；后者只是探索点，
  不能视为可行性上界，因为截面加大会改变荷载、刚度与内力分配。
- 每代在精英之外加入确定性的反馈候选：不可行时优先调整相关墙厚、梁宽和强度；
  梁高另行试探；可行后优先尝试单变量降档并修复墙厚的竖向单调约束。其余位置仍由GA交叉、变异与采样产生。
  已评价的反馈邻域不重复提出，同一种群尽量去重；所有真实调用仍统一缓存与记账。
- Agent停滞按相同的可行性/违反量/目标顺序判断，并记录实际违反量变化。
  局部邻域或参数上界没有成功，不等于已经证明该布局无解。

## 材料估算修正与范围

- 混凝土质量按2500 kg/m³计算，价格换算也使用相同密度；1 m³ C30的既定500元价格不再变成520.83元。
- 梁箍筋按闭合矩形周长计算理想长度；抗剪计算的双肢面积不再代替箍筋完整长度。
- 墙两端边缘纵筋按层高计算长度，横向钢筋体积按既有体积配箍率、边缘区面积和层高计算。
  不再误把边缘区的平面尺寸当成纵向长度。

当前目标仍是既有单价下的**梁、墙理想化材料成本**，不是施工预算或完整结构工程量。
不含锚固搭接、弯钩、节点扣重、楼板配筋与建筑成本；不宣称已经完成施工图级配筋校核。
改变布局后，过短墙肢与边缘区重叠等适用性问题仍需专门处理，不能靠降低失败权重获得通过。
本轮仅修正能由长度、面积、体积和单位直接核实的工程量错误，没有臆造新的构造限值。
分析实现指纹随材料汇总改变；旧结果和代理标签不得直接复用。

## 复现入口

使用已存在的当前生成布局，以及给定初始参数；复跑必须更换输出目录：

```powershell
.venv/Scripts/python.exe -m struct_agent.agent_cli --layout outputs/current/residential_001/layout.json --rooms outputs/current/residential_001/room_graph.json --spec configs/residential_12_story.json --initial-design outputs/current/design_12_story/design.json --run outputs/current/new_feedback_search --case-id residential_001 --purpose smoke_only --policy rules --seed 42 --budget-fea 6 --population 2 --generations 5
.venv/Scripts/python.exe -m pytest -q tests/unit/test_search_feedback.py tests/unit/test_incremental_ga.py tests/unit/test_optimization_env.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest -q --run-real
```

学校API已接入，规则决策不消耗API调用。早期28层反馈搜索保留为历史轨迹，不能用于当前物理指纹的标签。
上例已改为当前12层输入，但真实GA会因尚未消解的极短物理墙肢前置阻断，不应绕过门槛。
建模已按用户决定固定，软件差异排查结束，见 `final_model.md`；后续依照结构受理、工程校核及实验设计门槛推进。
