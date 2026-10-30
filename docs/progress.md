# 当前进度

更新：2026-10-30。Phase 4，软件差异排查已按用户决定结束，回到结构受理、参数优化与Agent闭环工作。
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
| 同实现数值回归 | `configs/real_fea_reference.json` → `outputs/reference/fea_12_story/` |
| RC-GNN/会话回归 | `outputs/reference/rcgnn_upstream/` |

## 本次：固定方案并删除排查分支

起点e3e68ff，工作区干净。按用户明确授权直接删除ETABS/YJK排查适配器、CLI、专用测试、证据索引、探索文档、报告和运行目录，未重新归档。
原混合ZIP删去24个排查运行，保留的14个非比对运行、155个文件逐字节核验一致。
只保留一份简明建模结论；12层条件改用业务名称，文件内容和生产物理指纹保持不变。
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
默认1个、真实8个既有PyG/ezdxf弃用提示，无失败。回归输入哈希、生产物理指纹及保留ZIP条目核验通过；
无失效文档链接或已删除模块的代码引用，当前inputs/reference可继续使用。检查暂存内容后提交本地Git，不推送。
