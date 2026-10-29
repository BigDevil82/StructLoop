# 梁墙连接与整栋细网格的继续诊断（2026-10-29）

本批从6504892继续，仅对原超限指标归因，原通过项保持关闭。
材料、截面、源图、楼层质量/转动惯量与加载点均不变；释放梁端弯矩属于诊断反事实，不代替实际设计连接。
生产物理指纹仍为e49011b22005316c54e0bfcc858207ddaeb65a0935ddf3430631badae595ac62。

## 实际分析端区：墙梁组合可排除该因素

在一个专用ETABS实例内重建原12层墙梁组合，求解后由FrameObj.GetElm找到12个分析线单元，
再用LineElm.GetEndLengthOffset和GetInsertionPoint读取实际分析值：两端长度偏移、RZ及插入偏移全部为0。
原超限逐层响应复现的最大绝对差为0，因此跳过重复的“关闭自动端区”求解。
这里已读取分析单元，不再依据对象层AutoOffset=True时的占位输入值推断。

接口依据：[CSI分析线端区](https://docs.csiamerica.com/help-files/etabs-api-2015/html/7643972c-5e05-e1ff-7f10-522e038a0994.htm)、
[对象到分析线映射](https://docs.csiamerica.com/help-files/etabs-api-2016/html/1c3fb93f-4599-8e1b-21ae-03f616dc6a82.htm)。

## 墙梁组合：区分积分效应与换壳后的弯矩耦合

ETABS释放R2/R3，两端轴向和扭转保持；OpenSees用elasticBeamColumn的releasey/releasez=3。
两软件均以属性/内力读回确认所释放端的两向弯矩为0，不以“API返回0”代替物理验证。
接口依据：[CSI释放定义](https://docs.csiamerica.com/help-files/etabs-api-2016/html/967eb7da-6e42-0708-a4e9-00a61d506575.htm)、
[OpenSees梁释放](https://openseespydoc.readthedocs.io/en/latest/src/elasticBeamColumn.html)。

首层主方向位移的相对差异绝对值：

| 诊断 | X差异 | Y差异 | 原51个超限指标在探针中进入5%以内 |
|---|---:|---:|---:|
| 原刚接MVLEM、c=0.4 | 22.18% | 23.36% | 0 |
| 刚接MVLEM、中点c=0.5 | 3.84% | 2.91% | 51 |
| 释放弯矩MVLEM、c=0.4 | 23.93% | 23.38% | 10 |
| 释放弯矩MVLEM、中点c=0.5 | 2.99% | 2.91% | 51 |
| 刚接ShellDKGQ | 110.15% | 0.52% | 21 |
| 释放弯矩ShellDKGQ | 1.51% | 0.56% | 37 |

结论有两层：原MVLEM组合的低层超限主要由积分位置解释；壳替换后新增的X向异常则明显受梁端弯矩传递影响。
不能将这两个现象混为同一根因。中点结果仍是诊断模型，未改生产c，也不把不同模型的通过项拼接成工程验收。

## 整栋第一轮：全梁释放会人为制造机构，已判无效

整栋81条源梁中，57条两端都有墙节点支承，23条只有一端有墙节点，另1条两端均为梁节点。
全部释放两端弯曲会使无墙支承的中间节点失去竖向刚度。
`whole_connection_01`中ETABS明确报告“THE STRUCTURE IS UNSTABLE OR ILL-CONDITIONED”，
尽管工况状态完成且负特征值计数为0；OpenSees则在UmfPack/Arpack阶段因奇异矩阵失败。
该轮完整保存，**不参与比较或定因数值**。不稳定属于这个全释放反事实，不是原住宅模型的诊断结论。

由此直接修复ETABS诊断验证漏洞：住宅适配器现检查原生model.LOG，拒绝明确不稳定/病态警告、
负特征值或缺少稳定性证据，保存solver_health.json；不会仅凭工况完成和有限位移宣布响应有效。
同时在类型化请求和OpenSees受控适配层拒绝对无墙支承节点直接进行全释放。
旧轮outcome中的SUCCESS是当时的API/有限响应判断，保留原件；本批明确将其重分类为无效。

同一校验复查了既有住宅1/2/4片归档日志以及五个子系统/连接日志，均未发现上述关键警告。
没有因此重做已通过项目的数值校准，也没有给无效模型补假支座或微小刚度。

## 整栋第二轮：57条墙—墙梁通道仍不足以解释全部差异

`whole_connection_02`仅释放57条两端都与墙共节点的梁，另外24条保留原连接。
12层共有972根分析梁，其中684根释放、288根保留；几何、质量、加载点及每层4片墙网格不变。
ETABS实际端区为0、无警告、负特征值为0；两种OpenSees单元模型均求解成功并通过整体平衡。
两软件被释放端弯矩的最大绝对值均为0。

| 每层4片整栋诊断 | 屋顶X差异 | 屋顶Y差异 |
|---|---:|---:|
| 原刚接MVLEM | 14.97% | 13.05% |
| 57条梁释放后MVLEM | 11.35% | 12.65% |
| 原刚接ShellDKGQ反事实 | 56.85% | 25.81% |
| 57条梁释放后ShellDKGQ反事实 | 34.29% | 9.44% |

MVLEM仍有超过5%的差异，所以已检查的57条梁通道不能单独解释整栋剩余问题。
另24条梁连接和墙体内部运动学尚未独立分离，不能现在就断言剩余误差全部来自墙或全部来自梁。
原121个超限指标在这组探针中分别有7项（MVLEM）、15项（ShellDKGQ）进入5%以内；其余保留。
下一批应在保持梁间节点支承的条件下分离剩余24条梁的墙端转角，结合墙体接点运动学继续定位，
不再对已通过单墙或材料参数作校准。

## 工件与验证

- 墙梁组合：`outputs/{current,reports}/beam_wall_connection_01/`，ETABS约93.39s。
- 无效全释放：`outputs/current/whole_connection_01/`，含原生日志和OpenSeesError/traceback。
- 有效整栋：`outputs/{current,reports}/whole_connection_02/`，ETABS约118.22s，
  OpenSees MVLEM/Shell分别约71.03s/46.27s。
- 汇总报告：`outputs/reports/connection_diagnosis_01/`，哈希入口 `configs/connection_diagnosis_evidence.json`。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_connection_audit.py tests/unit/test_connection_study.py tests/unit/test_solver_health.py tests/integration/test_structural_subsystem.py --run-real
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.connection_study --run outputs/current/beam_wall_connection_01 --report outputs/reports/beam_wall_connection_01
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.connection_study --whole-building-fine --run outputs/current/whole_connection_02 --report outputs/reports/whole_connection_02
.venv/Scripts/python.exe -m pytest -q
git diff --check
```

复跑必须替换新目录。目标14 passed（1.26s）；默认159 passed、32 skipped、1个既有PyG弃用提示（10.58s）。
新增测试覆盖真实端区读回、约束范围、释放后零端弯矩及零负特征值仍有不稳定警告的拒绝逻辑。
首轮新增测试有一处括号缺失，收集失败后修正并重跑通过；未用失败测试结果进入下一阶段。
