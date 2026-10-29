# 最终建模核对与已知差异的接受范围（2026-10-29）

本批从5afba18继续Phase 4，回应用户“继续找建模原因；确属单元差异则接受”的要求。
结论：**本轮未发现新的明确材料、截面、轴向或端区设置bug；证据支持将当前弹性对照剩余差异作为单元及梁墙耦合建模偏差收口，停止一致性校准。**
接受属于研究范围内的已知偏差处置，不将原大于等于5%的数值改判为通过，也不宣称已数学证明差异不可避免。

## 原整栋设置的最后核查

对归档中原始 `etabs_residential_12_euler_mesh4_01` 恢复指定EDB及缓存，核验整个ZIP的既有SHA256；
在专用实例内打开副本，对全部972根楼层梁（81条源梁×12层）读取截面、局部轴、插入、释放和分析线端区。
没有重新求解或保存EDB，源EDB/缓存及副本EDB字节哈希保持不变。

- 972根梁均为局部角0度、无高级轴、无弯曲释放；实际分析线两端长度偏移、RZ和插入偏移全部为0。
  因而原整栋的自动端区也不能解释现有差异，不仅是此前墙梁小模型的端区为0。
- 不按局部轴名称直接比较I22/I33与Iy/Iz：将惯性矩转为全局XYZ弯曲张量后比较。
  两软件全部972根梁的物理张量一致，最大相对差6.66e-16，未发现强弱轴颠倒。
- 新ETABS模型实际读回E=30GPa、nu约0.2、G=12.5GPa；墙厚160/200mm、ShellThin类型及膜/弯曲修正均与请求一致。
  没有为缩小差异调整材料或刚度系数。

首次补查打开EDB后直接GetElm返回码1，未生成可查询的分析图；失败目录完整保留。
修正受控诊断入口为在**副本**上先调用CreateAnalysisModel，再查询既有定义生成的线单元。
这是生成分析图，不调用RunAnalysis、不保存源模型；第二次查询成功，未以对象层自动端区占位值代替实际端区。

接口依据：[CSI梁变换矩阵](https://docs.csiamerica.com/help-files/etabs-api-2016/html/fa4f2d35-1740-d1f9-7164-a2ad9604afaa.htm)、
[CSI局部到全局方向余弦约定](https://docs.csiamerica.com/help-files/etabs-api-2016/html/5c7e36ef-0f7a-b3a8-1b11-77916018a048.htm)、
[CSI默认梁局部轴](https://docs.csiamerica.com/help-files/sap/Menus/Assign/Frame/Frame_Local_Axes.htm)。
矩阵约定另用全部实际梁的端点方向验证，未根据响应大小选择转置或互换截面轴。

## 纯墙反事实：分离梁墙耦合与墙单元近似

保持residential_001原布局、12×2.9m、分区墙厚、材料、固定底边、楼层刚性平面约束、原质量/惯量/中心和屋顶X/Y各1MN加载。
仅去掉全部972根梁的**刚度**；原梁几何贡献仍保留在双方一致的规定楼层质量与中心计算中，绝非实际无梁设计方案。
墙沿高度每层4片，不增加内部楼层质量、梁或刚性楼板。

原8个仅由梁连接的平面辅助点在12层共96个节点，移除梁后只参与水平楼板约束。
仅消去这些点未连接的UZ/RX/RY空自由度；不约束其UX/UY/RZ，不给墙节点增设支座。
独立几何检查确认8个辅助点都不在任何墙段上；双方96个辅助节点、楼层质量和中心一致。
这与上一批对仍有梁单元的节点添加支座完全不同，没有补造承重体系。

差异统一为abs(OpenSees−ETABS)/abs(ETABS)，不指定任一软件为真值：

| 同一纯墙模型的OpenSees单元 | 首层X | 首层Y | 屋顶X | 屋顶Y | 12阶周期最大差异 |
|---|---:|---:|---:|---:|---:|
| MVLEM_3D，原c=0.4，每层4片、纤维×2 | 13.55% | 12.82% | 4.49% | 3.82% | 13.47% |
| ShellDKGQ，同膜厚与板弯曲修正 | 0.28% | 0.26% | 0.14% | 0.10% | 0.81% |

ShellDKGQ与ETABS ShellThin的132项（12阶匹配周期、72项逐层UX/UY/RZ、48项平动层间位移角）全部小于5%，
最大差0.8125%；原整栋121个超限指标的同名项在这个探针中全部进入5%以内。
按用户规则，该纯墙壳对照关闭，不再校准。
MVLEM同条件99/132项通过，原121个超限同名项中99项在探针中通过，其余保留；不拼接其他探针的通过项。
两端求解均完成，稳定性/正特征值、整体平衡及有限响应检查通过。

## 能接受什么，还不能声称什么

1. 纯墙壳对照全部接近，而纯墙MVLEM仍有明显低层/高阶残差，支持将这一部分归于宏单元与壳的运动学/积分近似差异。
   此前中点积分探针已解释T形墙、墙梁组合的低层偏差；本轮没有为拟合结果改生产c=0.4。
2. 原带梁细网格MVLEM屋顶差14.97%/13.05%，移除梁刚度后降至4.49%/3.82%；
   原带梁ShellDKGQ屋顶差56.85%/25.81%，纯墙降至0.14%/0.10%。
   加上此前释放墙—墙梁弯矩的对照，说明梁墙转角兼容与连接耦合是另一重要通道。
   本轮轴、截面和原实际端区检查未发现可直接修正的参数错误。
3. 据这些受控对照，在**当前12层线弹性诊断条件和既有实现**下，剩余跨软件差异可按已知单元/连接建模偏差接受，
   停止追求数值一致的参数校准。不是“两个软件必然永远相差这些百分比”的证明；改变单元/连接建模方式仍可能缩小差异。
   如后续发现明确实现bug，仍须直接修正并更新适用结果。
4. 原整栋132项中的超限状态和全部1/2/4片结果原样保留。整栋2→4片仍明显变化，这是**各软件自身的网格可靠性问题**，
   不能用跨软件偏差接受来证明收敛。生产物理实现、指纹、布局、权重、GA门槛均未改变。
   本接受不外推至重力、反应谱、组合、规范配筋或正式优化有效性。

后续转向尚未覆盖的重力传递及谱/组合独立核对；整栋网格敏感性继续作为独立可靠性门槛记录，
不再通过反复调整E/G、泊松比、c或梁端刚度追求软件一致。

## 工件与验证

- 纯墙配对：`outputs/current/model_form_review_01/`；直接报告 `outputs/reports/model_form_review_01/`。
- 原整栋恢复来源：`outputs/current/model_form_original_01/`，13个指定文件、归档哈希及恢复映射。
- 原整栋实际端区/972梁轴审查：`outputs/current/model_form_original_audit_02/`；失败 `_01` 保留并排除有效查询结论。
- 最终处置和完整哈希入口：`outputs/reports/model_form_disposition_01/`、`configs/model_form_review_evidence.json`。
- 生产指纹仍为 `e49011b22005316c54e0bfcc858207ddaeb65a0935ddf3430631badae595ac62`。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_model_form_review.py tests/unit/test_connection_audit.py tests/unit/test_connection_study.py tests/unit/test_exceedance_causes.py tests/integration/test_structural_subsystem.py --run-real
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.model_form_review --run outputs/current/model_form_review_01 --report outputs/reports/model_form_review_01
.venv/Scripts/python.exe -m struct_agent.adapters.etabs.connection_audit --model outputs/current/model_form_original_01/model.EDB --run outputs/current/model_form_original_audit_02 --read-generated-lines --detailed-axes
.venv/Scripts/python.exe -m pytest -q
git diff --check
```

复跑须更换目录。最终目标20 passed（1.50s）；默认165 passed、34 skipped、1个既有PyG弃用提示（9.03s）。
纯墙ETABS123.70s，OpenSees MVLEM64.86s、ShellDKGQ52.71s；只读补查未重新求解。
首次入口曾因严格Schema用Python模式解析JSON列表而在创建运行前失败，已改为JSON模式；无失效数值被用于结论。
新增真实测试验证移除梁后质量保持、仅约束空自由度及两种墙单元稳定求解；单位测试覆盖强弱轴颠倒的检出和副本分析图查询。
