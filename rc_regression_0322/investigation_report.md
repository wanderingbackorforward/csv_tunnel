# TBM 停机调查报告

## 1. 一句话结论

当前 CSV 证据不支持 SER 直接触发停机；停机窗口中未见明显 HYD 行级异常；已逐案检查的 16 个停机案例中 15 个停机前未见明显行级异常、停机后恢复正常；停机性质仍需施工日志确认。

**关键发现：**
- 共发现 16 个停机案例，已逐案检查 16 个，未覆盖 0 个。
- 已查案例中，15 个停机前未见明显 SER/HYD 行级异常。
- SER 事件 208 个（15.2h），是重要线索，但当前未证明其为停机原因。
- HYD 事件 46 个，需进一步核查。

## 2. 这一天发生了什么

- 时间范围：2025-03-22 00:00:00 ~ 2025-03-22 23:59:59
- 共识别出 **16 段停机**，合计 **13.8h**
- 已逐案检查 16/16 段
- 最长一段停了 225 分钟（2025-03-22 05:12:46 ~ 2025-03-22 08:57:27）
- 当天共识别异常事件 346 个（停机相关 21 段、SER 207 个、HYD 46 个）

## 3. 最值得人工核查的停机段

以下停机段按时长从长到短排列，建议优先核查排在前面的案例。

| 优先级 | 案例 | 时间段 | 时长 | CSV 观察结论 | 建议核查原因 |
|--------|------|--------|------|-------------|-------------|
| 1 | SC_005 | 2025-03-22 05:12:46 ~ 2025-03-22 08:57:27 | 225min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 2 | SC_013 | 2025-03-22 17:09:10 ~ 2025-03-22 20:24:19 | 195min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 3 | SC_008 | 2025-03-22 11:36:41 ~ 2025-03-22 12:43:44 | 67min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 4 | SC_004 | 2025-03-22 03:20:28 ~ 2025-03-22 04:26:43 | 66min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 5 | SC_011 | 2025-03-22 15:28:36 ~ 2025-03-22 16:09:25 | 41min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 6 | SC_003 | 2025-03-22 01:53:21 ~ 2025-03-22 02:28:23 | 35min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 7 | SC_010 | 2025-03-22 14:23:04 ~ 2025-03-22 14:56:23 | 33min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 8 | SC_015 | 2025-03-22 22:17:04 ~ 2025-03-22 22:50:22 | 33min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 9 | SC_001 | 2025-03-22 00:00:00 ~ 2025-03-22 00:28:51 | 29min | 停机后恢复正常 | 性质待施工日志确认 |
| 10 | SC_009 | 2025-03-22 13:21:54 ~ 2025-03-22 13:41:35 | 20min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |

## 4. 我们已经查清了什么

### 4.1 停机

- 停机案例总数：16
- 已逐案检查：16
- 检查结果：**15 段**停机前后未见明显异常
- 1 段需人工进一步确认
- 未接入施工日志，停机性质（计划/异常）暂无法判定

### 4.2 掘进阻力异常（SER）

> SER = 疑似掘进阻力异常，即推进过程中遇到的地层阻力突然升高。

- SER 事件数：208 次
- SER 总时长：15.2h
- 其中推进中发生：87%
- 当前判断：推进中存在 SER，但与停机的关联不明确

### 4.3 液压异常（HYD）

HYD 事件 46 个，需进一步核查。

### 4.4 碎片化

- 短事件占比：80%
- 碎片化风险低，事件统计可信

## 5. 还不能下结论的地方

- 停机是否计划性/管理性：需施工日志确认
- SER 高发是否对应地层变化：需地质记录确认
- SC_005：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_013：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_008：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_004：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_003：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_015：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_007：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_006：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- 施工日志确认：2025-03-22 15:28:36 ~ 2025-03-22 16:09:25（SC_011）
- 施工日志确认：2025-03-22 14:23:04 ~ 2025-03-22 14:56:23（SC_010）
- 施工日志确认：2025-03-22 00:00:00 ~ 2025-03-22 00:28:51（SC_001）
- 施工日志确认：2025-03-22 13:21:54 ~ 2025-03-22 13:41:35（SC_009）
- 施工日志确认：2025-03-22 21:10:07 ~ 2025-03-22 21:25:54（SC_014）
- 施工日志确认：2025-03-22 00:51:29 ~ 2025-03-22 01:05:43（SC_002）
- 施工日志确认：2025-03-22 16:46:00 ~ 2025-03-22 16:59:08（SC_012）

> 以上不确定项是因为当前 CSV 数据不足以给出确定结论，需要结合施工日志或其他外部证据进一步判断。

## 6. 下一步怎么查

1. 确认停机性质（SC_005、SC_013、SC_008、SC_004、SC_011等）：计划安排、检修/换刀、等待、交接班、外部调度或异常停机
2. 核查 SER 高发时段对应的地层和操作记录，判断是否为地层变化导致
3. 核查施工日志

## 7. 技术附录

> 以下为技术审计信息，供系统开发者或审计人员参考。

## ReAct 调查轨迹

| 轮次 | Planner | LLM | 决策理由 | 调用工具 | 观察结果 | Evidence Gate |
|------|---------|-----|----------|----------|----------|--------------|
| 1 | 混合/规则 | — | 尚未检查当前文件概览 | inspect_file_overview | rows=86400, events=346, time=2025-03-22 00:00:00~2025-03-22 | — |
| 2 | 混合/规则 | — | 尚未加载事件摘要 | load_event_summary | events=346, sem_dist={'stoppage_segment': 21, 'low_efficienc | — |
| 3 | 混合/LLM | success | stopped_pct=53%，stoppage_segment=21，高停机率需优先追查；anal | analyze_stoppage_cases | 16 个停机案例，共 13.8h | — |
| 4 | 混合/LLM | success | 按规则推荐，对剩余停机案例中停机时长最长的SC_005 (225min) 进行窗口钻取，开始深入分析 | drilldown_time_window | [SC_005] 前:600行，速度24.43，normal_excavation98% / 中:13482行，速度0. | — |
| 5 | 混合/LLM | success | [已修正] → SC_003, SC_004, SC_008, SC_013, SC_015 | drilldown_time_windows_batch | 批量钻取 5/5 个目标完成，5 个停机前无异常 | — |
| 6 | 混合/LLM | success | 已钻取6个案例，5个显示停机前无异常，继续批量钻取可能收效有限。液压异常46个虽少但停了53%案例， | analyze_hydraulic_pattern | HYD 事件 46 个，共 0.1h，需核查统计口径 | — |
| 7 | 混合/LLM | success | SC_013已在already_drilled_sc_ids中，规则推荐违反硬约束。SER数据208 | analyze_resistance_pattern | SER 事件 208 个，共 15.2h，推进中占比 87%，时间集中 | — |
| 8 | 混合/LLM | success | SER占比87%且时间高度集中是严重异常信号，但规则推荐的drilldown_time_window | analyze_event_fragmentation | 事件 346 个，平均 307s，短事件占比 80% | — |
| 9 | 混合/LLM | success | [Evidence Gate] stoppage coverage 6/16 < depth tar | drilldown_time_windows_batch | 批量钻取 5/5 个目标完成，4 个停机前无异常 | override: generate_investigation_report→drilldown_time_windows_batch |
| 10 | 混合/LLM | success | [Evidence Gate] stoppage coverage 11/16 < depth ta | drilldown_time_windows_batch | 批量钻取 5/5 个目标完成，5 个停机前无异常 | override: generate_investigation_report→drilldown_time_windows_batch |
| 11 | 混合/LLM | success | 所有16个停机案例已完成钻取，remaining_sc_ids为空，无法继续钻取。P1/P3/P4已 | generate_investigation_report | report generated, 16 cases | — |

## Planner 与大模型调用审计

- Planner 类型：混合 planner（关键分支调用 LLM）
- LLM 调用次数：9
- LLM 成功次数：9
- fallback 次数：0
- 模型：MiniMax-M2.7

本次使用 hybrid planner，共 9 次 LLM planner 调用，全部成功。

### LLM 调用明细

> 以下为 LLM planner 决策摘要，仅用于审计；最终业务结论以 validator 校验后的调查结论为准。

| 轮次 | 状态 | 选择 | 耗时 | 摘要 |
|------|------|------|------|------|
| 3 | success | analyze_stoppage_cases | 9.7s |  |
| 4 | success | drilldown_time_window | 7.0s |  |
| 5 | success | drilldown_time_windows_batch | 27.9s |  |
| 6 | success | analyze_hydraulic_pattern | 14.1s |  |
| 7 | success | analyze_resistance_pattern | 10.1s |  |
| 8 | success | analyze_event_fragmentation | 10.8s |  |
| 9 | success | generate_investigation_report | 20.2s |  |
| 10 | success | generate_investigation_report | 11.2s |  |
| 11 | success | generate_investigation_report | 7.9s |  |

### Evidence Gate 审计

- Evidence Gate 触发次数：2
- 停机案例 drilldown 覆盖率：16/16
- 单次 drilldown 覆盖：SC_005
- batch drilldown 覆盖：SC_001, SC_002, SC_003, SC_004, SC_006, SC_007, SC_008, SC_009, SC_010, SC_011, SC_012, SC_013, SC_014, SC_015, SC_016

- 第 9 轮：LLM 选择 `generate_investigation_report`，但stoppage coverage 6/16 < depth target，批量钻取 ['SC_011', 'SC_010', 'SC_001', 'SC_009', 'SC_007']，因此改为 `drilldown_time_windows_batch()`
- 第 10 轮：LLM 选择 `generate_investigation_report`，但stoppage coverage 11/16 < depth target，批量钻取 ['SC_014', 'SC_002', 'SC_012', 'SC_006', 'SC_016']，因此改为 `drilldown_time_windows_batch()`

### drilldown 明细

| 目标 | 前窗口观察 | 事件期间观察 | 后窗口观察 | 初步解释 |
|------|-----------|-------------|-----------|----------|
| SC_005 | 600行，速度24.43，normal_excavation98% | 13482行，速度0.02，stopped98% | 600行，速度27.71，normal_excavation96% | 停机前未见明显异常；停机后恢复正常 |
| SC_013 | 600行，速度29.23，normal_excavation98% | 11710行，速度0.01，stopped98% | 600行，速度26.86，normal_excavation100% | 停机前未见明显异常；停机后恢复正常 |
| SC_008 | 600行，速度30.32，normal_excavation100% | 4024行，速度0.07，stopped92% | 600行，速度33.09，normal_excavation100% | 停机前未见明显异常；停机后恢复正常 |
| SC_004 | 600行，速度29.63，normal_excavation100% | 3976行，速度2.73，stopped81% | 600行，速度32.01，normal_excavation100% | 停机前未见明显异常；停机后恢复正常 |
| SC_003 | 600行，速度21.43，normal_excavation100% | 2103行，速度0.1，stopped88% | 600行，速度28.79，normal_excavation100% | 停机前未见明显异常；停机后恢复正常 |
| SC_015 | 600行，速度27.84，normal_excavation100% | 1999行，速度0.08，stopped90% | 600行，速度28.45，normal_excavation99% | 停机前未见明显异常；停机后恢复正常 |
| SC_011 | 600行，速度41.58，normal_excavation100% | 2450行，速度3.77，stopped80% | 600行，速度39.59，normal_excavation97% | 停机前未见明显异常；停机后恢复正常 |
| SC_010 | 600行，速度37.44，normal_excavation100% | 2000行，速度0.08，stopped93% | 600行，速度40.06，normal_excavation97% | 停机前未见明显异常；停机后恢复正常 |
| SC_001 | 无数据 | 1732行，速度0.07，stopped94% | 600行，速度38.08，normal_excavation100% | 停机后恢复正常 |
| SC_009 | 600行，速度41.08，normal_excavation100% | 1182行，速度0.13，stopped82% | 600行，速度33.75，normal_excavation100% | 停机前未见明显异常；停机后恢复正常 |
| SC_007 | 600行，速度24.37，normal_excavation98% | 1005行，速度0.13，stopped51% | 600行，速度14.96，normal_excavation66% | 停机前未见明显异常；停机后恢复正常 |
| SC_014 | 600行，速度19.74，normal_excavation100% | 948行，速度0.16，stopped80% | 600行，速度33.96，normal_excavation100% | 停机前未见明显异常；停机后恢复正常 |
| SC_002 | 600行，速度28.47，normal_excavation100% | 855行，速度0.15，stopped81% | 600行，速度31.0，normal_excavation97% | 停机前未见明显异常；停机后恢复正常 |
| SC_012 | 600行，速度40.88，normal_excavation100% | 789行，速度0.15，stopped68% | 600行，速度29.25，normal_excavation98% | 停机前未见明显异常；停机后恢复正常 |
| SC_006 | 600行，速度33.2，normal_excavation100% | 767行，速度0.15，stopped77% | 600行，速度25.68，normal_excavation98% | 停机前未见明显异常；停机后恢复正常 |
| SC_016 | 600行，速度28.88，normal_excavation100% | 722行，速度0.12，stopped81% | 无数据 | 停机前未见明显异常 |

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

#### 钻取详情：SC_011

- 事件期间重叠事件数：4
- 重叠 SER：2
- 重叠停机：2

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：2450行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=41.58，转矩=850.42，normal_excavation=100%
- 事件期间：速度=3.77，转矩=93.95，stopped=80%，low_load_operation=10%，normal_excavation=10%
- 后窗口：速度=39.59，转矩=848.53，normal_excavation=97%，low_load_operation=3%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_010

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：2000行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=37.44，转矩=906.2，normal_excavation=100%
- 事件期间：速度=0.08，转矩=12.29，stopped=93%，low_load_operation=7%，normal_excavation=0%
- 后窗口：速度=40.06，转矩=914.25，normal_excavation=97%，low_load_operation=3%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_001

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 事件期间：1732行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 事件期间：速度=0.07，转矩=12.58，stopped=94%，low_load_operation=6%，normal_excavation=0%
- 后窗口：速度=38.08，转矩=1093.2，normal_excavation=100%

- 初步解释: 停机后恢复正常
- 转变发现: 停机→恢复转变

#### 钻取详情：SC_009

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：1182行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=41.08，转矩=924.92，normal_excavation=100%，low_load_operation=0%
- 事件期间：速度=0.13，转矩=28.04，stopped=82%，low_load_operation=18%，normal_excavation=1%
- 后窗口：速度=33.75，转矩=869.43，normal_excavation=100%

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

#### 钻取详情：SC_014

- 事件期间重叠事件数：3
- 重叠 SER：1
- 重叠 HYD：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：948行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=19.74，转矩=504.15，normal_excavation=100%
- 事件期间：速度=0.16，转矩=24.63，stopped=80%，low_load_operation=19%，normal_excavation=1%
- 后窗口：速度=33.96，转矩=871.15，normal_excavation=100%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_002

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：855行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=28.47，转矩=901.45，normal_excavation=100%
- 事件期间：速度=0.15，转矩=28.49，stopped=81%，low_load_operation=18%，normal_excavation=1%
- 后窗口：速度=31.0，转矩=931.45，normal_excavation=97%，low_load_operation=3%，heavy_load_excavation=0%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_012

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：789行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=40.88，转矩=761.92，normal_excavation=100%
- 事件期间：速度=0.15，转矩=35.68，stopped=68%，low_load_operation=32%，normal_excavation=1%
- 后窗口：速度=29.25，转矩=590.77，normal_excavation=98%，low_load_operation=2%，heavy_load_excavation=0%

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

#### 钻取详情：SC_016

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：722行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=28.88，转矩=975.42，normal_excavation=100%
- 事件期间：速度=0.12，转矩=22.76，stopped=81%，low_load_operation=18%，normal_excavation=1%

- 初步解释: 停机前未见明显异常
- 转变发现: 推进→停机转变

### Top 停机案例

| 案例ID | 开始时间 | 结束时间 | 时长(min) | 合并事件数 | 分类 | 置信度 |
|--------|----------|----------|-----------|-----------|------|--------|
| SC_005 | 2025-03-22 05:12:46 | 2025-03-22 08:57:27 | 225 | 1 | 性质待施工日志确认 | 34% |
| SC_013 | 2025-03-22 17:09:10 | 2025-03-22 20:24:19 | 195 | 1 | 性质待施工日志确认 | 34% |
| SC_008 | 2025-03-22 11:36:41 | 2025-03-22 12:43:44 | 67 | 1 | 性质待施工日志确认 | 33% |
| SC_004 | 2025-03-22 03:20:28 | 2025-03-22 04:26:43 | 66 | 3 | 性质待施工日志确认 | 32% |
| SC_011 | 2025-03-22 15:28:36 | 2025-03-22 16:09:25 | 41 | 2 | 性质待施工日志确认 | 35% |
| SC_003 | 2025-03-22 01:53:21 | 2025-03-22 02:28:23 | 35 | 1 | 性质待施工日志确认 | 31% |
| SC_010 | 2025-03-22 14:23:04 | 2025-03-22 14:56:23 | 33 | 1 | 性质待施工日志确认 | 35% |
| SC_015 | 2025-03-22 22:17:04 | 2025-03-22 22:50:22 | 33 | 1 | 性质待施工日志确认 | 31% |
| SC_001 | 2025-03-22 00:00:00 | 2025-03-22 00:28:51 | 29 | 1 | 性质待施工日志确认 | 35% |
| SC_009 | 2025-03-22 13:21:54 | 2025-03-22 13:41:35 | 20 | 1 | 性质待施工日志确认 | 35% |

### 证据一致性检查

**分类修正：**
- SC_005: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_005: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_005: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_005: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_013: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_013: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_013: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_013: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_008: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_008: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_008: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_004: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_004: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_004: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_011: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_003: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_003: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_003: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_003: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_010: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_015: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_015: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_015: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_015: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_001: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_009: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_007: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_007: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_007: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_007: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_014: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_002: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_002: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_012: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_006: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_006: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_006: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_006: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾

**已验证案例：**
- SC_005：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_013：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_008：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_004：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_003：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_015：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_007：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_006：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认

### 调查问题完成情况

| 问题 | 状态 | 已调用工具 | 关键发现 | 人工核查 |
|------|------|-----------|----------|---------|
| Q1: 是否存在长停机？停机是否有异常前兆？ | 已回答 | analyze_stoppage_cases, drilldown_time_window, drilldown_time_windows_batch | SC_016: 停机前未见明显异常 | 是 |
| Q2: SER 是否是推进中的真实阻力异常，还是 | 部分回答 | analyze_resistance_pattern | SER 推进中占比 87% | 是 |
| Q3: HYD 是否是主因，还是启停边界伴随？ | 已回答 | analyze_hydraulic_pattern | HYD 需先核查统计口径 | 否 |
| Q4: 事件是否存在碎片化或规则放大？ | 已回答 | analyze_event_fragmentation | 碎片化风险低，短事件占比 80% | 否 |
| Q5: 哪些结论需要施工日志确认？ | 部分回答 | — | 需施工日志确认：Q1: SC_016: 停机前未见明显异常; Q2: SER 推 | 是 |
