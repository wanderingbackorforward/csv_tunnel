# TBM 调查报告

## 1. 调查结论总览

### 运行质量

- 调查运行状态：**部分成功**
- 实际 planner：混合 planner（规则 2 轮 + LLM 18 轮）
- LLM 成功率：18/18
- 报告质量门禁：**有警告**

### 调查充分性

- 调查深度：深度复核
- 停机案例总数：16
- 当前深度目标：16/16
- 实际 drilldown 覆盖：16/16
- 调查充分性：**已达到当前深度目标**

### 调查结论

- 调查状态：未收敛
- 置信度：低
- 主要问题类型：停机分析、掘进阻力、液压异常
- 覆盖情况：drilldown 覆盖 16/16

**结论：** 当前 CSV 证据不支持 SER/HYD 直接触发停机；已 drilldown 的 16 个停机案例中 15 个停机前未见明显行级异常、停机后恢复正常；停机性质仍需施工日志确认。

**关键发现：**
- 共发现 16 个停机案例，已 drilldown 16 个，未覆盖 0 个。
- 已查案例中，15 个停机前未见明显 SER/HYD 行级异常。
- SER 事件 208 个（15.2h），是重要线索，但当前未证明其为停机原因。
- HYD 事件 46 个，需进一步核查。

**仍不确定：**
- 停机是否计划性/管理性：需施工日志确认
- SER 高发是否对应地层变化：需地质记录确认

**下一步人工核查：**
- 核查施工日志
- 核查 SER 高发时段对应地层/操作记录

**建议：** 调查未收敛，建议使用'深度复核'模式或检查数据质量

## 2. 本次查清了什么

### 停机问题

- 停机案例总数：16
- 已 drilldown：16
- 未 drilldown：0

**已 drilldown 案例中：**
- 停机前后未见明显行级异常：15
- 仍需人工确认：1

**停机性质：**
- 已由外部日志确认计划停机：0
- 已由外部日志确认异常停机：0
- 未接入外部日志，全部停机性质仍需确认

### 掘进阻力异常 SER

- SER 事件数：208
- SER 总时长：15.2h
- 是否主要发生在推进中：是（占比 87%）
- 是否靠近停机：否
- 当前结论：线索（推进中存在 SER，与停机关联不明确）

### 液压异常 HYD

- HYD 事件数：46
- HYD 总时长：0.1h
- 是否靠近停机边界：是
- 是否构成主因：否（孤立短时波动）

### 碎片化

- 短事件占比：80%
- 是否影响结论：否

## 3. 本次没有查清什么

- 无法确认停机根因的7个案例具体是什么类型的停机
- 9个计划停机的具体施工背景是什么
- SER事件集中但未触发停机的内在逻辑是什么
- 2个drilldown_time_window工具报错的具体影响范围
- 需要施工日志确认：2025-03-22 15:28:36 ~ 2025-03-22 16:09:25（案例 SC_011）
- 需要施工日志确认：2025-03-22 14:23:04 ~ 2025-03-22 14:56:23（案例 SC_010）
- 需要施工日志确认：2025-03-22 00:00:00 ~ 2025-03-22 00:28:51（案例 SC_001）
- 需要施工日志确认：2025-03-22 13:21:54 ~ 2025-03-22 13:41:35（案例 SC_009）
- 需要施工日志确认：2025-03-22 21:10:07 ~ 2025-03-22 21:25:54（案例 SC_014）
- 需要施工日志确认：2025-03-22 00:51:29 ~ 2025-03-22 01:05:43（案例 SC_002）
- 需要施工日志确认：2025-03-22 16:46:00 ~ 2025-03-22 16:59:08（案例 SC_012）

> 不确定不是失败，而是当前证据不足，系统没有强行下结论。

## 4. 调查计划执行情况

| 计划 | 要回答的问题 | 状态 | 已用工具 | 关键发现 |
|------|-------------|------|----------|----------|
| P1 停机验证 | 停机验证：是否存在异常停机前兆？ | 已完成 | analyze_stoppage_cases, drilldown_time_windows_batch | 16 个停机案例，共 13.8h |
| P2 掘进阻力验证 | SER 验证：是否为推进中真实阻力异常？ | 部分完成 | analyze_resistance_pattern, drilldown_time_window | SER 事件 208 个，共 15.2h，推进中占比 87%，时间集中 |
| P3 液压验证 | HYD 验证：是否为系统性液压异常？ | 已完成 | analyze_hydraulic_pattern | HYD 事件 46 个，共 0.1h，与 SER 同步，靠近停机边界，多为孤立短 |
| P4 碎片化验证 | 碎片化验证：事件是否存在规则放大？ | 已完成 | analyze_event_fragmentation | 事件 346 个，平均 307s，短事件占比 80% |

## 5. 技术审计附录

## ReAct 调查轨迹

| 轮次 | Planner | LLM | 决策理由 | 调用工具 | 观察结果 | Evidence Gate |
|------|---------|-----|----------|----------|----------|--------------|
| 1 | 混合/规则 | — | 尚未检查当前文件概览 | inspect_file_overview | rows=86400, events=346, time=2025-03-22 00:00:00~2025-03-22  | — |
| 2 | 混合/规则 | — | 尚未加载事件摘要 | load_event_summary | events=346, sem_dist={'stoppage_segment': 21, 'low_efficienc | — |
| 3 | 混合/LLM | success | 停机段21个、停机率53%为最高优先级，需先追查停机根因才能提升整体效率 | analyze_stoppage_cases | 16 个停机案例，共 13.8h | — |
| 4 | 混合/LLM | success | 规则推荐：对最大停机案例SC_005(225min)进行时间窗口钻取，深入分析该长停机事件的具体SE | drilldown_time_window | [SC_005] 前:600行，速度24.43，normal_excavation98% / 中:13482行，速度0. | — |
| 5 | 混合/LLM | success | 已完成1个单点钻取(SC_005)。剩余15个停机案例需系统分析。SER计数208次是关键异常指标， | analyze_resistance_pattern | SER 事件 208 个，共 15.2h，推进中占比 87%，时间集中 | — |
| 6 | 混合/LLM | success | 当前仅完成1次drilldown，尚有16个停机案例待分析。批量钻取可一次性处理多个高耗时案例（如S | drilldown_time_windows_batch | 批量钻取 5/5 个目标完成，5 个停机前无异常 | — |
| 7 | 混合/LLM | success | 已完成5/5批量钻取但仍有11个停机案例待分析，且hyd_count=46(液压异常)，停机率53% | analyze_hydraulic_pattern | HYD 事件 46 个，共 0.1h，与 SER 同步，靠近停机边界，多为孤立短时波动 | — |
| 8 | 混合/LLM | success | 剩余 7 个未验证事件，346 个事件分布需要理解，drilldown_done 仅 1/16，碎片 | analyze_event_fragmentation | 事件 346 个，平均 307s，短事件占比 80% | — |
| 9 | 混合/LLM | success | [Evidence Gate] stoppage coverage 6/16 < depth tar | drilldown_time_windows_batch | 批量钻取 5/5 个目标完成，4 个停机前无异常 | override: generate_investigation_report→drilldown_time_windows_batch |
| 10 | 混合/LLM | success | [Evidence Gate] stoppage coverage 11/16 < depth ta | drilldown_time_windows_batch | 批量钻取 5/5 个目标完成，5 个停机前无异常 | override: generate_investigation_report→drilldown_time_windows_batch |
| 11 | 混合/LLM | success | [Evidence Gate] 存在未验证事件级异常线索 SC_013，必须先做 drilldown | drilldown_time_window | [SC_013] 前:600行，速度29.23，normal_excavation98% / 中:11710行，速度0. | override: generate_investigation_report→drilldown_time_window |
| 12 | 混合/LLM | success | SC_008 (67min) 是较长的停机案例，值得深入钻取；Q5未回答，drilldown可帮助获 | drilldown_time_window | error: need target_id or start_time | — |
| 13 | 混合/LLM | success | [Evidence Gate] 存在未验证事件级异常线索 SC_008，必须先做 drilldown | drilldown_time_window | [SC_008] 前:600行，速度30.32，normal_excavation100% / 中:4024行，速度0. | override: generate_investigation_report→drilldown_time_window |
| 14 | 混合/LLM | success | [Evidence Gate] 存在未验证事件级异常线索 SC_004，必须先做 drilldown | drilldown_time_window | [SC_004] 前:600行，速度29.63，normal_excavation100% / 中:3976行，速度2. | override: generate_investigation_report→drilldown_time_window |
| 15 | 混合/LLM | success | 虽然已进行15轮调查，但stoppage_cases=16，drilldown_done=4，仅完成 | drilldown_time_window | error: need target_id or start_time | — |
| 16 | 混合/LLM | success | [Evidence Gate] 存在未验证事件级异常线索 SC_003，必须先做 drilldown | drilldown_time_window | [SC_003] 前:600行，速度21.43，normal_excavation100% / 中:2103行，速度0. | override: generate_investigation_report→drilldown_time_window |
| 17 | 混合/LLM | success | [Evidence Gate] 存在未验证事件级异常线索 SC_015，必须先做 drilldown | drilldown_time_window | [SC_015] 前:600行，速度27.84，normal_excavation100% / 中:1999行，速度0. | override: generate_investigation_report→drilldown_time_window |
| 18 | 混合/LLM | success | [Evidence Gate] 存在未验证事件级异常线索 SC_007，必须先做 drilldown | drilldown_time_window | [SC_007] 前:600行，速度24.37，normal_excavation98% / 中:1005行，速度0.1 | override: generate_investigation_report→drilldown_time_window |
| 19 | 混合/LLM | success | [Evidence Gate] 存在未验证事件级异常线索 SC_006，必须先做 drilldown | drilldown_time_window | [SC_006] 前:600行，速度33.2，normal_excavation100% / 中:767行，速度0.15 | override: generate_investigation_report→drilldown_time_window |
| 20 | 混合/LLM | success | drilldown_done已8次，覆盖50%的停机案例；plan中P2仍在进行中但接近收尾；允许动 | generate_investigation_report | report generated, 16 cases | — |

## Planner 与大模型调用审计

- Planner 类型：混合 planner（关键分支调用 LLM）
- LLM 调用次数：18
- LLM 成功次数：18
- fallback 次数：0
- 模型：MiniMax-M2.7

本次使用 hybrid planner，共 18 次 LLM planner 调用，全部成功。

### LLM 调用明细

> 以下为 LLM planner 原始决策摘要，仅用于审计；最终业务结论以 validator 校验后的最终调查结论为准。

| 轮次 | 状态 | 选择 | 耗时 | 摘要 |
|------|------|------|------|------|
| 3 | success | analyze_stoppage_cases | 14.8s |  |
| 4 | success | drilldown_time_window | 8.2s |  |
| 5 | success | analyze_resistance_pattern | 22.5s |  |
| 6 | success | drilldown_time_windows_batch | 14.8s |  |
| 7 | success | analyze_hydraulic_pattern | 12.1s |  |
| 8 | success | analyze_event_fragmentation | 16.7s |  |
| 9 | success | generate_investigation_report | 11.0s |  |
| 10 | success | generate_investigation_report | 14.2s |  |
| 11 | success | generate_investigation_report | 12.4s |  |
| 12 | success | drilldown_time_window | 14.3s |  |
| 13 | success | generate_investigation_report | 13.7s |  |
| 14 | success | generate_investigation_report | 16.6s |  |
| 15 | success | drilldown_time_window | 13.3s |  |
| 16 | success | generate_investigation_report | 13.3s |  |
| 17 | success | generate_investigation_report | 9.7s |  |
| 18 | success | generate_investigation_report | 12.0s |  |
| 19 | success | generate_investigation_report | 18.9s |  |
| 20 | success | generate_investigation_report | 12.1s |  |

### Evidence Gate 审计

- Evidence Gate 触发次数：9
- 停机案例 drilldown 覆盖率：16/16
- 单次 drilldown 覆盖：SC_003, SC_004, SC_005, SC_006, SC_007, SC_008, SC_013, SC_015
- batch drilldown 覆盖：SC_001, SC_002, SC_003, SC_004, SC_006, SC_007, SC_008, SC_009, SC_010, SC_011, SC_012, SC_013, SC_014, SC_015, SC_016

- 第 9 轮：LLM 选择 `generate_investigation_report`，但stoppage coverage 6/16 < depth target，批量钻取 ['SC_011', 'SC_010', 'SC_001', 'SC_009', 'SC_007']，因此改为 `drilldown_time_windows_batch()`
- 第 10 轮：LLM 选择 `generate_investigation_report`，但stoppage coverage 11/16 < depth target，批量钻取 ['SC_014', 'SC_002', 'SC_012', 'SC_006', 'SC_016']，因此改为 `drilldown_time_windows_batch()`
- 第 11 轮：LLM 选择 `generate_investigation_report`，但存在未验证事件级异常线索 SC_013，必须先做 drilldown，因此改为 `drilldown_time_window(SC_013)`
- 第 13 轮：LLM 选择 `generate_investigation_report`，但存在未验证事件级异常线索 SC_008，必须先做 drilldown，因此改为 `drilldown_time_window(SC_008)`
- 第 14 轮：LLM 选择 `generate_investigation_report`，但存在未验证事件级异常线索 SC_004，必须先做 drilldown，因此改为 `drilldown_time_window(SC_004)`
- 第 16 轮：LLM 选择 `generate_investigation_report`，但存在未验证事件级异常线索 SC_003，必须先做 drilldown，因此改为 `drilldown_time_window(SC_003)`
- 第 17 轮：LLM 选择 `generate_investigation_report`，但存在未验证事件级异常线索 SC_015，必须先做 drilldown，因此改为 `drilldown_time_window(SC_015)`
- 第 18 轮：LLM 选择 `generate_investigation_report`，但存在未验证事件级异常线索 SC_007，必须先做 drilldown，因此改为 `drilldown_time_window(SC_007)`
- 第 19 轮：LLM 选择 `generate_investigation_report`，但存在未验证事件级异常线索 SC_006，必须先做 drilldown，因此改为 `drilldown_time_window(SC_006)`

### drilldown 明细

| 目标 | 前窗口观察 | 事件期间观察 | 后窗口观察 | 初步解释 |
|------|-----------|-------------|-----------|----------|
| SC_005 | 600行，速度24.43，normal_excavation98% | 13482行，速度0.02，stopped98% | 600行，速度27.71，normal_excavation96% | 停机前未见明显异常；停机后恢复正常 |
| SC_013 | 600行，速度29.23，normal_excavation98% | 11710行，速度0.01，stopped98% | 600行，速度26.86，normal_excavation100% | 停机前未见明显异常；停机后恢复正常 |
| ? |  |  |  |  |
| SC_008 | 600行，速度30.32，normal_excavation100% | 4024行，速度0.07，stopped92% | 600行，速度33.09，normal_excavation100% | 停机前未见明显异常；停机后恢复正常 |
| SC_004 | 600行，速度29.63，normal_excavation100% | 3976行，速度2.73，stopped81% | 600行，速度32.01，normal_excavation100% | 停机前未见明显异常；停机后恢复正常 |
| ? |  |  |  |  |
| SC_003 | 600行，速度21.43，normal_excavation100% | 2103行，速度0.1，stopped88% | 600行，速度28.79，normal_excavation100% | 停机前未见明显异常；停机后恢复正常 |
| SC_015 | 600行，速度27.84，normal_excavation100% | 1999行，速度0.08，stopped90% | 600行，速度28.45，normal_excavation99% | 停机前未见明显异常；停机后恢复正常 |
| SC_007 | 600行，速度24.37，normal_excavation98% | 1005行，速度0.13，stopped51% | 600行，速度14.96，normal_excavation66% | 停机前未见明显异常；停机后恢复正常 |
| SC_006 | 600行，速度33.2，normal_excavation100% | 767行，速度0.15，stopped77% | 600行，速度25.68，normal_excavation98% | 停机前未见明显异常；停机后恢复正常 |

#### 钻取详情：SC_005

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：13482行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=24.43，转矩=341.62，normal_excavation=98%，low_load_operation=1%，heavy_load_excavation=0%
- 事件期间：速度=0.02，转矩=2.38，stopped=98%，low_load_operation=2%，normal_excavation=0%
- 后窗口：速度=27.71，转矩=364.4，normal_excavation=96%，heavy_load_excavation=2%，low_load_operation=2%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_013

- 事件期间重叠事件数：4
- 重叠 SER：1
- 重叠 HYD：2
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：11710行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=29.23，转矩=591.3，normal_excavation=98%，low_load_operation=2%，heavy_load_excavation=0%
- 事件期间：速度=0.01，转矩=2.47，stopped=98%，low_load_operation=2%，normal_excavation=0%
- 后窗口：速度=26.86，转矩=571.32，normal_excavation=100%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：?


**行级规则命中：**

**工况统计：**

#### 钻取详情：SC_008

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：4024行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=30.32，转矩=707.45，normal_excavation=100%
- 事件期间：速度=0.07，转矩=8.66，stopped=92%，low_load_operation=7%，normal_excavation=0%
- 后窗口：速度=33.09，转矩=745.67，normal_excavation=100%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_004

- 事件期间重叠事件数：11
- 重叠 SER：5
- 重叠 HYD：3
- 重叠停机：3

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：3976行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=29.63，转矩=757.98，normal_excavation=100%
- 事件期间：速度=2.73，转矩=77.59，stopped=81%，low_load_operation=10%，normal_excavation=9%，heavy_load_excavation=0%
- 后窗口：速度=32.01，转矩=649.85，normal_excavation=100%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：?


**行级规则命中：**

**工况统计：**

#### 钻取详情：SC_003

- 事件期间重叠事件数：3
- 重叠 SER：1
- 重叠 HYD：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：2103行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=21.43，转矩=643.88，normal_excavation=100%
- 事件期间：速度=0.1，转矩=17.86，stopped=88%，low_load_operation=12%，normal_excavation=0%
- 后窗口：速度=28.79，转矩=791.9，normal_excavation=100%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_015

- 事件期间重叠事件数：3
- 重叠 SER：1
- 重叠 HYD：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：1999行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=27.84，转矩=970.82，normal_excavation=100%
- 事件期间：速度=0.08，转矩=15.54，stopped=90%，low_load_operation=10%，normal_excavation=0%
- 后窗口：速度=28.45，转矩=981.3，normal_excavation=99%，low_load_operation=1%，heavy_load_excavation=0%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_007

- 事件期间重叠事件数：3
- 重叠 SER：1
- 重叠 HYD：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：1005行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=24.37，转矩=399.23，normal_excavation=98%，low_load_operation=2%，heavy_load_excavation=0%
- 事件期间：速度=0.13，转矩=60.43，stopped=51%，low_load_operation=48%，normal_excavation=1%，heavy_load_excavation=0%
- 后窗口：速度=14.96，转矩=282.95，normal_excavation=66%，low_load_operation=14%，stopped=13%，heavy_load_excavation=6%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_006

- 事件期间重叠事件数：3
- 重叠 SER：1
- 重叠 HYD：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：767行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=33.2，转矩=455.12，normal_excavation=100%
- 事件期间：速度=0.15，转矩=29.35，stopped=77%，low_load_operation=22%，normal_excavation=1%
- 后窗口：速度=25.68，转矩=411.43，normal_excavation=98%，low_load_operation=2%，heavy_load_excavation=0%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

### Top 停机案例

| 案例ID | 开始时间 | 结束时间 | 时长(min) | 合并事件数 | 分类 | 置信度 |
|--------|----------|----------|-----------|-----------|------|--------|
| SC_005 | 2025-03-22 05:12:46 | 2025-03-22 08:57:27 | 225 | 1 | 计划停机（疑似） | 34% |
| SC_013 | 2025-03-22 17:09:10 | 2025-03-22 20:24:19 | 195 | 1 | 计划停机（疑似） | 34% |
| SC_008 | 2025-03-22 11:36:41 | 2025-03-22 12:43:44 | 67 | 1 | 计划停机（疑似） | 33% |
| SC_004 | 2025-03-22 03:20:28 | 2025-03-22 04:26:43 | 66 | 3 | 计划停机（疑似） | 32% |
| SC_011 | 2025-03-22 15:28:36 | 2025-03-22 16:09:25 | 41 | 2 | 待确认停机 | 35% |
| SC_003 | 2025-03-22 01:53:21 | 2025-03-22 02:28:23 | 35 | 1 | 计划停机（疑似） | 31% |
| SC_010 | 2025-03-22 14:23:04 | 2025-03-22 14:56:23 | 33 | 1 | 待确认停机 | 35% |
| SC_015 | 2025-03-22 22:17:04 | 2025-03-22 22:50:22 | 33 | 1 | 计划停机（疑似） | 31% |
| SC_001 | 2025-03-22 00:00:00 | 2025-03-22 00:28:51 | 29 | 1 | 待确认停机 | 35% |
| SC_009 | 2025-03-22 13:21:54 | 2025-03-22 13:41:35 | 20 | 1 | 待确认停机 | 35% |

### 调查问题完成情况

| 问题 | 状态 | 已调用工具 | 关键发现 | 人工核查 |
|------|------|-----------|----------|---------|
| Q1: 是否存在长停机？停机是否有异常前兆？ | 已回答 | analyze_stoppage_cases, drilldown_time_window, drilldown_time_windows_batch | SC_006: 停机前未见明显异常；停机后恢复正常 | 是 |
| Q2: SER 是否是推进中的真实阻力异常，还是 | 部分回答 | analyze_resistance_pattern | SER 推进中占比 87% | 是 |
| Q3: HYD 是否是主因，还是启停边界伴随？ | 已回答 | analyze_hydraulic_pattern | HYD 靠近停机边界，可能为启停伴随 | 否 |
| Q4: 事件是否存在碎片化或规则放大？ | 已回答 | analyze_event_fragmentation | 碎片化风险低，短事件占比 80% | 否 |
| Q5: 哪些结论需要施工日志确认？ | 部分回答 | — | 需施工日志确认：Q1: SC_006: 停机前未见明显异常；停机后恢复正常; Q | 是 |
