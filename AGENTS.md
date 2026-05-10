# AGENTS.md

This file provides guidance to Codex when working with this repository.

## Project Overview

**盾构/TBM CSV 智能诊断助手** — A local-first CLI tool for evidence-bounded analysis of shield/TBM time-series files.

This branch is a constraint-first refactor. The system must treat project/domain constraints as the foundation of every diagnosis:

- CSV evidence can show signals, trends, windows, missing fields, and event correlations.
- CSV evidence alone must not claim confirmed root cause, planned stoppage, tool wear, settlement cause, leakage, spewing, or site handling facts.
- Project profiles define the bounded problem space: machine type, parameter bands, risk families, evidence levels, claim policy, and staged data requests.
- Site-specific project profiles may contain sensitive engineering context and must stay local unless explicitly sanitized.

## Tech Stack

- Python 3.11+
- pandas, numpy, dataclasses, argparse
- openai SDK optional for non-authoritative summaries
- CLI first; local Streamlit demos may exist but must call internal/CLI capabilities

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

# Audit project/domain constraints
python -m tbm_diag.cli constraints
python -m tbm_diag.cli constraints --show-policy
python -m tbm_diag.cli constraints --profile project_profiles/local/site.json
```

## Architecture

Detection and explanation logic remain separated. The unit of output is an event segment, not a single data point.

```
CSV/XLS File
  └─> ingestion.py
        └─> schema.py
              └─> cleaning.py
                    └─> feature_engine.py
                          └─> detector.py
                                └─> segmenter.py
                                      └─> state_engine.py
                                            └─> evidence.py
                                                  └─> semantic_layer.py
                                                        └─> explainer.py

domain/
  ├─ models.py       # ProjectProfile, RiskFamily, ClaimPolicy, ClaimLevel
  ├─ loader.py       # Built-in/local profile loading
  ├─ audit.py        # Profile validation and evidence-level support checks
  └─ profiles/       # Sanitized built-in profiles only
```

## Constraint Rules

1. Constraints are the foundation. New diagnostic behavior must be expressible through project profile, ontology/risk family, evidence contract, or claim policy.
2. Stoppage is a state boundary or operational event, not a default root cause.
3. Reports must state evidence level. Without site logs or external monitoring records, conclusions remain "疑似" / "提示" / "需核查".
4. LLM output is never authoritative. It may summarize allowed facts but must not invent root cause or bypass claim policy.
5. Missing CSV fields must be tolerated gracefully. Skip unavailable checks and explain the evidence gap.
6. Real project profiles belong under `project_profiles/local/` or another ignored local path.
7. Built-in profiles must be sanitized examples, not raw施工组织设计, raw site logs, or real exported data.

## Stable Core Pipeline

Do not refactor these modules unless the task explicitly requires it:

- `ingestion.py`, `cleaning.py`, `detector.py`, `segmenter.py`
- `evidence.py`, `explainer.py`, `state_engine.py`
- `schema.py`, `feature_engine.py`

New features should be added through new modules or minimal integration points in `cli.py`.

## Testing Rules

Every code change must be tested before committing.

1. Run the CLI command(s) related to the change.
2. If the change touches the core pipeline, run the relevant regression commands:

```bash
python -m tbm_diag.cli inspect --input incoming/anomaly_segment.csv
python -m tbm_diag.cli detect --input incoming/anomaly_segment.csv
python -m tbm_diag.cli scan --input-dir incoming --output-dir scan_test_out --overwrite
```

3. Clean up test output directories after testing, or ensure they are ignored.

## README Sync Rules

- If you add a CLI command, parameter, output file, config option, or module capability, update README.md.
- README must only describe implemented and verified features.

## Repository Hygiene

Do not commit:

- `*.xls` / `*.xlsx` / large `*.csv`
- raw现场、客户、微信、工程项目数据
- `scan_real_out/`, `review_out/`, `investigation_out/`, demo upload/output directories
- `*.result.json`, `*.report.md`, `*.events.csv`
- `.env`, real API keys, credentials, or private project profiles

Before committing, check:

```bash
git status
git diff --stat
git ls-files | grep -E "(\.xls$|\.xlsx$|\.env$|scan_real_out|review_out|investigation_out|\.result\.json|\.report\.md|\.events\.csv)" || true
```

## Git Workflow

After every coding session:

1. Run tests relevant to the change.
2. Run `git status` and `git diff --stat`.
3. Stage only relevant files.
4. Commit with a conventional message.
5. Push only if a remote/branch policy is configured and pushing is appropriate.

## Change Output Format

After completing a task, output:

- Which files were changed
- Which tests were run and their results
- Whether README was updated
- Whether changes were committed
- Whether changes were pushed, and if not, why
