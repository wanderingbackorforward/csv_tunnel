"""
cli.py — 命令行入口

子命令：
  inspect  字段映射确认 + CSV 读取 + 基础清洗（原 --input 模式）
  detect   特征计算 + 异常点检测摘要

用法：
    python -m tbm_diag.cli inspect --input data.csv
    python -m tbm_diag.cli inspect --input data.csv --resample 5s --fill linear
    python -m tbm_diag.cli detect  --input data.csv
    python -m tbm_diag.cli detect  --input data.csv --verbose

    # 兼容旧用法（无子命令时默认走 inspect）：
    python -m tbm_diag.cli --input data.csv
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
from pathlib import Path

# ── 本地 .env 自动加载（系统环境变量优先，.env 仅补充缺失项）─────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)   # override=False → 已有的系统变量不被覆盖
except ImportError:
    pass  # python-dotenv 未安装时静默跳过，行为与之前完全一致

# Windows 控制台默认 GBK，强制 stdout/stderr 使用 UTF-8 输出
# 仅在 stdout 不是真正的 UTF-8 流时才替换（避免影响管道/重定向）
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd

from tbm_diag.cleaning import CleaningReport, clean
from tbm_diag.ingestion import IngestionResult, load_csv
from tbm_diag.schema import CANONICAL_META, FIELD_CATALOG, SUSPICIOUS_UNIT_FIELDS
from tbm_diag.feature_engine import enrich_features
from tbm_diag.detector import DetectionResult, DetectorConfig, detect
from tbm_diag.segmenter import Event, SegmenterConfig, segment_events
from tbm_diag.evidence import EventEvidence, extract_evidence
from tbm_diag.explainer import Explanation, TemplateExplainer
from tbm_diag.exporter import ResultBundle, to_events_csv, to_json, to_markdown
from tbm_diag.watcher import run_watch_loop
from tbm_diag.config import DiagConfig, load_config
from tbm_diag.state_engine import STATE_LABELS, classify_states, summarize_event_state
from tbm_diag.summarizer import LLMSummaryResult, build_summary_input, summarize
from tbm_diag.semantic_layer import apply_to_evidences, SEMANTIC_LABELS
from tbm_diag.agent import AgentResult, run_agent
from tbm_diag.scanner import ScanConfig, run_scan
from tbm_diag.reviewer import ReviewConfig, run_review

# tabulate 为可选依赖——若未安装，用简单对齐替代
try:
    from tabulate import tabulate as _tabulate
    _HAS_TABULATE = True
except ImportError:
    _HAS_TABULATE = False


# ── 日志 ───────────────────────────────────────────────────────────────────────

def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        format="%(levelname)s [%(name)s] %(message)s",
        level=logging.DEBUG if verbose else logging.WARNING,
        stream=sys.stderr,
    )


# ── 打印工具 ───────────────────────────────────────────────────────────────────

def _table(rows: list[list], headers: list[str], max_col_width: int = 40) -> str:
    """简单表格渲染，tabulate 存在时使用，否则用 str.ljust 对齐。"""
    # 预先截断并转为字符串，避免 tabulate maxcolwidths 的数字解析 bug
    str_rows = [
        [str(cell)[:max_col_width] for cell in row]
        for row in rows
    ]
    if _HAS_TABULATE:
        return _tabulate(
            str_rows,
            headers=headers,
            tablefmt="simple",
            disable_numparse=True,
        )
    # 回退：纯文本对齐
    all_rows = [headers] + str_rows
    col_widths = [
        min(max(len(str(r[i])) for r in all_rows), max_col_width)
        for i in range(len(headers))
    ]
    sep = "  "
    lines = []
    for i, row in enumerate(all_rows):
        line = sep.join(str(cell)[:col_widths[j]].ljust(col_widths[j]) for j, cell in enumerate(row))
        lines.append(line)
        if i == 0:
            lines.append("-" * len(line))
    return "\n".join(lines)


def _print_field_mapping(recognized: dict[str, str]) -> None:
    print("\n┌─ 字段映射表 " + "─" * 56)
    rows = []
    for raw_col, canonical in recognized.items():
        meta = FIELD_CATALOG.get(raw_col)
        unit = meta.raw_unit if meta else "?"
        desc = meta.description_zh if meta else ""
        note = "⚠ 单位可疑" if canonical in SUSPICIOUS_UNIT_FIELDS else ""
        rows.append([raw_col, canonical, unit, desc, note])

    print(_table(
        rows,
        headers=["原始列名", "标准列名", "单位", "说明", "备注"],
        max_col_width=36,
    ))
    print(f"  共 {len(rows)} 个识别字段")


def _print_unrecognized(unrecognized: list[str]) -> None:
    print("\n┌─ 未识别列 " + "─" * 58)
    if not unrecognized:
        print("  (无未识别列)")
        return
    for col in unrecognized:
        print(f"  • {col}")
    print(f"  共 {len(unrecognized)} 列（已原样保留在 DataFrame 中）")


def _print_cleaning_report(report: CleaningReport) -> None:
    print("\n┌─ 清洗报告 " + "─" * 58)

    # 行数流水
    print(f"  输入行数       : {report.rows_input:>8,}")
    ts_dropped = report.rows_input - report.rows_after_ts_drop
    dedup_dropped = report.rows_after_ts_drop - report.rows_after_dedup
    print(f"  去除 NaT 时间戳 : {ts_dropped:>8,}")
    print(f"  去除重复时间戳  : {dedup_dropped:>8,}")
    print(f"  重采样频率      : {'未重采样' if not report.resample_freq else report.resample_freq}")
    print(f"  输出行数        : {report.rows_output:>8,}")

    # 尖峰统计
    print()
    total_spikes = sum(report.spike_removed.values())
    if total_spikes:
        print(f"  IQR 尖峰去除  : 共 {total_spikes:,} 个点（以下列数量最多）")
        top_spikes = sorted(
            ((col, n) for col, n in report.spike_removed.items() if n > 0),
            key=lambda x: -x[1],
        )[:8]
        print(_table(
            [[col, f"{n:,}"] for col, n in top_spikes],
            headers=["标准列名", "去除点数"],
        ))
        if sum(1 for n in report.spike_removed.values() if n > 0) > 8:
            print(f"  （其余列尖峰较少，省略）")
    else:
        print("  IQR 尖峰去除  : 0 个点（数据质量良好或列全为常数）")

    # 残余 NaN
    print()
    residual = [(col, n) for col, n in report.null_counts_after.items() if n > 0]
    if residual:
        print(f"  残余 NaN ({len(residual)} 列)：")
        print(_table(
            sorted([[col, f"{n:,}"] for col, n in residual], key=lambda x: -int(x[1].replace(",", "")))[:8],
            headers=["标准列名", "NaN 数"],
        ))
    else:
        print("  残余 NaN      : 无（所有数值列均已填充）")

    # 警告
    if report.warnings:
        print()
        print("  ⚠ 清洗警告：")
        for w in report.warnings:
            print(f"    - {w}")


def _print_df_summary(df: pd.DataFrame) -> None:
    print("\n┌─ DataFrame 摘要 " + "─" * 52)
    print(f"  形状: {df.shape[0]:,} 行 × {df.shape[1]} 列")

    ts_col = "timestamp"
    if ts_col in df.columns:
        ts = df[ts_col].dropna()
        if not ts.empty:
            print(f"  时间起点: {ts.iloc[0]}")
            print(f"  时间终点: {ts.iloc[-1]}")
            duration = ts.iloc[-1] - ts.iloc[0]
            print(f"  持续时长: {duration}")

    # 主要工程量统计（仅选最关键的几列）
    KEY_COLS = [
        "cutter_speed_rpm",
        "cutter_torque_kNm",
        "total_thrust_kN",
        "penetration_rate_mm_per_rev",
        "advance_speed_mm_per_min",
        "main_pump_pressure_bar",
    ]
    stat_cols = [c for c in KEY_COLS if c in df.columns]
    if stat_cols:
        print()
        print("  关键参数统计：")
        stats = df[stat_cols].describe().T[["count", "mean", "std", "min", "max"]]
        stats["count"] = stats["count"].astype(int)
        print(_table(
            [[idx] + [f"{v:.2f}" if isinstance(v, float) else str(v) for v in row]
             for idx, row in zip(stats.index, stats.values)],
            headers=["列名", "count", "mean", "std", "min", "max"],
        ))


# ── 检测结果打印 ───────────────────────────────────────────────────────────────

_ANOMALY_LABELS: dict[str, str] = {
    "suspected_excavation_resistance": "疑似掘进阻力异常",
    "low_efficiency_excavation":       "低效掘进",
    "attitude_or_bias_risk":           "姿态偏斜风险",
    "hydraulic_instability":           "液压系统不稳定",
}


def _print_detection_summary(result: DetectionResult) -> None:
    total = result.total_rows
    any_hit = any(v > 0 for v in result.hit_counts.values())

    print("\n┌─ 检测摘要 " + "─" * 58)
    print(f"  总检测行数: {total:,}")

    if not any_hit:
        print("  ✓ 未发现异常点（所有类型命中数均为 0）")
    else:
        print()
        rows = []
        for name, label in _ANOMALY_LABELS.items():
            hits = result.hit_counts.get(name, 0)
            pct = hits / total * 100 if total > 0 else 0.0
            skipped = result.skipped_rules.get(name, [])
            skip_note = f"（跳过 {len(skipped)} 条规则）" if skipped else ""
            rows.append([label, f"{hits:,}", f"{pct:.1f}%", skip_note])
        print(_table(rows, headers=["异常类型", "命中点数", "占比", "备注"]))

    # 跳过规则详情
    all_skipped = {k: v for k, v in result.skipped_rules.items() if v}
    if all_skipped:
        print()
        print("  ⚠ 以下规则因缺少字段被跳过：")
        for name, rules in all_skipped.items():
            label = _ANOMALY_LABELS.get(name, name)
            print(f"    [{label}] {', '.join(rules)}")


def _print_detection_verbose(result: DetectionResult) -> None:
    """verbose 模式：打印最后 10 行关键检测列。"""
    df = result.df

    # 选取要展示的列
    key_cols = ["timestamp"] if "timestamp" in df.columns else []
    key_cols += [
        "advance_speed_mm_per_min",
        "cutter_torque_kNm",
        "penetration_rate_mm_per_rev",
    ]
    detect_cols = [c for c in df.columns if c.startswith("is_") or c.startswith("score_")]
    show_cols = [c for c in key_cols + detect_cols if c in df.columns]

    if not show_cols:
        return

    print("\n┌─ 最后 10 行检测列（verbose）" + "─" * 40)
    tail = df[show_cols].tail(10)
    # 格式化 bool 列
    for col in tail.columns:
        if tail[col].dtype == bool:
            tail = tail.copy()
            tail[col] = tail[col].map({True: "✓", False: "·"})
    print(tail.to_string(index=True))


def _print_event_summary(
    events: list[Event],
    verbose: bool = False,
    event_states: dict | None = None,
    evidences: list | None = None,
) -> None:
    print("\n┌─ 事件摘要 " + "─" * 58)

    if not events:
        print("  ✓ 未形成有效异常事件（所有异常点均未达到最小持续时长）")
        return

    # 按类型统计（用语义类型）
    sem_map = {ev.event_id: ev.semantic_event_type for ev in (evidences or []) if ev.semantic_event_type}
    type_counts: dict[str, int] = {}
    for e in events:
        sem = sem_map.get(e.event_id, e.event_type)
        type_counts[sem] = type_counts.get(sem, 0) + 1

    print(f"  共检测到 {len(events)} 个异常事件：")
    for atype, label in {**_ANOMALY_LABELS, **SEMANTIC_LABELS}.items():
        n = type_counts.get(atype, 0)
        if n > 0:
            print(f"    {label}: {n} 个")

    show = events if verbose else events[:5]
    if verbose:
        title = f"全部 {len(events)} 个事件"
    elif len(events) > 5:
        title = f"Top 5 事件（共 {len(events)} 个，--verbose 查看全部）"
    else:
        title = f"全部 {len(events)} 个事件"

    print(f"\n  {title}：")
    rows = []
    for e in show:
        sem = sem_map.get(e.event_id, e.event_type)
        label = SEMANTIC_LABELS.get(sem, _ANOMALY_LABELS.get(sem, sem))
        start = str(e.start_time)[:19] if e.start_time is not None else "—"
        end   = str(e.end_time)[:19]   if e.end_time   is not None else "—"
        dur_s = f"{e.duration_seconds:.0f}s" if e.duration_seconds is not None else "—"
        ds_key = event_states[e.event_id].dominant_state if event_states and e.event_id in event_states else ""
        ds_zh  = STATE_LABELS.get(ds_key, ds_key) if ds_key else "—"
        rows.append([
            e.event_id,
            label,
            start,
            end,
            f"{e.duration_points}点/{dur_s}",
            f"{e.peak_score:.3f}",
            f"{e.mean_score:.3f}",
            ds_zh,
        ])

    print(_table(
        rows,
        headers=["事件ID", "类型", "开始时间", "结束时间", "时长", "峰值分", "均值分", "主导工况"],
        max_col_width=24,
    ))


_SEVERITY_ICON: dict[str, str] = {
    "高风险": "▲▲",
    "中风险": "▲",
    "低风险": "△",
    "观察":   "○",
}


def _print_explanations(
    explanations: list[Explanation],
    verbose: bool = False,
    top_k: int = 3,
    event_states: dict | None = None,
) -> None:
    show = explanations if verbose else explanations[:top_k]
    if not show:
        return

    total = len(explanations)
    header_note = f"（共 {total} 个，--verbose 查看全部）" if not verbose and total > top_k else ""
    print(f"\n┌─ Top {len(show)} 事件解释{header_note} " + "─" * 30)

    for i, exp in enumerate(show, 1):
        icon = _SEVERITY_ICON.get(exp.severity_label, "○")
        start = str(exp.start_time)[:19] if exp.start_time is not None else "—"
        end   = str(exp.end_time)[:19]   if exp.end_time   is not None else "—"

        print(f"\n  [{i}] {exp.event_id}  {exp.title}  {icon}{exp.severity_label}"
              f"  ({start} ~ {end})")
        print(f"  总结：{exp.summary}")

        # 状态上下文
        state_ctx = exp.state_context
        if not state_ctx and event_states and exp.event_id in event_states:
            ds = event_states[exp.event_id].dominant_state
            label_zh = STATE_LABELS.get(ds, ds)
            state_ctx = f"该事件主要发生在\"{label_zh}\"状态下"
        if state_ctx:
            print(f"  状态上下文：{state_ctx}")

        print("  证据：")
        for bullet in exp.evidence_bullets:
            print(f"    • {bullet}")

        print("  可能原因：")
        for cause in exp.possible_causes[:3]:
            print(f"    - {cause}")

        print("  建议关注：")
        for action in exp.suggested_actions[:3]:
            print(f"    → {action}")

        if i < len(show):
            print("  " + "·" * 66)


def _print_llm_summary(result: LLMSummaryResult) -> None:
    """打印 LLM 跨事件总结块。"""
    print(f"\n┌─ LLM 跨事件总结 " + "─" * 52)
    print(f"  模型：{result.model_used}")
    print()
    print("  整体评估：")
    for line in result.overall_summary.splitlines():
        print(f"    {line}")
    if result.top_risks:
        print()
        print("  主要风险：")
        for risk in result.top_risks:
            print(f"    • {risk}")
    if result.suggested_actions:
        print()
        print("  建议关注：")
        for action in result.suggested_actions:
            print(f"    → {action}")


# ── 主函数 ─────────────────────────────────────────────────────────────────────

def _add_common_args(p: argparse.ArgumentParser) -> None:
    """向子命令解析器添加公共参数。"""
    p.add_argument("--input", "-i", required=True, metavar="FILE", help="输入 CSV 文件路径")
    p.add_argument("--resample", default=None, metavar="FREQ",
                   help="重采样频率（pandas offset alias，'none' 跳过）。默认由配置文件或 1s 决定")
    p.add_argument("--spike-k", type=float, default=None, metavar="K",
                   help="IQR 尖峰检测宽松倍数（默认由配置文件或 5.0 决定）")
    p.add_argument("--fill", choices=["ffill", "linear"], default=None,
                   help="缺失值填充方式（默认由配置文件或 ffill 决定）")
    p.add_argument("--max-gap", type=int, default=None, metavar="N",
                   help="最大连续填充步数（默认由配置文件或 5 决定）")
    p.add_argument("--verbose", "-v", action="store_true", help="显示 DEBUG 日志")
    p.add_argument("--config", default=None, metavar="PATH",
                   help="配置文件路径（.yaml / .yml / .json）")


def _load_and_clean(
    args: argparse.Namespace,
    cfg: DiagConfig,
) -> tuple[pd.DataFrame, IngestionResult, "CleaningReport"]:
    """公共加载 + 清洗流程，返回 (cleaned_df, ingestion_result, cleaning_report)。"""
    print(f"[1/2] 加载文件: {args.input}")
    try:
        result: IngestionResult = load_csv(args.input)
    except FileNotFoundError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        sys.exit(2)
    except ValueError as exc:
        print(f"✗ 加载失败: {exc}", file=sys.stderr)
        sys.exit(1)

    print(
        f"  ✓ 编码: {result.encoding_used}  |  分隔符: {result.delimiter_used!r}  |  "
        f"原始维度: {result.df.shape[0]:,} 行 × {result.df.shape[1]} 列"
    )

    # CLI 参数优先；未指定时回退到配置文件值
    cc = cfg.cleaning
    resample_raw = args.resample if args.resample is not None else cc.resample
    resample_freq = None if (resample_raw or "").strip().lower() == "none" else (resample_raw or "").strip() or None
    spike_k   = args.spike_k  if args.spike_k  is not None else cc.spike_k
    fill      = args.fill     if args.fill      is not None else cc.fill
    max_gap   = args.max_gap  if args.max_gap   is not None else cc.max_gap
    iqr_exempt = set(cc.iqr_exempt_fields) if cc.iqr_exempt_fields else None

    print(
        f"\n[2/2] 清洗中 "
        f"(resample={resample_freq or '跳过'}, spike_k={spike_k}, "
        f"fill={fill}, max_gap={max_gap}) …"
    )
    try:
        df, report = clean(
            result.df,
            resample_freq=resample_freq,
            spike_k=spike_k,
            fill_method=fill,
            max_gap_fill=max_gap,
            skip_spike_cols=iqr_exempt,
        )
    except Exception as exc:
        print(f"✗ 清洗失败: {exc}", file=sys.stderr)
        sys.exit(1)

    _print_cleaning_report(report)
    return df, result, report


def _cmd_inspect(args: argparse.Namespace) -> int:
    """inspect 子命令：字段映射 + 清洗报告 + DataFrame 摘要。"""
    _setup_logging(args.verbose)
    cfg = load_config(getattr(args, "config", None))

    if args.no_clean:
        print(f"[1/1] 加载文件: {args.input}")
        try:
            result: IngestionResult = load_csv(args.input)
        except FileNotFoundError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"✗ 加载失败: {exc}", file=sys.stderr)
            return 1
        df = result.df
        print(f"  ✓ 识别字段: {len(result.recognized)}  |  未识别字段: {len(result.unrecognized)}")
        _print_field_mapping(result.recognized)
        _print_unrecognized(result.unrecognized)
    else:
        df, result = _load_and_clean(args, cfg)[:2]
        _print_field_mapping(result.recognized)
        _print_unrecognized(result.unrecognized)

    _print_df_summary(df)

    if hasattr(args, "output") and args.output:
        out = Path(args.output)
        try:
            df.to_csv(out, index=False, encoding="utf-8-sig")
            print(f"\n✓ 已导出: {out}  ({len(df):,} 行 × {df.shape[1]} 列, UTF-8 BOM)")
        except Exception as exc:
            print(f"✗ 导出失败: {exc}", file=sys.stderr)
            return 1

    print("\n✓ 完成")
    return 0


def _cmd_detect(args: argparse.Namespace) -> int:
    """detect 子命令：特征计算 + 异常点检测 + 事件分段。"""
    _setup_logging(args.verbose)
    cfg = load_config(getattr(args, "config", None))

    df, _ingestion_result, _cleaning_report = _load_and_clean(args, cfg)

    print("\n[3/4] 特征计算 + 异常检测 …")
    try:
        enriched = enrich_features(df, window=cfg.feature.rolling_window)
        result = detect(enriched, config=cfg.detector)
    except Exception as exc:
        print(f"✗ 检测失败: {exc}", file=sys.stderr)
        return 1

    _print_detection_summary(result)

    if args.verbose:
        _print_detection_verbose(result)

    print("\n[4/4] 事件分段 …")
    try:
        events = segment_events(result.df, config=cfg.segmenter)
    except Exception as exc:
        print(f"✗ 分段失败: {exc}", file=sys.stderr)
        return 1

    _print_event_summary(events, verbose=args.verbose, event_states=None)

    event_states: dict = {}
    if events:
        # 状态分类
        try:
            enriched = classify_states(enriched, config=cfg.state)
            event_states = {e.event_id: summarize_event_state(enriched, e) for e in events}
        except Exception as exc:
            print(f"⚠ 工况状态分类失败（跳过）: {exc}", file=sys.stderr)

        # verbose 状态分布
        if args.verbose and "machine_state" in enriched.columns:
            counts = enriched["machine_state"].value_counts()
            total_rows = len(enriched)
            print("\n┌─ 工况状态分布 " + "─" * 54)
            for state_key in ["stopped", "low_load_operation", "normal_excavation", "heavy_load_excavation"]:
                n = counts.get(state_key, 0)
                pct = n / total_rows * 100 if total_rows > 0 else 0.0
                label = STATE_LABELS.get(state_key, state_key)
                print(f"  {label:<12}: {pct:5.1f}%  ({n:,} 行)")

        try:
            evidences = extract_evidence(enriched, events, event_states=event_states)
            apply_to_evidences(evidences)   # 语义重分类：(event_type, dominant_state) → semantic_event_type
            explanations = TemplateExplainer().explain_all(evidences, event_states=event_states)
        except Exception as exc:
            print(f"✗ 解释生成失败: {exc}", file=sys.stderr)
            return 1

        # 重新打印带语义标签的事件摘要（替换上方无语义信息的早期打印）
        _print_event_summary(events, verbose=args.verbose, event_states=event_states, evidences=evidences)
        _print_explanations(explanations, verbose=args.verbose, top_k=cfg.cli.top_k_explanations, event_states=event_states)

        # ── LLM 跨事件总结（可选）────────────────────────────────────────────
        llm_result = None
        if getattr(args, "llm_summary", False):
            # --llm-model CLI 参数覆盖 config 默认值
            llm_cfg = cfg.llm
            if getattr(args, "llm_model", None):
                from dataclasses import replace as dc_replace
                llm_cfg = dc_replace(llm_cfg, model=args.llm_model)
            from tbm_diag.reviewer import _compute_semantic_stats
            summary_input = build_summary_input(
                input_file=args.input,
                total_rows=len(enriched),
                explanations=explanations,
                evidences=evidences,
                events=events,
                event_states=event_states,
                enriched_df=enriched,
                semantic_stats=_compute_semantic_stats(evidences, events),
            )
            if summary_input:
                print("\n[LLM] 正在生成跨事件总结 …", end="", flush=True)
                llm_result = summarize(summary_input, llm_cfg)
                if llm_result:
                    print(" 完成")
                    _print_llm_summary(llm_result)
                else:
                    print(" 跳过（见上方警告）", file=sys.stderr)
                    print()
            else:
                logger.debug("summarizer: build_summary_input returned None, skipping")

    # ── 导出 ──────────────────────────────────────────────────────────────────
    need_export = any([
        getattr(args, "save_json", None),
        getattr(args, "save_report", None),
        getattr(args, "save_events_csv", None),
    ])
    if need_export and events:
        bundle = ResultBundle(
            input_file=args.input,
            ingestion=_ingestion_result,
            cleaning=_cleaning_report,
            detection=result,
            events=events,
            evidences=evidences,
            explanations=explanations,
            llm_summary=llm_result,
        )
        if args.save_json:
            try:
                to_json(bundle, Path(args.save_json))
                print(f"\n✓ JSON 已导出: {args.save_json}")
            except Exception as exc:
                print(f"✗ JSON 导出失败: {exc}", file=sys.stderr)

        if args.save_report:
            try:
                to_markdown(bundle, Path(args.save_report), verbose=args.verbose)
                print(f"✓ 报告已导出: {args.save_report}")
            except Exception as exc:
                print(f"✗ 报告导出失败: {exc}", file=sys.stderr)

        if args.save_events_csv:
            try:
                to_events_csv(bundle, Path(args.save_events_csv))
                print(f"✓ 事件表已导出: {args.save_events_csv}")
            except Exception as exc:
                print(f"✗ 事件表导出失败: {exc}", file=sys.stderr)

    if hasattr(args, "output") and args.output:
        out = Path(args.output)
        try:
            result.df.to_csv(out, index=False, encoding="utf-8-sig")
            print(f"\n✓ 已导出检测结果: {out}  ({len(result.df):,} 行 × {result.df.shape[1]} 列)")
        except Exception as exc:
            print(f"✗ 导出失败: {exc}", file=sys.stderr)
            return 1

    print("\n✓ 完成")
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    """watch 子命令：监听目录，自动分析新 CSV 文件。"""
    _setup_logging(args.verbose)
    cfg = load_config(getattr(args, "config", None))
    state_file = Path(args.state_file) if args.state_file else None
    # CLI --interval 优先；未指定时使用配置文件值
    interval = args.interval if args.interval != 3.0 else cfg.cli.watch_interval
    run_watch_loop(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        interval=interval,
        state_file=state_file,
        cfg=cfg,
    )
    return 0


def _cmd_agent(args: argparse.Namespace) -> int:
    """agent 子命令：通过 OpenAI-compatible tool calling 运行 agent 诊断。"""
    _setup_logging(args.verbose)
    cfg = load_config(getattr(args, "config", None))

    # --agent-model 覆盖 config 默认值
    agent_cfg = cfg.agent
    if getattr(args, "agent_model", None):
        from dataclasses import replace as dc_replace
        agent_cfg = dc_replace(agent_cfg, model=args.agent_model)
    if getattr(args, "no_reasoning_split", False):
        from dataclasses import replace as dc_replace
        agent_cfg = dc_replace(agent_cfg, reasoning_split=False)

    print(f"[agent] 启动 agent 模式  model={agent_cfg.model}")
    print(f"[agent] 输入文件: {args.input}", flush=True)

    result: AgentResult = run_agent(
        file_path=args.input,
        cfg=agent_cfg,
        save_json=getattr(args, "save_json", None),
        save_report=getattr(args, "save_report", None),
        save_events_csv=getattr(args, "save_events_csv", None),
        verbose=args.verbose,
    )

    if result.final_report:
        print(f"\n┌─ Agent 诊断报告 " + "─" * 52)
        for line in result.final_report.splitlines():
            print(f"  {line}")

    if result.exported_paths:
        print()
        for p in result.exported_paths:
            print(f"✓ 已导出: {p}")

    if result.error:
        print(f"\n⚠ {result.error}", file=sys.stderr)

    print("\n✓ 完成")
    return 0 if result.final_report else 1


def _cmd_review(args: argparse.Namespace) -> int:
    """review 子命令：对 scan_index.csv 中的高风险文件批量执行 AI 复核。"""
    _setup_logging(args.verbose)
    cfg = load_config(getattr(args, "config", None))

    import dataclasses
    review_cfg = dataclasses.replace(
        cfg.review,
        top_n=args.top_n,
        use_agent=args.use_agent,
        overwrite=args.overwrite,
        require_llm=getattr(args, "require_llm", False),
    )

    if getattr(args, "llm_model", None):
        cfg.llm = dataclasses.replace(cfg.llm, model=args.llm_model)

    records = run_review(
        scan_index_path=Path(args.scan_index),
        output_dir=Path(args.output_dir),
        review_cfg=review_cfg,
        shared_cfg=cfg,
    )

    if review_cfg.require_llm:
        ok_n = sum(1 for r in records if r.status == "ok")
        llm_ok = sum(1 for r in records if r.summary_source == "llm")
        if llm_ok < ok_n:
            return 1
    return 0


def _cmd_llm_check(args: argparse.Namespace) -> int:
    """llm-check 子命令：测试 OpenAI-compatible API 连通性。"""
    import os
    cfg = load_config(getattr(args, "config", None))

    api_key = os.environ.get(cfg.llm.api_key_env, "").strip()
    base_url = os.environ.get(cfg.llm.base_url_env, "").strip() or None
    model = os.environ.get("LLM_MODEL", "").strip() or cfg.llm.model

    print("[llm-check] OpenAI-compatible API 连通性测试")
    print(f"  API Key 环境变量 : {cfg.llm.api_key_env} = {'已设置' if api_key else '未设置'}")
    print(f"  Base URL         : {base_url or '(默认 OpenAI)'}")
    print(f"  模型             : {model}")

    if not api_key:
        print("\n✗ 状态: no_key — 未设置 API Key")
        return 1

    try:
        from openai import OpenAI
    except ImportError:
        print("\n✗ 状态: no_sdk — openai SDK 未安装 (pip install openai)")
        return 1

    client = OpenAI(api_key=api_key, base_url=base_url)
    print("\n  发送测试请求 …", end="", flush=True)

    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=256,
            temperature=0,
            timeout=30,
            messages=[{"role": "user", "content": '直接输出 JSON，不要思考：{"ok": true, "message": "hello"}'}],
        )
        raw = (resp.choices[0].message.content or "").strip()
        print(" 收到响应")
    except Exception as exc:
        exc_name = type(exc).__name__
        if "timeout" in exc_name.lower() or "timed out" in str(exc).lower():
            print(f"\n✗ 状态: timeout — {exc}")
            return 1
        print(f"\n✗ 状态: api_error — {exc_name}: {exc}")
        return 1

    print(f"  原始响应预览     : {raw[:200]}")

    from tbm_diag.summarizer import robust_json_extract
    parsed = robust_json_extract(raw)
    if parsed and parsed.get("ok"):
        print(f"\n✓ 状态: success — API 调用成功，JSON 解析成功")
        return 0
    elif parsed:
        print(f"\n⚠ 状态: success (partial) — JSON 解析成功但内容不符预期: {parsed}")
        return 0
    else:
        print(f"\n⚠ 状态: parse_error — API 调用成功但 JSON 解析失败")
        return 1


def _cmd_llm_planner_check(args: argparse.Namespace) -> int:
    """llm-planner-check：测试 LLM planner 是否能稳定返回可解析 action。"""
    import os
    import json

    cfg = load_config(getattr(args, "config", None))

    api_key = os.environ.get(cfg.llm.api_key_env, "").strip()
    base_url = os.environ.get(cfg.llm.base_url_env, "").strip() or None
    model = os.environ.get("LLM_MODEL", "").strip() or cfg.llm.model

    use_reasoning_split = os.environ.get("LLM_REASONING_SPLIT", "").strip().lower() in ("true", "1", "yes")

    print("[llm-planner-check] LLM Planner 可用性测试")
    print(f"  Provider        : {base_url or 'api.openai.com'}")
    print(f"  Model           : {model}")
    print(f"  reasoning_split : {use_reasoning_split}")
    print(f"  API Key         : {'已设置' if api_key else '未设置'}")

    if not api_key:
        print("\n✗ 状态: no_key — 未设置 API Key")
        return 1

    try:
        from openai import OpenAI
    except ImportError:
        print("\n✗ 状态: no_sdk — openai SDK 未安装")
        return 1

    from tbm_diag.investigation.planner import parse_planner_response, LLM_TOOL_WHITELIST, _LLM_SYSTEM_PROMPT, _TBM_GLOSSARY

    scenarios = [
        {
            "name": "场景1: 初始状态，应选 inspect_file_overview",
            "state": {
                "mode": "single_file", "focus": "auto", "current_file": "test.csv",
                "round": 1, "max_iterations": 15,
                "actions_done": [],
                "last_observation": "尚未检查文件概览",
                "indicators": {"event_count": 0, "stoppage_segment_count": 0,
                               "stopped_ratio_pct": 0, "ser_count": 0, "hyd_count": 0},
                "evidence_status": {"stoppage_case_count": 0, "drilldown_sc_count": 0, "unverified_not_drilled": []},
                "open_questions": [],
                "available_tools": list(LLM_TOOL_WHITELIST),
                "completed_tools": [],
            },
            "expected_actions": ["inspect_file_overview"],
        },
        {
            "name": "场景2: 11个停机案例未drilldown，应选停机分析",
            "state": {
                "mode": "single_file", "focus": "auto", "current_file": "test.csv",
                "round": 4, "max_iterations": 15,
                "actions_done": ["inspect_file_overview", "load_event_summary"],
                "last_observation": "已有 11 个停机案例，drilldown_count=0，存在未验证停机线索",
                "indicators": {"event_count": 25, "stoppage_segment_count": 11,
                               "stopped_ratio_pct": 45, "ser_count": 3, "hyd_count": 2},
                "evidence_status": {"stoppage_case_count": 11, "drilldown_sc_count": 0,
                                    "unverified_not_drilled": ["SC_001", "SC_002", "SC_003"]},
                "open_questions": [{"qid": "Q1", "text": "停机原因是什么", "priority": "high", "status": "unanswered"}],
                "available_tools": [t for t in LLM_TOOL_WHITELIST if t not in ("inspect_file_overview", "load_event_summary")],
                "completed_tools": ["inspect_file_overview", "load_event_summary"],
            },
            "expected_actions": ["analyze_stoppage_cases", "drilldown_time_window", "drilldown_time_windows_batch"],
        },
        {
            "name": "场景3: 所有分析完成，应选 generate_investigation_report",
            "state": {
                "mode": "single_file", "focus": "auto", "current_file": "test.csv",
                "round": 12, "max_iterations": 15,
                "actions_done": list(LLM_TOOL_WHITELIST),
                "last_observation": "P1/P2/P3/P4 已完成，coverage 足够，质量门禁通过",
                "indicators": {"event_count": 25, "stoppage_segment_count": 11,
                               "stopped_ratio_pct": 45, "ser_count": 3, "hyd_count": 2},
                "evidence_status": {"stoppage_case_count": 11, "drilldown_sc_count": 11,
                                    "unverified_not_drilled": []},
                "open_questions": [],
                "available_tools": ["generate_investigation_report"],
                "completed_tools": [t for t in LLM_TOOL_WHITELIST if t != "generate_investigation_report"],
            },
            "expected_actions": ["generate_investigation_report"],
        },
    ]

    client = OpenAI(api_key=api_key, base_url=base_url)
    success_count = 0
    parse_error_count = 0
    schema_invalid_count = 0
    invalid_action_count = 0

    for i, sc in enumerate(scenarios):
        print(f"\n{'='*60}")
        print(f"  {sc['name']}")
        available = sc["state"].get("available_tools", LLM_TOOL_WHITELIST)
        system_msg = _LLM_SYSTEM_PROMPT.format(tools=", ".join(available), glossary=_TBM_GLOSSARY)
        user_msg = json.dumps(sc["state"], ensure_ascii=False)

        create_kwargs: dict = dict(
            model=model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=512,
            temperature=0.2,
            timeout=30,
        )
        if use_reasoning_split:
            create_kwargs["extra_body"] = {"reasoning_split": True}

        try:
            try:
                resp = client.chat.completions.create(**create_kwargs)
            except Exception as exc:
                if use_reasoning_split and any(k in str(exc).lower() for k in (
                    "extra_body", "reasoning_split", "unknown", "invalid", "unexpected", "parameter",
                )):
                    create_kwargs.pop("extra_body", None)
                    resp = client.chat.completions.create(**create_kwargs)
                else:
                    raise

            msg = resp.choices[0].message
            pr = parse_planner_response(msg, whitelist=LLM_TOOL_WHITELIST)

            raw_preview = (pr.raw_content or "")[:200]
            cleaned_preview = (pr.cleaned_content or "")[:200]

            print(f"  raw_preview     : {raw_preview}")
            print(f"  cleaned_preview : {cleaned_preview}")
            print(f"  parse_strategy  : {pr.parse_strategy}")
            print(f"  status          : {pr.status}")

            if pr.status == "success":
                action = pr.parsed["selected_action"]
                print(f"  selected_action : {action}")
                if action in sc["expected_actions"]:
                    print(f"  ✓ 符合预期")
                    success_count += 1
                else:
                    print(f"  ✗ 不符合预期（期望 {sc['expected_actions']}）")
                    invalid_action_count += 1
            else:
                print(f"  error_message   : {pr.error_message}")
                if pr.status in ("schema_invalid",):
                    schema_invalid_count += 1
                else:
                    parse_error_count += 1
        except Exception as exc:
            print(f"  ✗ API 异常: {type(exc).__name__}: {str(exc)[:200]}")
            parse_error_count += 1

    print(f"\n{'='*60}")
    print(f"[llm-planner-check] 结果汇总")
    print(f"  Provider        : {base_url or 'api.openai.com'}")
    print(f"  Model           : {model}")
    print(f"  success_count   : {success_count}/3")
    print(f"  parse_error     : {parse_error_count}")
    print(f"  schema_invalid  : {schema_invalid_count}")
    print(f"  invalid_action  : {invalid_action_count}")

    if success_count >= 2:
        print(f"\n✓ LLM planner 可用（success >= 2/3）")
        return 0
    else:
        print(f"\n✗ LLM planner 不可用（success < 2/3），请检查模型输出格式")
        return 1


def _cmd_investigate(args: argparse.Namespace) -> int:
    """investigate 子命令：停机案例追查 ReAct Agent。"""
    _setup_logging(args.verbose)

    from tbm_diag.investigation.controller import run_investigation

    input_files: list[str] = []
    mode = "single_file"

    if args.input:
        p = Path(args.input)
        if not p.exists():
            print(f"✗ 文件不存在: {p}", file=sys.stderr)
            return 2
        input_files = [str(p)]
    elif args.scan_index:
        idx_path = Path(args.scan_index)
        if not idx_path.exists():
            print(f"✗ scan_index 不存在: {idx_path}", file=sys.stderr)
            return 2
        idx_df = pd.read_csv(idx_path, encoding="utf-8-sig")
        if "risk_rank_score" in idx_df.columns:
            idx_df = idx_df.sort_values("risk_rank_score", ascending=False)
        top_n = args.top_n
        for _, row in idx_df.head(top_n).iterrows():
            fp = row.get("file_path", "")
            if fp and Path(fp).exists():
                input_files.append(str(fp))
        mode = "scan_topn"
        if not input_files:
            print("✗ scan_index 中无可用文件", file=sys.stderr)
            return 1

    result = run_investigation(
        input_files=input_files,
        mode=mode,
        output_dir=args.output_dir,
        use_llm=args.use_llm_planner,
        max_iterations=args.max_iterations,
        planner_audit=getattr(args, "planner_audit", False),
        focus=getattr(args, "mode", "auto"),
        planner_mode=getattr(args, "planner", "rule"),
    )

    if result.report_text:
        print(f"\n{'='*70}")
        for line in result.report_text.splitlines()[:30]:
            print(f"  {line}")
        if len(result.report_text.splitlines()) > 30:
            print(f"  ... (完整报告见 {result.report_path})")
        print(f"{'='*70}")

    print(f"\n✓ 报告: {result.report_path}")
    print(f"✓ 状态: {result.state_path}")
    print(f"✓ 记忆: {result.memory_path}")
    return 0


def _cmd_investigate_modes(args: argparse.Namespace) -> int:
    """investigate-modes 子命令：依次运行四种 mode，输出 mode_comparison.md。"""
    _setup_logging(args.verbose)
    from tbm_diag.investigation.controller import run_investigation

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"✗ 文件不存在: {input_path}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    modes = ["stoppage", "resistance", "hydraulic", "fragmentation"]
    mode_labels = {
        "stoppage": "停机追查",
        "resistance": "掘进阻力追查",
        "hydraulic": "液压异常追查",
        "fragmentation": "碎片化检查",
    }
    results: list[dict] = []

    for mode in modes:
        mode_dir = output_dir / mode
        mode_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n{'='*60}")
        print(f"[investigate-modes] 运行 mode={mode} ({mode_labels[mode]})")
        print(f"{'='*60}")

        result = run_investigation(
            input_files=[str(input_path)],
            mode="single_file",
            output_dir=str(mode_dir),
            use_llm=False,
            max_iterations=args.max_iterations,
            planner_audit=True,
            focus=mode,
        )

        import json as _json
        state_path = mode_dir / "investigation_state.json"
        action_seq = ""
        rounds = 0
        triggered_fields: list[str] = []
        conclusion = ""
        if state_path.exists():
            state_doc = _json.loads(state_path.read_text(encoding="utf-8"))
            action_names = [a.get("action", "") for a in state_doc.get("actions_taken", [])]
            action_seq = " → ".join(action_names)
            rounds = state_doc.get("iteration_count", 0)
            for audit in state_doc.get("audit_log", []):
                tf = audit.get("triggered_by_field", "")
                if tf and tf not in triggered_fields:
                    triggered_fields.append(tf)
            conclusion = state_doc.get("stop_reason", "")

        results.append({
            "mode": mode,
            "label": mode_labels[mode],
            "action_sequence": action_seq,
            "rounds": rounds,
            "triggered_fields": "、".join(triggered_fields) if triggered_fields else "—",
            "conclusion": conclusion,
            "output_dir": str(mode_dir),
        })

    # 生成 mode_comparison.md
    import json as _json
    from datetime import datetime
    lines = [
        "# investigate 模式对比",
        "",
        f"- 输入文件：`{input_path}`",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 最大轮数：{args.max_iterations}",
        "",
        "## 对比表",
        "",
        "| mode | action_sequence | rounds | 关键触发字段 | 结论摘要 | 输出目录 |",
        "|------|----------------|-------:|------------|---------|---------|",
    ]
    for r in results:
        lines.append(
            f"| {r['mode']} | `{r['action_sequence']}` | {r['rounds']} | {r['triggered_fields']} | {r['conclusion']} | `{r['output_dir']}` |"
        )

    lines += [
        "",
        "## 说明",
        "",
        "不同 mode 会调用不同的工具链，产生不同的 action_sequence。",
        "这说明 investigate 是真正的 ReAct 动态调查，而非固定 pipeline。",
        "",
        "每个 mode 的完整 ReAct 调查轨迹见对应输出目录下的 `investigation_state.json`。",
    ]

    comp_path = output_dir / "mode_comparison.md"
    comp_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"[investigate-modes] 对比报告已生成: {comp_path}")
    for r in results:
        print(f"  {r['mode']:15s} rounds={r['rounds']:2d}  {r['action_sequence']}")
    print(f"{'='*60}")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    """scan 子命令：批量扫描目录，生成 scan_index.csv。"""
    _setup_logging(args.verbose)
    cfg = load_config(getattr(args, "config", None))

    # CLI 参数覆盖 ScanConfig 默认值
    import dataclasses
    scan_cfg = dataclasses.replace(
        cfg.scan,
        overwrite=args.overwrite,
        recursive=not args.non_recursive,
        max_file_size_mb=args.max_file_size_mb,
    )
    if args.max_workers is not None:
        scan_cfg = dataclasses.replace(scan_cfg, max_workers=args.max_workers)
    if args.llm_summary:
        scan_cfg = dataclasses.replace(scan_cfg, include_llm_summary=True)
    if args.agent:
        scan_cfg = dataclasses.replace(scan_cfg, include_agent=True)

    if scan_cfg.include_llm_summary or scan_cfg.include_agent:
        print("⚠ 注意：大批量场景下不推荐默认开启 LLM/agent，建议仅对少量重点文件使用。")

    run_scan(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        scan_cfg=scan_cfg,
        shared_cfg=cfg,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tbm_diag.cli",
        description="盾构/TBM CSV 智能诊断助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python -m tbm_diag.cli inspect --input data.csv
  python -m tbm_diag.cli inspect --input data.csv --resample 5s --fill linear --output cleaned.csv
  python -m tbm_diag.cli detect  --input data.csv
  python -m tbm_diag.cli detect  --input data.csv --verbose
        """,
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ── inspect 子命令 ─────────────────────────────────────────────────────────
    p_inspect = subparsers.add_parser("inspect", help="字段映射 + 清洗报告 + DataFrame 摘要")
    _add_common_args(p_inspect)
    p_inspect.add_argument("--no-clean", action="store_true", help="跳过清洗步骤")
    p_inspect.add_argument("--output", "-o", default=None, metavar="FILE",
                           help="将清洗后 DataFrame 导出为 CSV（UTF-8 BOM）")

    # ── detect 子命令 ──────────────────────────────────────────────────────────
    p_detect = subparsers.add_parser("detect", help="特征计算 + 异常点检测摘要")
    _add_common_args(p_detect)
    p_detect.add_argument("--output", "-o", default=None, metavar="FILE",
                          help="将检测结果 DataFrame 导出为 CSV（UTF-8 BOM）")
    p_detect.add_argument("--save-json", default=None, metavar="PATH",
                          help="导出完整结构化 JSON 结果")
    p_detect.add_argument("--save-report", default=None, metavar="PATH",
                          help="导出 Markdown 诊断报告")
    p_detect.add_argument("--save-events-csv", default=None, metavar="PATH",
                          help="导出事件表 CSV（UTF-8 BOM，兼容 Excel）")
    p_detect.add_argument("--llm-summary", action="store_true",
                          help="调用 LLM 生成跨事件总结（需设置 ANTHROPIC_API_KEY）")
    p_detect.add_argument("--llm-model", default=None, metavar="MODEL",
                          help="覆盖 config 中的 LLM 模型名（可选）")

    # ── watch 子命令 ───────────────────────────────────────────────────────────
    p_watch = subparsers.add_parser("watch", help="监听目录，自动分析新 CSV 文件")
    p_watch.add_argument("--input-dir",  "-I", required=True, metavar="DIR",
                         help="监听的输入目录")
    p_watch.add_argument("--output-dir", "-O", required=True, metavar="DIR",
                         help="结果输出目录")
    p_watch.add_argument("--interval", type=float, default=3.0, metavar="SEC",
                         help="轮询间隔（秒，默认 3）")
    p_watch.add_argument("--state-file", default=None, metavar="FILE",
                         help="已处理记录文件（默认 output-dir/.watcher_state.json）")
    p_watch.add_argument("--verbose", "-v", action="store_true", help="显示 DEBUG 日志")
    p_watch.add_argument("--config", default=None, metavar="PATH",
                         help="配置文件路径（.yaml / .yml / .json）")

    # ── agent 子命令 ───────────────────────────────────────────────────────────
    p_agent = subparsers.add_parser(
        "agent",
        help="OpenAI-compatible tool-using agent 诊断（默认适配 MiniMax）",
        description=(
            "通过 OpenAI-compatible API 运行 tool-using agent 诊断。\n"
            "默认适配 MiniMax，也支持任何 OpenAI-compatible 服务。\n\n"
            "MiniMax 示例：\n"
            "  export OPENAI_API_KEY=sk-api-xxx\n"
            "  export OPENAI_BASE_URL=https://api.minimaxi.com/v1\n"
            "  python -m tbm_diag.cli agent --input data.csv\n\n"
            "标准 OpenAI 示例：\n"
            "  export OPENAI_API_KEY=sk-xxx\n"
            "  python -m tbm_diag.cli agent --input data.csv --agent-model gpt-4o-mini --no-reasoning-split"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_agent.add_argument("--input", "-i", required=True, metavar="FILE",
                         help="输入 CSV/XLS 文件路径")
    p_agent.add_argument("--agent-model", default=None, metavar="MODEL",
                         help="覆盖 config 中的 agent 模型名（默认 MiniMax-M2.7-highspeed）")
    p_agent.add_argument("--no-reasoning-split", action="store_true",
                         help="关闭 MiniMax reasoning_split 参数（使用标准 OpenAI 服务时建议加此 flag）")
    p_agent.add_argument("--save-json", default=None, metavar="PATH",
                         help="导出完整结构化 JSON 结果")
    p_agent.add_argument("--save-report", default=None, metavar="PATH",
                         help="导出 Markdown 诊断报告")
    p_agent.add_argument("--save-events-csv", default=None, metavar="PATH",
                         help="导出事件表 CSV（UTF-8 BOM，兼容 Excel）")
    p_agent.add_argument("--verbose", "-v", action="store_true",
                         help="显示 DEBUG 日志及 tool 返回内容")
    p_agent.add_argument("--config", default=None, metavar="PATH",
                         help="配置文件路径（.yaml / .yml / .json）")

    # ── scan 子命令 ────────────────────────────────────────────────────────────
    p_scan = subparsers.add_parser(
        "scan",
        help="批量扫描目录，对所有 CSV/XLS/XLSX 文件运行规则诊断，生成 scan_index.csv",
        description=(
            "批量扫描输入目录，对每个文件运行规则诊断内核，\n"
            "生成每文件的 JSON / Markdown / events CSV，以及总索引 scan_index.csv。\n\n"
            "默认不启用 LLM/agent（大批量场景下成本高、速度慢）。\n"
            "如需对少量重点文件深度分析，请使用 detect --llm-summary 或 agent 子命令。\n\n"
            "示例：\n"
            "  python -m tbm_diag.cli scan --input-dir data/ --output-dir scan_out/\n"
            "  python -m tbm_diag.cli scan --input-dir data/ --output-dir scan_out/ --overwrite"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_scan.add_argument("--input-dir",  "-I", required=True, metavar="DIR",
                        help="输入目录（含 CSV/XLS/XLSX 文件）")
    p_scan.add_argument("--output-dir", "-O", required=True, metavar="DIR",
                        help="结果输出目录（自动创建）")
    p_scan.add_argument("--config", default=None, metavar="PATH",
                        help="配置文件路径（.yaml / .yml / .json）")
    p_scan.add_argument("--overwrite", action="store_true",
                        help="强制重新处理所有文件（忽略已有状态）")
    p_scan.add_argument("--non-recursive", action="store_true",
                        help="不递归扫描子目录（默认递归）")
    p_scan.add_argument("--max-workers", type=int, default=None, metavar="N",
                        help="并发数（v1 仅支持 1，保留参数供后续扩展）")
    p_scan.add_argument("--llm-summary", action="store_true",
                        help="为每个文件生成 LLM 跨事件总结（大批量不推荐，需设置 ANTHROPIC_API_KEY）")
    p_scan.add_argument("--agent", action="store_true",
                        help="为每个文件运行 agent 模式（大批量不推荐）")
    p_scan.add_argument("--max-file-size-mb", type=float, default=0.0, metavar="MB",
                        help="跳过超过此大小的文件（MB），0 表示不限制")
    p_scan.add_argument("--verbose", "-v", action="store_true",
                        help="显示 DEBUG 日志")

    # ── review 子命令 ──────────────────────────────────────────────────────────
    p_review = subparsers.add_parser(
        "review",
        help="对 scan_index.csv 中的高风险文件批量执行 AI 复核",
        description=(
            "读取 scan_index.csv，按 risk_rank_score 筛出 Top N 文件，\n"
            "批量调用 LLM summary 或 agent，生成 review_summary.md / review_summary.json。\n\n"
            "示例：\n"
            "  python -m tbm_diag.cli review \\\n"
            "    --scan-index scan_real_out/scan_index.csv \\\n"
            "    --output-dir review_out --top-n 5\n\n"
            "  # 使用 agent 模式（需设置 OPENAI_API_KEY / OPENAI_BASE_URL）\n"
            "  python -m tbm_diag.cli review \\\n"
            "    --scan-index scan_real_out/scan_index.csv \\\n"
            "    --output-dir review_out --top-n 3 --use-agent"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_review.add_argument("--scan-index", required=True, metavar="PATH",
                          help="scan_index.csv 路径")
    p_review.add_argument("--output-dir", "-O", required=True, metavar="DIR",
                          help="复核结果输出目录")
    p_review.add_argument("--top-n", type=int, default=5, metavar="N",
                          help="只 review Top N 高风险文件（默认 5）")
    p_review.add_argument("--use-agent", action="store_true",
                          help="使用 agent 模式（需设置 OPENAI_API_KEY / OPENAI_BASE_URL）")
    p_review.add_argument("--overwrite", action="store_true",
                          help="强制重新 review 已有结果")
    p_review.add_argument("--llm-model", default=None, metavar="MODEL",
                          help="覆盖 config 中的 LLM 模型名")
    p_review.add_argument("--require-llm", action="store_true",
                          help="要求所有文件 LLM 成功，否则 exit code 非 0")
    p_review.add_argument("--config", default=None, metavar="PATH",
                          help="配置文件路径（.yaml / .yml / .json）")
    p_review.add_argument("--verbose", "-v", action="store_true",
                          help="显示 DEBUG 日志")

    # ── investigate 子命令 ─────────────────────────────────────────────────────
    p_inv = subparsers.add_parser(
        "investigate",
        help="停机案例追查 ReAct Agent",
        description=(
            "对高风险文件运行停机案例追查，合并碎片停机事件为案例，\n"
            "分析前后窗口，分类计划/异常停机，生成调查报告。\n\n"
            "示例：\n"
            "  python -m tbm_diag.cli investigate --input data.xls\n"
            "  python -m tbm_diag.cli investigate --scan-index scan_real_out/scan_index.csv --top-n 3\n"
            "  python -m tbm_diag.cli investigate --input data.xls --use-llm-planner"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    inv_input = p_inv.add_mutually_exclusive_group(required=True)
    inv_input.add_argument("--input", "-i", metavar="FILE",
                           help="单文件调查")
    inv_input.add_argument("--scan-index", metavar="PATH",
                           help="scan_index.csv 路径，取 Top N 高风险文件调查")
    p_inv.add_argument("--top-n", type=int, default=3, metavar="N",
                       help="从 scan_index 取 Top N 文件（默认 3）")
    p_inv.add_argument("--output-dir", "-O", default="investigation_out", metavar="DIR",
                       help="输出目录（默认 investigation_out）")
    p_inv.add_argument("--mode", default="auto",
                       choices=["auto", "stoppage", "resistance", "hydraulic", "fragmentation"],
                       help="调查聚焦模式（默认 auto）")
    p_inv.add_argument("--planner", default="rule",
                       choices=["rule", "llm", "hybrid"],
                       help="planner 模式：rule=纯规则 llm=每轮调LLM hybrid=混合（默认 rule；演示 LLM ReAct 请用 --planner llm）")
    p_inv.add_argument("--use-llm-planner", action="store_true",
                       help="（已废弃，请用 --planner llm）使用 LLM planner")
    p_inv.add_argument("--max-iterations", type=int, default=50, metavar="N",
                       help="最大迭代轮数（默认 50）")
    p_inv.add_argument("--config", default=None, metavar="PATH",
                       help="配置文件路径")
    p_inv.add_argument("--verbose", "-v", action="store_true",
                       help="显示 DEBUG 日志")
    p_inv.add_argument("--planner-audit", action="store_true",
                       help="启用 planner 审计模式，记录每轮候选/拒绝 action")

    # ── investigate-modes 子命令 ────────────────────────────────────────────────
    p_inv_modes = subparsers.add_parser(
        "investigate-modes",
        help="依次运行四种 investigate mode 并生成对比表（演示/审计工具）",
        description=(
            "依次对同一文件运行 stoppage / resistance / hydraulic / fragmentation 四种 mode，\n"
            "每种 mode 都带 --planner-audit，生成 mode_comparison.md 对比表。\n\n"
            "目的：演示不同 mode 调用不同工具链，验证 ReAct 动态选择。\n\n"
            "示例：\n"
            "  python -m tbm_diag.cli investigate-modes --input sample2.xls --output-dir investigation_modes_demo --max-iterations 12"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_inv_modes.add_argument("--input", "-i", required=True, metavar="FILE",
                             help="输入文件路径")
    p_inv_modes.add_argument("--output-dir", "-O", default="investigation_modes_demo", metavar="DIR",
                             help="输出目录（默认 investigation_modes_demo）")
    p_inv_modes.add_argument("--max-iterations", type=int, default=12, metavar="N",
                             help="每种 mode 的最大轮数（默认 12）")
    p_inv_modes.add_argument("--verbose", "-v", action="store_true",
                             help="显示 DEBUG 日志")

    # ── llm-check 子命令 ──────────────────────────────────────────────────────
    p_llm = subparsers.add_parser(
        "llm-check",
        help="测试当前 OpenAI-compatible API 是否可用",
    )
    p_llm.add_argument("--config", default=None, metavar="PATH",
                       help="配置文件路径")

    # ── llm-planner-check 子命令 ──────────────────────────────────────────────
    p_planner = subparsers.add_parser(
        "llm-planner-check",
        help="测试 LLM planner 是否能稳定返回可解析 action（3 个固定场景）",
    )
    p_planner.add_argument("--config", default=None, metavar="PATH",
                           help="配置文件路径")

    # ── 兼容旧用法：无子命令时若有 --input 则默认走 inspect ──────────────────
    args, _ = parser.parse_known_args(argv)

    if args.command is None:
        raw = list(argv or sys.argv[1:])
        if "--input" in raw or "-i" in raw:
            args = parser.parse_args(["inspect"] + raw)
        else:
            parser.print_help()
            return 0

    if args.command == "inspect":
        return _cmd_inspect(args)
    elif args.command == "detect":
        return _cmd_detect(args)
    elif args.command == "watch":
        return _cmd_watch(args)
    elif args.command == "agent":
        return _cmd_agent(args)
    elif args.command == "scan":
        return _cmd_scan(args)
    elif args.command == "review":
        return _cmd_review(args)
    elif args.command == "investigate":
        return _cmd_investigate(args)
    elif args.command == "investigate-modes":
        return _cmd_investigate_modes(args)
    elif args.command == "llm-check":
        return _cmd_llm_check(args)
    elif args.command == "llm-planner-check":
        return _cmd_llm_planner_check(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
