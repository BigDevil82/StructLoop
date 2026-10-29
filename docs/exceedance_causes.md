# 结构超限项的原因检查（2026-10-29）

本批只对31a5160批量报告中达到5%的指标做归因，原通过项保持关闭。
复用已有真实ETABS结果，完成8组OpenSees反事实、1组墙梁壳替换补充及1次ETABS专用实例只读连接审查。
没有修改生产建模器、E/G、墙厚、源图、模型权重或原始结果；没有将反事实替换为生产标签。

## 已确认的重要因素：MVLEM转动中心的离散效应

生产MVLEM_3D取c=0.4，即沿单元高度40%处的集中转动。对恒EI、单位端力、H=12的独立梁，
楼层高度z的连续柔度积分为 `int_0^z (H−x)(z−x)dx = Hz²/2−z³/6`。
离散取值为 `sum_j (H−q_j)(z−q_j)h`，`q_j=(j+c)h`。
每层一片时c=0.4对首层的积分偏差为+19.31%，屋顶仅约+2.35%；
中点c=0.5的首层偏差为−1.43%。这是独立数学推导，不是按软件结果拟合参数。

实际对照保持几何、材料、纤维数、边界、质量及加载点不变，仅改变诊断转动中心：

| 原超限指标 | 原c=0.4差异 | 中点诊断c=0.5差异 |
|---|---:|---:|
| T形墙首层X位移 | 9.42% | 0.36% |
| T形墙首层Y位移 | 22.63% | 3.85% |
| T形墙屋顶X位移 | 5.64% | 3.60% |
| T形墙屋顶Y位移 | 5.81% | 3.21% |
| 整栋粗网格首层X位移 | 21.35% | 8.23% |
| 整栋粗网格首层Y位移 | 22.44% | 8.04% |

T形墙原86个超限指标中76个在探针里降至5%以内，剩余为6项耦合响应和4项耦合层间量，
其主方向逐层位移/层间响应均进入5%以内。整栋低层差异明显缩小，但仍有其他因素。
细化整栋改中点不能解释原约13%–15%的屋顶差异，原121个超限项只减少2项。

[官方MVLEM_3D定义](https://opensees.github.io/OpenSeesDocumentation/user/manual/model/elements/MVLEM_3D.html)
仍推荐默认c=0.4，且该单元有特定梁化运动学。这是离散模型选择造成的偏差，不据此宣布其原生实现有bug，
也不直接将生产c改成0.5。中点诊断仅用于定因，生产状态和原判定不变。

## 可排除为主要原因的因素

- T形墙纤维数增加4倍，屋顶X/Y差仅从5.64%/5.81%降至5.32%/5.59%，
  首层Y仍22.40%。纤维截面误差不是该批主因。
- 生产MVLEM没有显式传面外泊松比，默认0.25；ETABS弹性材料nu=0.2，双方此参数并非完全一致。
  单独把细化整栋MVLEM面外nu设为0.2后，屋顶X/Y差由14.97%/13.05%变为14.92%/13.01%，影响不足0.1个百分点。
  所以它不是剩余超限的主要解释；该试验不改变面内E/G。
- 原平面全部243个构件成对检查（162墙段、81梁），在1e−6m容差下，未发现交点未同时成为两端节点的情形，
  也未发现正长度重叠。因此当前证据不支持“梁端/墙端漏共节点”是主因。
- 存档MVLEM公开源码会内部交换第3/4节点序号，局部竖向向量使用的是交换后的左上点；
  不能把其变量名误读为以对角线作局部轴。原生单元解析回归和已有1:1重建测试也不支持此项几何错误。

## 仍需处理：梁墙连接与单元运动学

用ShellDKGQ替换MVLEM，膜厚、材料和0.63³面外弯曲修正保持一致。
该替换是独立的模型诊断，不指定ShellDKGQ为真值。
[壳单元定义](https://openseespydoc.readthedocs.io/en/latest/src/ShellDKGQ.html)及
[板截面弯曲修正定义](https://openseespydoc.readthedocs.io/en/latest/src/elasticMembranePlateSection.html)
支持上述分离设置。

- 无梁T形墙首层X/Y与ETABS差为0.41%/0.61%，主方向位移差显著缩小；12阶周期差最大约0.49%。
- 有梁组合的原超限首层Y差降至0.52%，X差却扩大到110.15%。
- 整栋壳替换同样没有改善：粗网格首层X/Y差约101.25%/52.19%；
  细网格屋顶X/Y差约56.85%/25.81%，相关失败结果全部保留，不选择有利结果。

无梁T形墙能接近，而有梁组合出现很强的方向性差异，**支持将梁端弯矩—墙节点转角耦合列为首要剩余嫌疑**。
目前尚未分离到具体的壳钻转稳定刚度、自动端区或截面转角传递项，不能把其中任意一项写成已确认原因。
存档公开源码含随单元高度变化的MVLEM内部水平梁刚度项（其中I与h³有关），
也提示高度细分不只是增加采样点，还会改变复杂节点处的离散运动学；这仍需针对性的原生单元证据验证。

此外，当前分析墙段最短27mm，13段小于100mm、35段小于200mm；这些是**分析分段**，不等同于物理墙肢。
细分会显著改变单元长宽比和接点转角场，可能放大不同壳/宏纤维体系的差异，目前未量化其独立贡献。

### ETABS连接设置的实际读回

在独立实例打开哈希绑定的模型副本，没有求解、保存或附着用户工程。12根楼层梁全部读回：

- 插入点10（形心），两端三个方向偏移均0；局部轴角0，未开启高级局部轴。
- 两端六自由度均未释放；没有发现显式偏置或释放与OpenSees中心线梁不一致。
- `AutoOffset=True`，长度及RZ字段读回均0。自动模式下这些输入字段不等于已解析分析端区，
  **不能凭这组0值完全排除自动端区影响**。后续须查分析线单元实际端区或显式关闭自动端区做受控对照。

插入点编号依据[CSI接口定义](https://docs.csiamerica.com/help-files/etabs-api-2015/html/af52715a-299d-b81c-7372-03fef249e45f.htm)，
自动模式字段解释依据[CSI端区接口](https://docs.csiamerica.com/help-files/etabs-api-2015/html/7e64e86f-c753-b434-afa8-79b391daa48f.htm)。
两轮源EDB哈希未变，第二轮源缓存哈希核验未变。第一轮只复制EDB导致软件提示缺少inspection.Y_，属性查询仍成功；
补复制同名Y*缓存后在新目录复查，原生stderr为空。两轮原始日志均保留。

## 极大相对百分比的含义

原细化整栋某耦合层间量的ETABS值为−3.47e−9、OpenSees为1.49e−6，
由于分母接近0，显示约43149.6%差异；绝对层间量差为1.50e−6，对应2.9m层高下约0.00434mm位移差。
这解释了百分比为何很大，不代表将其判成通过：仍按用户5%规则保留超限，并同时给出绝对量。

## 证据、验证及下一步

主工件/报告：`outputs/{current,reports}/exceedance_causes_01/`。
墙梁壳补充：`outputs/{current,reports}/exceedance_wall_beam_shell_01/`。
连接审查：`outputs/current/connection_audit_{01,02}/`。
哈希、几何审查和读入编码错误/缓存提示的处理记录见 `configs/exceedance_causes_evidence.json`。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_exceedance_causes.py tests/unit/test_connection_audit.py tests/integration/test_structural_subsystem.py tests/integration/test_substructure_convergence.py --run-real
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.exceedance_causes --run outputs/current/exceedance_causes_01 --report outputs/reports/exceedance_causes_01
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.connection_audit --model outputs/current/structural_comparison_01/etabs/wall_beam/model.EDB --run outputs/current/connection_audit_02
.venv/Scripts/python.exe -m pytest -q
git diff --check
```

重跑必须使用新目录。目标14 passed（0.67s）；默认152 passed、30 skipped、1个既有PyG弃用提示（23.25s）。
下一批保持原质量、加载点和截面，直接隔离梁墙节点的弯矩/转角传递及实际端区；
不继续检查原小于5%的项目，不改材料参数去拟合，不把反事实数值混入工程或论文标签。
