# 最小运行代码迁移说明

2026-10-28。本轮按用户请求迁移专业工具，不推进 Agent 编排和 DWG 产品能力。

来源为 `E:/Common/Desktop/Research/deepLearning/codes/Png2Dxf`：

| 保留能力 | 私有运行模块 | 新公共入口 |
|---|---|---|
| RC-GNN | shearwall_pred 的模型/配置/必要预处理、data_engine 的房间图/墙段拓扑 | `adapters/rcgnn.py` |
| CASINO | GA、筛选、材料排序、在线局部校准、目标汇总 | `adapters/casino.py` |
| FuseGNN | model、推理所需 dataset/preprocessor、特征提取/room_v2 编码 | `adapters/casino_assets.py` |
| FEA | MVLEM、必要几何/荷载/谱分析/组合/校核/配筋依赖 | `adapters/fea.py` + `services/analysis.py` |

未迁移训练器、数据集生成主流程、批量论文实验、图像处理、绘图函数、CAD 插件、
ETABS/YJK、壳/等效框架建模器、Optuna/PSO 等额外优化器。
保留了运行类所依赖的原有内部方法；没有为追求行数减少而重写结构计算。

脚本通过 AST 提取运行依赖闭包，得到 48 个模块、约 5,176 行 Python。
每个源文件与目标文件 SHA256 均存于 `_vendor/migration_manifest.json`。
生成后的 vendor 修改会使 `--refresh` 拒绝覆盖；运行工件、权重和源数据也不覆盖。
本次源文件/资产 57 项哈希复核无变化。

明确改写范围：

1. 私有导入命名空间改为 `struct_agent._vendor`；清除训练/绘图导入和 import 时的日志副作用。
2. 推理数据集的 `CLASS_TASK` 改为相同常量，避免把训练工程引入运行。
3. FEA 仅保留 MVLEM 建模器；异常原样向 Adapter 抛出，保留完整异常上下文。
4. 原 `_evaluate_decision` 中的目标计算拆为 `summarize_analysis`，数值公式不变，真实求解经过统一预算入口。
5. 新 Adapter 关闭隐式几何放大，显式限制固定层高/板厚/材料口径；没有修改原工程的这些假设。
6. 新 Adapter 保留主次梁角色及构件 ID；离散域修复不生成域外墙厚值。

回归证据包括：原模型/迁移模型输出一致、四类核心算法 AST 一致、目标函数公式 AST 一致，
以及原 OpenSees/迁移版 35 字段数值比较（rtol=1e-5、atol=1e-8）。
这些是本地迁移回归，不是工程规范全覆盖、泛化有效性或优化性能验证。
