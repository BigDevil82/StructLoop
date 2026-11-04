# StructLoop

住宅结构设计Agent：复用RC-GNN、CASINO和OpenSees，逐步完成方案生成、查询、修改和真实分析反馈。

## 从哪里阅读

| 文档 | 只负责什么 |
|---|---|
| [PLAN.md](docs/PLAN.md) | 项目目标、近期重点和后置范围 |
| [progress.md](docs/progress.md) | 当前完成情况、关键验证结果和原始证据入口 |
| [phase4_agent.md](docs/phase4_agent.md) | Agent运行命令、工具协议与输出 |
| [final_model.md](docs/final_model.md) | 唯一建模配置、校核假定及工程边界 |
| [RESEARCH_ROADMAP.md](docs/RESEARCH_ROADMAP.md) | 尚待检验的研究问题与评价口径 |
| [AGENTS.md](AGENTS.md) | 开发协作纪律 |

同一事项只在所属文档维护；其他文档用链接引用。详细过程留在Git历史和原始运行记录，不再逐轮追加到多份文档。

## 环境与本地数据

本地使用Python 3.12和`.venv`；依赖版本见`requirements.lock.txt`。

```powershell
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -r requirements.lock.txt --extra-index-url https://download.pytorch.org/whl/cu124 --index-strategy unsafe-best-match
uv pip install --python .venv/Scripts/python.exe -e .
```

默认真实案例为`configs/test_case.json`指定的`residential_001`（原图`archi_comp.dxf`）。
DXF、权重和密钥不入Git；本地资产缺失时可运行`scripts.import_local_assets`，来源与哈希由配置记录。
内部几何单位为m，原生mm参数在Adapter边界转换；原图单位解释见案例配置。

## 入口

生成一份布局及房间图，输出目录必须是新的：

```powershell
.venv/Scripts/python.exe -m struct_agent.cli generate --seed 42 --run outputs/current/new_layout
```

先查看生成目录的`geometry_review.json`与`junction_preprocessing.json`，需要修复的物理短墙会阻断真实优化。
Agent完整命令见[运行说明](docs/phase4_agent.md#运行)；其他入口可直接查看帮助：

```powershell
.venv/Scripts/python.exe -m struct_agent.agent_cli --help
.venv/Scripts/python.exe -m struct_agent.cli optimize --help
.venv/Scripts/python.exe -m struct_agent.diagnostics_cli --help
```

最终验收默认只运行一次：

```powershell
.venv/Scripts/python.exe -B -m pytest -q --run-real -p no:cacheprovider
```

开发时先跑相关目标测试。部分集成测试使用真实权重和合成FEA，仅验证流程；工程证据必须来自`fidelity=full`。

## 代码与结果

公共契约在`schemas/`，专业接口在`adapters/`，统一分析记账在`services/analysis.py`，编排在`workflows/`。
`src/struct_agent/_vendor/`为受保护的专业计算库，修改约束见AGENTS。
`outputs/`、缓存、权重、真实图纸和`.env`被忽略；运行目录不可覆盖，重要结果由manifest及输入/代码/物理指纹追溯。
当前回归参考由`configs/real_fea_reference.json`索引，旧输出索引为`docs/outputs_archive_index.json`。
