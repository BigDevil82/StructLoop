# Phase 4：X向位移、子结构与网格检查（2026-10-29）

## 检查含义

子结构检查是把整栋拆成可控的小问题，例如单根悬臂梁、单片墙、L/T形墙连接或墙—梁组合。
先与解析解核对，再逐项增加连接和约束，定位差异来自单元、截面、连接还是结果提取。
本轮完成梁/单片墙解析核对、L形墙原网格重建等价性和T形交点共节点测试；
尚未完成ETABS与OpenSees的真实墙—梁子结构逐项对照。

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

汇总报告及带输入哈希的manifest：`outputs/x_displacement_diagnosis_01/`。
原始输出为 `etabs_residential_12_euler_01`、`etabs_residential_12_euler_mesh{2,4}_01`，
以及 `opensees_residential_12_{rebuild,fibers2,mesh2,mesh4}_01`；
解析子结构最终运行 `x_displacement_substructures_02`。目录均在outputs下，不覆盖旧结果。

等价住宅命令（必须换新目录）：

```powershell
.venv/Scripts/python.exe -m struct_agent.etabs_cli residential --layout outputs/residential_001_rcgnn_03/layout.json --spec configs/etabs_12_story_spec.json --design outputs/residential_12_inputs_01/design.json --beam-theory euler_comparison --wall-vertical-subdivisions 2 --reference-wall-subdivisions 2 --reference-fiber-refinement 2 --run outputs/new_etabs_mesh2 --opensees-reference outputs/new_opensees_mesh2 --comparison outputs/new_mesh2_comparison
.venv/Scripts/python.exe -c "from pathlib import Path; from struct_agent.adapters.etabs.substructures import run_substructures; run_substructures(Path('outputs/new_substructures'))"
```

两软件的水平离散、泊松效应、面外行为和连接运动学仍非完全等价。
本轮只完成有界的1/2/4片敏感性调查，不以任意阈值宣布收敛；状态为
`MESH_CONVERGENCE_NOT_ESTABLISHED` / `NOT_VALIDATED`。
细化仅用于位移/模态诊断，新单元不能直接使用原构件内力汇总接口或作为GA标签。
生产物理指纹仍为e49011b22005316c54e0bfcc858207ddaeb65a0935ddf3430631badae595ac62；
现有粗模型回归仅证明同实现复算一致，不证明离散误差可接受。

下一最小任务：在两端建立一致的单片墙→L/T形墙→墙—梁子结构，
分别检查有/无刚性楼板约束的高度细分响应，定位粗网格过硬及两端细化后差异；
再确定适用的生产单元/网格策略。当前不能将某个细网格值当成真值，或调整物理参数去拟合。
重力/反应谱及配筋独立验证仍未完成，正式优化必须等待相关分析基础验证。
