# StructLoop

住宅剪力墙布置、固定布置参数优化及结构分析的最小可复用工具。
规划见 [docs/PLAN.md](docs/PLAN.md)；接口证据见 [docs/upstream_contracts.md](docs/upstream_contracts.md)。

本项目从只读上游提取运行所需模块，不迁移训练、论文实验或 CAD 交互工程。
内部几何单位为 m；旧模型的 mm 特征与参数只在 Adapter 边界转换。
当前迁移状态、验证结果与限制见 [docs/progress.md](docs/progress.md)。

## 已迁入的最小能力

- RC-GNN：准备好的房间图或符合旧项目图层约定的 DXF → 五折推理 → 墙、主次梁、楼板拓扑。
- CASINO：固定布置 → FuseGNN 可行性筛选/钢筋量排序 → GA 参数搜索 → 真实 FEA → 独立局部校准缓冲区。
- OpenSees：仅 MVLEM_3D 建模、反应谱/静力组合、原有校核与配筋用量。

48 个旧工程运行模块（约 5,176 行）存放在私有 `src/struct_agent/_vendor/`；
新代码只通过 `schemas/`、`adapters/`、`services/analysis.py` 暴露公共接口。
不依赖旧仓库的 `sys.path`、训练工程或运行目录。来源与哈希见
[`migration_manifest.json`](src/struct_agent/_vendor/migration_manifest.json)。

## 环境

本地已建立 `.venv`，Python 3.12.12。终端默认 `python` 目前是 Windows Store 占位程序，
请激活环境或显式使用下述解释器。`requirements.lock.txt` 锁定实际安装版本，
不是对其他系统/CUDA 版本的兼容性声明。

```powershell
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -r requirements.lock.txt --extra-index-url https://download.pytorch.org/whl/cu124 --index-strategy unsafe-best-match
uv pip install --python .venv/Scripts/python.exe -e .
```

如果本地工件尚未导入，运行一次（现有文件会使导入停止，防止覆盖）：

```powershell
.venv/Scripts/python.exe -m scripts.import_local_assets
```

该开发脚本从只读上游复制 5 个 RC-GNN 权重、2 个 CASINO 权重及一个案例的 DXF/JSON，
验证 SHA256 后写入 `configs/local_assets.json`。大型权重、案例与运行输出已加入 Git 忽略。
迁移本身可由 `python -m scripts.migrate_runtime` 复现；日常运行无需再次迁移。

## 生成结构布置

默认工程测试案例为用户指定的 **residential_001**：
`data/local/residential_001/architecture_preprocessed.dxf`，原文件为 `archi_comp.dxf`。
来源、SHA256、类别及单位解释保存在 [configs/test_case.json](configs/test_case.json)。
后续真实生成、优化与闭环测试使用此图；L17_101 仅保留历史迁移回归，toy_01 仅保留 mock 测试。

```powershell
.venv/Scripts/python.exe -m struct_agent.cli generate --seed 42 --run outputs/current/new_residential_generation
```

默认入口校验 DXF 哈希并使用旧项目为此图指定的 `category=2`。
指定其他图时必须同时提供 `--dxf` 和 `--category`，不会从文件名或默认案例静默推断。
原文件头 `INSUNITS=6`（m），但坐标量级和上游处理约定是 mm；原文件逐字节保留，Adapter 按 mm 读取。
原图房间范围 27.1 × 12.5 m；旧算法的 200 mm 坐标对齐后为 27.1 × 12.3 m，保留原始全局原点。
当前 `symmetry_mode=none`，未迁入旧案例入口的 `union` 对称化后处理；这不是已审批结构方案。

目录必须是新的。保存 `manifest.json`、`room_graph.json`、`ratios.npy` 和 `layout.json`。
已有房间图可直接调用 `RCGNNAdapter.generate()`；字段和单位见
[公共数据契约](docs/data_contracts.md)。单一条件只生成一个确定性候选。

## 固定布置参数优化

```powershell
.venv/Scripts/python.exe -m struct_agent.cli optimize --layout outputs/current/residential_001/layout.json --rooms outputs/current/residential_001/room_graph.json --spec configs/etabs_12_story_spec.json --seed 42 --budget-fea 20 --population 24 --generations 20 --run outputs/current/new_residential_optimization
```

`reference_spec.json` **仅为迁移回归示例**，显式列出了旧入口的 28 层、2.9m 层高、
120mm 板厚及材料/地震参数。正式项目条件、荷载与规范版本仍需工程师确认。
上述命令采用获准用于诊断的12层条件，仍仅展示接口用法；当前布局含极短物理墙肢，会在真实优化前置检查处阻断。
整栋网格尚未收敛，先解决分析基础问题，再开展正式优化。
也可提供符合公共 Schema 的人工修改方案。
`--rooms` 必须对应该建筑，CASINO 每次从实际墙线重新编码布局特征，禁止套用另一布置缓存。

每次运行保存配置/输入/权重哈希、软件版本、源码哈希、逐次 FEA（含失败）、
OpenSees 日志、优化历史和结果。无 Git 时以源码哈希标识代码版本。
失败求解的 `feasible=null`；代理拒绝不会生成 FEA 记录。
历史被预算截断时 `history_complete=false`，已经完成的逐次分析仍保留。

### 在同一会话中继续优化

`CasinoSession` 保留同一布局的种群、GA/采样/探索随机状态、历史、预测缓存和局部校准器。
调用 `session.advance(1)` 推进一代，再次调用继续原会话；总世代上限来自 `CasinoConfig.generations`。
换布局或设计条件必须创建新会话；共享 `AnalysisService` 可继续使用同一全局 FEA 预算。

CLI 在上述 `optimize` 命令中添加 `--generations-per-step 1` 即逐代推进并保存每段记录。
需要在代际决策时使用后文 `agent_cli`。默认 `--device cpu` 用于可复现回归；
可显式选择 `--device cuda`，但 GPU 推理不保证逐数值完全一致。
不传 `--generations-per-step` 时一次执行，同样调用当前共用的生成引擎。

每段写入 `optimization/steps/advance_*.json`，包括种群、历史、随机状态、校准样本、
评价增量和错误；结束时写入 `history.json`、`summary.json`。当前仅支持**同进程、代际边界**续行，
这些 JSON 是审计快照，不是可从磁盘加载的恢复点。部分代因预算/求解异常中断后终止，不能重试该会话。

当前一代表示一个完成评价和排序的种群；没有被忽略的尾随种群。
`advance(1)` 不等于一次 FEA，实际次数由种群、代理与缓存决定。
可用 `--initial-design` 从已有结构参数开始；按可行性、违反量、材料成本排序，
并以真实反馈提出离散参数调整。流程与材料估算修正见 [优化迭代说明](docs/optimization_iteration.md)。

对应验证：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_incremental_ga.py
.venv/Scripts/python.exe -m pytest -q tests/integration/test_casino_session.py --run-real
```

后一组使用当前工程图和真实 FuseGNN 权重，但 **FEA 响应为明确标记的合成数据**，
只验证会话一致性、预算和隔离。它不证明新工程结构可行，也不代表真实局部校准效果。

## 模拟状态机（Phase 2 最小切片）

先生成一次合成算例（已存在则不覆盖），再运行新的输出目录：

```powershell
.venv/Scripts/python.exe scripts/make_dummy_case.py --out data/examples/toy_01
.venv/Scripts/python.exe -m struct_agent.cli run-case --case data/examples/toy_01/case.json --run outputs/current/my_mock_01 --seed 42 --budget-fea 4
```

默认在请求切换布局时停为 `WAITING_APPROVAL`。若要测试完整的模拟审批链，在新运行命令中
添加 `--approve-mock-layout layout_b`；此选项只表示显式允许该**模拟布局**切换，不代表工程师签审。
`--policy fixed` 可运行不换布局的固定流程。所有响应和摘要均标记 `mock`，未调用真实 FEA。

保存 `case.json`、`manifest.json`、`events.jsonl`、逐步 `states/`、`analyses/` 和 `summary.json`。
该算例使用预置候选队列；`CONTINUE_OPTIMIZATION` 目前在此入口中仅消费下一候选，尚未接入 CASINO 会话。
种子记录在 manifest；当前 fixture 与策略没有随机采样，同种子轨迹逐字节一致。

## 验证

```powershell
.venv/Scripts/python.exe scripts/audit_upstream.py --output docs/upstream_contracts.md
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest -q tests/integration/test_real_adapters.py -m real --run-real
```

最后一条是本机真实回归：RC-GNN 使用当前 residential_001 图纸；FEA 对照使用当前计算指纹的独立详细分析工件。
需要已经生成的参考工件，准备步骤及命令见
[进度记录](docs/progress.md)。普通测试默认跳过真实权重/求解器测试。

## Phase 4 决策与学校 LLM

已接入固定/规则/LLM 策略、CASINO 代际反馈、全局预算、布局切换审批及证据回放。
学校 API 默认绕过系统代理直连，密钥读取本地 `.env` 的 `apikey`，不会写入运行审计。
完整用法、真实与合成验证边界见 [Phase 4 使用说明](docs/phase4_agent.md)。

```powershell
.venv/Scripts/python.exe -m struct_agent.agent_cli --help
.venv/Scripts/python.exe -m pytest -q tests/unit/test_llm_policy.py tests/unit/test_optimization_env.py tests/unit/test_comparison.py
```

`outputs/archive/evidence_20261029.zip::phase4_real_llm_01/` 已完成“真实分析→LLM 再决策→再次真实分析”，
5 次 FEA 均求解成功但结构不可行，预算耗尽后模型请求人工检查；仅作冒烟。
用户已批准 `residential_001_symmetry_02` 作为本轮第二候选，批准绑定布局与设计条件哈希，
不代表正式工程签审。后续真实跨布局结果见 [进度记录](docs/progress.md)。

已补充可选构件级 FEA 诊断，可复算某条真实记录并保留控制构件、组合剪力及配筋消息：
`.venv/Scripts/python.exe -m struct_agent.diagnostics_cli --help`。
极短墙段、内力组合/包络、局部坐标及墙配筋漏检等问题已直接修复，见 [计算逻辑修正记录](docs/physics_fixes.md)。
分析分段已按直墙肢汇总；当前12层回归由 `configs/real_fea_reference.json` 绑定，旧28层诊断已退役。
新生成 `residential_001_rcgnn_03` 保留短墙原类别并输出几何审查；未消解短墙时真实优化会前置阻断。
本机已找到YJK 2025并验证官方API导入；成熟前处理与验算尚未接通，见 [模型语义与软件对照](docs/model_semantics.md)。
真实优化默认直接 FEA；旧代理权重在与修正后的标签验证兼容前不参与筛选。

## 当前边界

- 原工程 `axis_engine` 是 CAD/规则布置模块；真正的 RC-GNN 位于 `Png2Dxf/src/shearwall_pred`。
  本次没有把 CAD 插件及整套骨架提取工程搬进来。原生 DWG/任意图层解析未实现。
- 暂时沿用上游固定层高/板厚/分区材料口径；不支持的输入直接拒绝。
- 默认筛选阈值在迁移生成案例上拒绝了本轮候选；这不证明候选一定不可行。
  `--screening-threshold 0.0` 仅用于另行标记的调用链冒烟验证，不代表 CASINO 效率实验。
- 实际求解冒烟方案均未通过结构校核。没有宣称获得工程可行解或证明论文研究假设。
- 已接入真实 FEA 反馈和学校 LLM；审批文件只能来自受信任操作方，并绑定候选/条件/用途。
  从磁盘恢复及工程人工审批界面尚未实现；同进程会话和已获批候选可继续执行。
- 论文 Ours 的决策收益机制、正式对比及消融尚待研究设计与实验，不以冒烟替代科学结论。

## ETABS验证

ETABS小模型与12层住宅对照见 [docs/etabs_cross_validation.md](docs/etabs_cross_validation.md)。
使用可选 `etabs` 依赖（Windows comtypes、psutil）；与OpenSees比较时还需现有 `runtime` 环境。
固定入口为 `python -m struct_agent.etabs_cli`，只创建独立实例，不附着用户工程。
12层条件独立保存在 `configs/etabs_12_story_spec.json`，原28层配置不变。
当前只完成弹性水平诊断和解析解验证；新增检查发现两端整栋竖向网格敏感、尚未收敛，见 [子结构与网格检查](docs/x_displacement_checks.md)。尚未完成ETABS重力/反应谱/配筋复核，不能作为工程通过结论。

## Git 与本地数据

本地仓库使用 `main` 分支。每次任务完成并验证后更新进度记录、检查暂存内容并提交；不自动推送远端。
源码、测试、配置、合成 fixture 与数据哈希受版本管理；`.venv`、真实 DXF/DWG、权重、缓存、日志、
`outputs/` 和密钥文件被忽略。真实案例需保留本地副本或从配置中记录的来源恢复，再校验 SHA256。
输出保留规则、当前证据入口和清理记录见 [输出管理](docs/output_management.md)。
