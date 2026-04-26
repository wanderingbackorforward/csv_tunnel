# TBM 调查报告

## 1. 结论摘要

### 调查对象

- 文件：sample2.xls
- 时间范围：2025-02-22 00:00:00 ~ 2025-02-22 23:59:59
- 调查深度：深度复核
- 停机案例：10 个，总时长 17.4h
- 逐案钻取（drilldown）：10/10

**结论：** 当前 CSV 证据不支持 SER/HYD 直接触发停机；已 drilldown 的 10 个停机案例中 9 个停机前未见明显行级异常、停机后恢复正常；停机性质仍需施工日志确认。

**关键发现：**
- 共发现 10 个停机案例，已 drilldown 10 个，未覆盖 0 个。
- 已查案例中，9 个停机前未见明显 SER/HYD 行级异常。
- SER 事件 39 个（18.5h），是重要线索，但当前未证明其为停机原因。

**仍不确定：**
- 停机是否计划性/管理性：需施工日志确认
- SER 高发是否对应地层变化：需地质记录确认

**下一步人工核查：**
- 核查施工日志
- 核查 SER 高发时段对应地层/操作记录

**建议：** 部分问题需外部证据确认：；核查施工日志；核查 SER 高发时段对应地质/操作记录；核查检修/换刀/班次记录

### 调查充分性

- 调查深度：深度复核
- 停机案例总数：10
- 当前深度目标：10/10
- 实际逐案钻取覆盖：10/10
- 调查充分性：**已达到当前深度目标**

### 技术状态摘要（开发者参考）

- 调查运行状态：**部分成功**
- 实际 planner：混合 planner（规则 2 轮 + LLM 8 轮）
- LLM 成功率：8/8
- 报告质量门禁：**有警告**

## 2. 本次查清了什么

### 停机问题

- 停机案例总数：10
- 已逐案钻取：10
- 未逐案钻取：0

**已逐案钻取案例中：**
- 停机前后未见明显行级异常：9
- 仍需人工确认：1

**停机性质：**
- 已由外部日志确认计划停机：0
- 已由外部日志确认异常停机：0
- 未接入外部日志，全部停机性质仍需确认

### 掘进阻力异常 SER

- SER 事件数：39
- SER 总时长：18.5h
- 是否主要发生在推进中：否（占比 8%）
- 是否靠近停机：是
- 当前结论：未支持

### 液压异常 HYD

未执行液压分析。

### 碎片化

- 短事件占比：16%
- 是否影响结论：否

## 3. 本次没有查清什么

- 停机是否计划性/管理性：需施工日志确认
- SER 高发是否对应地层变化：需地质记录确认
- 需要施工日志确认：2025-02-22 14:30:04 ~ 2025-02-22 15:11:27（案例 SC_007）
- 需要施工日志确认：2025-02-22 12:07:17 ~ 2025-02-22 12:41:44（案例 SC_005）
- 需要施工日志确认：2025-02-22 23:17:40 ~ 2025-02-22 23:46:17（案例 SC_010）
- 需要施工日志确认：2025-02-22 15:51:21 ~ 2025-02-22 16:19:12（案例 SC_008）

> 不确定不是失败，而是当前证据不足，系统没有强行下结论。

## 4. 调查计划执行情况

| 计划 | 要回答的问题 | 状态 | 已用工具 | 关键发现 |
|------|-------------|------|----------|----------|
| P1 停机验证 | 停机验证：是否存在异常停机前兆？ | 已完成 | analyze_stoppage_cases, drilldown_time_windows_batch | 10 个停机案例，共 17.4h |
| P2 掘进阻力验证 | SER 验证：是否为推进中真实阻力异常？ | 部分完成 | analyze_resistance_pattern, drilldown_time_window | SER 事件 39 个，共 18.5h，推进中占比 8%，时间集中，靠近停机 |
| P3 液压验证 | HYD 验证：是否为系统性液压异常？ | 因轮数不足跳过 | analyze_hydraulic_pattern |  |
| P4 碎片化验证 | 碎片化验证：事件是否存在规则放大？ | 已完成 | analyze_event_fragmentation | 事件 81 个，平均 1642s，短事件占比 16% |

## 5. 技术审计附录

## ReAct 调查轨迹

| 轮次 | Planner | LLM | 决策理由 | 调用工具 | 观察结果 | Evidence Gate |
|------|---------|-----|----------|----------|----------|--------------|
| 1 | 混合/规则 | — | 尚未检查当前文件概览 | inspect_file_overview | rows=86400, events=81, time=2025-02-22 00:00:00~2025-02-22 2 | — |
| 2 | 混合/规则 | — | 尚未加载事件摘要 | load_event_summary | events=81, sem_dist={'stoppage_segment': 12, 'low_efficiency | — |
| 3 | 混合/LLM | success | 规则推荐，停机段12个且停止率71%，需分析停机模式特征 | analyze_stoppage_cases | 10 个停机案例，共 17.4h | — |
| 4 | 混合/LLM | success | SC_003停机356分钟（5.9小时），占10个案例总停机时间的34%，是最大停机案例且未被钻取。 | drilldown_time_window | [SC_003] 前:600行，速度35.35，normal_excavation90% / 中:21344行，速度0. | — |
| 5 | 混合/LLM | success | SC_009拥有330分钟长停机，是高价值钻取目标；已完成1/10钻取，需继续覆盖remaining | drilldown_time_window | [SC_006] 前:600行，速度34.34，normal_excavation83% / 中:1465行，速度0.1 | — |
| 6 | 混合/LLM | success | 规则推荐对SC_009(330min)做窗口钻取，SC_009在remaining_sc_ids中符 | drilldown_time_windows_batch | 批量钻取 5/5 个目标完成，4 个停机前无异常 | — |
| 7 | 混合/LLM | success | SER（掘进阻力异常）占比39/81最高，且已有7个案例窗口钻取完成，analyze_resista | analyze_resistance_pattern | SER 事件 39 个，共 18.5h，推进中占比 8%，时间集中，靠近停机 | — |
| 8 | 混合/LLM | success | SC_009 已在 already_drilled_sc_ids 中，违反硬约束。SER 事件集中在 | analyze_event_fragmentation | 事件 81 个，平均 1642s，短事件占比 16% | — |
| 9 | 混合/LLM | success | [Evidence Gate] stoppage coverage 7/10 < depth tar | drilldown_time_windows_batch | 批量钻取 3/3 个目标完成，3 个停机前无异常 | override: generate_investigation_report→drilldown_time_windows_batch |
| 10 | 混合/LLM | success | 所有10个停机案例已完成钻取（SC_001-SC_010），remaining_sc_ids为空，无 | generate_investigation_report | report generated, 10 cases | — |

## Planner 与大模型调用审计

- Planner 类型：混合 planner（关键分支调用 LLM）
- LLM 调用次数：8
- LLM 成功次数：8
- fallback 次数：0
- 模型：MiniMax-M2.7

本次使用 hybrid planner，共 8 次 LLM planner 调用，全部成功。

### LLM 调用明细

> 以下为 LLM planner 原始决策摘要，仅用于审计；最终业务结论以 validator 校验后的最终调查结论为准。

| 轮次 | 状态 | 选择 | 耗时 | 摘要 |
|------|------|------|------|------|
| 3 | success | analyze_stoppage_cases | 13.9s |  |
| 4 | success | drilldown_time_window | 9.0s |  |
| 5 | success | drilldown_time_window | 8.2s |  |
| 6 | success | drilldown_time_windows_batch | 19.5s |  |
| 7 | success | analyze_resistance_pattern | 23.2s |  |
| 8 | success | analyze_event_fragmentation | 11.8s |  |
| 9 | success | generate_investigation_report | 14.7s |  |
| 10 | success | generate_investigation_report | 14.5s |  |

### Evidence Gate 审计

- Evidence Gate 触发次数：1
- 停机案例 drilldown 覆盖率：10/10
- 单次 drilldown 覆盖：SC_003, SC_006
- batch drilldown 覆盖：SC_001, SC_002, SC_004, SC_005, SC_007, SC_008, SC_009, SC_010

- 第 9 轮：LLM 选择 `generate_investigation_report`，但stoppage coverage 7/10 < depth target，批量钻取 ['SC_008', 'SC_002', 'SC_004']，因此改为 `drilldown_time_windows_batch()`

### drilldown 明细

| 目标 | 前窗口观察 | 事件期间观察 | 后窗口观察 | 初步解释 |
|------|-----------|-------------|-----------|----------|
| SC_003 | 600行，速度35.35，normal_excavation90% | 21344行，速度0.01，stopped99% | 600行，速度38.37，normal_excavation99% | 停机前未见明显异常；停机后恢复正常 |
| SC_006 | 600行，速度34.34，normal_excavation83% | 1465行，速度0.1，stopped90% | 600行，速度35.4，normal_excavation82% | 停机前未见明显异常；停机后恢复正常 |

#### 钻取详情：SC_003

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：21344行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=35.35，转矩=518.03，normal_excavation=90%，low_load_operation=10%
- 事件期间：速度=0.01，转矩=2.3，stopped=99%，low_load_operation=1%，normal_excavation=0%
- 后窗口：速度=38.37，转矩=805.98，normal_excavation=99%，low_load_operation=1%，heavy_load_excavation=0%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

#### 钻取详情：SC_006

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：1465行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=34.34，转矩=677.95，normal_excavation=83%，low_load_operation=17%
- 事件期间：速度=0.1，转矩=23.45，stopped=90%，low_load_operation=10%，normal_excavation=0%
- 后窗口：速度=35.4，转矩=619.38，normal_excavation=82%，low_load_operation=18%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

### Top 停机案例

| 案例ID | 开始时间 | 结束时间 | 时长(min) | 合并事件数 | 分类 | 置信度 |
|--------|----------|----------|-----------|-----------|------|--------|
| SC_003 | 2025-02-22 04:22:24 | 2025-02-22 10:18:07 | 356 | 1 | 计划停机（疑似） | 32% |
| SC_009 | 2025-02-22 17:04:54 | 2025-02-22 22:35:07 | 330 | 1 | 计划停机（疑似） | 50% |
| SC_001 | 2025-02-22 00:00:00 | 2025-02-22 02:54:10 | 174 | 2 | 计划停机（疑似） | 50% |
| SC_007 | 2025-02-22 14:30:04 | 2025-02-22 15:11:27 | 41 | 1 | 待确认停机 | 35% |
| SC_005 | 2025-02-22 12:07:17 | 2025-02-22 12:41:44 | 34 | 1 | 待确认停机 | 35% |
| SC_010 | 2025-02-22 23:17:40 | 2025-02-22 23:46:17 | 29 | 1 | 待确认停机 | 35% |
| SC_008 | 2025-02-22 15:51:21 | 2025-02-22 16:19:12 | 28 | 1 | 待确认停机 | 35% |
| SC_006 | 2025-02-22 13:19:12 | 2025-02-22 13:43:36 | 24 | 1 | 计划停机（疑似） | 31% |
| SC_002 | 2025-02-22 03:28:34 | 2025-02-22 03:45:26 | 17 | 1 | 计划停机（疑似） | 57% |
| SC_004 | 2025-02-22 11:00:30 | 2025-02-22 11:11:44 | 11 | 1 | 计划停机（疑似） | 57% |

### 调查问题完成情况

| 问题 | 状态 | 已调用工具 | 关键发现 | 人工核查 |
|------|------|-----------|----------|---------|
| Q1: 是否存在长停机？停机是否有异常前兆？ | 已回答 | analyze_stoppage_cases, drilldown_time_window, drilldown_time_windows_batch | SC_004: 停机前未见明显异常；停机后恢复正常 | 是 |
| Q2: SER 是否是推进中的真实阻力异常，还是 | 部分回答 | analyze_resistance_pattern | SER 推进中占比 8% | 是 |
| Q3: HYD 是否是主因，还是启停边界伴随？ | 未回答 | — | 未执行 HYD 分析（因轮数不足跳过） | 是 |
| Q4: 事件是否存在碎片化或规则放大？ | 已回答 | analyze_event_fragmentation | 碎片化风险低，短事件占比 16% | 否 |
| Q5: 哪些结论需要施工日志确认？ | 部分回答 | — | 需施工日志确认：Q1: SC_004: 停机前未见明显异常；停机后恢复正常; Q | 是 |
