# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**盾构/TBM CSV 智能诊断助手** — A CLI tool for intelligent diagnosis of shield/TBM (Tunnel Boring Machine) time-series data exported as CSV files.

Input: Manually exported CSV files containing high-frequency TBM parameters (timestamp, cutter torque, advance speed, thrust force, penetration rate, cylinder pressure, inclination, stabilizer stroke, etc.)

Output: Auto-detected anomaly events with severity ranking, evidence, and engineer-friendly explanations via CLI.

## Tech Stack

- Python 3.11+
- pandas, numpy, dataclasses, argparse
- CLI only — no web UI

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run diagnosis on a CSV file
python -m tbm_diag.cli --input data.csv

# Run with custom config
python -m tbm_diag.cli --input data.csv --config config.yaml

# Run a single module test
python -m tbm_diag.ingestion data.csv
```

## Architecture

Detection logic and explanation logic are strictly separated. The system is event-driven — anomalies are merged into event segments, not treated as individual data points.

```
CSV File
  └─> ingestion.py      # Load CSV, auto-detect delimiter/encoding
        └─> schema.py   # Field mapping, canonical name normalization
              └─> cleaning.py      # Missing value handling, outlier removal, resampling
                    └─> feature_engine.py  # Compute derived time-series features
                          └─> detector.py  # Rule-based anomaly detection (thresholds from config)
                                └─> segmenter.py  # Merge consecutive anomaly points into event segments
                                      └─> scorer.py    # Assign severity and priority to each event
                                            └─> evidence.py  # Extract supporting data for each event
                                                  └─> explainer.py  # Generate engineer-facing text explanations
                                                        └─> cli.py  # Output: one-line conclusion + Top 3 events
```

## Module Responsibilities

| File | Responsibility |
|------|---------------|
| `schema.py` | Field alias mapping, canonical column names, unit definitions |
| `ingestion.py` | CSV loading with encoding/delimiter auto-detection, graceful handling of missing fields |
| `cleaning.py` | Null filling, spike removal, resampling to uniform time grid |
| `feature_engine.py` | Compute rolling stats, rate-of-change, penetration index, etc. |
| `detector.py` | Apply threshold rules to produce per-row anomaly flags; all thresholds in config |
| `segmenter.py` | Merge consecutive flagged rows into named event segments with start/end time |
| `scorer.py` | Score each event segment by severity (low/medium/high/critical) and priority |
| `evidence.py` | Pull raw values and stats that support each event's diagnosis |
| `explainer.py` | Render human-readable explanation strings from event + evidence data |
| `cli.py` | Argparse entry point; prints one-line summary and Top 3 anomalies |

## Key Design Rules

1. All detection thresholds are centralized in a single config file (e.g., `config.yaml` or `thresholds.py`) — never hardcoded in detector logic.
2. Missing CSV fields must be tolerated gracefully — skip unavailable checks, do not exit.
3. Detection logic (`detector.py`) must not contain any text/explanation — that belongs in `explainer.py`.
4. The unit of output is an **event segment**, not a data point.
5. Each module has a single responsibility — no cross-module logic leakage.
