# 本地输出管理

| 用途 | 路径 |
|---|---|
| 当前布局、房间图及几何审查 | `outputs/current/residential_001/` |
| 当前12层设计 | `outputs/current/design_12_story/` |
| 工程条件 | `configs/residential_12_story.json` |
| 结构计算结果检查：固定输入重新计算，与保存的结果核对 | `outputs/reference/fea_12_story/`，输入和参考结果路径见 `configs/real_fea_reference.json` |
| 布置生成与优化流程测试：检查RC-GNN输出及优化继续运行的功能 | `outputs/reference/rcgnn_upstream/` |
| 后续正常业务报告 | `outputs/reports/` |
| 非比对的布置、迁移、Agent历史 | `outputs/archive/evidence_20261029.zip`，索引 `docs/outputs_archive_index.json` |

最终建模配置与已接受的软件差异统一见 [final_model.md](final_model.md)。
2026-10-30按用户明确要求，软件比对排查代码、报告、运行及原ZIP内的相关条目已直接删除，不再归档。
保留的非比对历史条目逐字节不变；图纸、权重、环境及密钥不属于本次清理范围。

正常业务运行仍创建新目录、保存可复现输入和结果，不覆盖既有分析。真实工程图纸、权重及运行文件不提交Git。
