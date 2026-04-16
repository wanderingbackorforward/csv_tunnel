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


def _print_event_summary(events: list[Event], verbose: bool = False) -> None:
    print("\n┌─ 事件摘要 " + "─" * 58)

    if not events:
        print("  ✓ 未形成有效异常事件（所有异常点均未达到最小持续时长）")
        return

    # 按类型统计
    type_counts: dict[str, int] = {}
    for e in events:
        type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1

    print(f"  共检测到 {len(events)} 个异常事件：")
    for atype, label in _ANOMALY_LABELS.items():
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
        label = _ANOMALY_LABELS.get(e.event_type, e.event_type)
        start = str(e.start_time)[:19] if e.start_time is not None else "—"
        end   = str(e.end_time)[:19]   if e.end_time   is not None else "—"
        dur_s = f"{e.duration_seconds:.0f}s" if e.duration_seconds is not None else "—"
        rows.append([
            e.event_id,
            label,
            start,
            end,
            f"{e.duration_points}点/{dur_s}",
            f"{e.peak_score:.3f}",
            f"{e.mean_score:.3f}",
        ])

    print(_table(
        rows,
        headers=["事件ID", "类型", "开始时间", "结束时间", "时长", "峰值分", "均值分"],
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

    _print_event_summary(events, verbose=args.verbose)

    if events:
        try:
            evidences = extract_evidence(enriched, events)
            explanations = TemplateExplainer().explain_all(evidences)
        except Exception as exc:
            print(f"✗ 解释生成失败: {exc}", file=sys.stderr)
            return 1
        _print_explanations(explanations, verbose=args.verbose, top_k=cfg.cli.top_k_explanations)

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
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
