# 计算逻辑修正（2026-10-28）

按用户明确授权直接修复确认的实现 bug；不保留错误算法的旧版运行分支。
真实工程条件仍未补充，本轮继续使用已获准的 28 层等条件做冒烟。

## 已修正

| 问题 | 当前逻辑 | 验证依据 |
|---|---|---|
| 组合系数被取 abs，正负组合相同 | 静力效应带符号线性组合；CQC 地震幅值按显式 +/- 组合 | D=-10、E=30 的两组合分别得到 20、-40 |
| 负剪力被截为零、控制组合为空 | 以效应绝对值参与包络，保留对应有符号组合内力 | 全负和全零反例；零效应仍有控制组合 |
| 不同组合限值下仅按最大剪力选组合 | 按对应限值的利用率选控制项 | 非地震 V=180/限值0.2，地震 V=170/限值0.15，后者控制 |
| 梁从全局力分量取弯矩，旋转后取错 | 读取 localForce；统一截面图符号，j 端抵抗弯矩反号 | X/Y/45° 悬臂梁的 M=PL、V=P、位移 PL³/(3EI) |
| 墙剪力按激励全局方向截取 | 始终投影到墙肢自身平面方向，排除面外分量 | 旋转墙肢的力积分不变量 |
| CQC 将特征值比误作频率比 | 先取 omega=sqrt(lambda)，再计算相关系数 | ANSYS 1% 阻尼近频振型例，相关系数约0.276；零阻尼退化SRSS |
| 未预测的小梁间隙被补成墙、零长度区间留下伪墙 | 未预测区间为梁；零区间去除；间隙合并用实际长度单位 | 几何覆盖与区间单元测试 |
| min_length 未落实、近重合节点留下1 mm墙 | 复用2 mm容差吸附节点并进行毫米取整；短墙转梁保留边界；不跨T节点强行合并 | 两个工程布局均无小于0.1 m的墙，连接拓扑通过 |
| 长度<=0.5 m的墙未执行配筋却可能显示设计通过 | 所有建模墙肢执行配筋设计，缺少设计结果视为错误 | 管线调用测试及实际构件-楼层覆盖核验 |
| 普通/详细入口重复汇总逻辑 | 共用 parametric/summary.py | 普通真实入口与详细入口的35字段独立复算 |
| 更改计算后仍可能命中旧缓存或误用旧代理标签 | 结果与缓存绑定当前分析实现指纹；真实代理须声明匹配的训练指纹 | 缓存隔离、模型不兼容拒绝测试 |

没有通过放宽限值、忽略超限或改写结果来获得通过。保留既有荷载和材料条件。
`_vendor` 中的本地副本已直接修正；原 Png2Dxf 仓库只读。迁移清单更新本地文件哈希及修正说明。

## 外部核对资料

- [OpenSees Linear 几何变换与局部坐标定义](https://opensees.github.io/OpenSeesDocumentation/user/manual/model/geomTransf/Linear.html)
- [OpenSees localForce 为局部抵抗力](https://opensees.berkeley.edu/OpenSees/manuals/usermanual/882.htm)
- [OpenSees 反应谱分析的特征值、周期及用户振型组合责任](https://opensees.github.io/OpenSeesDocumentation/user/manual/analysis/responseSpectrumAnalysis.html)
- [ANSYS 近频振型相关系数数值例](https://ansyshelp.ansys.com/public/Views/Secured/corp/v242/en/ans_tec/tecmissingmassresults.html)，
  [该例1%阻尼设置](https://ansyshelp.ansys.com/public/Views/Secured/corp/v242/en/ans_tec/tecmissingmassanalysis.html)

本项目继承的0.15/0.2等工程限值没有在这次软件修正中重新选定，不能将软件单元测试等同于完整规范认证。

## 当前输入与真实输出

- 建筑图仍为 `configs/test_case.json` 中同一份 DXF，未改变图纸和RC-GNN权重。
- 当前原布局：`outputs/residential_001_rcgnn_02/`，149墙、81梁、43楼板区域。
- 当前对称布局：`outputs/residential_001_symmetry_03/`，187墙、73梁、43楼板区域。
- 当前详细复算：`outputs/member_diagnostics_{baseline,symmetry}_04/`，各1次真实建筑FEA。
- 当前 Agent 冒烟：`outputs/physics_fix_agent_02/`，1次真实FEA，遵守总预算并正常结束。
- 新实现指纹：`981ea4234286f985cdfeb0fc4181c20bd245c26e82362dba6e7034344b625644`。

两个最终详细复算均求解成功、结构不可行。原布局墙/梁配筋失败为133/7项，
对称布局为506/28项，均按构件-楼层计数；4172/5236项墙检查分别全部执行，无配筋漏检。
两布局的墙剪压控制指标约0.281888/0.295153（对应限值0.15），
梁约0.288996/0.300145（对应限值0.15）。这些是修正后的失败，保留为反馈。

中间 `_03` 诊断、`physics_fix_agent_01` 在发现控制组合选择问题前运行，不作为最终验证或论文标签。
旧工件不回写，也不强求新结果与错误历史数值相等。

## CASINO 权重边界与使用

当前可运行同布局的真实FEA参数优化。旧 FuseGNN 权重缺少修正后物理标签的兼容性证据，
因此 `CasinoConfig.use_surrogate` 默认 false。不是重新训练或把旧模型宣称为有效。
若使用 `--use-surrogate`，权重资产清单的 feasibility/steel 项必须给出一致且匹配当前实现的
`analysis_signature`（须先按真实验证/训练来源确认，不得直接填写以绕过检查）；权重文件哈希仍须匹配。
模型兼容性不满足时明确 BLOCKED，不进行筛选。仅 mock 集成可用旧权重检验软件机械行为。

```powershell
.venv/Scripts/python.exe -m struct_agent.diagnostics_cli --layout outputs/residential_001_rcgnn_02/layout.json --spec configs/reference_spec.json --design outputs/physics_fix_inputs_01/design_baseline.json --run outputs/new_diagnostic_run
.venv/Scripts/python.exe -m struct_agent.agent_cli --layout outputs/residential_001_rcgnn_02/layout.json --rooms outputs/residential_001_rcgnn_02/room_graph.json --spec configs/reference_spec.json --run outputs/new_agent_run --case-id residential_001 --purpose smoke_only --policy rules --seed 42 --budget-fea 2 --population 2 --generations 1
```

诊断入口接受显式 `--design`；可用 `--reference` 对同一当前实现的记录做复算对照，拒绝跨实现对照。
使用新输出目录，避免覆盖。下一步基于正确标签验证代理模型，并依据当前控制构件完善布局/参数优化。
