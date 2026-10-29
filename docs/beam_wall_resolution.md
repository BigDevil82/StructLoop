# 梁墙连接区、墙单元假设与整栋网格诊断

本批从 cb39393 继续 Phase 4，将有梁子结构、连接区、竖向网格和整栋对照合并完成。
沿用 residential_001 和已批准的12层诊断输入，不以任何软件或最细网格为真值。
相对差统一为 `abs(OpenSees−ETABS)/abs(ETABS)`，严格小于5%的项关闭。

## 当前可以确认的原因

1. **梁端弯矩如何进入墙体是可改变的建模因素。** 原直接共节点模型中，梁强轴转角对应相连墙壳的法向钻转；
   换成另一种壳但仍沿用点连接，不能自动保证该局部转动柔度一致。
   两端使用相同、由实际梁高决定的有限连接区后，ShellDKGQ子结构的120项静力比较全部通过；
   首层I/J端MY单位弯矩柔度差从原140.23%/144.09%降至3.05%/0.29%。这是连接敏感性的证据，
   不是将任意刚臂或软件结果指定为真实节点刚度。
   这里同时改变了原来的局部离散，不能将全部改善归于刚体联系：相同梁表面网格的point_2也有120/120项静力通过，
   但J端MY柔度仍差12.06%；point_4为106/120、I/J端MY差7.79%/15.41%。
   同网格rigid_4才同时得到静力全通过及两端MY通过，支持“近节点网格与连接共同影响”的有限结论。
2. **MVLEM_3D不是各向同性二维连续壳。** 本机原生单元的规定位移静力试验显示，
   相同E、nu并不产生相同的双向膜内本构；仅细分竖向宏单元无法消除这类差异。
   本批已把该区别从泛泛的“单元不同”落实为实际应变/力响应，但没有把整栋每一项误差都归于它。
3. **主要方向接近不等于整栋所有响应通过。** 保留972根实际楼层梁的有限连接区模型中，
   ShellDKGQ在竖向4/8分的全部48项主方向位移和层间位移均小于5%；耦合项仍有超限。
   MVLEM在同样连接区下仍明显依赖竖向离散，不能用屋顶某次小于5%宣布完整收敛。

## 双方实际使用的模型

| 项目 | ETABS | OpenSees |
|---|---|---|
| 墙 | ShellThin，二维膜及薄板弯曲 | 分别比较MVLEM_3D和ShellDKGQ，绝不混成一个结果 |
| 材料 | E=30GPa、nu=0.2、零容重 | 相同E/G；ShellDKGQ nu=0.2，MVLEM按其单轴纤维/独立剪切机制 |
| 面外刚度 | 原有0.63³弯曲修正 | ShellDKGQ相同修正；MVLEM沿用官方默认面外假设 |
| 梁 | 原主次梁全部保留；剪切面积系数1e6，近似Euler | 原elasticBeamColumn，保留EA、EIy、EIz、GJ |
| 楼层 | 12×2.9m，原3/5/4层墙厚分区 | 完全相同 |
| 边界/楼板 | 底部固定；仅真实楼层刚性平面楼板 | 同样约束UX/UY/RZ；楼板主节点UZ/RX/RY固定 |
| 质量/加载 | 原规定质量、惯量、质心；屋顶X/Y各1MN | 相同；中间网格节点无新增质量、楼板或楼层梁 |
| 几何非线性 | 线弹性静力 | Linear几何变换，线弹性静力 |

子结构为原图五段墙和一根1.8m、250×500mm主梁逐层重复；整栋仍为162段分析墙、81根源梁，
共972根楼层梁。没有删除梁刚度、释放梁端、调整E/墙厚或拟合弹簧。
既有“纯墙132项最大差0.81%”只适用于双方都移除梁刚度的反事实，本批有梁结果另行列出。

## 有限连接区的定义和验证

在原梁端同一XY处，建立由实际梁高确定的竖直刚性截面线，范围为楼面Z上下各半梁高，屋顶截断于现有墙顶。
同一点有多根梁时取实际最大梁高；主次梁分别为0.5/0.4m，不引入人工调参长度。
竖向网格同时包括规则分点和梁上下表面；`point_n`与`rigid_n`共享完全相同的节点/壳网格，
前者不施加刚体联系，后者施加六自由度刚体联系。没有把墙边割线转角强制当成钻转真值。

ETABS用六自由度Fixed的无质量Link，显式刚度/阻尼输入为0并读回；OpenSees用`rigidLink beam`。
后者与真实楼层刚性平面楼板形成嵌套约束，使用Lagrange精确约束方程；不能直接串接Transformation处理器。
方程缩放`sqrt(E*t_first_floor)`只是数值尺度，不是物理罚弹簧。
逐节点核验 `u_slave=u_master+theta×offset` 及转角相等，力矩汇总始终包含 `r×F`。
所有有效配对均通过整体平衡、有限性和刚体约束残差；子结构另通过梁刚度方程、FZ/MX/MY节点平衡与柔度互等性。

## 主要静力结果

本批每配对120项：72项逐层UX/UY/RZ及48项平动层间位移；**没有新增模态比较**，不能写成132项。
全部18组有效配对由原始结果重算于 `outputs/reports/beam_wall_resolution_02/`；`_01`为首16组早期汇总，保留不覆盖。

| 范围/连接 | 墙单元 | 通过/120 | 主位移最大差 | 主层间位移最大差 | 屋顶X/Y差 |
|---|---|---:|---:|---:|---|
| 子结构 point_4 | ShellDKGQ | 106 | 5.152% | 5.341% | 4.969% / 0.453% |
| 子结构 rigid_4 | ShellDKGQ | 120 | 1.973% | 1.973% | 0.246% / 0.385% |
| 子结构 rigid_4 | MVLEM_3D | 114 | 8.854% | 8.854% | 0.720% / 1.780% |
| 子结构 rigid_16 | MVLEM_3D | 106 | 21.623% | 21.623% | 4.233% / 2.227% |
| 整栋 rigid_4 | ShellDKGQ | 72 | 2.886% | 2.994% | 2.886% / 0.237% |
| 整栋 rigid_8 | ShellDKGQ | 71 | 3.086% | 3.178% | 3.086% / 0.461% |
| 整栋 rigid_4 | MVLEM_3D | 25 | 22.066% | 22.066% | 4.481% / 3.744% |
| 整栋 rigid_8 | MVLEM_3D | 12 | 43.462% | 43.462% | 17.218% / 11.039% |
| 整栋 rigid_4_h2，关闭边约束 | ShellDKGQ | 78 | 2.648% | 2.791% | 2.648% / 0.949% |

整栋rigid_8中，X加载屋顶侧向耦合位移为ETABS 0.0511790mm、ShellDKGQ 0.0463468mm，
绝对差0.0048322mm、相对差9.442%；低层/层间耦合量的最大相对差36.667%。
这些小响应没有删除或按分母下限改写为通过，整体71/120仍为部分超限。

竖向4→8分时整栋主屋顶位移变化：ETABS X/Y +3.681%/+1.468%，ShellDKGQ +3.882%/+1.695%，
MVLEM +16.320%/+8.604%。这是各自离散敏感性，不是跨软件误差；不能从屋顶变化小于5%外推全部内力/模态收敛。
已有子结构ShellDKGQ的合格MY柔度、单墙等已关闭，不继续增加网格来校准它们。

## 膜内解析应变试验及诊断代码修正

`beam_interface_membrane_patch_04`对单片XZ墙全部24个自由度施加真实静力SP约束，
由收敛后的原生单元节点力积分正应力（N、m、Pa；不是仅手工写入节点位移）。

| 规定位移应变 | 二维各向同性平面应力 / ShellDKGQ | MVLEM_3D实测 |
|---|---|---|
| eps_xx=−nu×1e−5，eps_zz=1e−5 | sigma_xx≈0、sigma_zz=300000Pa | −120000 / 300000Pa |
| eps_xx=1e−5，eps_zz=0 | 312500 / 62500Pa | 600000 / 约0Pa |

上述边界场下宏模型投影出的法向响应为diag(2E,E)，没有二维泊松交叉耦合；这不是把宏单元宣称为通用二维本构。
结果与[官方MVLEM_3D定义](https://opensees.github.io/OpenSeesDocumentation/user/manual/model/elements/MVLEM_3D.html)
“平面内线模型经几何变换、面内/面外解耦、Poisson选项用于面外”的说明一致。
因此不能将同E、同nu或无限竖向细化当作与壳等价的保证；也不能据此断言原生单元存在实现bug。

本批修正两项**诊断设置/结果读取错误**，未改生产求解器：

- `setNodeDisp(..., '-commit')`在宏单元材料更新前先提交节点，可能使其增量归零。
  旧刚体检查仅有位移读回不足以独立证明宏材料状态；本批统一改为真实静力SP步，所有节点DOF逐项读回，
  有效重新检查 `beam_interface_rigid_patch_02` 的三个单元XYZ刚体转动仍全部通过。
- MVLEM内部返回节点顺序为 `[1,2,4,3]`，不是Shell的 `[1,2,3,4]`；积分改为按`eleNodes`对应节点力。
  `_membrane_patch_01`提交设置无效，`_02/_03`的横向力积分/解释无效，均保留并排除。
  `_04`为有效应变/应力证据；测试同时检查非零竖向材料响应与横向2E响应，避免零状态假通过。

## 用户建模建议的逐项落实

用户新增 `docs/check_model_set.md` 已于北京时间23:31恢复工作后完整阅读，原文内容保留，仅按仓库`.gitattributes`统一LF换行；提供时与入库后的哈希均保留。
其中经验误差范围是建议，不能替代本机实际对照，也未直接采信未核实的作者/实现归属。

| 提醒 | 处置/证据 |
|---|---|
| Euler与Timoshenko一致 | 既有ETABS两剪切面积系数1e6及梁方程读回已隔离此因素；不重复重开已通过检查 |
| 梁端区、局部轴、插入、释放 | 既有全部972根实际梁读回：解析端长/RZ/插入均0，惯性张量一致，无释放 |
| 梁壳钻转/有限连接范围 | 本批实际梁高截面刚体联系，双方相同；无极大E虚拟梁或任意钻转弹簧 |
| 质量、荷载、自重、PDelta | 原零容重、规定集中质量/惯量/中心、同位置屋顶力及线弹性假设保持 |
| 实际自动网格/边约束 | `beam_interface_area_audit_03`专用实例只读生成副本分析图：7776对象=7776分析单元，角点一一匹配，7776对象边约束开启；源EDB/缓存哈希不变 |
| 水平与竖向双向网格 | 已真实完成水平1/2分、竖向4分的整栋配对；水平4分组启动时再次锁屏，BLOCKED，未产生模型或求解值 |
| 内力参考点/局部轴 | 子结构梁方程用同一全局向量，有限连接区壁端力含r×F；整栋全部Pier/梁端内力跨软件验收尚未完成 |

`beam_interface_horizontal_01/etabs/rigid_4`显式关闭全部边约束后，15228对象=15228分析单元，
边约束读回为0；与原`beam_interface_whole_01/etabs/rigid_4`的两工况全部楼层UX/UY/RZ逐值相同（最大绝对变化0）。
因此开启边约束并非本模型现有响应差异的原因，该项关闭，不继续校准。

水平二分 `rigid_4_h2` 原生30456对象=30456分析单元，全部角点匹配、边约束0，972根梁仍各对应1个分析线单元。
ETABS批次738.59s；OpenSees水平1/2分各105.66/567.64s，均实际求解并通过基底平衡及约束残差。
二分后120项通过78项，主方向48项全部通过；耦合最大差18.360%，由一分的34.996%下降，仍不改变超限判定。
二分屋顶横向耦合为0.0511828/0.0479238mm，绝对差0.0032590mm、相对差6.367%；两向屋顶扭转差0.223%/2.043%通过。
水平1→2分时两端屋顶X变化5.483%/5.239%、Y变化2.416%/3.144%，说明水平方向仍需收敛证据。

水平四分组 `beam_interface_horizontal_fine_01` 在ApplicationStart再次遇到锁屏及退出提示，未开始建模。
已请求用户再次手动解锁；此项状态为 **BLOCKED_WINDOWS_LOCKED**，不能宣称四分结果或网格收敛通过。
下一批最小且唯一所需补查是同条件水平四分ShellDKGQ/ETABS配对，随后按5%规则关闭通过项或按已知偏差有界报告；
不再重开已排除的边约束、梁轴/端区或合格子结构MY项。
解锁后的待执行命令如下，**尚未运行**，必须使用新目录：

```powershell
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.interface_study --whole-building --subdivisions 4 --horizontal-subdivisions 4 --disable-edge-constraints --formulations shell_dkgq --run outputs/current/beam_interface_horizontal_fine_02 --report outputs/reports/beam_interface_horizontal_fine_02
```

锁屏期间两个专用ETABS新实例在ApplicationStart阶段异常退出，未进入结构求解。
`beam_interface_area_audit_01/_02`保留COM错误、日志、源快照及归属进程记录；只清理本任务拥有的实例。
用户解锁后 `_03`真实审查成功，不把前两次启动失败混作模型失稳。

## 求解失败与证据使用范围

`beam_interface_whole_01`的ETABS两工况成功，但首个OpenSees UmfPack数值分解失败；
`whole_resume_01`仅调整约束尺度仍失败。日志记录`numeric analysis returns -1`；UMFPACK将−1定义为out-of-memory，
不能将它误报为结构负刚度或物理机构。状态定义见[UMFPACK官方头文件](https://raw.githubusercontent.com/DrTimothyAldenDavis/SuiteSparse/dev/UMFPACK/Include/umfpack.h)，
OpenSees对应调用见[官方求解器源码](https://github.com/OpenSees/OpenSees/blob/master/SRC/system_of_eqn/linearSOE/umfGEN/UmfpackGenLinSolver.cpp)。
完整失败输出保留，均不进入配对统计；`whole_resume_02`严格核对相同请求并复用成功ETABS工件，
改用带主元的SparseGeneral后两端整体平衡与约束残差通过。
后续X/Y线性工况可共享一次因式分解，明确核验荷载因子分别为[1,0]/[0,1]，并以完整位移场与独立求解相互校验。
可选列重排试算`beam_interface_ordering_01`未纳入物理配对：一分响应最大绝对变化1.49e−12，
但耗时105.66→137.38s；二分重排试算在完成前主动停止，保留源快照、取消记录及分类说明，不编造其响应或速度收益。
该可选入口已撤回，最终代码保留既有经验证的数值设置；不从不完整试算推断内存改善或模型失稳。

生产建模器和物理指纹 `e49011b22005316c54e0bfcc858207ddaeb65a0935ddf3430631badae595ac62`不变。
本批没有训练、正式GA/学校LLM调用或YJK重试。测试通过不等于跨软件全部指标通过；正式优化仍未解禁。

证据入口为 `configs/beam_wall_resolution_evidence.json`，工件映射见 `docs/output_management.md`。
全部运行使用新的不可变目录；既有报告、失败工件及旧证据哈希不覆盖。

## 本批执行与复现入口

以下为本批关键实际命令。复跑必须更换所有新建的run/report目录；`--resume-etabs`仅可指向请求完全相同、状态SUCCESS的原生批次。

```powershell
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.interface_study --subdivisions 2 4 --include-point-controls --run outputs/current/beam_interface_substructure_01 --report outputs/reports/beam_interface_substructure_01
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.interface_study --subdivisions 8 16 --formulations mvlem --run outputs/current/beam_interface_substructure_fine_01 --report outputs/reports/beam_interface_substructure_fine_01
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.interface_study --whole-building --subdivisions 2 4 --resume-etabs outputs/current/beam_interface_whole_01/etabs --solver SparseGeneral --run outputs/current/beam_interface_whole_resume_02 --report outputs/reports/beam_interface_whole_resume_02
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.interface_study --whole-building --subdivisions 8 --run outputs/current/beam_interface_whole_fine_01 --report outputs/reports/beam_interface_whole_fine_01
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.membrane_patch --source-manifest outputs/current/structural_comparison_01/etabs/wall_beam/manifest.json --run outputs/current/beam_interface_membrane_patch_04
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.joint_patch --source-manifest outputs/current/structural_comparison_01/etabs/wall_beam/manifest.json --run outputs/current/beam_interface_rigid_patch_02
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.connection_audit --model outputs/current/model_form_original_01/model.EDB --run outputs/current/beam_interface_area_audit_03 --area-mesh-only
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.interface_study --whole-building --subdivisions 4 --horizontal-subdivisions 1 2 --disable-edge-constraints --formulations shell_dkgq --run outputs/current/beam_interface_horizontal_01 --report outputs/reports/beam_interface_horizontal_01
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.interface_report --runs outputs/current/beam_interface_substructure_01 outputs/current/beam_interface_substructure_fine_01 outputs/current/beam_interface_whole_resume_02 outputs/current/beam_interface_whole_fine_01 outputs/current/beam_interface_horizontal_01 --report outputs/reports/beam_wall_resolution_02
.venv/Scripts/python.exe -m pytest -q tests/unit/test_area_mesh_audit.py tests/unit/test_connection_audit.py tests/unit/test_interface_geometry.py tests/unit/test_horizontal_mesh.py tests/integration/test_finite_interface.py tests/integration/test_structural_subsystem.py tests/integration/test_membrane_idealization.py --run-real
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest -q --run-real
git diff --check
```

最终目标28 passed（6.59s）；默认173 passed、45 skipped、1个既有PyG弃用提示（9.39s）。
此前完整真实测试217 passed、8个既有PyG/ezdxf弃用提示（38.46s）；之后新增的请求Schema测试已包含在目标/默认测试中。
