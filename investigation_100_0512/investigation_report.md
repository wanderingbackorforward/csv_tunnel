# TBM 调查报告

## 1. 调查结论总览

### 运行质量

- 调查运行状态：**部分成功**
- 实际 planner：混合 planner（规则 2 轮 + LLM 17 轮）
- LLM 成功率：16/17
- 报告质量门禁：**有警告**

### 调查充分性

- 调查深度：深度复核
- 停机案例总数：9
- 当前深度目标：9/9
- 实际 drilldown 覆盖：9/9
- 调查充分性：**已达到当前深度目标**

### 调查结论

- 调查状态：部分收敛
- 置信度：中
- 主要问题类型：停机分析、掘进阻力、液压异常
- 覆盖情况：drilldown 覆盖 9/9

**结论：** 当前 CSV 证据不支持 SER/HYD 直接触发停机；已 drilldown 的 9 个停机案例中 9 个停机前未见明显行级异常、停机后恢复正常；停机性质仍需施工日志确认。

**关键发现：**
- 共发现 9 个停机案例，已 drilldown 9 个，未覆盖 0 个。
- 已查案例中，9 个停机前未见明显 SER/HYD 行级异常。
- SER 事件 241 个（19.1h），是重要线索，但当前未证明其为停机原因。
- HYD 事件 63 个，需进一步核查。

**仍不确定：**
- 停机是否计划性/管理性：需施工日志确认
- SER 高发是否对应地层变化：需地质记录确认

**下一步人工核查：**
- 核查施工日志
- 核查 SER 高发时段对应地层/操作记录

**建议：** 部分问题未查清，建议增加调查轮数或针对未覆盖案例做专项调查

## 2. 本次查清了什么

### 停机问题

- 停机案例总数：9
- 已 drilldown：9
- 未 drilldown：0

**已 drilldown 案例中：**
- 停机前后未见明显行级异常：9

**停机性质：**
- 已由外部日志确认计划停机：0
- 已由外部日志确认异常停机：0
- 未接入外部日志，全部停机性质仍需确认

### 掘进阻力异常 SER

- SER 事件数：241
- SER 总时长：19.1h
- 是否主要发生在推进中：是（占比 81%）
- 是否靠近停机：是
- 当前结论：部分支持（推进中存在 SER 且靠近停机）

### 液压异常 HYD

- HYD 事件数：63
- HYD 总时长：0.1h
- 是否靠近停机边界：是
- 是否构成主因：否（孤立短时波动）

### 碎片化

- 短事件占比：78%
- 是否影响结论：否
- 短事件占比：78%
- 是否影响结论：否

## 3. 本次没有查清什么

- 需要施工日志确认：2025-05-12 15:43:49 ~ 2025-05-12 16:12:14（案例 SC_007）
- 需要施工日志确认：2025-05-12 03:22:08 ~ 2025-05-12 03:44:32（案例 SC_002）

> 不确定不是失败，而是当前证据不足，系统没有强行下结论。

## 4. 调查计划执行情况

| 计划 | 要回答的问题 | 状态 | 已用工具 | 关键发现 |
|------|-------------|------|----------|----------|
| P1 停机验证 | 停机验证：是否存在异常停机前兆？ | 已完成 | analyze_stoppage_cases, drilldown_time_windows_batch | 9 个停机案例，共 16.4h |
| P2 掘进阻力验证 | SER 验证：是否为推进中真实阻力异常？ | 部分完成 | analyze_resistance_pattern, drilldown_time_window | SER 事件 241 个，共 19.1h，推进中占比 81%，时间集中，靠近停机 |
| P3 液压验证 | HYD 验证：是否为系统性液压异常？ | 已完成 | analyze_hydraulic_pattern | HYD 事件 63 个，共 0.1h，与 SER 同步，靠近停机边界，多为孤立短 |
| P4 碎片化验证 | 碎片化验证：事件是否存在规则放大？ | 已完成 | analyze_event_fragmentation | 事件 444 个，平均 304s，短事件占比 78% |

## 5. 技术审计附录

## ReAct 调查轨迹

| 轮次 | Planner | LLM | 决策理由 | 调用工具 | 观察结果 | Evidence Gate |
|------|---------|-----|----------|----------|----------|--------------|
| 1 | 混合/规则 | — | 尚未检查当前文件概览 | inspect_file_overview | rows=86400, events=444, time=2025-05-12 00:00:00~2025-05-12  | — |
| 2 | 混合/规则 | — | 尚未加载事件摘要 | load_event_summary | events=444, sem_dist={'stoppage_segment': 14, 'low_efficienc | — |
| 3 | 混合/LLM | success | 规则推荐：停机片段14个，停止率64%，停机案例优先追查可揭示SER高发的根本原因 | analyze_stoppage_cases | 9 个停机案例，共 16.4h | — |
| 4 | 混合/LLM | success | 首次钻取应聚焦最大停机案例。SC_008停机353分钟(占总量的36%)，钻取该窗口可获取最多信息用 | drilldown_time_window | [SC_008] 前:600行，速度23.25，normal_excavation84% / 中:21198行，速度0. | — |
| 5 | 混合/LLM | success | 规则推荐对SC_003(243min)停机案例做窗口钻取；已完成1次钻取，还有8个停机案例待钻取；需 | drilldown_time_window | [SC_003] 前:600行，速度22.97，normal_excavation100% / 中:14578行，速度0 | — |
| 6 | 混合/LLM | success | 已完成2个停机案例钻取（SC_003），还有7个案例待处理。批量钻取可提高效率，且SC_003已展示 | drilldown_time_windows_batch | 批量钻取 5/5 个目标完成，5 个停机前无异常 | — |
| 7 | 混合/LLM | success | 批量钻取5/5完成但显示drilldown_done=2存在数据不一致，且stoppage_case | drilldown_time_windows_batch | 批量钻取 2/2 个目标完成，2 个停机前无异常 | — |
| 8 | 混合/LLM | success | 9个停机案例中只完成2个钻取，剩余7个待处理，规则推荐对SC_004(153min)停机案例进行窗口 | drilldown_time_window | error: need target_id or start_time | — |
| 9 | 混合/LLM | success | 钻取动作连续失败5次(last_obs报错)，应转为分析已积累的241个SER阻力异常数据，理解停机 | analyze_resistance_pattern | SER 事件 241 个，共 19.1h，推进中占比 81%，时间集中，靠近停机 | — |
| 10 | 混合/LLM | success | Q3-Q5未回答，SER推进中占比81%且时间集中需液压侧解释。hyd_count:63数据已积累但 | analyze_hydraulic_pattern | HYD 事件 63 个，共 0.1h，与 SER 同步，靠近停机边界，多为孤立短时波动 | — |
| 11 | 混合/LLM | api_error | 对停机案例 SC_004 (153min) 做窗口钻取 | drilldown_time_window | [SC_004] 前:600行，速度13.08，normal_excavation91% / 中:9182行，速度0.0 | — |
| 12 | 混合/LLM | success | [Evidence Gate] 存在未验证事件级异常线索 SC_001，必须先做 drilldown | drilldown_time_window | [SC_001] 前:600行，速度37.11，normal_excavation98% / 中:8419行，速度0.0 | override: generate_investigation_report→drilldown_time_window |
| 13 | 混合/LLM | success | 规则推荐：对 SC_007 (28min) 做窗口钻取；仍有3个未验证案例需排查；drilldown | drilldown_time_window | error: need target_id or start_time | — |
| 14 | 混合/LLM | success | drilldown_time_window已执行4次并返回错误，规则推荐动作无法继续。SER数量24 | analyze_event_fragmentation | 事件 444 个，平均 304s，短事件占比 78% | — |
| 15 | 混合/LLM | success | [Evidence Gate] 存在未验证事件级异常线索 SC_006，必须先做 drilldown | drilldown_time_window | [SC_006] 前:600行，速度20.23，normal_excavation95% / 中:1072行，速度0.1 | override: generate_investigation_report→drilldown_time_window |
| 16 | 混合/LLM | success | 已完成5个钻取案例，仍有2个未验证；Q5未回答且可能涉及事件碎片化模式；444事件中仅63个液压事件 | analyze_event_fragmentation | 事件 444 个，平均 304s，短事件占比 78% | — |
| 17 | 混合/LLM | success | [Evidence Gate] 存在未验证事件级异常线索 SC_005，必须先做 drilldown | drilldown_time_window | [SC_005] 前:600行，速度26.39，normal_excavation93% / 中:874行，速度0.22 | override: generate_investigation_report→drilldown_time_window |
| 18 | 混合/LLM | success | [Evidence Gate] 存在未验证事件级异常线索 SC_009，必须先做 drilldown | drilldown_time_window | [SC_009] 前:600行，速度35.48，normal_excavation97% / 中:763行，速度0.29 | override: generate_investigation_report→drilldown_time_window |
| 19 | 混合/LLM | success | drilldown_done=7，stoppage_cases=9，仍有2个停机案例未钻取，但all | generate_investigation_report | report generated, 9 cases | — |

## Planner 与大模型调用审计

- Planner 类型：混合 planner（关键分支调用 LLM）
- LLM 调用次数：17
- LLM 成功次数：16
- fallback 次数：1
- 模型：MiniMax-M2.7

本次使用 hybrid planner，共 17 次 LLM 调用，16 次成功，1 次 fallback 到规则。

### LLM 调用明细

> 以下为 LLM planner 原始决策摘要，仅用于审计；最终业务结论以 validator 校验后的最终调查结论为准。

| 轮次 | 状态 | 选择 | 耗时 | 摘要 |
|------|------|------|------|------|
| 3 | success | analyze_stoppage_cases | 11.2s |  |
| 4 | success | drilldown_time_window | 8.5s |  |
| 5 | success | drilldown_time_window | 13.1s |  |
| 6 | success | drilldown_time_windows_batch | 11.3s |  |
| 7 | success | drilldown_time_windows_batch | 14.9s |  |
| 8 | success | drilldown_time_window | 13.9s |  |
| 9 | success | analyze_resistance_pattern | 11.7s |  |
| 10 | success | analyze_hydraulic_pattern | 20.2s |  |
| 11 | api_error | — | 16.4s | APIConnectionError: Connection error. |
| 12 | success | generate_investigation_report | 26.0s |  |
| 13 | success | drilldown_time_window | 10.0s |  |
| 14 | success | analyze_event_fragmentation | 15.2s |  |
| 15 | success | generate_investigation_report | 12.9s |  |
| 16 | success | analyze_event_fragmentation | 12.6s |  |
| 17 | success | generate_investigation_report | 18.1s |  |
| 18 | success | generate_investigation_report | 9.6s |  |
| 19 | success | generate_investigation_report | 20.5s |  |

### Evidence Gate 审计

- Evidence Gate 触发次数：4
- 停机案例 drilldown 覆盖率：9/9
- 单次 drilldown 覆盖：SC_001, SC_003, SC_004, SC_005, SC_006, SC_008, SC_009
- batch drilldown 覆盖：SC_001, SC_002, SC_004, SC_005, SC_006, SC_007, SC_009

- 第 12 轮：LLM 选择 `generate_investigation_report`，但存在未验证事件级异常线索 SC_001，必须先做 drilldown，因此改为 `drilldown_time_window(SC_001)`
- 第 15 轮：LLM 选择 `generate_investigation_report`，但存在未验证事件级异常线索 SC_006，必须先做 drilldown，因此改为 `drilldown_time_window(SC_006)`
- 第 17 轮：LLM 选择 `generate_investigation_report`，但存在未验证事件级异常线索 SC_005，必须先做 drilldown，因此改为 `drilldown_time_window(SC_005)`
- 第 18 轮：LLM 选择 `generate_investigation_report`，但存在未验证事件级异常线索 SC_009，必须先做 drilldown，因此改为 `drilldown_time_window(SC_009)`

### drilldown 明细

| 目标 | 前窗口观察 | 事件期间观察 | 后窗口观察 | 初步解释 |
|------|-----------|-------------|-----------|----------|
| SC_008 | 600行，速度23.25，normal_excavation84% | 21198行，速度0.08，stopped99% | 600行，速度33.28，normal_excavation96% | 停机前未见明显异常；停机后恢复正常 |
| SC_003 | 600行，速度22.97，normal_excavation100% | 14578行，速度0.02，stopped97% | 600行，速度10.84，normal_excavation71% | 停机前未见明显异常；停机后恢复正常 |
| ? |  |  |  |  |
| SC_004 | 600行，速度13.08，normal_excavation91% | 9182行，速度0.04，stopped70% | 600行，速度11.57，normal_excavation81% | 停机前未见明显异常；停机后恢复正常 |
| SC_001 | 600行，速度37.11，normal_excavation98% | 8419行，速度0.02，stopped98% | 600行，速度32.79，normal_excavation95% | 停机前未见明显异常；停机后恢复正常 |
| ? |  |  |  |  |
| SC_006 | 600行，速度20.23，normal_excavation95% | 1072行，速度0.15，stopped72% | 600行，速度16.79，normal_excavation72% | 停机前未见明显异常；停机后恢复正常 |
| SC_005 | 600行，速度26.39，normal_excavation93% | 874行，速度0.22，stopped89% | 600行，速度21.88，normal_excavation96% | 停机前未见明显异常；停机后恢复正常 |
| SC_009 | 600行，速度35.48，normal_excavation97% | 763行，速度0.29，stopped80% | 600行，速度34.21，normal_excavation93% | 停机前未见明显异常；停机后恢复正常 |

#### 钻取详情：SC_008

- 事件期间重叠事件数：4
- 重叠 SER：2
- 重叠停机：2

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：21198行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=23.25，转矩=833.88，normal_excavation=84%，low_load_operation=16%，heavy_load_excavation=0%
- 事件期间：速度=0.08，转矩=4.24，stopped=99%，low_load_operation=1%，normal_excavation=0%
- 后窗口：速度=33.28，转矩=1179.67，normal_excavation=96%，low_load_operation=4%，heavy_load_excavation=0%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_003

- 事件期间重叠事件数：3
- 重叠 SER：1
- 重叠 HYD：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：14578行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=22.97，转矩=937.23，normal_excavation=100%
- 事件期间：速度=0.02，转矩=6.25，stopped=97%，low_load_operation=3%，normal_excavation=0%
- 后窗口：速度=10.84，转矩=588.58，normal_excavation=71%，low_load_operation=16%，heavy_load_excavation=13%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：?


**行级规则命中：**

**工况统计：**

#### 钻取详情：SC_004

- 事件期间重叠事件数：5
- 重叠 SER：2
- 重叠 HYD：1
- 重叠停机：2

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：9182行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=13.08，转矩=659.82，normal_excavation=91%，low_load_operation=9%，heavy_load_excavation=0%
- 事件期间：速度=0.04，转矩=33.25，stopped=70%，low_load_operation=29%，normal_excavation=2%
- 后窗口：速度=11.57，转矩=601.6，normal_excavation=81%，low_load_operation=18%，heavy_load_excavation=1%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_001

- 事件期间重叠事件数：3
- 重叠 SER：1
- 重叠 HYD：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：8419行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=37.11，转矩=1333.37，normal_excavation=98%，low_load_operation=2%，heavy_load_excavation=0%
- 事件期间：速度=0.02，转矩=3.58，stopped=98%，low_load_operation=2%，normal_excavation=0%
- 后窗口：速度=32.79，转矩=1261.2，normal_excavation=95%，low_load_operation=4%，heavy_load_excavation=1%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：?


**行级规则命中：**

**工况统计：**

#### 钻取详情：SC_006

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：1072行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=20.23，转矩=880.1，normal_excavation=95%，low_load_operation=5%
- 事件期间：速度=0.15，转矩=43.85，stopped=72%，low_load_operation=27%，normal_excavation=1%
- 后窗口：速度=16.79，转矩=706.3，normal_excavation=72%，low_load_operation=28%，heavy_load_excavation=1%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_005

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：874行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=26.39，转矩=1116.82，normal_excavation=93%，low_load_operation=7%，heavy_load_excavation=0%
- 事件期间：速度=0.22，转矩=30.8，stopped=89%，low_load_operation=9%，normal_excavation=2%
- 后窗口：速度=21.88，转矩=940.85，normal_excavation=96%，low_load_operation=4%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_009

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：763行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=35.48，转矩=1386.6，normal_excavation=97%，low_load_operation=3%
- 事件期间：速度=0.29，转矩=43.11，stopped=80%，low_load_operation=18%，normal_excavation=1%
- 后窗口：速度=34.21，转矩=1253.58，normal_excavation=93%，low_load_operation=7%，heavy_load_excavation=1%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

### Top 停机案例

| 案例ID | 开始时间 | 结束时间 | 时长(min) | 合并事件数 | 分类 | 置信度 |
|--------|----------|----------|-----------|-----------|------|--------|
| SC_008 | 2025-05-12 16:42:13 | 2025-05-12 22:35:30 | 353 | 2 | 计划停机（疑似） | 34% |
| SC_003 | 2025-05-12 04:52:49 | 2025-05-12 08:55:46 | 243 | 1 | 计划停机（疑似） | 32% |
| SC_004 | 2025-05-12 10:41:10 | 2025-05-12 13:14:11 | 153 | 2 | 计划停机（疑似） | 34% |
| SC_001 | 2025-05-12 00:10:52 | 2025-05-12 02:31:10 | 140 | 1 | 计划停机（疑似） | 34% |
| SC_007 | 2025-05-12 15:43:49 | 2025-05-12 16:12:14 | 28 | 1 | 待确认停机 | 35% |
| SC_002 | 2025-05-12 03:22:08 | 2025-05-12 03:44:32 | 22 | 1 | 待确认停机 | 35% |
| SC_006 | 2025-05-12 14:45:30 | 2025-05-12 15:03:21 | 18 | 1 | 计划停机（疑似） | 31% |
| SC_005 | 2025-05-12 14:13:29 | 2025-05-12 14:28:02 | 15 | 1 | 计划停机（疑似） | 31% |
| SC_009 | 2025-05-12 23:13:37 | 2025-05-12 23:26:19 | 13 | 1 | 计划停机（疑似） | 31% |

### 调查问题完成情况

| 问题 | 状态 | 已调用工具 | 关键发现 | 人工核查 |
|------|------|-----------|----------|---------|
| Q1: 是否存在长停机？停机是否有异常前兆？ | 已回答 | analyze_stoppage_cases, drilldown_time_window, drilldown_time_windows_batch | SC_009: 停机前未见明显异常；停机后恢复正常 | 是 |
| Q2: SER 是否是推进中的真实阻力异常，还是 | 部分回答 | analyze_resistance_pattern | SER 推进中占比 81% | 是 |
| Q3: HYD 是否是主因，还是启停边界伴随？ | 已回答 | analyze_hydraulic_pattern | HYD 靠近停机边界，可能为启停伴随 | 否 |
| Q4: 事件是否存在碎片化或规则放大？ | 已回答 | analyze_event_fragmentation | 碎片化风险低，短事件占比 78% | 否 |
| Q5: 哪些结论需要施工日志确认？ | 部分回答 | — | 需施工日志确认：Q1: SC_009: 停机前未见明显异常；停机后恢复正常; Q | 是 |
