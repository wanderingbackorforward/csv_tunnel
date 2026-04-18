# 项目迭代故事

## Phase 1：规则诊断内核（v0.1）

**要解决的问题**

对方系统只能导出 CSV，没有实时接口，也不允许改动原有系统。工程师每天手动翻文件找异常，效率低，容易漏掉跨时段规律。需要一个能读 CSV、自动检测异常、输出可读报告的工具。

**做了什么**

从零搭建完整链路：`ingestion.py`（自动识别编码和分隔符）→ `schema.py`（字段别名映射）→ `cleaning.py`（缺失值填充、IQR 尖峰去除、重采样）→ `feature_engine.py`（滚动统计、比值特征）→ `detector.py`（规则检测，输出 `is_xxx` / `score_xxx`）→ `segmenter.py`（连续命中点合并为事件段）→ `evidence.py`（事件窗口内关键信号提取）→ `explainer.py`（模板解释）→ `exporter.py`（JSON / Markdown / CSV 导出）→ `cli.py`（argparse 入口）。

跑真实数据（8.6 万行）时发现并修复了几个实际问题：IQR 清洗把高负载工况下的真实高转矩误判为尖峰（加了 `iqr_exempt_fields` 豁免机制）；3 点孤立命中产生大量噪声事件（加了 `min_event_points=5` 过滤）；重复时间戳和混合时间格式导致崩溃（清洗层专项处理）。

**为什么这么做**

先把链路做稳，再叠加能力。工业时序数据需要确定性和可回溯性，规则检测天然满足，LLM 不行。这个阶段结束时系统已经是可交付的基线，不是 demo。

**没选什么**

没有一开始就接 LLM 直接分析原始 CSV。原因是：几万行数值序列放不进上下文；LLM 对数值的判断不稳定；检测结果需要可回溯，不能依赖黑盒。

**收益**

在真实数据上跑通完整链路，有 watch 目录监听模式、YAML 外部配置、多格式导出，可以独立交付。

---

## Phase 2：工况状态识别层（v0.2）

**要解决的问题**

跑真实数据时发现结构性问题：停机占了 70% 的时间，停机状态下的"低速"和正常推进中的"低速"含义完全不同，但系统用同一套阈值对待它们。调阈值解决不了这个问题，需要工况上下文。

**做了什么**

新增 `state_engine.py`，在 `feature_engine` 之后、`evidence` 之前，对每行数据分类为四种工况：停机/静止、低负载运行、正常推进、重载推进。分类规则基于刀盘转速、推进速度、推进力的组合阈值。把事件窗口内的主导状态（dominant_state）和状态分布注入 `EventEvidence`，再传递给 `explainer.py` 生成带工况语义的解释。

**为什么这么做**

零侵入插入：状态层不改 `detector.py` 的任何逻辑，只在 evidence 层增加一个字段。这样主链路不受影响，状态层可以独立迭代。

**没选什么**

没有用滑动窗口投票或状态机做更复杂的状态识别。当前四分类已经能区分停机和推进，满足需求，过度设计没有必要。

**收益**

输出从"液压压力波动超阈值"升级为"该事件主要发生在正常推进状态下，液压压力出现明显波动"。工程师拿到报告，第一眼就能判断这个事件值不值得关注。

---

## Phase 3：LLM 总结层 + OpenAI-compatible Agent（v0.3）

**要解决的问题**

规则检测能发现单个事件，但无法做跨事件归纳：今天 3 个事件集中在上午 10 点、某时段停机频率异常高——这类结论规则做不了，需要语义理解能力。

**做了什么**

两步走：

1. **LLM 总结层**（`summarizer.py`）：把所有事件的结构化摘要（每个事件约 5 行文字）传给 LLM，让它做跨事件归纳，输出 `overall_summary` / `top_risks` / `suggested_actions`。LLM 不接触原始 DataFrame，只看精简摘要。`--llm-summary` 是可选 flag，失败五级降级，不影响主链路。

2. **Tool-using Agent**（`agent.py`）：基于 OpenAI-compatible API（适配 MiniMax），agent 通过工具调用驱动完整检测链路，支持多轮推理。工具包括 `run_detect`、`get_event_details`、`get_state_distribution` 等，agent 可以自主决定调用顺序和深度。

**为什么这么做**

LLM 的切入点是"跨事件归纳"，不是"检测"。把 LLM 放在规则检测的下游，让它做它擅长的事。agent 模式让 LLM 可以主动探索数据，而不是被动接收固定摘要。

**没选什么**

没有让 LLM 直接看原始 CSV 或 DataFrame。上下文长度不够，数值判断不稳定，检测结果需要确定性。

**收益**

LLM 总结层在真实数据上能生成有意义的跨事件结论。Agent 模式验证了 tool-calling 循环可以跑通完整诊断流程。

---

## Phase 4：scan / review / semantic-aware review（v0.4）

**要解决的问题**

有几十个历史 XLS 文件需要批量分析。全量跑 LLM 成本高、速度慢；但只看规则输出又缺少语义归纳。另外，review 结果发现大量高风险文件的 Top 事件都是"低效掘进"，但这些事件的主导状态全部是停机——语义上是错的，AI 总结因此把停机问题误写成推进参数问题。

**做了什么**

三件事：

1. **`scan` 子命令**（`scanner.py`）：对全量文件并行跑规则诊断，生成每文件的 JSON / Markdown / events CSV，以及总索引 `scan_index.csv`（含 `risk_rank_score`、`event_count`、`max_severity_label` 等字段）。

2. **`review` 子命令**（`reviewer.py`）：读取 `scan_index.csv`，按 `risk_rank_score` 筛出 Top N 文件，调 LLM 深度复核，生成 `review_summary.md`（含各文件 AI 总结 + 跨文件共性分析）。

3. **Semantic Layer**（`semantic_layer.py`）：基于 `(event_type, dominant_state)` 组合规则，对事件进行业务语义重分类：`low_efficiency_excavation + stopped → stoppage_segment`（停机片段）；`low_efficiency_excavation + normal/heavy_load → low_efficiency_excavation`（推进中低效掘进）；`suspected_excavation_resistance + heavy_load → excavation_resistance_under_load`（重载推进下的掘进阻力异常）。不改 `detector.py` 原始字段，保留 `event_type` 供回溯。

   同时把 semantic stats 注入 LLM 提示词，明确告知 LLM"停机片段属于停机/静止工况，不是推进效率问题，请单独描述"。

**为什么这么做**

scan + review 两阶段把 AI 调用成本集中在真正高风险的文件上，而不是全量跑。semantic layer 解决的是数据语义问题，不是模型能力问题——LLM 再强，输入标签错了，输出结论也会错。

**没选什么**

没有直接修改 `detector.py` 的检测逻辑来区分停机和推进。检测器的职责是发现异常点，语义解释是另一层的事，混在一起会破坏单一职责原则。

**收益**

review_summary 能正确区分"停机时间过长（停机片段 43 个/37.8h）"和"推进中低效掘进（406 个/4.0h）"，核心问题判断从"低效掘进问题"修正为"停机管理问题"。LLM 总结文案不再出现"需调整推进参数"这类对停机片段无意义的建议。

---

## 版本节点

| 版本 | 内容 |
|------|------|
| v0.1 | 基础链路：ingestion → cleaning → feature → detect → segment → evidence → explain → export；watch 模式；YAML 配置 |
| v0.2 | 工况状态识别层（state_engine）；IQR 豁免；min_event_points |
| v0.3 | 可选 LLM 总结层（summarizer）；OpenAI-compatible tool-using agent |
| v0.4 | scan / review 两阶段批量流程；semantic layer 事件语义重分类；review_summary 语义感知 |
