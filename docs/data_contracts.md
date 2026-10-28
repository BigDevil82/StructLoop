# 公共数据契约 v1

所有公共 JSON 经 Pydantic 校验，禁止额外字段、非有限数值及隐式字符串转数值。
Python 接口接收不可变元组；JSON 接口使用 `model_validate_json()` 读取数组。
工具契约与 mock 状态机契约分开；后者暂不接收真实工程评价。

| 对象 | 必需内容 | 单位/Shape |
|---|---|---|
| `RoomGraph` | 原生特征、边、类别、房间多边形、8 半边掩码 | x float32[N,25]；edge_index int64[2,E]；edge_attr float32[E,8]；多边形 global XY m |
| `LayoutCandidate` | 布置 ID、来源、墙/主次梁、楼板多边形 | 构件端点 float64[M,2,2]，global XY m |
| `ProjectSpec` | 条件 ID、层数、层高、板厚、设防参数、规范说明、8 个具名离散变量 | 尺寸 m；材料 grade；人民币材料成本沿用上游价格口径 |
| `DesignCandidate` | 布置/条件/设计 ID、具名变量取值 | 与 `ProjectSpec` 域一致，墙厚自下而上不增加 |
| `AnalysisRecord` | 状态、fidelity、输入哈希、solver/版本、耗时、可行性、响应、错误、日志引用 | 成功真实响应按 `NativeResponse` 严格校验；失败可行性 null |
| `ErrorRecord` | 异常类型、原消息、traceback、上下文、attempt | 本轮不自动重试，attempt=1 |

`native_feature_length_unit="mm"` 表示原生几何预处理以 mm 为输入；x/edge_attr 中几何特征
按上游规则归一化，并非将其全部当作有量纲 mm 数值。公共几何转换为 m 后保存，
在原生图构建/墙段解码边界转换回 mm，**不对已编码的 x 再缩放**。
节点及房间顺序、上/右/下/左及每边的半边/端点顺序均保持原模型规则。

CASINO 参数的公共名保留原名：`tw_bot/tw_mid/tw_top` 为分区墙厚，
`hb_main/bb_main/hb_sec/bb_sec` 为主次梁高/宽，`conc_bot` 为统一混凝土等级。
Adapter 将 m 转为整数 mm；非整 mm 数值拒绝转换，不做静默舍入。
给定离散域修复墙厚时必须落在其声明域内；域不兼容时显式报错。
配筋由原 FEA 设计链计算，不作为本轮直接优化变量。

FEA 原生响应的周期为 s，材料用量 kg，总质量 t，其余公开响应为无量纲比值/布尔判定。
原建模器内部采用 m/N/Pa/kg；其内部应力与力不能直接当作公共 MPa/kN 使用。
当前 Adapter 只输出聚合比值和材料用量，尚无额外的构件内力交换 API。
刚度通过标志同时覆盖相邻层和平均层规则，上游只暴露相邻层最小值，不能仅由该值重建总判定。

`SUCCESS` 仅表示求解完整返回；`feasible=false` 表示真实校核/配筋不通过。
`MODEL_ERROR/SOLVER_ERROR/INVALID_RESULT` 均保持 `feasible=null`，不加入局部校准训练。
代理筛掉/排序未选中的项只存在优化历史中，不得计入真实 FEA 样本或可行解。
`fidelity="mock"` 的测试记录与真实运行分别保存，优化摘要保留同一标识。

每次优化都新建 `(layout, condition)` 实例、图缓存、特征和校准器。
布局文件名使用完整拓扑摘要，避免用户 ID 冲突/路径穿越；历史继续/恢复为后续任务。
最终工程状态固定为 `engineering_review=PENDING`，没有自动完成工程审批的接口。

## 模拟状态机契约

- `MockCase`：强制 `fidelity=mock`，固定 scenario 版本；引用已有布局、条件、参数 Schema，
  严格校验 ID、候选参数域与失败注入目标。预置候选队列不代表 CASINO 搜索轨迹。
- `DesignState`：保存当前布局/参数、求解状态、约束比、模拟目标、最佳模拟可行解、候选游标、
  预算消耗与待审批目标。`fea_budget_remaining` 由预算减已用次数计算，不另存冗余字段。
  `solver_status!=SUCCESS` 时 `feasible=null`。换布局清空当前响应，保留共享预算及各布局游标。
- `Decision`：四个动作 `CONTINUE_OPTIMIZATION/SWITCH_LAYOUT/REQUEST_HUMAN_REVIEW/FINALIZE`，
  记录理由和当前评价证据引用。只有换布局动作接受目标 ID，执行器检查动作前提。
- `DecisionEvent`：动作前后完整状态、相对证据路径、真实发生的 mock 调用增量；
  `mock_approval` 事件单独记录模拟审批来源。请求切换不会自行执行切换或耗费评价预算。

合成函数把墙线在 X/Y 方向上的投影长度（m）乘底部墙厚（m），与虚构的 2 m² 需求比较。
`synthetic_x/y` 为无量纲比值；`mock_score` 是总墙长乘墙厚得到的测试分数，不是材料费。
嵌套 `ProjectSpec.objective` 仅为复用参数契约保留原有值，mock 不执行其中的造价目标。
`COMPLETED` 仅指模拟终止条件达到，摘要始终 `engineering_review=NOT_PERFORMED`。
预算用尽、候选用尽、待审批及待检查分别记录，不等同于找到可行结构。
