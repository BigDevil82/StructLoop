# 当前进度

更新：2026-10-30。Phase 4，软件差异排查已按用户决定结束，继续建模前检查、参数优化和Agent功能开发。
统一建模配置和已接受的差异仅见 [final_model.md](final_model.md)，不再保留逐轮排查记录或相关待办。

## 当前能力

- RC-GNN生成、CASINO/GA会话、真实OpenSees与学校LLM调用链已接通；尚未证明正式优化或论文策略收益。
- 唯一结构建模器为完整有梁MVLEM_3D粗网格，原已修正的物理、组合、构件汇总与校核逻辑继续保留。
- 建筑固定为residential_001；12层条件仍沿用原批准用途，图纸确认不代替正式工程条件或最终签审。
- 当前布局仍有物理短墙前置审查事项；旧代理标签未经兼容验证，正式筛选默认禁用代理。
- 已有运行未得到通过全部工程校核的设计；人工交互、磁盘恢复、DWG成果及正式对比/消融属于后续工作。

## 当前入口

| 用途 | 路径 |
|---|---|
| 建筑布局/房间图 | `outputs/current/residential_001/` |
| 12层条件 | `configs/residential_12_story.json` |
| 当前设计 | `outputs/current/design_12_story/design.json` |
| 生产建模 | `src/struct_agent/adapters/fea.py`、`src/struct_agent/_vendor/shearwall_modeling/builders/mvlem_frame.py` |
| 结构计算结果检查（与之前保存的结果核对） | `configs/real_fea_reference.json` → `outputs/reference/fea_12_story/` |
| 布置生成与优化流程测试（检查RC-GNN输出及优化继续运行的功能） | `outputs/reference/rcgnn_upstream/` |

## 本次：把说明改为直白用词

按用户后续要求，本次只修改现有文字，不补写探索过程，也不恢复已删除文件。
将表格中的名称改为“结构计算结果检查”和“布置生成与优化流程测试”，并直接说明检查内容。
README及现有说明中的同类说法已统一修改；`AGENTS.md`新增用词要求，后续回复、文档、界面说明和注释优先使用直白表述。
程序、计算参数、命令示例和已有数值结论不变。文档检查及测试完成后本地提交，不推送。
文档链接、命令示例及已有建模数值检查通过；`.venv/Scripts/python.exe -m pytest -q`：106项通过、19项按默认设置跳过（7.43s），有1条第三方库的既有弃用提示。

## 上次：固定方案并删除排查分支

起点e3e68ff，工作区干净。按用户明确授权直接删除ETABS/YJK排查适配器、CLI、专用测试、证据索引、探索文档、报告和运行目录，未重新归档。
原混合ZIP删去24个排查运行，保留的14个非比对运行、155个文件逐字节核验一致。
只保留一份简明建模结论；12层条件改用业务名称，文件内容和计算代码版本校验值保持不变。
README、PLAN、ROADMAP、执行约定及输出管理已统一，不再要求继续软件比对。

本次没有重新求解商业模型、训练模型、调用学校LLM或执行正式优化。
验证命令：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_fea_physics.py tests/integration/test_opensees_beam_mechanics.py tests/integration/test_mvlem_panel_mechanics.py tests/integration/test_wall_pier_mechanics.py tests/integration/test_real_adapters.py::test_real_fea_matches_current_detailed_result --run-real
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest -q --run-real
git diff --check
```

目标19 passed（35.37s）；默认106 passed、19 skipped（24.49s）；完整真实125 passed（38.98s）。
默认1个、真实8个既有PyG/ezdxf弃用提示，无失败。结果检查所用输入哈希、计算代码版本校验值及保留ZIP条目核验通过；
无失效文档链接或已删除模块的代码引用，当前输入和参考结果可继续使用。检查暂存内容后提交本地Git，不推送。
