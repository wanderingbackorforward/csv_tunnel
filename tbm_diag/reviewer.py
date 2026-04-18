"""
reviewer.py — AI 二次复核层

对 scan_index.csv 中筛出的高风险文件批量执行 AI 复核。
复用现有 detect / agent / summarizer 主链路，不重写。

用法：
    python -m tbm_diag.cli review \
        --scan-index scan_real_out/scan_index.csv \
        --output-dir review_out \
        --top-n 5
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── ReviewConfig ───────────────────────────────────────────────────────────────

@dataclass
class ReviewConfig:
    top_n: int = 5
    """默认只 review Top N 高风险文件。"""
    use_agent: bool = False
    """True 时调用 agent 模式；False 时调用 detect + LLM summary。"""
    overwrite: bool = False
    """True 时强制重新 review 已有结果。"""
    min_severity: str = ""
    """最低严重度过滤（高风险/中风险/低风险/观察），空字符串不过滤。"""


# ── ReviewRecord ───────────────────────────────────────────────────────────────

@dataclass
class ReviewRecord:
    """单文件 AI 复核结果。"""
    file_name: str
    file_path: str
    risk_rank_score: float
    event_count: int
    max_severity_label: str
    status: str                    # ok / error
    ai_summary: str = ""
    top_risks: list = field(default_factory=list)
    suggested_actions: list = field(default_factory=list)
    top_event_type: str = ""
    error_message: str = ""
    review_json_path: str = ""
    review_md_path: str = ""
    semantic_type_counts: dict = field(default_factory=dict)
    """各 semantic_event_type 的统计：{sem_type: {"count": N, "total_seconds": X}}"""


# ── 读取 scan_index ────────────────────────────────────────────────────────────

_SEV_ORDER = {"高风险": 4, "中风险": 3, "低风险": 2, "观察": 1}


def load_scan_index(path: Path) -> list[dict]:
    """读取 scan_index.csv，返回按 risk_rank_score 降序排列的记录列表。"""
    if not path.exists():
        print(f"✗ scan_index.csv 不存在: {path}", file=sys.stderr)
        sys.exit(2)
    records = []
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    row["risk_rank_score"] = float(row.get("risk_rank_score") or 0)
                except (ValueError, TypeError):
                    row["risk_rank_score"] = 0.0
                try:
                    row["event_count"] = int(row.get("event_count") or 0)
                except (ValueError, TypeError):
                    row["event_count"] = 0
                records.append(row)
    except Exception as exc:
        print(f"✗ 读取 scan_index.csv 失败: {exc}", file=sys.stderr)
        sys.exit(1)
    records.sort(key=lambda r: r["risk_rank_score"], reverse=True)
    return records


def select_targets(records: list[dict], cfg: ReviewConfig) -> list[dict]:
    """按 ReviewConfig 筛选目标文件。"""
    min_order = _SEV_ORDER.get(cfg.min_severity, 0)
    filtered = []
    for r in records:
        if r.get("status") not in ("ok", "skipped"):
            continue
        if min_order > 0:
            if _SEV_ORDER.get(r.get("max_severity_label", ""), 0) < min_order:
                continue
        filtered.append(r)
    return filtered[:cfg.top_n]


# ── detect + LLM summary pipeline ─────────────────────────────────────────────

def _compute_semantic_stats(evidences: list, events: list) -> dict:
    """从 evidences 汇总各 semantic_event_type 的事件数和总时长。"""
    dur_map = {e.event_id: (e.duration_seconds or 0.0) for e in events}
    stats: dict[str, dict] = {}
    for ev in evidences:
        sem = ev.semantic_event_type or ev.event_type
        if sem not in stats:
            stats[sem] = {"count": 0, "total_seconds": 0.0}
        stats[sem]["count"] += 1
        stats[sem]["total_seconds"] += dur_map.get(ev.event_id, 0.0)
    return stats


def _run_detect_and_summarize(
    file_path: str,
    output_dir: Path,
    shared_cfg: Any,
) -> tuple:
    """运行完整检测链路 + LLM 总结，返回 (llm_result, fallback_str, json_path, md_path, semantic_stats)。"""
    from tbm_diag.cleaning import clean
    from tbm_diag.detector import detect
    from tbm_diag.evidence import extract_evidence
    from tbm_diag.explainer import TemplateExplainer
    from tbm_diag.exporter import ResultBundle, to_json, to_markdown
    from tbm_diag.feature_engine import enrich_features
    from tbm_diag.ingestion import load_csv
    from tbm_diag.segmenter import segment_events
    from tbm_diag.state_engine import classify_states, summarize_event_state
    from tbm_diag.summarizer import build_summary_input, summarize
    from tbm_diag.semantic_layer import apply_to_evidences

    cfg = shared_cfg
    cc = cfg.cleaning
    resample_freq = None if (cc.resample or "").strip().lower() == "none" else cc.resample
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(file_path).stem

    ingestion = load_csv(file_path)
    df, cleaning = clean(ingestion.df, resample_freq=resample_freq,
                         spike_k=cc.spike_k, fill_method=cc.fill, max_gap_fill=cc.max_gap)
    enriched  = enrich_features(df, window=cfg.feature.rolling_window)
    detection = detect(enriched, config=cfg.detector)
    events    = segment_events(detection.df, config=cfg.segmenter)

    event_states: dict = {}
    if events:
        enriched = classify_states(enriched, config=cfg.state)
        event_states = {e.event_id: summarize_event_state(enriched, e) for e in events}

    evidences    = extract_evidence(enriched, events, event_states=event_states)
    apply_to_evidences(evidences)
    explanations = TemplateExplainer().explain_all(evidences, event_states=event_states)
    semantic_stats = _compute_semantic_stats(evidences, events)

    bundle = ResultBundle(input_file=file_path, ingestion=ingestion, cleaning=cleaning,
                          detection=detection, events=events, evidences=evidences,
                          explanations=explanations)
    json_path = output_dir / f"{stem}.review.json"
    md_path   = output_dir / f"{stem}.review.md"
    to_json(bundle, json_path)
    to_markdown(bundle, md_path)

    llm_result = None
    if events:
        si = build_summary_input(file_path, len(enriched), explanations,
                                 evidences, events, event_states, enriched,
                                 semantic_stats=semantic_stats)
        if si:
            llm_result = summarize(si, cfg.llm)

    fallback = None
    if not llm_result and explanations:
        top = explanations[0]
        fallback = f"共 {len(events)} 个事件，最高 {top.severity_label}。{top.summary}"

    return llm_result, fallback, str(json_path), str(md_path), semantic_stats


# ── 单文件 review ──────────────────────────────────────────────────────────────

def _review_one_llm(row: dict, output_dir: Path, shared_cfg: Any) -> ReviewRecord:
    file_path = row.get("file_path", "")
    rec = ReviewRecord(
        file_name=row.get("file_name", ""), file_path=file_path,
        risk_rank_score=row["risk_rank_score"], event_count=row["event_count"],
        max_severity_label=row.get("max_severity_label", ""),
        top_event_type=row.get("top_event_type", ""), status="error",
    )
    if not Path(file_path).exists():
        rec.error_message = f"原始文件不存在: {file_path}"
        return rec
    try:
        llm_result, fallback, jp, mp, sem_stats = _run_detect_and_summarize(file_path, output_dir, shared_cfg)
        rec.review_json_path = jp
        rec.review_md_path   = mp
        rec.semantic_type_counts = sem_stats
        rec.status = "ok"
        if llm_result:
            rec.ai_summary        = llm_result.overall_summary
            rec.top_risks         = llm_result.top_risks
            rec.suggested_actions = llm_result.suggested_actions
        elif fallback:
            rec.ai_summary = fallback
    except Exception as exc:
        rec.error_message = str(exc)
        logger.exception("review_one_llm failed for %s", file_path)
    return rec


def _review_one_agent(row: dict, output_dir: Path, agent_cfg: Any) -> ReviewRecord:
    from tbm_diag.agent import run_agent
    file_path = row.get("file_path", "")
    stem = Path(file_path).stem
    rec = ReviewRecord(
        file_name=row.get("file_name", ""), file_path=file_path,
        risk_rank_score=row["risk_rank_score"], event_count=row["event_count"],
        max_severity_label=row.get("max_severity_label", ""),
        top_event_type=row.get("top_event_type", ""), status="error",
    )
    if not Path(file_path).exists():
        rec.error_message = f"原始文件不存在: {file_path}"
        return rec
    output_dir.mkdir(parents=True, exist_ok=True)
    jp = str(output_dir / f"{stem}.review.json")
    mp = str(output_dir / f"{stem}.review.md")
    try:
        result = run_agent(file_path=file_path, cfg=agent_cfg, save_json=jp, save_report=mp)
        rec.review_json_path = jp
        rec.review_md_path   = mp
        rec.status = "ok"
        if result.final_report:
            sentences = [s.strip() for s in result.final_report.replace("\n", " ").split("。") if s.strip()]
            rec.ai_summary = "。".join(sentences[:3]) + ("。" if sentences[:3] else "")
        if result.error:
            rec.error_message = result.error
    except Exception as exc:
        rec.error_message = str(exc)
        logger.exception("review_one_agent failed for %s", file_path)
    return rec


# ── 跨文件分析（语义层）─────────────────────────────────────────────────────────

_SEM_LABELS_ZH = {
    "stoppage_segment":                 "停机片段",
    "low_efficiency_excavation":        "推进中低效掘进",
    "excavation_resistance_under_load": "重载推进下的掘进阻力异常",
    "suspected_excavation_resistance":  "疑似掘进阻力异常",
    "attitude_or_bias_risk":            "姿态偏斜风险",
    "hydraulic_instability":            "液压系统不稳定",
}


def _fmt_hours(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 60:.0f}min"


def _build_cross_analysis(records: list[ReviewRecord]) -> dict:
    ok = [r for r in records if r.status == "ok"]
    if not ok:
        return {"note": "无成功 review 的文件"}

    # ── 语义类型跨文件汇总 ────────────────────────────────────────────────────
    sem_agg: dict[str, dict] = {}
    for r in ok:
        for sem, stats in r.semantic_type_counts.items():
            if sem not in sem_agg:
                sem_agg[sem] = {"count": 0, "total_seconds": 0.0, "file_count": 0}
            sem_agg[sem]["count"] += stats.get("count", 0)
            sem_agg[sem]["total_seconds"] += stats.get("total_seconds", 0.0)
            sem_agg[sem]["file_count"] += 1

    # ── 严重度分布 ────────────────────────────────────────────────────────────
    sev_counts: dict[str, int] = {}
    for r in ok:
        k = r.max_severity_label or "无事件"
        sev_counts[k] = sev_counts.get(k, 0) + 1

    # ── 主要业务问题判断 ──────────────────────────────────────────────────────
    stoppage   = sem_agg.get("stoppage_segment", {})
    efficiency = sem_agg.get("low_efficiency_excavation", {})
    resistance = sem_agg.get("excavation_resistance_under_load", {})

    total_events = sum(v["count"] for v in sem_agg.values())
    stoppage_pct   = stoppage.get("count", 0) / total_events * 100 if total_events else 0
    efficiency_pct = efficiency.get("count", 0) / total_events * 100 if total_events else 0
    resistance_pct = resistance.get("count", 0) / total_events * 100 if total_events else 0

    if stoppage_pct >= 50:
        dominant_issue = f"停机时间过长（停机片段占 {stoppage_pct:.0f}% 事件），核心问题是停机管理而非推进参数"
    elif resistance_pct >= 30:
        dominant_issue = f"重载推进下掘进阻力异常（占 {resistance_pct:.0f}% 事件），需关注地层变化与刀具状态"
    elif efficiency_pct >= 30:
        dominant_issue = f"推进中低效掘进（占 {efficiency_pct:.0f}% 事件），需关注推进参数与地层匹配"
    else:
        dominant_issue = "多类型异常并存，建议逐文件详查"

    # ── 优先级排序 ────────────────────────────────────────────────────────────
    priority = sorted(ok, key=lambda r: r.risk_rank_score, reverse=True)

    return {
        "total_reviewed": len(ok),
        "high_risk_count": sum(1 for r in ok if r.max_severity_label == "高风险"),
        "severity_distribution": sev_counts,
        "semantic_event_breakdown": {
            sem: {
                "label_zh": _SEM_LABELS_ZH.get(sem, sem),
                "total_count": v["count"],
                "total_duration": _fmt_hours(v["total_seconds"]),
                "file_count": v["file_count"],
            }
            for sem, v in sorted(sem_agg.items(), key=lambda x: -x[1]["count"])
        },
        "dominant_issue": dominant_issue,
        "priority_order": [
            {"rank": i + 1, "file": r.file_name, "score": r.risk_rank_score,
             "events": r.event_count, "severity": r.max_severity_label}
            for i, r in enumerate(priority)
        ],
    }


# ── 写汇总报告 ─────────────────────────────────────────────────────────────────

def _write_review_summary(
    records: list[ReviewRecord],
    targets: list[dict],
    cfg: ReviewConfig,
    output_dir: Path,
) -> tuple[Path, Path]:
    cross = _build_cross_analysis(records)

    doc = {
        "generated_at": datetime.now().isoformat(),
        "review_config": {"top_n": cfg.top_n, "use_agent": cfg.use_agent, "min_severity": cfg.min_severity},
        "coverage": {
            "selected_files": len(targets),
            "ok_count":    sum(1 for r in records if r.status == "ok"),
            "error_count": sum(1 for r in records if r.status == "error"),
        },
        "file_results": [
            {"file_name": r.file_name, "risk_rank_score": r.risk_rank_score,
             "event_count": r.event_count, "max_severity_label": r.max_severity_label,
             "status": r.status, "ai_summary": r.ai_summary,
             "top_risks": r.top_risks, "suggested_actions": r.suggested_actions,
             "semantic_type_counts": r.semantic_type_counts,
             "error_message": r.error_message,
             "review_json_path": r.review_json_path, "review_md_path": r.review_md_path}
            for r in records
        ],
        "cross_file_analysis": cross,
    }
    json_path = output_dir / "review_summary.json"
    tmp = json_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(json_path)

    # ── Markdown ──────────────────────────────────────────────────────────────
    _SEV_ICON = {"高风险": "[高风险]", "中风险": "[中风险]", "低风险": "[低风险]", "观察": "[观察]"}
    mode_str = "Agent" if cfg.use_agent else "LLM Summary"
    sel_rule = f"Top {cfg.top_n}" + (f"（最低：{cfg.min_severity}）" if cfg.min_severity else "")
    lines = [
        "# AI 复核总报告", "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 覆盖文件数：{len(records)}",
        f"- 入选规则：{sel_rule} 高风险文件（按 risk_rank_score 排序）",
        f"- 执行模式：{mode_str}", "",
        "---", "", "## 各文件简要结论", "",
    ]
    for i, r in enumerate(records, 1):
        icon = _SEV_ICON.get(r.max_severity_label, "")
        lines += [f"### {i}. {r.file_name}  {icon}", "",
                  f"- 风险分：{r.risk_rank_score:.0f}  |  事件数：{r.event_count}  |  状态：{r.status}"]
        # 语义事件分布（每文件）
        if r.semantic_type_counts:
            sem_parts = []
            for sem, stats in sorted(r.semantic_type_counts.items(), key=lambda x: -x[1]["count"]):
                label = _SEM_LABELS_ZH.get(sem, sem)
                dur = _fmt_hours(stats.get("total_seconds", 0))
                sem_parts.append(f"{label} {stats['count']} 个/{dur}")
            lines.append(f"- 语义事件分布：{'，'.join(sem_parts)}")
        if r.ai_summary:
            lines += ["", f"AI 总结：{r.ai_summary}", ""]
        if r.top_risks:
            lines.append("主要风险：")
            lines += [f"- {x}" for x in r.top_risks[:3]]
            lines.append("")
        if r.suggested_actions:
            lines.append("建议：")
            lines += [f"- {x}" for x in r.suggested_actions[:3]]
            lines.append("")
        if r.error_message:
            lines += [f"> 错误：{r.error_message}", ""]
        if r.review_md_path:
            lines += [f"详细报告：{r.review_md_path}", ""]
        lines += ["---", ""]

    # ── 跨文件语义分析 ────────────────────────────────────────────────────────
    lines += ["## 跨文件语义分析", "",
              f"- 成功 review：{cross.get('total_reviewed', 0)} 个文件",
              f"- 高风险文件：{cross.get('high_risk_count', 0)} 个", ""]

    if cross.get("dominant_issue"):
        lines += [f"> **核心问题判断**：{cross['dominant_issue']}", ""]

    sem_breakdown = cross.get("semantic_event_breakdown", {})
    if sem_breakdown:
        lines += ["**各业务语义类型汇总**", ""]
        lines += ["| 语义类型 | 事件数 | 总时长 | 涉及文件数 |",
                  "|----------|--------|--------|------------|"]
        for sem, info in sem_breakdown.items():
            lines.append(
                f"| {info['label_zh']} | {info['total_count']} | "
                f"{info['total_duration']} | {info['file_count']}/{cross.get('total_reviewed', 0)} |"
            )
        lines.append("")

    lines += ["## 建议优先人工查看顺序", ""]
    for p in cross.get("priority_order", []):
        lines.append(f"{p['rank']}. {p['file']}  [{p['severity']}] score={p['score']:.0f}  events={p['events']}")

    md_path = output_dir / "review_summary.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


# ── 主入口 ─────────────────────────────────────────────────────────────────────

def run_review(
    scan_index_path: Path,
    output_dir: Path,
    review_cfg: ReviewConfig,
    shared_cfg: Any = None,
) -> list[ReviewRecord]:
    from tbm_diag.config import DiagConfig
    if shared_cfg is None:
        shared_cfg = DiagConfig()

    output_dir.mkdir(parents=True, exist_ok=True)
    all_rows = load_scan_index(scan_index_path)
    targets  = select_targets(all_rows, review_cfg)

    if not targets:
        print("⚠ 没有符合条件的文件可 review（检查 scan_index.csv 内容和筛选条件）")
        return []

    mode_str = "agent" if review_cfg.use_agent else "llm-summary"
    print(f"\n[review] AI 复核启动")
    print(f"  scan_index : {scan_index_path}")
    print(f"  输出目录   : {output_dir}")
    print(f"  执行模式   : {mode_str}")
    print(f"  选中文件数 : {len(targets)}")
    print()
    for i, row in enumerate(targets, 1):
        print(f"  {i}. {row.get('file_name')}  score={row['risk_rank_score']:.0f}  events={row['event_count']}")
    print()

    records: list[ReviewRecord] = []
    width = len(str(len(targets)))

    for i, row in enumerate(targets, 1):
        fname = row.get("file_name", "")
        print(f"  [{i:>{width}}/{len(targets)}] {fname} …", end="", flush=True)
        if review_cfg.use_agent:
            rec = _review_one_agent(row, output_dir, shared_cfg.agent)
        else:
            rec = _review_one_llm(row, output_dir, shared_cfg)
        records.append(rec)
        if rec.status == "ok":
            has_llm = bool(rec.ai_summary)
            print(f" OK  {'(AI总结已生成)' if has_llm else '(规则降级)'}")
        else:
            print(f" FAIL  {rec.error_message[:60]}")

    json_path, md_path = _write_review_summary(records, targets, review_cfg, output_dir)

    ok_n  = sum(1 for r in records if r.status == "ok")
    err_n = sum(1 for r in records if r.status == "error")
    print(f"\n[review] 完成  OK={ok_n}  失败={err_n}")
    print(f"[review] 总结 JSON : {json_path}")
    print(f"[review] 总结 MD   : {md_path}")
    return records

