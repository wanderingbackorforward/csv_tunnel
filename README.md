# TBM CSV 诊断助手

基于 CSV 输入的盾构/TBM 时序异常检测与解释 CLI 工具。

适用场景：盾构设备管理系统只能持续导出 CSV 文件，无法直接对接实时数据流。本工具作为外挂式分析层，读取 CSV → 自动检测异常 → 输出工程师可读的事件报告，无需改动原有系统。

---

## 当前支持能力

| 子命令 | 功能 |
|--------|------|
| `inspect` | 字段映射确认、清洗报告、DataFrame 摘要 |
| `detect` | 异常点检测、事件分段、证据提取、模板解释、三种格式导出 |
| `watch` | 轮询目录，自动处理新 CSV，每文件产出三种结果 |
| `constraints` | 加载并审计项目约束 profile：参数边界、风险族、证据等级、报告禁语 |

- **配置文件**：通过 `.yaml` / `.json` 调整清洗参数、检测阈值、分段规则、输出行为，无需改代码
- **约束层**：通过项目 profile 明确 CSV 能说什么、不能说什么，以及哪些结论必须等待现场记录
- **容错设计**：CSV 缺列自动跳过对应规则，不中断流程
- **零外部服务**：纯本地 CLI，不依赖数据库、Web 框架或 LLM

---

## 安装

**Python 版本要求：3.11+**

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 若需要 YAML 配置文件支持（推荐）
pip install pyyaml
```

`requirements.txt` 依赖：`pandas>=2.0.0`、`numpy>=1.24.0`、`chardet>=5.2.0`、`tabulate>=0.9.0`

---

## 快速开始

### 字段检查

```bash
python -m tbm_diag.cli inspect --input sample.csv
```

查看字段映射、清洗报告、关键参数统计。加 `--no-clean` 跳过清洗步骤。

### 异常检测

```bash
# 基础检测
python -m tbm_diag.cli detect --input sample.csv

# 详细输出（含最后 10 行检测列 + 全部事件解释）
python -m tbm_diag.cli detect --input sample.csv --verbose
```

### 导出结果

```bash
python -m tbm_diag.cli detect --input sample.csv \
  --save-json out/result.json \
  --save-report out/report.md \
  --save-events-csv out/events.csv
```

### 使用配置文件

```bash
python -m tbm_diag.cli detect --input sample.csv --config sample_config.yaml
```

### 审计项目约束

```bash
# 查看内置脱敏约束示例
python -m tbm_diag.cli constraints

# 查看结论等级、允许限定词、禁止表述
python -m tbm_diag.cli constraints --show-policy

# 加载本地真实项目 profile（建议放在 project_profiles/local/，不要提交）
python -m tbm_diag.cli constraints --profile project_profiles/local/site.json
```

### 目录监听模式

```bash
# 启动后将 CSV 文件放入 incoming/ 目录，自动处理，Ctrl+C 退出
python -m tbm_diag.cli watch \
  --input-dir incoming \
  --output-dir watch_out \
  --config sample_config.yaml
```

---

## 配置文件

项目提供 `sample_config.yaml` 作为起点，直接复制修改即可。

```yaml
cleaning:
  resample: "1s"       # 重采样频率，'none' 跳过
  fill: "ffill"        # 缺失值填充：ffill | linear
  max_gap: 5           # 最大连续填充步数
  spike_k: 5.0         # IQR 尖峰检测宽松倍数

feature:
  rolling_window: 5    # 滚动统计窗口（点数）

detector:
  resist_torque_rolling_hi: 3000.0    # 转矩偏高阈值（kNm）
  resist_speed_rolling_lo: 20.0       # 推进速度偏低阈值（mm/min）
  # ... 共 16 个阈值，详见 sample_config.yaml

segmenter:
  gap_tolerance_points: 2   # 允许合并的最大间隙点数
  min_event_points: 5       # 事件最小持续点数

cli:
  top_k_explanations: 3     # 默认输出 Top-K 事件解释
  watch_interval: 3.0       # watch 模式轮询间隔（秒）
```

**优先级规则：CLI 显式参数 > 配置文件 > 代码默认值**

支持 `.yaml` / `.yml` / `.json` 三种格式，缺失字段自动回退默认值。

---

## 项目约束层

约束层用于把开放的盾构/TBM 诊断问题收缩为可审计的问题空间。它不是根因判定器，而是规定：

- 当前项目有哪些可讨论的风险族；
- CSV 字段能支持哪些线索；
- 哪些结论必须依赖施工日志、报警记录、监测日报、换刀/维修记录；
- 报告中哪些表述必须降级或禁止。

内置 profile 位于 `tbm_diag/domain/profiles/urban_rail_epb_soft_ground.json`，是脱敏示例。真实工程 profile 可能包含项目、工区、里程、参数边界等现场上下文，建议放在：

```text
project_profiles/local/
```

该目录已加入 `.gitignore`，避免误提交现场资料。

当前内置 profile 定义了四级结论边界：

| 等级 | 含义 | 最低证据 |
|------|------|----------|
| `L1_csv_signal` | CSV 参数线索 | CSV 时序数据 |
| `L2_project_risk_candidate` | 项目风险族候选 | CSV + project profile |
| `L3_cross_record_supported` | 跨记录支持 | CSV + project profile + 监测/报警记录 |
| `L4_confirmed_by_site_log` | 现场记录确认 | CSV + project profile + 施工/操作日志 |

因此，系统可以说“CSV 显示某窗口存在掘进阻力线索”，但不能仅凭 CSV 说“确认刀具磨损”“确认计划停机”或“根因就是某项施工问题”。

---

## 支持的异常类型

| 类型标识 | 中文名 | 说明 |
|----------|--------|------|
| `suspected_excavation_resistance` | 疑似掘进阻力异常 | 转矩偏高 + 推进速度偏低，疑似地层变化或刀盘负载异常 |
| `low_efficiency_excavation` | 低效掘进 | 推进速度与贯入度持续偏低，掘进效率不足 |
| `attitude_or_bias_risk` | 姿态偏斜风险 | 稳定器行程/压力不均衡，盾体可能存在偏转 |
| `hydraulic_instability` | 液压系统不稳定 | 主推进泵或推进压力组出现明显波动 |

每类异常输出：
- `is_{type}`（bool）：是否命中
- `score_{type}`（0~1 float）：命中子规则比例
- 事件段：start_time / end_time / duration / peak_score / mean_score
- 证据：3~5 条关键信号摘要（均值、峰值、方向）
- 解释：总结 + 可能原因 + 建议关注项

---

## 输出文件说明

### `detect` 命令

| 参数 | 文件 | 内容 |
|------|------|------|
| `--save-json PATH` | `result.json` | 完整结构化结果（ingestion / cleaning / detection / events / evidences / explanations） |
| `--save-report PATH` | `report.md` | Markdown 诊断报告，含总结、统计表、Top-3 事件解释 |
| `--save-events-csv PATH` | `events.csv` | 事件表，UTF-8 BOM，兼容 Windows Excel |

### `watch` 模式

每个输入文件 `{name}.csv` 自动产出：

```
watch_out/
├── {name}.json
├── {name}_report.md
├── {name}_events.csv
└── .watcher_state.json    # 已处理记录，重启后不重复处理
```

---

## 项目目录结构

```
csv_tunnel/
├── tbm_diag/
│   ├── schema.py          # 字段别名映射、规范列名、单位定义
│   ├── ingestion.py       # CSV 加载，自动识别编码和分隔符
│   ├── cleaning.py        # 缺失值填充、尖峰去除、重采样
│   ├── feature_engine.py  # 滚动统计、跨列特征、比值特征
│   ├── detector.py        # 规则检测，输出 is_xxx / score_xxx 列
│   ├── segmenter.py       # 连续命中点合并为事件段
│   ├── evidence.py        # 事件窗口内关键信号提取
│   ├── explainer.py       # 模板解释生成（无 LLM）
│   ├── exporter.py        # JSON / Markdown / CSV 导出
│   ├── domain/            # 项目约束 profile、风险族、证据等级、claim policy
│   ├── watcher.py         # 目录轮询监听器
│   ├── config.py          # 配置文件加载与合并
│   └── cli.py             # 命令行入口（inspect / detect / watch）
├── sample_config.yaml     # 可直接使用的配置文件模板
├── requirements.txt
└── CLAUDE.md
```

---

## 设计原则

- **检测与解释分离**：`detector.py` 只输出布尔标记和分数，`explainer.py` 负责文本生成，互不耦合
- **以事件为核心**：`segmenter.py` 将逐点命中合并为有起止时间的事件段，输出单位是事件而非数据点
- **对脏数据容错**：缺列自动跳过对应规则；编码、分隔符自动识别；NaT / 重复时间戳自动清理
- **本地优先**：纯 CLI，无需网络、数据库或外部服务，适合现场外挂式部署

---

## 当前限制

- 检测规则基于第一版经验阈值，尚未经过大量真实数据校准
- 模板解释器未接 LLM，解释文本为固定模板，不随数据动态生成
- 未提供 Web 前端、REST API 或数据库集成
- 字段映射基于固定中文列名，CSV 列名变更需更新 `schema.py`
- 适合原型验证、现场演示和外挂式分析，不是完整的数据中台

---

## 清洗经验说明

`cutter_torque_kNm`（刀盘转矩）在部分高负载掘进工况下可能被全局 IQR 标记为尖峰并置空（实测 sample2.xls 中有 5,242 个点超出 k=5 上界 900 kNm，对应推进速度均值 41 mm/min，属于真实掘进数据）。但在当前基于滚动均值的检测规则中，IQR 置空后经 ffill 填充，对最终事件检测结果影响有限。因此默认仍保留清洗行为。若后续引入峰值型规则（逐点判断而非滚动均值），可通过 `iqr_exempt_fields` 配置按字段豁免：

```yaml
cleaning:
  iqr_exempt_fields:
    - cutter_torque_kNm
```

示例配置见 `sample_config_torque_exempt.yaml`。

---

## 后续方向

- **规则校准**：基于真实标注数据调整各类异常阈值，减少误报
- **更多异常类型**：刀具磨损预警、同步注浆异常、管片拼装偏差等
- **报告优化**：支持 PDF 导出，增加趋势图表
- **轻量前端**：基于现有 JSON 输出接入简单 Web 查看页面
