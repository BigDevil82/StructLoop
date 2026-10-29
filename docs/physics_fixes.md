# 计算逻辑修正（2026-10-28）

> 2026-10-29 ETABS独立对照新增修正：矩形梁Saint-Venant扭转常数、MVLEM剪切弹簧N/m单位及逐墙片5GA/(6h)、最少8宏纤维。
> 当前计算指纹为e49011b22005316c54e0bfcc858207ddaeb65a0935ddf3430631badae595ac62；此前 `_04/_05/_06` 记录均为历史数据。
> 现用12层真实回归由 `configs/real_fea_reference.json` 绑定；独立对照证据、适用边界及未解决差异见 `etabs_cross_validation.md`。

> 旧28层中间诊断已退役并清理，删除目录摘要见 `cleanup_2026-10-29.json`；旧文档见Git提交ef2c915。
> 当前仍存在整栋网格敏感性，见 `x_displacement_checks.md`，不能把测试通过等同于工程验收。

按用户明确授权直接修复确认的实现 bug；不保留错误算法的旧版运行分支。
真实工程条件仍未补充；28层为早期冒烟设置，当前独立诊断采用获准的12层。

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
| min_length 未落实、近重合节点留下1 mm墙 | 坐标容差处理与物理构件类别分开；保留短墙原类别并审查，不跨T节点强行合并 | 当前生成几何审查与极短物理墙肢前置阻断测试；不会把短墙转梁当作修复 |
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

默认建筑为 `configs/test_case.json`，当前布局为 `outputs/residential_001_rcgnn_03/`。
12层条件见 `configs/etabs_12_story_spec.json`，参数见 `outputs/residential_12_inputs_01/design.json`。
详细结果由 `configs/real_fea_reference.json` 按哈希绑定；目前不可行，墙配筋55项、墙剪压3项、梁剪压16项失败。
这些是本地简化检查结果，ETABS重力/反应谱/配筋尚未完成独立验证。

此前各 `_04/_05/_06` 对应不同阶段实现，不能沿用其数值或旧代理标签。
早期诊断的组合、几何与漏检问题已修正，逐轮开发记录保存在Git历史中，不再作为当前使用说明。

## CASINO 权重边界与使用

当前可运行同布局的真实FEA参数优化。旧 FuseGNN 权重缺少修正后物理标签的兼容性证据，
因此 `CasinoConfig.use_surrogate` 默认 false。不是重新训练或把旧模型宣称为有效。
若使用 `--use-surrogate`，权重资产清单的 feasibility/steel 项必须给出一致且匹配当前实现的
`analysis_signature`（须先按真实验证/训练来源确认，不得直接填写以绕过检查）；权重文件哈希仍须匹配。
模型兼容性不满足时明确 BLOCKED，不进行筛选。仅 mock 集成可用旧权重检验软件机械行为。

```powershell
.venv/Scripts/python.exe -m struct_agent.diagnostics_cli --layout outputs/residential_001_rcgnn_03/layout.json --spec configs/etabs_12_story_spec.json --design outputs/residential_12_inputs_01/design.json --run outputs/new_diagnostic_run
.venv/Scripts/python.exe -m struct_agent.agent_cli --layout outputs/residential_001_rcgnn_03/layout.json --rooms outputs/residential_001_rcgnn_03/room_graph.json --spec configs/etabs_12_story_spec.json --run outputs/new_agent_run --case-id residential_001 --purpose smoke_only --policy rules --seed 42 --budget-fea 2 --population 2 --generations 1
```

诊断入口接受显式 `--design`；可用 `--reference` 对同一当前实现的记录做复算对照，拒绝跨实现对照。
使用新输出目录，避免覆盖。当前真实GA会被极短物理墙肢门槛拦截；先定位并解决离散/连接问题，再验证代理标签及正式优化。
