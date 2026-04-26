# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**盾构/TBM CSV 智能诊断助手** — A CLI tool for intelligent diagnosis of shield/TBM (Tunnel Boring Machine) time-series data exported as CSV files.

Input: Manually exported CSV/XLS files containing high-frequency TBM parameters (timestamp, cutter torque, advance speed, thrust force, penetration rate, cylinder pressure, inclination, stabilizer stroke, etc.)

Output: Auto-detected anomaly events with severity ranking, evidence, and engineer-friendly explanations via CLI. Investigation-level stoppage case reports with classification and transition analysis.

## Tech Stack

- Python 3.11+
- pandas, numpy, dataclasses, argparse
- openai SDK (optional, for LLM planner / agent)
- CLI 优先，并提供本地 Streamlit 演示入口

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Inspect a file
python -m tbm_diag.cli inspect --input data.csv

# Run anomaly detection
python -m tbm_diag.cli detect --input data.csv

# Batch scan a directory
python -m tbm_diag.cli scan --input-dir data/ --output-dir scan_out/

# AI review of top high-risk files
python -m tbm_diag.cli review --scan-index scan_out/scan_index.csv --output-dir review_out --top-n 5

# Tool-using agent diagnosis
python -m tbm_diag.cli agent --input data.csv

# Stoppage investigation (ReAct agent)
python -m tbm_diag.cli investigate --input data.xls --output-dir investigation_out
python -m tbm_diag.cli investigate --scan-index scan_out/scan_index.csv --top-n 3 --output-dir investigation_out

# Mode comparison (demo/audit)
python -m tbm_diag.cli investigate-modes --input sample2.xls --output-dir investigation_modes_demo --max-iterations 12
```

## Architecture

Detection and explanation logic are strictly separated. The system is event-driven.

### Core Detection Pipeline

```
CSV/XLS File
  └─> ingestion.py       # Load file, auto-detect delimiter/encoding
        └─> schema.py    # Field mapping, canonical name normalization
              └─> cleaning.py       # Missing value handling, outlier removal, resampling
                    └─> feature_engine.py  # Compute derived time-series features
                          └─> detector.py  # Rule-based anomaly detection
                                └─> segmenter.py  # Merge consecutive anomaly points into events
                                      └─> state_engine.py  # Classify machine state per row
                                            └─> evidence.py    # Extract supporting data
                                                  └─> semantic_layer.py  # Reclassify events by state
                                                        └─> explainer.py   # Generate explanations
```

### Investigation Module (ReAct Agent)

```
tbm_diag/investigation/
  state.py             # InvestigationState and related dataclasses
  tools.py             # 12 investigation tools (including dynamic analysis tools)
  planner.py           # LLM planner + dynamic rule-based fallback
  controller.py        # Reason-Act-Observe loop
  memory.py            # Case-level structured memory
  context_retriever.py # Keyword-based context retrieval
  report.py            # Markdown report generator with ReAct trace table
```

## Key Design Rules

1. All detection thresholds are centralized in config — never hardcoded in detector logic.
2. Missing CSV fields must be tolerated gracefully — skip unavailable checks, do not exit.
3. Detection logic (`detector.py`) must not contain any text/explanation — that belongs in `explainer.py`.
4. The unit of output is an **event segment**, not a data point.
5. Each module has a single responsibility — no cross-module logic leakage.
6. Investigation classify results are always "疑似" — never claim certainty without ops logs.

## Stable Core Pipeline — Do Not Refactor

These modules form the stable core. Do not refactor unless the task explicitly requires it:

- `ingestion.py`, `cleaning.py`, `detector.py`, `segmenter.py`
- `evidence.py`, `explainer.py`, `state_engine.py`
- `schema.py`, `feature_engine.py`

New features should be added via new modules or minimal integration points in `cli.py`.

## Testing Rules

Every code change must be tested before committing.

1. Run the CLI command(s) related to the change.
2. If the change touches the core pipeline, run the full regression set:

```bash
python -m tbm_diag.cli inspect --input incoming/anomaly_segment.csv
python -m tbm_diag.cli detect --input incoming/anomaly_segment.csv
python -m tbm_diag.cli scan --input-dir incoming --output-dir scan_test_out --overwrite
python -m tbm_diag.cli investigate --input sample2.xls --output-dir investigation_test_out --max-iterations 12
```

3. Clean up test output directories after testing (they are in .gitignore).

## GUI Rules

1. GUI 面向中文演示时，所有用户可见文案必须使用简体中文。
2. 不要默认写英文按钮、英文 Tab、英文说明。
3. 技术字段可以内部保留英文，但展示给用户时应转成中文。
4. 新增 GUI 后必须检查中文化，包括标题、按钮、提示语、表格列名。
5. GUI 只能调用已有 CLI / 内部能力，不复制核心诊断算法。
6. 不要提交临时上传和输出目录，例如 `tmp_demo_uploads/`、`tmp_demo_outputs/`、`scan_demo_out/`、`review_demo_out/`、`investigation_demo_out/`。

## README Sync Rules

- If you add a CLI command, parameter, output file, config option, or module capability, update README.md.
- README must only describe implemented and verified features.
- Do not write future plans as if they are implemented.

## Git Workflow

After every coding session, stage and commit all changes before finishing.

- Run `git status` to confirm the change scope.
- `git add` relevant files. Exclude output dirs in .gitignore.
- Commit with conventional message (`feat:` / `fix:` / `refactor:` / `docs:` / `chore:`).
- Split commits if changes span multiple concerns.
- If a remote is configured, run `git push`. If push fails, report the reason — do not fake success.

## Sensitive Information Rules

- Never commit real API keys into code, README, sample configs, or commit messages.
- `.env` must be in `.gitignore`.
- `.env.example` may only contain placeholder values.
- CLAUDE.md is a project development spec and should be committed, but must not contain API keys, real file paths, real data content, or sensitive information.

## Repository Hygiene / 文件提交规范

### 不要提交真实数据文件

- 不要提交 `*.xls` / `*.xlsx` / 大体积 `*.csv`
- 不要提交来自微信、现场、客户、工程项目的原始数据
- 不要提交 `scan_real_out/` / `review_out/` / `investigation_out/` 等运行结果

### 不要提交运行产物

- 不要提交 `*.result.json` / `*.report.md` / `*.events.csv`
- 不要提交 `scan_index.csv` / `scan_summary.json`
- 不要提交 `.scan_state.json` / `.watcher_state.json`

### 如果需要示例文件

- 只能提交脱敏、小体积、专门放在 `tests/fixtures/` 下的样例
- 必须确认不包含真实工程信息

### 每次 commit 前必须检查

提交前运行以下命令，确认没有可疑文件被跟踪：

```bash
git status
git diff --stat
git ls-files | grep -E "(\.xls$|\.xlsx$|\.env$|scan_real_out|review_out|investigation_out|\.result\.json|\.report\.md|\.events\.csv)" || true
```

如果发现上述文件被跟踪，必须先停止并清理（`git rm --cached`），不能直接 commit。

## LLM Status Tracking Rules

- 不允许用 `ai_summary` 非空判断 LLM 是否成功。必须检查 `summary_source` 字段。
- LLM 调用必须记录 `summary_source` / `llm_status` / `llm_error_message`。
- fallback 摘要仍然保留，但必须标记为 `summary_source="fallback"`。
- 演示前必须跑 `python -m tbm_diag.cli llm-check` 确认 API 可用。
- GUI 必须展示 LLM 状态（总结来源列），不得把 fallback 伪装成 AI 成功。

## AI Review Report Rules

- AI 复核报告不得只给自然语言结论，必须展示工具轨迹和证据链。
- 每个文件的 review 结果必须包含 tool_traces 和 evidence_items。
- LLM 输出必须引用 evidence_id（E1-E6），不允许编造未在证据中出现的指标。
- 不允许把时间窗口推测（E6 停机时间模式）写成确定结论，必须标注"需施工日志确认"。
- 跨文件核心问题判断必须同时看事件数和持续时长，不能只按事件数占比判断。
- 演示页面必须展示"工具调用与证据链"，不能只显示"运行状态：成功"。
- review 是分诊，不是 ReAct。review 不得伪装成 ReAct 调查。
- review 必须输出"建议进一步调查的问题"和推荐命令。
- 禁止在 review 中做粗糙 H1-H6 假设评分。

## ReAct Investigation Rules

- ReAct 必须体现动态工具选择，不同文件应产生不同 action 序列。
- 如果只是固定调用工具，应称为 pipeline，不得称为 ReAct。
- 禁止把 ReAct 简化成固定证据 + 粗糙打分表。
- investigate 报告必须包含 ReAct 调查轨迹表（轮次/决策理由/调用工具/观察结果）。
- investigation_state.json 的 actions_taken 必须包含 observation_summary。
- normal 文件应较早结束调查，不应无意义调用所有工具。
- 停机主导文件应优先走 analyze_stoppage_cases。
- SER 主导文件应优先走 analyze_resistance_pattern。
- 碎片化文件应走 analyze_event_fragmentation。

## ReAct 验收与展示规则

- 如果用户说"看不到 ReAct"，优先检查 GUI 是否展示 investigation_state.json，而不是继续改 review_summary。
- review 只做分诊，不要求动态工具顺序。
- ReAct 的验收对象是 investigation_report.md / investigation_state.json / GUI 的 ReAct 调查轨迹。
- 演示时必须展示 action_sequence，而不是只展示 AI 自然语言总结。
- GUI 中"智能复核"页面可直接运行推荐的 investigate mode 并展示 ReAct 轨迹。
- `investigate-modes` 命令可用于演示不同 mode 的工具调用路径。
- 不允许把 rule planner 伪装成 LLM ReAct。
- 每次称为 LLM ReAct，必须能在报告里看到 llm_call_count > 0 且 llm_success_count > 0。
- ReAct 报告必须显示"Planner 与大模型调用审计"，明确 planner_type 和 LLM 调用次数。
- 如果没有 LLM 调用，只能称为"rule-based investigation"或"ReAct-style workflow"。
- investigate 默认 --planner rule，演示 LLM ReAct 需显式 --planner llm。

## Investigation 产品化规则

- 不要把所有内部 mode（stoppage/resistance/hydraulic/fragmentation）暴露到 GUI 主界面。
- GUI 默认主流程必须少而清晰：快速初筛 / 标准调查（推荐）/ 深度复核。
- 技术审计（ReAct 轨迹、LLM 明细、fallback、arg_resolver）不能放在报告第一屏。
- 报告先给结论，再给证据，最后给轨迹。
- LLM planner 的 raw 摘要只能放审计附录，不能当业务结论。
- 如果某个 mode 在当前模型能力下不稳定，不要作为推荐入口。
- 半路中断后继续任务时，必须先 git status / git diff，不能直接重写。
- executive_summary 是面向业务用户的结论摘要，禁止包含 fallback/arg_resolver/action_sequence 等技术术语。
- coverage 统计必须使用 compute_drilldown_coverage() 统一函数，报告和 GUI 不能出现口径不一致。

## Change Output Format

After completing a task, output:

- Which files were changed
- Which tests were run and their results
- Whether README was updated
- Whether changes were committed
- Whether changes were pushed (and if not, why)
