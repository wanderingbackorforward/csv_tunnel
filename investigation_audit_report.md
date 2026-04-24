# Investigation ReAct 审计报告（第二轮）

## 1. investigate --help 是否支持 mode/audit

**是。** `--mode {auto,stoppage,resistance,hydraulic,fragmentation}` 和 `--planner-audit` 均已接入 CLI。

## 2. 四种 mode 的 action_sequence（sample2.xls）

| mode | rounds | action_sequence |
|------|--------|-----------------|
| stoppage | 7 | overview → events → **analyze_stoppage_cases** → **drilldown×3** → report |
| resistance | 4 | overview → events → **analyze_resistance_pattern** → report |
| hydraulic | 4 | overview → events → **analyze_hydraulic_pattern** → report |
| fragmentation | 4 | overview → events → **analyze_event_fragmentation** → report |

四种 mode 产生四种不同的 action_sequence。planner 的 audit_log 确认非匹配分支被 `focus=<mode>` 原因拒绝。

## 3. normal auto 的 action_sequence

| file | mode | rounds | action_sequence |
|------|------|--------|-----------------|
| normal_segment.csv | auto | 3 | overview → events → report |

0 事件，所有分支阈值不满足，3 轮结束。符合预期。

## 4. 哪些 mode 符合预期

| mode | 符合预期 | 问题 |
|------|---------|------|
| stoppage | 部分 | 有 analyze_stoppage_cases + drilldown×3，但缺少独立的 classify_stoppage_case 调用（被 analyze_stoppage_cases 内部执行了） |
| resistance | 部分 | 有 analyze_resistance_pattern，但缺少 drilldown_time_window 对 SER 事件的钻取（planner 中 SER drilldown 要求 ser_count>=1 且 top_events 中有 SER 类型，但 top_events 按 peak_score 排序，SER 事件可能不在前列） |
| hydraulic | 部分 | 有 analyze_hydraulic_pattern，但缺少 drilldown 和 check_hydraulic_near_transition（后者工具不存在） |
| fragmentation | 符合 | 有 analyze_event_fragmentation，碎片化分析本身不需要 drilldown |

## 5. 哪些 mode 只是壳，没有真实工具路径

没有纯壳 mode。四种 mode 都调用了对应的分析工具。但 resistance 和 hydraulic 的 drilldown 没有触发，原因是 planner 中 SER/HYD drilldown 依赖 `event_summary.top_events` 中存在对应类型的事件，而 `top_events` 只取前 10 个事件且按 peak_score 排序，SER/HYD 事件可能排不进前 10。

## 6. 当前是否可以称为 ReAct

**mode-based 条件分支，不是 observation-driven ReAct。**

- mode 选择确实产生不同路径 — 这是进步
- 但每个 mode 内部仍然是固定 pipeline（stoppage 永远是 analyze → drilldown top3 → report）
- planner 不读 drilldown 返回的 interpretation_hint 来决定后续策略
- planner 不读 analyze_resistance_pattern 返回的 near_stoppage 来决定是否补充 drilldown

准确定义：**mode-gated conditional pipeline**，比上一轮的"全量 pipeline"好，但还不是"根据中间 observation 动态调整"的 ReAct。

## 7. 最小修复建议

### 7.1 resistance mode 缺少 drilldown

问题：`event_summary.top_events` 按 peak_score 排序，SER 事件可能不在前 10。
修复：planner 中 SER drilldown 不应依赖 top_events，应直接从 events 列表中筛选 SER 类型事件。

### 7.2 hydraulic mode 缺少 drilldown

同上，HYD 事件可能不在 top_events 前 10。
修复：同 7.1，直接从 events 列表筛选。

### 7.3 check_hydraulic_near_transition 工具不存在

预期中有这个工具但未实现。可以用 drilldown_time_window 替代（对 HYD 事件做窗口钻取即可判断是否在停机边界）。

### 7.4 planner 不读中间 observation

这是"条件分支 pipeline"和"真 ReAct"的核心区别。最小修复：
- 如果 stoppage drilldown 返回"停机前存在异常迹象"，则补充 resistance drilldown
- 如果 resistance 分析返回 near_stoppage=True，则补充 stoppage 分析

这需要 planner 读取 `state.observations` 中最近一次工具返回的 data 字段。
