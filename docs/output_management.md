# 本地输出管理

outputs只保留四类目录，默认建筑仍为configs/test_case.json指定的residential_001。
图纸、权重、.env、.venv及用户API指南不属于结果清理范围。

```text
outputs/
├── current/       # 当前布局/房间图、12层参数
├── reference/     # 回归测试直接使用的文件
├── reports/       # 直接查看的X向/网格报告及ETABS对照
└── archive/       # 已完成运行的完整压缩证据
```

## 常用入口

| 用途 | 路径 |
|---|---|
| 当前布局/房间图/几何审查 | `outputs/current/residential_001/` |
| 当前12层条件与参数 | `configs/etabs_12_story_spec.json`、`outputs/current/design_12_story/design.json` |
| 同实现分析回归与构件覆盖 | `configs/real_fea_reference.json` → `outputs/reference/fea_12_story/` |
| 上游几何/会话集成测试 | `outputs/reference/rcgnn_upstream/`，原RC-GNN _02工件 |
| X向/网格诊断 | `outputs/reports/x_displacement/report.md` |
| ETABS独立对照 | `outputs/reports/etabs_comparison/report.md` |
| 同边界单墙解析/网格对照 | `outputs/reports/single_wall_12_02/report.md`，哈希/重试链见 `configs/single_wall_evidence.json` |
| 单墙正式原生证据 | `outputs/current/single_wall_12_02/`（10个ETABS、12个OpenSees工况） |
| 结构批量对照与5%逐项判定 | `outputs/reports/structural_comparison_01/`，索引 `configs/structural_comparison_evidence.json` |
| L/T形墙、墙梁组合原生证据及整栋归档输入副本 | `outputs/current/structural_comparison_01/` |
| 结构超限归因 | `outputs/reports/exceedance_causes_01/`，详细结论 `docs/exceedance_causes.md`，索引 `configs/exceedance_causes_evidence.json` |
| 梁墙壳替换补充及ETABS只读连接设置 | `outputs/{current,reports}/exceedance_wall_beam_shell_01/`、`outputs/current/connection_audit_{01,02}/` |
| 实际端区与梁墙弯矩通道汇总 | `outputs/reports/connection_diagnosis_01/`，索引 `configs/connection_diagnosis_evidence.json` |
| 墙梁/整栋连接探针 | `outputs/current/beam_wall_connection_01/`、`whole_connection_02/`；无效 `whole_connection_01/`完整保留且排除比较 |
| 最终纯墙配对与已知偏差处置 | `outputs/current/model_form_review_01/`；`outputs/reports/model_form_disposition_01/`，索引 `configs/model_form_review_evidence.json` |
| 原整栋实际端区/梁轴只读补查 | 来源 `outputs/current/model_form_original_01/`；有效 `model_form_original_audit_02/`，失败 `_01`保留；未重新求解 |
| 全部38个已完成运行 | `outputs/archive/evidence_20261029.zip`，原始目录名保持不变 |

归档整理时建立的当前输入、回归文件和原两份报告是逐字节副本，不是重新求解结果。
新增单墙报告来自本轮真实求解，不属于原38项归档。`single_wall_12_01`的失败/部分结果保留在current；
`single_wall_native_probe_01`为仅有输入/结果的初步Adapter试算，不参与配对结论。两者均由新证据索引注明。
完整原件均在ZIP中，包括原模型、原生日志、执行源代码、负面网格发现、YJK失败、LLM历史及批准记录。
归档前后逐文件SHA256核验。旧28层轨迹及RC-GNN旧版输出不能混作当前物理标签。
整栋网格仍未收敛，不因整理改变结论。

## 归档引用与恢复

索引为docs/outputs_archive_index.json，记录ZIP哈希、各原运行树哈希及当前副本映射。
文档中的 `outputs/archive/evidence_20261029.zip::<run>/file` 表示ZIP内成员，不是普通磁盘路径。
configs/solver_inventory.json中归档引用使用 `{archive, member}` 对象。
原manifest中的绝对路径保留为执行时证据；原 `outputs/<run>/...` 对应ZIP中的 `<run>/...`。
不能按已移除的旧绝对路径直接读文件，需查索引或解压后使用明确的新路径。

仅在检查原始求解模型时解压到新的临时目录，不覆盖当前视图：

```powershell
Expand-Archive -LiteralPath outputs/archive/evidence_20261029.zip -DestinationPath outputs/current/restored_evidence_01
```

后续运行统一在 `outputs/current/<new_run_id>` 创建新目录；当前副本和归档保持只读，不在原运行内挑删求解数据或改写manifest。
不设置按日期/编号自动删除。完成的小任务保留关键报告后可再次按用途归档。
上一轮直接删除的过期运行见cleanup_2026-10-29.json，其原始数据不在本ZIP中；哈希不能恢复已删除文件。
历史代码和文档由Git保存，例：`git show ef2c915:docs/progress.md`。
