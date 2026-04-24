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
| `review` | 对 scan_index 中高风险文件批量执行 AI 复核 |
| `agent` | OpenAI-compatible tool-using agent，单文件工具编排和报告生成 |
| `investigate` | ReAct-style 停机案例追查 agent，合并碎片停机事件为 case，检查前后窗口，分类输出追查报告 |
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
# 单文件追查
python -m tbm_diag.cli investigate \
  --input sample2.xls \
  --output-dir investigation_out

# 从 scan_index 取 Top 3 高风险文件追查
python -m tbm_diag.cli investigate \
  --scan-index scan_real_out/scan_index.csv \
  --top-n 3 \
  --output-dir investigation_out \
  --max-iterations 30
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

### 诊断假设收敛

review 对每个文件生成一个"假设收敛板"（Hypothesis Board），对 6 个候选假设进行规则评分：

| 假设 | 含义 |
|------|------|
| H1 | 计划性停机 / 班次或检修安排 |
| H2 | 疑似异常停机 / 设备或地层导致停机 |
| H3 | 推进中掘进阻力异常 / 地层或刀盘负载问题 |
| H4 | 推进参数不匹配 / 操作策略问题 |
| H5 | 液压系统问题 |
| H6 | 事件切片或规则放大 |

评分完全由规则基于 E1-E6 证据计算，LLM 只负责解释评分结果，不决定分数。

收敛状态：
- 已收敛：top 假设 >= 60 分且分差 >= 20
- 部分收敛：top 假设 >= 40 分但分差 < 20，或缺少关键证据
- 未收敛：top 假设 < 40 分

H1/H2（计划/异常停机）没有施工日志时最多为"部分收敛"，不会标记为确认。

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
- 智能复核：对 `scan_index.csv` 中的重点文件运行 `review`
- 停机追查：对高风险文件运行 `investigate`，查看停机案例摘要

---

## agent 与 investigate 的区别

| | `agent` | `investigate` |
|---|---------|---------------|
| 定位 | 工具编排型 agent | 调查追因型 ReAct agent |
| 流程 | 固定 inspect → detect → summarize → export | 根据观察结果动态决策下一步 |
| 输出 | 单文件诊断报告 | case-level 停机追查报告 |
| 核心问题 | "这个文件有什么异常？" | "这些碎片停机背后到底是几次真正的停机？哪些像异常停机？" |
| LLM 依赖 | 必须有 OpenAI-compatible API | 可选，无 key 时使用 rule-based fallback planner |

### investigate 的 ReAct 工作流

```
inspect file overview
→ load event summary
→ 判断是否存在大量停机片段 (stoppage_segment)
→ merge stoppage segments into cases
→ inspect transition window (停机前后窗口)
→ classify stoppage cases (planned / abnormal / uncertain)
→ 多文件时：跨文件比较
→ generate investigation report
```

每一轮 planner 根据已有观察决定下一步 action，不是固定顺序。

---

## investigate 输出文件

investigation 输出目录包含：

| 文件 | 内容 |
|------|------|
| `investigation_report.md` | case-level 追查报告：核心结论、Top 停机案例、异常/计划/待确认分类、建议核查时间段 |
| `investigation_state.json` | 完整调查状态：actions_taken、observations、stoppage_cases、classifications |
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
