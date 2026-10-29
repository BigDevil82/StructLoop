# 结构层面批量对照（2026-10-29）

按用户最新规则，同条件响应满足 `abs(OpenSees−ETABS)/abs(ETABS) < 0.05` 即通过，
直接关闭且不再核查校准。ETABS仅作为相对差异的分母约定，不指定任一软件为真值。
精确双零通过；单零非零超限；小量仍保留绝对差异，等于5%及以上单列。

已完成L形墙、T形墙、墙梁组合，以及12层住宅整体1/2/4片的批量比对。
单墙原有10个墙顶位移工况全部通过并关闭，取消原计划的水平离散/泊松补查。
生产物理实现、原布局、历史数值及权重不改写。

## 输入、求解与证据

- 当前residential_001_rcgnn_03，获准的12层×2.9m条件及3/5/4层截面分区；
  C30、墙厚200/160/160mm、主梁250×500mm、次梁300×400mm。
- L形墙抽取原图 `shearwalls_4,87`；T形墙抽取 `shearwalls_9,10,116`；
  墙梁组合抽取 `shearwalls_4,5,79,80,87` 和 `beams_4`。原构件端点、类别与共节点保留。
- 两端固定底部，每层刚性楼板，采用相同质量/转动惯量和X/Y屋顶1MN线性柔度探针。
  ETABS采用Euler比较设置，与OpenSees Euler梁对齐；不通过改E/厚度/泊松比拟合响应。
- 子系统保留父布局楼板多边形以复用双方相同的**规定质量协议**；这不是实际分担面积或设计荷载的确认。
  1MN用于线性响应比例比较，孤立子系统的大位移不作为实际设计变形或可行解。
- 三个子系统本批真实计算，单个ETABS专用实例总用时96.14s；OpenSees各自独立求解，
  六分量整体平衡及有限响应均通过。三份原生日志均无负刚度特征值、warning/error条目。
- 整栋直接复用已验证SHA256的历史归档：`etabs_residential_12_euler_{01,mesh2_01,mesh4_01}`
  对应 `opensees_residential_12_{02,mesh2_01,mesh4_01}`。没有重跑已有整栋或挑选有利网格。

工件：`outputs/current/structural_comparison_01/`。
报告和逐项判定：`outputs/reports/structural_comparison_01/{report.md,assessment.json}`。
源码、原生文件、输入及逐次结果保留；索引与哈希见 `configs/structural_comparison_evidence.json`。

## 结构对照结果

屋顶主加载方向位移差，统一相对ETABS，以下均为绝对百分比：

| 结构 | X差异 | Y差异 | 屋顶主方向结论 | 周期通过数 |
|---|---:|---:|---|---:|
| L形墙 | 4.87% | 4.52% | 通过，关闭 | 12/12 |
| T形墙 | 5.64% | 5.81% | 超限 | 12/12 |
| 墙梁组合 | 4.62% | 4.47% | 通过，关闭 | 12/12 |
| 12层住宅，每层1片 | 3.08% | 4.26% | 通过，关闭 | 9/12 |
| 12层住宅，每层2片 | 9.28% | 13.38% | 超限 | 11/12 |
| 12层住宅，每层4片 | 14.97% | 13.05% | 超限 | 6/12 |

每个模型同时完整评价12个MAC匹配周期、72项逐层UX/UY/RZ以及48项两向层间位移角，
共132项。6个模型合计792项，其中288项通过、504项超限；通过项全部关闭。
既有单墙另有10项通过。这里包括近零耦合分量，不将其大相对差异藏入屋顶主响应结论。

整栋每层1片时，首层Y位移为ETABS 0.0416804mm、OpenSees 0.0510319mm，
差0.0093515mm、相对22.44%，不能由屋顶通过代替其判定；第10–12阶周期差达到约5.10%–6.03%。
整栋每层4片时，最大主方向层间位移角差约18.39%，位于X加载屋顶层。
L/T/墙梁子系统的部分低层响应也超限，完整工况/楼层/分量/绝对差异/相对差异均在assessment.json。

**弹性结构层面比对已完成，存在超限项目，不能将整个模型标为全部通过。**
不再对任何小于5%的项目核查校准。后续集中处理整栋超限的层间响应、T形墙及连接运动学，
不再追加已通过单墙的水平网格研究。重力、地震谱/组合与规范配筋尚未比对，不能由弹性响应替代。

## 复现与验证

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_structural_tolerance.py tests/unit/test_etabs.py tests/integration/test_structural_subsystem.py --run-real
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.structural_batch --run outputs/current/structural_comparison_01 --report outputs/reports/structural_comparison_01
.venv/Scripts/python.exe -m pytest -q
git diff --check
```

重跑须替换为全新的运行/报告目录。配置为 `configs/structural_comparison.json`。
目标测试27 passed（0.52s）；默认全量146 passed、29 skipped、1个既有PyG弃用提示（8.92s）。
新增测试覆盖严格5%边界、零/小量、无效响应、源构件/条件隔离、逐层与层间差异，以及真实OpenSees L形墙。

后续已完成[超限原因检查](exceedance_causes.md)：MVLEM转动中心的离散积分能解释T形墙和整栋低层差异的大部分，
细化整栋剩余差异指向梁墙连接/单元运动学。反事实仅用于归因，不改写本报告或生产参数，原通过项保持关闭。
