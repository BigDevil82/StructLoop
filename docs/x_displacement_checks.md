# Phase 4：X向位移、子结构与网格检查（2026-10-29）

## 检查含义

子结构检查是把整栋拆成可控的小问题，例如单根悬臂梁、单片墙、L/T形墙连接或墙—梁组合。
先与解析解核对，再逐项增加连接和约束，定位差异来自单元、截面、连接还是结果提取。
此前完成梁/单片墙解析核对、L形墙原网格重建等价性和T形交点共节点测试；
后续已完成下文的两软件同边界单片墙对照，尚未完成L/T形墙及墙—梁的真实逐项对照。

网格收敛检查保持建筑几何、材料、真实楼层、边界及荷载不变，只细分计算单元。
例如每层一片墙在高度上分为1、2、4片，比较位移、周期和内力是否趋于稳定。
新中间节点不是楼层，不增加楼面质量、楼板约束或楼层梁。
MVLEM截面纤维数量是另一个独立的离散参数，必须与高度细分分开考察。
计算平衡、互易性成立与两软件结果接近，都不能单独证明网格已经收敛。

## 固定输入及对照范围

仍用 `configs/etabs_12_story_spec.json`、`residential_001_rcgnn_03`，12层×2.9m，
同一截面/弹性材料、刚性楼板、固定底部、逐层规定质量及转动惯量，屋顶X/Y分别1MN诊断力。
不改变物理短墙/梁，不把数值加密当成极端构件治理。原始图、权重、正式建模器默认离散不变。
所有值来自本机实际求解；合成子结构明确单独标记，不混入住宅数据。

ETABS原矩形梁包含剪切变形，OpenSees原梁为Euler梁。
诊断选项 `euler_comparison` 仅将ETABS两方向剪切面积修正系数放大到1e6，
近似抑制剪切变形；轴向/弯曲/扭转刚度及重量/质量系数保持1，并从API读回核实。
这是隔离梁理论影响的试验，不是推荐工程参数。
修正系数次序见 [CSI官方API](https://docs.csiamerica.com/help-files/etabs-api-2015/html/cfc36c75-7890-32a3-178a-d44abb5f1202.htm)，
单元定义见 [OpenSees Timoshenko梁](https://openseespydoc.readthedocs.io/en/latest/src/ElasticTimoshenkoBeam.html)
及 [MVLEM_3D](https://opensees.github.io/OpenSeesDocumentation/user/manual/model/elements/MVLEM_3D.html)。

## 实际结果

屋顶主方向位移，单位mm：

| 模型 | 每层墙竖向1片 | 2片 | 4片 |
|---|---:|---:|---:|
| ETABS，抑制梁剪切，X | 2.374560 | 4.061073 | 5.124680 |
| OpenSees，Euler梁，X | 2.447730 | 3.684367 | 4.357638 |
| ETABS，抑制梁剪切，Y | 2.573717 | 3.665682 | 3.994666 |
| OpenSees，Euler梁，Y | 2.683477 | 3.175187 | 3.473434 |

OpenSees 2/4片采用相同的原纤维数×2；另跑仅纤维×2、竖向仍1片的控制组，
X/Y为2.447585/2.683089mm，相对原1片变化均小于0.02%。因此不能把上表的大变化归因于纤维加密。
ETABS从2片到4片X仍增26.2%，OpenSees仍增18.3%；两端整栋均未证明收敛。
这比原粗网格X向9.43%的软件间差异更需要优先处理，Y向原先接近也不能作为充分证据。

ETABS保留剪切变形的原粗模型为X/Y=2.702472/2.714278mm。
仅抑制梁剪切后变为2.374560/2.573717mm，变化约−12.13%/−5.18%。
梁理论确实显著影响结果，但不能认定原X差异已完全解释；不同因素可能互相抵消。

验证工具及小构件：

- 整栋原网格1:1重新创建MVLEM墙，X/Y复现原结果至约1e−11相对误差，未发现重建改变原模型。
- T形交点细分后仍共享一个节点，不额外增加楼层质量/梁/约束。
- 三种长度的Euler及Timoshenko悬臂梁均符合各自闭式解。
- 12m高、2m长、0.2m厚合成单墙使用明确平截面约束，64纤维时，
  竖向8/16/32/64片相对连续梁解析位移误差约3.36%/1.78%/0.92%/0.48%。
  独立推导的离散应变能解与实际MVLEM响应一致；粗网格误差不保证单调，全部保留。
  该结果仅支持这个梁化子结构，不能外推为住宅收敛或深墙壳效应验证。
- 各住宅工况整体平衡通过，X/Y柔度互易性及正功检查通过；这些仅排除部分加载/提取错误。

## 工件与复现

汇总报告及带输入哈希的manifest：`outputs/reports/x_displacement/`。
原始输出为 `etabs_residential_12_euler_01`、`etabs_residential_12_euler_mesh{2,4}_01`，
以及 `opensees_residential_12_{rebuild,fibers2,mesh2,mesh4}_01`；
解析子结构最终运行 `x_displacement_substructures_02`。这些原始目录已整体收入
`outputs/archive/evidence_20261029.zip`，汇总报告可直接在reports下查看。
索引与恢复方式见 `output_management.md`；原始manifest及数值未改写。

等价住宅命令（必须换新目录）：

```powershell
.venv/Scripts/python.exe -m struct_agent.etabs_cli residential --layout outputs/current/residential_001/layout.json --spec configs/etabs_12_story_spec.json --design outputs/current/design_12_story/design.json --beam-theory euler_comparison --wall-vertical-subdivisions 2 --reference-wall-subdivisions 2 --reference-fiber-refinement 2 --run outputs/current/new_etabs_mesh2 --opensees-reference outputs/current/new_opensees_mesh2 --comparison outputs/current/new_mesh2_comparison
.venv/Scripts/python.exe -c "from pathlib import Path; from struct_agent.adapters.etabs.substructures import run_substructures; run_substructures(Path('outputs/current/new_substructures'))"
```

两软件的水平离散、泊松效应、面外行为和连接运动学仍非完全等价。
本轮只完成有界的1/2/4片敏感性调查，不以任意阈值宣布收敛；状态为
`MESH_CONVERGENCE_NOT_ESTABLISHED` / `NOT_VALIDATED`。
细化仅用于位移/模态诊断，新单元不能直接使用原构件内力汇总接口或作为GA标签。
生产物理指纹仍为e49011b22005316c54e0bfcc858207ddaeb65a0935ddf3430631badae595ac62；
现有粗模型回归仅证明同实现复算一致，不证明离散误差可接受。

后续按单片墙→L/T形墙→墙—梁子结构推进，分别检查有/无刚性楼板约束的高度细分响应，
定位粗网格过硬及两端细化后差异，再确定适用的生产单元/网格策略。
当前不能将某个细网格值当成真值，或调整物理参数去拟合。
重力/反应谱及配筋独立验证仍未完成，正式优化必须等待相关分析基础验证。

## 同边界单片墙：已执行的最小切片

正式工件：`outputs/current/single_wall_12_02/`；报告与逐文件SHA256索引：
`outputs/reports/single_wall_12_02/`。跟踪输入、报告和失败重试的哈希入口为
`configs/single_wall_evidence.json`，其用途是证据定位，不是新的生产回归真值。

这是从当前residential_001抽取的**简化弹性诊断**：

- `shearwalls_3`，原端点(739.416, −258.476)至(741.716, −258.476)m，长度2.3m；
  平移/转入全局XZ平面，不改源布局。截取单段，不包括邻接0.1m段或其他墙/梁。
- 获准12层×2.9m，总高34.8m；全高固定底区200mm墙厚，以隔离厚度分区变化。
  C30弹性E=30GPa、nu=0.2、G=12.5GPa；并非原住宅完整截面分区。
- 底部六自由度固定；其余节点限制UY/RX/RZ，UX/UZ/RY自由。
  墙顶两端各施加5kN的+X力，合计10kN，无端部附加弯矩。
- ETABS为每排一个ShellThin矩形，OpenSees为每排一个MVLEM_3D、64条形心纤维、c=0.4、
  K=5GA/(6h)；面外参数显式对齐，但面外自由度已限制。
- 分开运行无楼板、仅真实楼层刚性楼板两组。在本平面内，后者等价于同层两端UX相等，
  不约束UZ/RY；两端分别用ETABS diaphragm和OpenSees equalDOF实现。
  竖向每层1/2/4/8片，中间网格不加楼板约束、梁或质量。
- 不含自重、重力、楼层质量、显式楼板或几何非线性；没有开展模态/规范/配筋校核。

边界、材料和荷载已对齐，但壳面内运动学与宏纤维运动学并非同一离散理论。
[OpenSees官方说明](https://opensees.github.io/OpenSeesDocumentation/user/manual/model/elements/MVLEM_3D.html)
明确MVLEM_3D的梁型面内行为与板型面外行为解耦，`-Poisson`用于面外弯曲；
不能把该参数当作面内泊松伸缩的开关。
[CSI楼板说明](https://docs.csiamerica.com/help-files/etabs/Menus/Define/Diaphragms.htm)
定义刚性/半刚性楼板及其分配方式。本例的平面化边界推导和实测一致性只适用于这片单墙。

### 数值与解析对照

墙顶两端UX平均值，单位mm。以下无楼板组与楼板组的最大ETABS差仅8.4e−10mm；
OpenSees两组也在数值精度内一致。这与该对称单墙中约束冗余的预期一致，不能外推到L/T形墙。

| 每层竖向片数 | ETABS，nu=0.2 | OpenSees，nu=0.2 | 连续梁估计 |
|---|---:|---:|---:|
| 1 | 22.917675339 | 23.712495148 | 23.164701373 |
| 2 | 22.667802552 | 23.450239849 | 23.164701373 |
| 4 | 22.403397386 | 23.312495667 | 23.164701373 |
| 8 | 22.279994114 | 23.241969442 | 23.164701373 |

连续估计为u=FH³/(3EI)+FH/(5GA/6)，I=tL³/12；这是自由截面Timoshenko梁理论，
不是根部夹固二维弹性壳的精确解。MVLEM另用独立应变能和核对：

`u_discrete = FH³/(E*I*(1−1/m²)) * [1/3+0.1/N+(0.6²−0.6+1/6)/N²] + FH/(5GA/6)`，

其中N=12×每层片数，m为纤维数。10个配对工况及2个纤维控制工况均与离散公式在1e−7相对容差内一致；
该容差用于同一线性单元理论核对，不用于跨软件或工程验收。

零泊松控制保持几何、E与荷载不变，G按E/[2(1+nu)]同步变为15GPa；
两种楼板条件均在每层8片重算：ETABS=23.141878680mm，OpenSees=23.229865096mm，
连续梁估计=23.152597025mm（上列数值为无楼板组）。软件间ETABS/OS−1由−4.1390%变为−0.3788%。
nu变化导致的解析剪切位移变化仅0.012104348mm，而ETABS位移增加0.861884566mm；
这提示面内泊松效应/离散约束值得优先排查，尚不能仅凭此证明具体锁定机制。
零泊松是材料控制试验，不是建议修改住宅物理参数。

保持每层8片不变，OpenSees纤维32/64/128条分别为23.258955764/23.241969442/23.237726750mm；
它与竖向网格是独立控制项，不能把纤维加密当作壳的水平网格加密。

### 证据与当前结论

- ETABS 18.1.0 Build 2117正式运行用时176.47s，10个工况全部完成；原生LOG壳数逐项为
  12/24/48/96（零泊松组96），负刚度特征值均0，无warning/error条目。
  保存逐节点/连接/材料/约束读回、EDB、LOG/OUT、API历史与执行源码快照。
- OpenSees 3.8.0完成10个配对与2个纤维控制工况；两端全部六分量平衡、有限响应与正功检查通过。
  原始逐节点位移、反力、解析分解及软件版本均保留。
- 1→8片时ETABS位移−2.7825%、OpenSees−1.9843%；4→8片仍变化−0.5508%/−0.3025%。
  此单墙没有复现整栋细化后显著变软，因此不能用孤立直墙的竖向离散单独解释整栋现象。
  **不据这些百分比宣布收敛，也不据nu=0组的接近宣布整栋通过。**
- 首轮`single_wall_12_01`在默认D1重名处返回API码1，4个无楼板工况完成后停止；
  修正为`SL_WALL_D*`后在新目录完整复跑。失败源码、错误类型、traceback、进程清理和部分结果保留。
  `single_wall_native_probe_01`是正式运行前的单次Adapter试算，仅有输入/结果，不参与配对结论。

复现命令（两处输出目录必须是新的）：

```powershell
.venv/Scripts/python.exe -m struct_agent.etabs_cli single-wall --layout outputs/current/residential_001/layout.json --spec configs/etabs_12_story_spec.json --design outputs/current/design_12_story/design.json --wall-member shearwalls_3 --timeout 600 --run outputs/current/new_single_wall --comparison outputs/reports/new_single_wall
.venv/Scripts/python.exe -m pytest -q tests/unit/test_single_wall.py tests/unit/test_etabs.py tests/integration/test_single_wall_mechanics.py tests/integration/test_substructure_convergence.py --run-real
```

下一最小任务：保持本单墙物理条件，增加壳水平离散控制并分离泊松伸缩影响，再以相同审计方式
扩展到共享竖向边的L/T形墙及墙梁连接。当前生产网格与物理指纹不变，整栋仍为NOT_VALIDATED，
本工件不进入GA/代理标签，不开展正式优化。
