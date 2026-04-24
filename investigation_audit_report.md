# Investigation ReAct 审计报告

## 1. 当前是否是真动态 ReAct

**部分是，但不完全是。**

当前 planner 确实根据文件特征（stoppage_count、SER_count、HYD_count、stopped_pct、event_count）选择不同路径。不同文件产生不同 action 序列。但它不根据工具返回的 observation 内容调整后续策略——它只看初始 overview 中的计数，不看 drilldown 返回的 interpretation_hint、analyze_resistance_pattern 返回的 near_stoppage 等字段。

准确定义：**条件分支 pipeline，基于初始特征分流，不基于中间 observation 动态调整。**

## 2. 当前是否存在固定 pipeline

对于"什么都有"的文件（如 sample2.xls），planner 会按固定优先级走完所有满足阈值的分支：

```
overview → events → stoppage → drilldown×3 → resistance → hydraulic → fragmentation → report
```

这个顺序由 if-else 优先级决定，不会因为 drilldown 发现"停机前无异常"就跳过后续 resistance 分析。

对于低事件文件（normal、anomaly），planner 正确地在 3 轮内结束。

## 3. 哪些工具永远不会被 fallback planner 调用

| 工具 | 是否会被调用 | 原因 |
|------|-------------|------|
| `merge_stoppage_cases` | 不会单独调用 | 被 `analyze_stoppage_cases` 内部调用 |
| `inspect_transition_window` | 不会单独调用 | 被 `analyze_stoppage_cases` 内部调用 |
| `classify_stoppage_case` | 不会单独调用 | 被 `analyze_stoppage_cases` 内部调用 |
| `retrieve_operation_context` | 永远不会 | planner 中无触发条件 |
| `compare_cases_across_files` | 仅多文件模式 | 单文件模式不触发 |

## 4. 哪些 action 是写死顺序

- 前两步永远是 `inspect_file_overview → load_event_summary`（合理，必须先看数据）
- 最后一步永远是 `generate_investigation_report`（合理，必须生成报告）
- 中间步骤的优先级写死为：stoppage > drilldown(stoppage) > resistance > drilldown(SER) > hydraulic > drilldown(HYD) > fragmentation

## 5. 哪些 observation 被 planner 使用

| observation 来源 | 被使用的字段 | 使用方式 |
|-----------------|-------------|---------|
| `inspect_file_overview` | `semantic_event_distribution`, `state_distribution`, `event_count` | 决定走哪些分支 |
| `load_event_summary` | `top_events` | 选择 drilldown 目标 |
| `analyze_stoppage_cases` | `stoppage_cases`（通过 state） | 选择 drilldown 的 case_id |

## 6. 哪些 observation 没有被使用

| observation 来源 | 未使用的字段 | 应该怎么用 |
|-----------------|-------------|-----------|
| `drilldown_time_window` | `interpretation_hint`, `transition_findings`, `ser_ratio`, `hyd_ratio` | 应根据 drilldown 结果决定是否需要更多钻取或切换方向 |
| `analyze_resistance_pattern` | `near_stoppage`, `concentrated_in_time`, `in_advancing_ratio` | 应决定是否补充 drilldown SER 事件 |
| `analyze_hydraulic_pattern` | `sync_with_ser`, `near_stoppage_boundary`, `isolated_short_fluctuation` | 应决定 HYD 是主因还是伴随 |
| `analyze_event_fragmentation` | `fragmentation_risk`, `short_event_ratio` | 应决定是否需要进一步分析 |

## 7. 三个测试文件的 action sequence 对比

| 文件 | 轮次 | action 序列 |
|------|------|-------------|
| normal_segment.csv | 3 | overview → events → report |
| anomaly_segment.csv | 3 | overview → events → report |
| sample2.xls | 10 | overview → events → stoppage → drilldown×3 → resistance → hydraulic → fragmentation → report |

normal 和 anomaly 走相同路径（都是 3 轮直接结束），但原因不同：
- normal: events=0, 所有分支阈值不满足
- anomaly: events=2, SER=1<3, stoppage=0, HYD=0 — 所有分支阈值不满足

sample2 走了完整路径，因为所有阈值都满足。

**判定：2 种不同路径，部分动态。路径选择基于初始特征，不基于中间 observation。**

## 8. 下一步最小修复建议

### 8.1 让 drilldown 结果影响后续决策

当前 drilldown 返回 `interpretation_hint`，但 planner 不看。最小修复：

- 如果 3 个 stoppage case 的 drilldown 都返回"停机前未见明显异常"，则跳过 resistance 分析（因为停机不是由 SER 引起的）
- 如果 drilldown 返回"停机前存在异常迹象"，则优先 drilldown 该 case 前窗口的 SER 事件

### 8.2 让 analyze_* 结果影响后续决策

- 如果 `analyze_resistance_pattern` 返回 `near_stoppage=True`，则对最近的 SER 事件做 drilldown
- 如果 `analyze_hydraulic_pattern` 返回 `isolated_short_fluctuation=True`，则不需要 drilldown HYD 事件
- 如果 `analyze_event_fragmentation` 返回 `fragmentation_risk=True`，则在报告中标注"事件数可能被规则放大"

### 8.3 不需要新增工具

当前工具集已经足够。问题不在工具数量，在于 planner 不读工具返回值。

### 8.4 需要改的 report 文案

- 报告标题从"调查报告"改为更准确的描述
- 如果所有 drilldown 都显示"无异常迹象"，报告应明确说"停机更像计划停机"

### 8.5 如何测试不同文件走不同路径

已有 `scripts/audit_investigation_paths.py`。理想状态下：
- 一个纯停机文件应该只走 stoppage + drilldown，不走 resistance
- 一个纯 SER 文件应该只走 resistance + drilldown，不走 stoppage
- 当前缺少这样的测试文件（sample2 什么都有）

## 发现的 Bug

controller.py 中 `state.observations.append` 被调用了两次（已修复）。
