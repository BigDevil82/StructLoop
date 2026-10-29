# 保留梁刚度的梁墙节点转角传递对照（2026-10-29）

本批从83fea85继续Phase 4。按用户最新要求，所有有梁对照保留梁的轴向、两向弯曲及扭转刚度，
不移除梁、不释放梁端、不拟合E/G、墙厚或连接弹簧。生产模型及指纹不变。

**范围纠正**：此前83fea85的“已知差异收口”对实际带梁体系表述过强。
纯墙ShellThin/ShellDKGQ的132项通过仅适用于去梁诊断，不能外推实际带梁整栋通过或剩余差异不可避免。
旧报告/工件原样保留，本记录及当前progress优先；现在仍在定位带梁体系差异，未开放正式优化。

## 对照模型与新增观测

沿用原住宅抽取的12层墙梁子结构：墙shearwalls_4/5/79/80/87，梁beams_4。
梁沿全局+X，长1.8m，250×500mm；原分区墙厚、材料、固定底部、楼层质量/惯量、刚性楼板及加载点保持。
每层原单片墙网格，原12根楼层梁完整保留；没有改变几何或新增刚接区。

- ETABS：ShellThin墙＋Euler比较设置的框架梁，全部未释放。
- OpenSees主对照：MVLEM_3D墙＋elasticBeamColumn梁，生产c=0.4不变。
- OpenSees诊断：ShellDKGQ墙＋同样的完整梁；另加ASDShellQ4默认参数独立控制，
  不改变其稳定参数，也不把这个控制模型当作真值或生产候选。
- 保留原屋顶X/Y各1MN两个线性工况，新增首层梁I/J端全局MX/MY各1kNm，共四个单位弯矩诊断。
  这些新增工况只测局部转角柔度，不是补造设计荷载或工程条件。

读取每层全部源节点六自由度位移、全部梁端六分量内力，以及墙单元全局节点力。
统一CSI局部轴/截面切面符号与OpenSees全局节点抵抗力，不直接比较符号不同的M3与My。
保存六个工况的全部原始量，不只保存有利楼层。

## 基本力学核验：梁正常工作、节点没有丢失弯矩

独立采用完整Euler梁刚度矩阵，由实测的两端12自由度位移重算梁端力；每个软件使用自己的实际截面J。
ETABS的两项剪切面积倍率仍为1e6，所以与理想Euler有极小的可预期差值。
在首层梁I/J两端检查FZ/MX/MY直接平衡；楼板约束作用于UX/UY/RZ，不用其反力掩盖这三项残差。
四个单位弯矩工况还组成4×4转角柔度矩阵，检查互等性和正定性。

| 模型 | 梁刚度方程最大相对残差 | 节点FZ/MX/MY最大相对残差 | 柔度互等性相对残差 |
|---|---:|---:|---:|
| ETABS | 2.23e-7 | 1.53e-12 | 2.33e-18 |
| MVLEM | 2.24e-13 | 2.07e-11 | 1.69e-15 |
| ShellDKGQ | 4.20e-13 | 1.14e-12 | 5.93e-16 |
| ASDShellQ4默认控制 | 1.89e-13 | 4.09e-13 | 1.18e-14 |

上述检查全部通过。ETABS原屋顶逐层UX/UY/RZ与既有刚接结果复现的最大绝对变化为0。
ETABS原生日志无关键不稳定警告、负特征值为0；三种OpenSees模型均通过原整体平衡及新增单位弯矩基底平衡。
这些结果支持排除本例“梁刚度没保留、端弯矩没传递、梁端力取错轴/符号”为剩余现象的主要原因。

## 差异集中在墙壳法向转角与梁强轴弯曲的耦合

梁沿X，强轴弯曲转角是全局RY；其端部相连的直墙位于XZ平面，所以RY是该墙的法向钻转自由度。
梁截面转动与墙节点钻转共用一个节点自由度，但不同墙单元对这个自由度的插值/约束不一定相同。

在原屋顶X荷载下，首层梁I端实际测得：

| 模型 | 梁墙共同节点RY/rad | 墙顶边割线转角/rad | 本层梁I端全局My/kNm |
|---|---:|---:|---:|
| ETABS ShellThin | +0.00297457 | +0.00303050 | 614.964 |
| MVLEM_3D | +0.00306717 | +0.00307617 | 617.568 |
| ShellDKGQ | −0.00103010 | +0.00776144 | 566.914 |
| ASDShellQ4默认控制 | +0.00191191 | +0.00392620 | 518.097 |

墙顶边割线转角定义为−(UZ右−UZ左)/墙段长度，是观测量，**不是对节点钻转应相等的强制判据**。
剪切变形、角部局部变形及插值都会使两者不同；不能直接把二者差值定义成实现bug。
ShellDKGQ本例的节点RY与该割线转角反号，说明只比较楼层位移或检查“已共节点”不足以判断转角耦合是否等价。

对首层梁端施加同样1kNm纯弯矩，直接获得更清晰的方向分离：

| 作用点/弯矩 | ETABS同向转角/rad | ShellDKGQ同向转角/rad | 跨软件相对差异 |
|---|---:|---:|---:|
| I端MX，绕梁轴扭转 | 1.097746e-4 | 1.097961e-4 | 0.0195% |
| J端MX，绕梁轴扭转 | 1.099088e-4 | 1.099077e-4 | 0.0010% |
| I端MY，强轴弯曲/该墙法向钻转 | 5.999799e-7 | 1.441361e-6 | 140.23% |
| J端MY，强轴弯曲/该墙法向钻转 | 5.861546e-7 | 1.430729e-6 | 144.09% |

即ShellDKGQ的MY节点转角柔度约为ETABS的2.4倍，而同一模型MX通道已小于5%，关闭后不再校准。
I端MY=1000Nm时，同层梁分担My分别为ETABS182.17Nm、MVLEM178.71Nm、ShellDKGQ263.10Nm；
与相邻上下墙在该节点的My之和都等于1000Nm。差异来自耦合后的刚度分配，不是力矩消失。

## 已缩小范围，尚未宣布不可避免或实际模型通过

1. 本批将此前笼统的“梁墙连接嫌疑”缩小到**墙面内钻转与梁端强轴弯曲的耦合通道**。
   这符合不同壳/宏单元运动学造成方向性差异的解释，不是给全部超限套用“软件算法不同”。
2. 对三个OpenSees单元另做XYZ三向微小刚体转动检查，逐节点确认完整规定位移被保留后读取抵抗力。
   最大归一残差分别4.32e-15、1.14e-17、0；均通过。没有发现简单的整体转角符号错误。
   该检查不能证明角部转角插值或梁墙连接区域已经工程等价。
3. ASDShellQ4默认控制也没有整体解决本例差异：原132项仅8项通过；其MY柔度差更大。
   该控制同时改变膜、板和钻转公式，不能据此独立量化某一个稳定项，更不能选择某个有利位移替代验收。
4. 目前还不能把局部钻转插值、连接区有限尺寸和邻近网格的影响彻底分离；
   更不能说“已经证明某软件原生单元有bug”或“实际带梁模型的差异无法避免”。
   下一最小任务是保留真实梁刚度，针对该节点比较直接共节点与按实际梁截面尺寸定义的连接区转角传递；
   不通过释放梁、添加任意弹簧刚度或将割线转角强制等同钻转来拟合软件。

原屋顶工况132项的通过数为MVLEM81、ShellDKGQ44、默认ASD8；全部指标、原有超限及近零响应均保留。
整栋1/2/4片差异与网格敏感性没有被这次子结构结果覆盖；重力/谱/组合/配筋及正式优化可靠性仍未完成。

理论/接口依据：[CSI壳节点力](https://docs.csiamerica.com/help-files/etabs-api-2016/html/e6826614-bf6b-d3cd-a0e5-5d70e06cbc07.htm)、
[CSI梁切面内力符号](https://docs.csiamerica.com/help-files/sap/Output/Frame_Element_Internal_Forces_Output_Conventions.htm)、
[ShellDKGQ膜钻转及薄板定义](https://opensees.github.io/OpenSeesDocumentation/user/manual/model/elements/ShellDKGQ.html)、
[ASDShellQ4默认钻转处理](https://opensees.github.io/OpenSeesDocumentation/user/manual/model/elements/ASDShellQ4.html)。
上述机理定位是结合实际原生结果的推断，未将公开master源码视为安装二进制的同版本证明。

## 工件、失败保留与验证

- 主工件：`outputs/current/full_stiffness_joint_01/`，ETABS71.97s；OpenSees各约0.10/0.14/0.12s。
- 原始报告：`outputs/reports/full_stiffness_joint_01/`；本批汇总 `outputs/reports/full_stiffness_joint_summary_01/`。
- 有效刚体检查：`outputs/current/full_stiffness_joint_patch_02/`。
  `_01`诊断设置遗漏setNodeDisp的逐DOF提交，之前设置的完整位移未被保留，结果判无效并排除单元结论。
  修正为逐DOF提交且逐节点读回验证后复跑通过；两次执行源代码均与原manifest记录的SHA256逐字节匹配。
  该失败不属于原生单元物理bug，不据此修改生产单元。
- 证据入口：`configs/joint_rotation_evidence.json`。生产物理指纹仍e49011b22005316c54e0bfcc858207ddaeb65a0935ddf3430631badae595ac62。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_joint_mechanics.py tests/integration/test_structural_subsystem.py --run-real
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.joint_study --run outputs/current/full_stiffness_joint_01 --report outputs/reports/full_stiffness_joint_01
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.joint_patch --source-manifest outputs/current/structural_comparison_01/etabs/wall_beam/manifest.json --run outputs/current/full_stiffness_joint_patch_02
.venv/Scripts/python.exe -m pytest -q
git diff --check
```

复跑须更换新目录。目标14 passed（2.33s）；默认全量167 passed、40 skipped，1个既有PyG弃用提示。
新增真实测试核验梁全部刚度、内力方程、节点平衡、柔度互等性，并确认人为篡改节点弯矩会被检出；
另覆盖三个单元的刚体转动及规定节点位移的读回，不把研究上的超限当成测试通过。
