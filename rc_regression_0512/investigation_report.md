# TBM 停机调查报告

## 1. 一句话结论

当前 CSV 证据不支持 SER 直接触发停机；停机窗口中未见明显 HYD 行级异常；已逐案检查的 9 个停机案例中 9 个停机前未见明显行级异常、停机后恢复正常；停机性质仍需施工日志确认。

**关键发现：**
- 共发现 9 个停机案例，已逐案检查 9 个，未覆盖 0 个。
- 已查案例中，9 个停机前未见明显 SER/HYD 行级异常。
- SER 事件 241 个（19.1h），是重要线索，但当前未证明其为停机原因。
- HYD 事件 63 个，需进一步核查。

## 2. 这一天发生了什么

- 时间范围：2025-05-12 00:00:00 ~ 2025-05-12 23:59:59
- 共识别出 **9 段停机**，合计 **16.4h**
- 已逐案检查 9/9 段
- 最长一段停了 353 分钟（2025-05-12 16:42:13 ~ 2025-05-12 22:35:30）
- 当天共识别异常事件 444 个（停机相关 14 段、SER 241 个、HYD 63 个）

## 3. 最值得人工核查的停机段

以下停机段按时长从长到短排列，建议优先核查排在前面的案例。

| 优先级 | 案例 | 时间段 | 时长 | CSV 观察结论 | 建议核查原因 |
|--------|------|--------|------|-------------|-------------|
| 1 | SC_008 | 2025-05-12 16:42:13 ~ 2025-05-12 22:35:30 | 353min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 2 | SC_003 | 2025-05-12 04:52:49 ~ 2025-05-12 08:55:46 | 243min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 3 | SC_004 | 2025-05-12 10:41:10 ~ 2025-05-12 13:14:11 | 153min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 4 | SC_001 | 2025-05-12 00:10:52 ~ 2025-05-12 02:31:10 | 140min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 5 | SC_007 | 2025-05-12 15:43:49 ~ 2025-05-12 16:12:14 | 28min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 6 | SC_002 | 2025-05-12 03:22:08 ~ 2025-05-12 03:44:32 | 22min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 7 | SC_006 | 2025-05-12 14:45:30 ~ 2025-05-12 15:03:21 | 18min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 8 | SC_005 | 2025-05-12 14:13:29 ~ 2025-05-12 14:28:02 | 15min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |
| 9 | SC_009 | 2025-05-12 23:13:37 ~ 2025-05-12 23:26:19 | 13min | 停机前未见明显异常；停机后恢复正常 | 性质待施工日志确认 |

## 4. 我们已经查清了什么

### 4.1 停机

- 停机案例总数：9
- 已逐案检查：9
- 检查结果：**9 段**停机前后未见明显异常
- 未接入施工日志，停机性质（计划/异常）暂无法判定

### 4.2 掘进阻力异常（SER）

> SER = 疑似掘进阻力异常，即推进过程中遇到的地层阻力突然升高。

- SER 事件数：241 次
- SER 总时长：19.1h
- 其中推进中发生：81%
- 当前判断：推进中存在 SER，且与停机时段相邻，可能是停机诱因

### 4.3 液压异常（HYD）

HYD 事件 63 个，需进一步核查。

### 4.4 碎片化

- 短事件占比：78%
- 碎片化风险低，事件统计可信

## 5. 还不能下结论的地方

- 停机是否计划性/管理性：需施工日志确认
- SER 高发是否对应地层变化：需地质记录确认
- SC_008：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_003：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_004：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_001：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_006：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_005：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_009：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- 施工日志确认：2025-05-12 15:43:49 ~ 2025-05-12 16:12:14（SC_007）
- 施工日志确认：2025-05-12 03:22:08 ~ 2025-05-12 03:44:32（SC_002）

> 以上不确定项是因为当前 CSV 数据不足以给出确定结论，需要结合施工日志或其他外部证据进一步判断。

## 6. 下一步怎么查

1. 确认停机性质（SC_008、SC_003、SC_004、SC_001、SC_007等）：计划安排、检修/换刀、等待、交接班、外部调度或异常停机
2. 核查 SER 高发时段对应的地层和操作记录，判断是否为地层变化导致
3. 核查施工日志

## 7. 技术附录

> 以下为技术审计信息，供系统开发者或审计人员参考。

## ReAct 调查轨迹

| 轮次 | Planner | LLM | 决策理由 | 调用工具 | 观察结果 | Evidence Gate |
|------|---------|-----|----------|----------|----------|--------------|
| 1 | 混合/规则 | — | 尚未检查当前文件概览 | inspect_file_overview | rows=86400, events=444, time=2025-05-12 00:00:00~2025-05-12 | — |
| 2 | 混合/规则 | — | 尚未加载事件摘要 | load_event_summary | events=444, sem_dist={'stoppage_segment': 14, 'low_efficienc | — |
| 3 | 混合/LLM | success | stoppage_cases=0，无法执行停机分析。SER共241例，占比最高(54%)，是掘进阻力 | analyze_resistance_pattern | SER 事件 241 个，共 19.1h，推进中占比 81%，时间集中，靠近停机 | — |
| 4 | 混合/LLM | success | stoppage_cases=0无可钻停机案例，SER时间集中特征已明，需解构241个SER事件与6 | analyze_event_fragmentation | 事件 444 个，平均 304s，短事件占比 78% | — |
| 5 | 混合/LLM | success | 停机率64%为关键风险点，SER占54%且未执行任何drilldown，P2进行中，规则优先追查停机 | analyze_stoppage_cases | 9 个停机案例，共 16.4h | — |
| 6 | 混合/LLM | success | 遵循规则推荐，对停机时间最长的案例之一 SC_008 (353min) 进行窗口钻取，尚未有任何 d | drilldown_time_window | [SC_008] 前:600行，速度23.25，normal_excavation84% / 中:21198行，速度0. | — |
| 7 | 混合/LLM | success | SC_003有243分钟停机时长，是较长停机案例，从remaining_sc_ids中选取进行时间窗 | drilldown_time_window | [SC_003] 前:600行，速度22.97，normal_excavation100% / 中:14578行，速度0 | — |
| 8 | 混合/LLM | success | 规则推荐：SC_004 停机时长153分钟，属于较长停机案例，需要钻取时间窗口分析停机前后的异常信号 | drilldown_time_window | [SC_004] 前:600行，速度13.08，normal_excavation91% / 中:9182行，速度0.0 | — |
| 9 | 混合/LLM | success | [已修正] → SC_001, SC_005, SC_006, SC_007, SC_009 | drilldown_time_windows_batch | 批量钻取 5/5 个目标完成，5 个停机前无异常 | — |
| 10 | 混合/LLM | success | 硬约束阻止选择规则推荐动作（SC_001已钻取）。剩余SC_002已完成8/9钻取。水力异常63个、 | analyze_hydraulic_pattern | HYD 事件 63 个，共 0.1h，需核查统计口径 | — |
| 11 | 混合/LLM | success | [Evidence Gate] stoppage coverage 不足，需 drilldown S | drilldown_time_window | [SC_002] 前:600行，速度24.13，normal_excavation100% / 中:1345行，速度0. | override: generate_investigation_report→drilldown_time_window |
| 12 | 混合/LLM | success | 所有9个停机案例(SC_001~SC_009)已完成drilldown，remaining_sc_i | generate_investigation_report | report generated, 9 cases | — |

## Planner 与大模型调用审计

- Planner 类型：混合 planner（关键分支调用 LLM）
- LLM 调用次数：10
- LLM 成功次数：10
- fallback 次数：0
- 模型：MiniMax-M2.7

本次使用 hybrid planner，共 10 次 LLM planner 调用，全部成功。

### LLM 调用明细

> 以下为 LLM planner 决策摘要，仅用于审计；最终业务结论以 validator 校验后的调查结论为准。

| 轮次 | 状态 | 选择 | 耗时 | 摘要 |
|------|------|------|------|------|
| 3 | success | analyze_resistance_pattern | 19.7s |  |
| 4 | success | analyze_event_fragmentation | 13.4s |  |
| 5 | success | analyze_stoppage_cases | 13.0s |  |
| 6 | success | drilldown_time_window | 4.9s |  |
| 7 | success | drilldown_time_window | 6.8s |  |
| 8 | success | drilldown_time_window | 8.3s |  |
| 9 | success | drilldown_time_windows_batch | 7.2s |  |
| 10 | success | analyze_hydraulic_pattern | 14.0s |  |
| 11 | success | generate_investigation_report | 11.7s |  |
| 12 | success | generate_investigation_report | 8.2s |  |

### Evidence Gate 审计

- Evidence Gate 触发次数：1
- 停机案例 drilldown 覆盖率：9/9
- 单次 drilldown 覆盖：SC_002, SC_003, SC_004, SC_008
- batch drilldown 覆盖：SC_001, SC_005, SC_006, SC_007, SC_009

- 第 11 轮：LLM 选择 `generate_investigation_report`，但stoppage coverage 不足，需 drilldown SC_002，因此改为 `drilldown_time_window(SC_002)`

### drilldown 明细

| 目标 | 前窗口观察 | 事件期间观察 | 后窗口观察 | 初步解释 |
|------|-----------|-------------|-----------|----------|
| SC_008 | 600行，速度23.25，normal_excavation84% | 21198行，速度0.08，stopped99% | 600行，速度33.28，normal_excavation96% | 停机前未见明显异常；停机后恢复正常 |
| SC_003 | 600行，速度22.97，normal_excavation100% | 14578行，速度0.02，stopped97% | 600行，速度10.84，normal_excavation71% | 停机前未见明显异常；停机后恢复正常 |
| SC_004 | 600行，速度13.08，normal_excavation91% | 9182行，速度0.04，stopped70% | 600行，速度11.57，normal_excavation81% | 停机前未见明显异常；停机后恢复正常 |
| SC_002 | 600行，速度24.13，normal_excavation100% | 1345行，速度0.16，stopped86% | 600行，速度26.16，normal_excavation100% | 停机前未见明显异常；停机后恢复正常 |
| SC_001 | 600行，速度37.11，normal_excavation98% | 8419行，速度0.02，stopped98% | 600行，速度32.79，normal_excavation95% | 停机前未见明显异常；停机后恢复正常 |
| SC_006 | 600行，速度20.23，normal_excavation95% | 1072行，速度0.15，stopped72% | 600行，速度16.79，normal_excavation72% | 停机前未见明显异常；停机后恢复正常 |
| SC_005 | 600行，速度26.39，normal_excavation93% | 874行，速度0.22，stopped89% | 600行，速度21.88，normal_excavation96% | 停机前未见明显异常；停机后恢复正常 |
| SC_009 | 600行，速度35.48，normal_excavation97% | 763行，速度0.29，stopped80% | 600行，速度34.21，normal_excavation93% | 停机前未见明显异常；停机后恢复正常 |
| SC_007 | 600行，速度17.88，normal_excavation71% | 1706行，速度0.11，stopped91% | 600行，速度23.73，normal_excavation89% | 停机前未见明显异常；停机后恢复正常 |

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

#### 钻取详情：SC_002

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：1345行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=24.13，转矩=996.23，normal_excavation=100%
- 事件期间：速度=0.16，转矩=26.39，stopped=86%，low_load_operation=13%，normal_excavation=1%
- 后窗口：速度=26.16，转矩=1013.38，normal_excavation=100%

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

#### 钻取详情：SC_007

- 事件期间重叠事件数：2
- 重叠 SER：1
- 重叠停机：1

**行级规则命中：**
- 前窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 事件期间：1706行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%
- 后窗口：600行，SER=0/0.0%，HYD=0/0.0%，LEE=0/0.0%

**工况统计：**
- 前窗口：速度=17.88，转矩=684.85，normal_excavation=71%，low_load_operation=29%，heavy_load_excavation=0%
- 事件期间：速度=0.11，转矩=17.8，stopped=91%，low_load_operation=9%，normal_excavation=1%
- 后窗口：速度=23.73，转矩=901.92，normal_excavation=89%，low_load_operation=11%，heavy_load_excavation=0%

- 初步解释: 停机前未见明显异常；停机后恢复正常
- 转变发现: 推进→停机转变，停机→恢复转变

### Top 停机案例

| 案例ID | 开始时间 | 结束时间 | 时长(min) | 合并事件数 | 分类 | 置信度 |
|--------|----------|----------|-----------|-----------|------|--------|
| SC_008 | 2025-05-12 16:42:13 | 2025-05-12 22:35:30 | 353 | 2 | 性质待施工日志确认 | 34% |
| SC_003 | 2025-05-12 04:52:49 | 2025-05-12 08:55:46 | 243 | 1 | 性质待施工日志确认 | 32% |
| SC_004 | 2025-05-12 10:41:10 | 2025-05-12 13:14:11 | 153 | 2 | 性质待施工日志确认 | 34% |
| SC_001 | 2025-05-12 00:10:52 | 2025-05-12 02:31:10 | 140 | 1 | 性质待施工日志确认 | 34% |
| SC_007 | 2025-05-12 15:43:49 | 2025-05-12 16:12:14 | 28 | 1 | 性质待施工日志确认 | 35% |
| SC_002 | 2025-05-12 03:22:08 | 2025-05-12 03:44:32 | 22 | 1 | 性质待施工日志确认 | 35% |
| SC_006 | 2025-05-12 14:45:30 | 2025-05-12 15:03:21 | 18 | 1 | 性质待施工日志确认 | 31% |
| SC_005 | 2025-05-12 14:13:29 | 2025-05-12 14:28:02 | 15 | 1 | 性质待施工日志确认 | 31% |
| SC_009 | 2025-05-12 23:13:37 | 2025-05-12 23:26:19 | 13 | 1 | 性质待施工日志确认 | 31% |

### 证据一致性检查

**分类修正：**
- SC_008: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_008: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_008: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_008: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_003: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_003: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_003: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_004: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_004: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_004: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_004: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_001: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_001: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_001: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_001: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_007: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_007: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_002: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_002: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_006: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_006: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_006: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_006: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_005: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_005: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_005: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_005: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾
- SC_009: 分类依据「停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 SER 未被窗口证据支持（pre SER ratio=0.000）
- SC_009: 分类依据「停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——停机前 HYD 未被窗口证据支持（pre HYD hits=0）
- SC_009: 分类依据「恢复后仍有异常事件（事件级证据，未经 drilldown 验证）」已按 drilldown 修正——恢复后窗口未检测到异常
- SC_009: 分类从 event_level_abnormal_unverified 降级为 planned_like_stoppage——drilldown 显示「停机前未见明显异常；停机后恢复正常」，与异常线索矛盾

**已验证案例：**
- SC_008：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_003：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_004：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_001：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_006：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_005：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认
- SC_009：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；性质仍需施工日志确认

### 调查问题完成情况

| 问题 | 状态 | 已调用工具 | 关键发现 | 人工核查 |
|------|------|-----------|----------|---------|
| Q1: 是否存在长停机？停机是否有异常前兆？ | 已回答 | analyze_stoppage_cases, drilldown_time_window, drilldown_time_windows_batch | SC_002: 停机前未见明显异常；停机后恢复正常 | 是 |
| Q2: SER 是否是推进中的真实阻力异常，还是 | 部分回答 | analyze_resistance_pattern | SER 推进中占比 81% | 是 |
| Q3: HYD 是否是主因，还是启停边界伴随？ | 已回答 | analyze_hydraulic_pattern | HYD 需先核查统计口径 | 否 |
| Q4: 事件是否存在碎片化或规则放大？ | 已回答 | analyze_event_fragmentation | 碎片化风险低，短事件占比 78% | 否 |
| Q5: 哪些结论需要施工日志确认？ | 部分回答 | — | 需施工日志确认：Q1: SC_002: 停机前未见明显异常；停机后恢复正常; Q | 是 |
