# TBM CSV 诊断助手

基于 CSV/XLS 输入的盾构/TBM 时序异常检测与解释 CLI 工具。

适用场景：盾构设备管理系统只能持续导出 CSV 文件，无法直接对接实时数据流。本工具作为外挂式分析层，读取 CSV/XLS → 自动检测异常 → 输出工程师可读的事件报告，无需改动原有系统。

---

## 当前支持能力

| 子命令 | 功能 |
|--------|------|
| `inspect` | 字段映射确认、清洗报告、DataFrame 摘要 |
| `detect` | 异常点检测、事件分段、证据提取、模板解释、三种格式导出 |
| `watch` | 轮询目录，自动处理新 CSV，每文件产出三种结果 |
| `scan` | 批量扫描目录，生成 scan_index.csv 风险排序 |
| `review` | 对 scan_index 中高风险文件批量执行 AI 复核（分诊与证据摘要） |
| `agent` | OpenAI-compatible tool-using agent，单文件工具编排和报告生成 |
| `investigate` | ReAct-style 动态工具调用调查 agent，根据文件特征选择停机追查、阻力分析、液压分析或碎片化检查 |
| `llm-check` | 测试当前 OpenAI-compatible API 连通性 |

- **配置文件**：通过 `.yaml` / `.json` 调整清洗参数、检测阈值、分段规则、输出行为
- **容错设计**：CSV 缺列自动跳过对应规则，不中断流程
- **本地优先**：纯 CLI，不依赖数据库或 Web 框架

---

## 安装

**Python 版本要求：3.11+**

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install pyyaml               # 若需要 YAML 配置文件支持
```

---

## 快速开始

### 字段检查

```bash
python -m tbm_diag.cli inspect --input sample.csv
```

### 异常检测

```bash
python -m tbm_diag.cli detect --input sample.csv
python -m tbm_diag.cli detect --input sample.csv --verbose
```

### 导出结果

```bash
python -m tbm_diag.cli detect --input sample.csv \
  --save-json out/result.json \
  --save-report out/report.md \
  --save-events-csv out/events.csv
```

### 批量扫描

```bash
python -m tbm_diag.cli scan --input-dir data/ --output-dir scan_out/
```

### AI 复核

```bash
python -m tbm_diag.cli review \
  --scan-index scan_out/scan_index.csv \
  --output-dir review_out --top-n 5
```

### 停机案例追查

```bash
# 单文件追查（规则 planner，默认）
python -m tbm_diag.cli investigate \
  --input sample2.xls \
  --output-dir investigation_out

# 推荐演示方式：LLM ReAct，50 轮
python -m tbm_diag.cli investigate \
  --input sample2.xls \
  --mode auto \
  --planner llm \
  --max-iterations 50 \
  --planner-audit \
  --output-dir investigation_out

# 从 scan_index 取 Top 3 高风险文件追查
python -m tbm_diag.cli investigate \
  --scan-index scan_real_out/scan_index.csv \
  --top-n 3 \
  --output-dir investigation_out \
  --max-iterations 50
```

### API 连通性检查

```bash
python -m tbm_diag.cli llm-check
```

输出 API Key 是否设置、模型名、API 调用是否成功、JSON 解析是否成功。演示前建议先跑一次。

### review 中的 LLM 状态

review 每个文件会明确标记总结来源：

- `LLM成功`：大模型返回了可解析的 JSON 总结
- `规则降级`：LLM 调用失败或 JSON 解析失败，使用规则生成的摘要
- `无事件/未请求LLM`：文件无异常事件，未调用 LLM

加 `--require-llm` 可在演示前自检：任何文件 LLM 未成功则 exit code 非 0。

### review 报告中的工具轨迹与证据链

review_summary.md 和 review_summary.json 中每个文件包含：

- **工具调用轨迹**（tool_traces）：记录本次复核调用了哪些分析工具，每个工具的作用和关键输出
- **证据链**（evidence_items）：每条证据有唯一编号（E1-E6），标注来源工具、解读和可靠性级别
  - E1：扫描索引基础信息（risk_rank_score / event_count / max_severity_label）
  - E2：语义事件分类统计（各类型事件数和持续时长）
  - E3：工况分布（stopped / normal / heavy_load 等占比）
  - E4：Top 事件摘要（类型、时长、状态）
  - E5：LLM 总结状态（summary_source / llm_status / model）
  - E6：停机时间模式分析（时间窗口分布和疑似标签）
- **AI 结论引用证据**：LLM 输出的每条风险和建议引用 evidence_id，标注 confidence 级别

可靠性级别：
- `direct_stat`：数据直接统计
- `derived_stat`：派生统计
- `llm_inference`：LLM 推断
- `needs_external_confirmation`：需施工日志等外部信息确认

### 停机时间模式分析

review 会对每个文件的停机片段进行时间窗口分析，输出疑似标签：
- `possible_meal_break_pattern`：疑似午间停机特征（11:30-13:30）
- `possible_shift_or_evening_stop_pattern`：疑似晚间/交接停机特征（17:00-20:30）
- `possible_overnight_stop_pattern`：疑似夜间停机特征（22:00-06:00）

这些标签只是时间窗口特征的统计结果，不等于确认计划停机。确认需要施工日志。

### 跨文件核心问题判断

review 的跨文件分析同时从两个维度评估核心问题：
- **按事件数**：哪类事件出现最多
- **按持续时长**：哪类事件累计影响时间最长

综合判断基于事件数（30%权重）、持续时长（50%权重）、涉及文件数（20%权重）的加权评分，避免仅按事件数低估长时间停机的影响。

```bash
python -m tbm_diag.cli review \
  --scan-index scan_real_out/scan_index.csv \
  --output-dir review_out --top-n 3 \
  --require-llm
```

### OpenAI-compatible API 配置

通过环境变量或 `.env` 文件配置：

```
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL=your-model-name
```

review 也支持 `--llm-model` 覆盖配置文件中的模型名。

---

## 本地 GUI 演示

启动命令：

```bash
streamlit run app_demo.py
```

该网页是本地演示入口，不是生产 Web 平台。

页面包含 5 个部分：

- 项目说明：介绍项目定位、演示路线和整体处理链路
- 单文件诊断：对单个 CSV/XLS/XLSX 文件运行 `detect`，查看异常摘要与报告
- 批量扫描：对目录运行 `scan`，快速筛出高风险文件并预览报告
- 智能复核：对 `scan_index.csv` 中的重点文件运行 `review`（分诊与证据摘要）
- ReAct 调查：对高风险文件运行 `investigate`，查看动态工具调用轨迹和调查报告

---

## review 与 investigate 的区别

| | `review` | `investigate` |
|---|---------|---------------|
| 定位 | 分诊与证据摘要 | 真正 ReAct 动态工具调用调查 |
| 流程 | 固定证据链（E1-E6）+ AI 总结 | 根据观察结果动态选择下一步工具 |
| 输出 | 证据链、AI 摘要、建议进一步调查的问题 | 调查报告 + ReAct 调查轨迹表 |
| 核心问题 | "这个文件有什么问题？下一步该查什么？" | "根据数据特征，逐步接近真相" |
| LLM 依赖 | 可选，无 key 时使用规则降级 | 可选，无 key 时使用 rule-based fallback planner |

review 不是 ReAct。review 是分诊，告诉你下一步该用什么工具查。investigate 才是真正的动态工具调用调查。

### investigate 的 Planner 模式

investigate 支持三种 planner：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `--planner rule` | 纯规则 planner，不调用 LLM API | CLI 默认，零成本，确定性工具选择 |
| `--planner llm` | 每轮调用 LLM 选择下一步工具 | **GUI 默认推荐**，演示真正 LLM ReAct |
| `--planner hybrid` | 前 2 轮规则，后续关键分支调 LLM | 节省成本的折中方案 |

报告中会明确标注每轮的 planner 类型、是否调用 LLM、LLM 状态和 fallback 情况。
rule planner 只能称为"规则驱动 ReAct-style 调查"，不能称为"LLM ReAct"。

```bash
# 推荐演示方式：LLM planner，50 轮（GUI 默认）
python -m tbm_diag.cli investigate --input data.xls --planner llm --max-iterations 50 --planner-audit

# 规则 planner（CLI 默认，无需 API Key）
python -m tbm_diag.cli investigate --input data.xls --planner rule

# 混合 planner
python -m tbm_diag.cli investigate --input data.xls --planner hybrid --planner-audit
```

#### 调查深度

`--max-iterations` 控制调查深度（默认 50）：

| 深度 | 轮数 | Planner | 适用场景 |
|------|------|---------|---------|
| 快速规则初筛 | 12 | rule | 不调用 LLM，适合快速预览或 API 不可用时 |
| 标准混合调查 | 20 | hybrid | 兼顾稳定和成本，部分关键轮次调用大模型 |
| 深度 LLM 调查（推荐） | 50 | llm | 大模型参与每轮决策，展示完整 ReAct 能力 |

#### GUI 主流程

GUI（`streamlit run app_demo.py`）的 ReAct 调查页面提供三档主入口：

- **深度 LLM 调查（推荐，默认）**：mode=auto, planner=llm, 50 轮
- 标准混合调查：mode=auto, planner=hybrid, 20 轮
- 快速规则初筛：mode=auto, planner=rule, 12 轮

GUI 默认选中"深度 LLM 调查"。如果未配置 OPENAI_API_KEY，GUI 会显示明确错误并阻止运行，不会静默 fallback 伪装成 LLM ReAct。

#### 报告结构

investigation_report.md 按以下顺序组织：

1. 调查结论总览 — 非技术人员可读的业务结论
2. 本次查清了什么 — 停机/SER/HYD/碎片化各维度结论
3. 本次没有查清什么 — 未覆盖案例、需施工日志确认的缺口
4. 调查计划执行情况 — P1~P4 中文表格
5. 技术审计附录 — ReAct 轨迹、LLM 明细、drilldown 详情等

GUI 结果页同样先展示结论卡片，技术审计默认折叠。

系统会根据文件特征自动计算推荐轮数，如果实际轮数不足会在报告中标注。
批量钻取工具（`drilldown_time_windows_batch`）可一轮内验证多个停机案例，减少轮数消耗。

### investigate 的 ReAct 工作流

```
inspect file overview
→ load event summary
→ 生成调查计划（P1~P4）和调查问题（Q1~Q5）
→ 根据观察结果动态选择路径：
  - 停机占比高 → analyze_stoppage_cases
  - SER 事件多 → analyze_resistance_pattern
  - HYD 事件频繁 → analyze_hydraulic_pattern
  - 事件碎片化 → analyze_event_fragmentation
→ 根据分析结果决定是否补充调查
→ generate investigation report
```

不同文件会产生不同的 action 序列。normal 文件会较早结束，不会无意义调用所有工具。

### investigate 可用工具

| 工具 | 用途 |
|------|------|
| `inspect_file_overview` | 获取文件概览 |
| `load_event_summary` | 获取事件摘要 |
| `analyze_stoppage_cases` | 综合停机分析（合并+窗口+分类） |
| `analyze_resistance_pattern` | 掘进阻力异常模式分析 |
| `analyze_hydraulic_pattern` | 液压不稳定模式分析 |
| `analyze_event_fragmentation` | 事件碎片化分析 |
| `merge_stoppage_cases` | 合并停机事件为案例 |
| `inspect_transition_window` | 检查停机前后窗口 |
| `classify_stoppage_case` | 分类停机案例 |
| `compare_cases_across_files` | 跨文件比较 |
| `generate_investigation_report` | 生成调查报告 |

### investigate 输出中的 ReAct 调查轨迹

investigation_report.md 包含 ReAct 调查轨迹表：

| 轮次 | 决策理由 | 调用工具 | 观察结果 |
|------|----------|----------|----------|

investigation_state.json 中 actions_taken 每条记录包含 round_num、action、arguments、rationale、observation_summary。

### 从 review 推荐到 investigate 执行

review 分诊后，每个文件的"建议进一步调查的问题"会推荐具体的 investigate mode：

- `--mode stoppage`：停机案例追查
- `--mode resistance`：掘进阻力异常追查
- `--mode hydraulic`：液压异常追查
- `--mode fragmentation`：碎片化检查

在 GUI 的"智能复核"页面中，可以直接点击对应按钮运行 investigate 并查看 ReAct 调查轨迹。
手动运行时使用推荐的命令即可。

### investigate-modes（模式对比 / 演示）

一键运行四种 mode 并生成对比表，验证不同 mode 调用不同工具链：

```bash
python -m tbm_diag.cli investigate-modes \
  --input sample2.xls \
  --output-dir investigation_modes_demo \
  --max-iterations 12
```

输出 `mode_comparison.md` 包含：

| mode | action_sequence | rounds | 关键触发字段 | 结论摘要 | 输出目录 |
|------|----------------|-------:|------------|---------|---------|

每个 mode 的完整 ReAct 调查轨迹见对应输出目录下的 `investigation_state.json`。

---

## investigate 输出文件

investigation 输出目录包含：

| 文件 | 内容 |
|------|------|
| `investigation_report.md` | 产品化报告：结论总览 → 查清了什么 → 没查清什么 → 计划执行 → 技术审计附录 |
| `investigation_state.json` | 完整调查状态：actions_taken、observations、stoppage_cases、classifications、executive_summary |
| `case_memory.json` | 每个 case 的结构化记录：时间、时长、分类、置信度、判定依据 |

---

## 配置文件

项目提供 `sample_config.yaml` 作为起点。

```yaml
cleaning:
  resample: "1s"
  fill: "ffill"
  max_gap: 5
  spike_k: 5.0

feature:
  rolling_window: 5

detector:
  resist_torque_rolling_hi: 3000.0
  resist_speed_rolling_lo: 20.0

segmenter:
  gap_tolerance_points: 2
  min_event_points: 5

cli:
  top_k_explanations: 3
  watch_interval: 3.0
```

优先级：CLI 显式参数 > 配置文件 > 代码默认值

---

## 支持的异常类型

| 类型标识 | 中文名 | 说明 |
|----------|--------|------|
| `suspected_excavation_resistance` | 疑似掘进阻力异常 | 转矩偏高 + 推进速度偏低 |
| `low_efficiency_excavation` | 低效掘进 | 推进速度与贯入度持续偏低 |
| `attitude_or_bias_risk` | 姿态偏斜风险 | 稳定器行程/压力不均衡 |
| `hydraulic_instability` | 液压系统不稳定 | 主推进泵或推进压力组波动 |

语义层额外分类：

| 语义类型 | 说明 |
|----------|------|
| `stoppage_segment` | 低效掘进 + 停机状态 → 停机片段 |
| `excavation_resistance_under_load` | 掘进阻力 + 重载推进 → 重载下的阻力异常 |

---

## 项目目录结构

```
csv_tunnel/
├── tbm_diag/
│   ├── schema.py            # 字段别名映射、规范列名
│   ├── ingestion.py         # CSV/XLS 加载，编码/分隔符自动识别
│   ├── cleaning.py          # 缺失值填充、尖峰去除、重采样
│   ├── feature_engine.py    # 滚动统计、跨列特征
│   ├── detector.py          # 规则检测
│   ├── segmenter.py         # 事件分段
│   ├── state_engine.py      # 工况状态识别
│   ├── semantic_layer.py    # 语义事件再分类
│   ├── evidence.py          # 事件证据提取
│   ├── explainer.py         # 模板解释生成
│   ├── summarizer.py        # LLM 跨事件总结
│   ├── exporter.py          # JSON / Markdown / CSV 导出
│   ├── scanner.py           # 批量扫描
│   ├── reviewer.py          # AI 复核
│   ├── agent.py             # Tool-using agent
│   ├── watcher.py           # 目录监听
│   ├── config.py            # 配置加载
│   ├── cli.py               # 命令行入口
│   └── investigation/       # 停机案例追查 ReAct Agent
│       ├── state.py
│       ├── tools.py
│       ├── planner.py
│       ├── controller.py
│       ├── memory.py
│       ├── context_retriever.py
│       └── report.py
├── sample_config.yaml
├── requirements.txt
├── CLAUDE.md
└── README.md
```

---

## 当前限制

- 检测规则基于第一版经验阈值，尚未经过大量真实数据校准
- 字段映射基于固定中文列名，CSV 列名变更需更新 `schema.py`
- investigate 的 planned_like / abnormal_like 分类是基于数据迹象的初步判断（疑似），不是确定性结论
- 没有施工日志时，无法确认计划停机或异常停机，需结合现场施工记录、班次记录、检修记录进一步确认
- 多文件 investigate 受 max_iterations 限制，top-n 较大时建议调高 `--max-iterations`
- 未提供 Web 前端、REST API 或数据库集成

---

## 设计原则

- **检测与解释分离**：`detector.py` 只输出标记和分数，`explainer.py` 负责文本
- **以事件为核心**：输出单位是事件段，不是数据点
- **对脏数据容错**：缺列跳过、编码自动识别、NaT 自动清理
- **本地优先**：纯 CLI，无需网络或外部服务
- **调查结论审慎**：investigate 输出始终使用"疑似""建议核查"措辞，不做确定性判断
