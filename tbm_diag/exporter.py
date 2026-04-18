"""
exporter.py — 结果导出

提供三种导出格式：
  to_json()        → 完整结构化 JSON（datetime 安全序列化）
  to_markdown()    → 可读 Markdown 报告
  to_events_csv()  → 事件表 CSV（utf-8-sig，兼容 Windows Excel）

所有函数接受同一个 ResultBundle dataclass，不依赖 CLI 参数。
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from tbm_diag.cleaning import CleaningReport
from tbm_diag.detector import DetectionResult
from tbm_diag.evidence import EventEvidence
from tbm_diag.explainer import Explanation
from tbm_diag.ingestion import IngestionResult
from tbm_diag.segmenter import Event
from tbm_diag.summarizer import LLMSummaryResult

logger = logging.getLogger(__name__)


# ── 结果包 ─────────────────────────────────────────────────────────────────────

@dataclass
class ResultBundle:
    """detect 命令产出的全部结果，供各导出函数消费。"""
    input_file: str
    ingestion: IngestionResult
    cleaning: CleaningReport
    detection: DetectionResult
    events: list[Event]
    evidences: list[EventEvidence]
    explanations: list[Explanation]
    generated_at: datetime = field(default_factory=datetime.now)
    llm_summary: Optional[LLMSummaryResult] = None


# ── 内部辅助 ───────────────────────────────────────────────────────────────────

def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _dt_str(ts: Any) -> Optional[str]:
    """将 pandas Timestamp / datetime / None 统一转为 ISO 字符串。"""
    if ts is None:
        return None
    try:
        return ts.isoformat()
    except AttributeError:
        return str(ts)


class _JsonEncoder(json.JSONEncoder):
    """处理 datetime、pandas Timestamp、numpy 数值等不可序列化类型。"""
    def default(self, obj: Any) -> Any:
        # pandas / datetime
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        # numpy scalar
        try:
            import numpy as np
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        return super().default(obj)


# ── 公开接口 ───────────────────────────────────────────────────────────────────

def to_json(bundle: ResultBundle, path: Path) -> None:
    """
    导出完整结构化 JSON。

    结构：
      meta / ingestion / cleaning / detection_summary /
      events / evidences / explanations
    """
    _ensure_dir(path)

    cr = bundle.cleaning
    dr = bundle.detection

    doc: dict[str, Any] = {
        "meta": {
            "generated_at": bundle.generated_at.isoformat(),
            "input_file": bundle.input_file,
        },
        "ingestion": {
            "encoding": bundle.ingestion.encoding_used,
            "delimiter": bundle.ingestion.delimiter_used,
            "raw_rows": bundle.ingestion.df.shape[0],
            "raw_cols": bundle.ingestion.df.shape[1],
            "recognized_fields": bundle.ingestion.recognized,
            "unrecognized_fields": bundle.ingestion.unrecognized,
        },
        "cleaning": {
            "rows_input": cr.rows_input,
            "rows_after_ts_drop": cr.rows_after_ts_drop,
            "rows_after_dedup": cr.rows_after_dedup,
            "rows_output": cr.rows_output,
            "resample_freq": cr.resample_freq,
            "total_spikes_removed": sum(cr.spike_removed.values()),
            "warnings": cr.warnings,
        },
        "detection_summary": {
            "total_rows": dr.total_rows,
            "hit_counts": dr.hit_counts,
            "skipped_rules": dr.skipped_rules,
        },
        "events": [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "start_time": _dt_str(e.start_time),
                "end_time": _dt_str(e.end_time),
                "duration_points": e.duration_points,
                "duration_seconds": e.duration_seconds,
                "peak_score": e.peak_score,
                "mean_score": e.mean_score,
                "dominant_state": next(
                    (ev.dominant_state for ev in bundle.evidences if ev.event_id == e.event_id),
                    None,
                ),
                "semantic_event_type": next(
                    (ev.semantic_event_type for ev in bundle.evidences if ev.event_id == e.event_id),
                    None,
                ),
            }
            for e in bundle.events
        ],
        "evidences": [
            {
                "event_id": ev.event_id,
                "event_type": ev.event_type,
                "severity_score": ev.severity_score,
                "signals": [
                    {
                        "signal_name": s.signal_name,
                        "display_name": s.display_name,
                        "direction": s.direction,
                        "magnitude_text": s.magnitude_text,
                        "evidence_text": s.evidence_text,
                        "value_summary": {
                            "mean": s.value_summary.mean,
                            "min": s.value_summary.min,
                            "max": s.value_summary.max,
                            "start": s.value_summary.start,
                            "end": s.value_summary.end,
                            "change_pct": s.value_summary.change_pct,
                        },
                    }
                    for s in ev.top_signals
                ],
            }
            for ev in bundle.evidences
        ],
        "explanations": [
            {
                "event_id": exp.event_id,
                "event_type": exp.event_type,
                "severity_label": exp.severity_label,
                "severity_score": exp.severity_score,
                "start_time": _dt_str(exp.start_time),
                "end_time": _dt_str(exp.end_time),
                "title": exp.title,
                "summary": exp.summary,
                "state_context": exp.state_context,
                "semantic_event_type": exp.semantic_event_type,
                "evidence_bullets": exp.evidence_bullets,
                "possible_causes": exp.possible_causes,
                "suggested_actions": exp.suggested_actions,
            }
            for exp in bundle.explanations
        ],
    }

    # llm_summary 节（可选）
    if bundle.llm_summary is not None:
        ls = bundle.llm_summary
        doc["llm_summary"] = {
            "overall_summary": ls.overall_summary,
            "top_risks": ls.top_risks,
            "suggested_actions": ls.suggested_actions,
            "model_used": ls.model_used,
            "generated_at": ls.generated_at,
        }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2, cls=_JsonEncoder)

    logger.info("JSON exported → %s", path)


def to_markdown(
    bundle: ResultBundle,
    path: Path,
    verbose: bool = False,
) -> None:
    """
    导出 Markdown 报告。

    verbose=True 时输出全部事件解释，否则只输出 Top 3。
    """
    _ensure_dir(path)

    lines: list[str] = []
    app = lines.append

    dr = bundle.detection
    cr = bundle.cleaning
    exps = bundle.explanations
    show_exps = exps if verbose else exps[:3]

    # ── 标题 ──────────────────────────────────────────────────────────────────
    app(f"# TBM 诊断报告")
    app(f"")
    app(f"- **生成时间**：{bundle.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
    app(f"- **输入文件**：`{bundle.input_file}`")
    app(f"- **数据行数**：清洗后 {cr.rows_output:,} 行（原始 {cr.rows_input:,} 行）")
    app(f"")

    # ── 总体结论 ──────────────────────────────────────────────────────────────
    app(f"## 总体结论")
    app(f"")
    n_events = len(bundle.events)
    if n_events == 0:
        app(f"本次诊断未发现有效异常事件，数据质量良好。")
    else:
        high = sum(1 for e in exps if e.severity_label == "高风险")
        mid  = sum(1 for e in exps if e.severity_label == "中风险")
        low  = sum(1 for e in exps if e.severity_label in ("低风险", "观察"))
        app(f"共检测到 **{n_events}** 个异常事件，其中高风险 {high} 个、中风险 {mid} 个、低风险/观察 {low} 个。")
        if high > 0:
            top = exps[0]
            app(f"")
            app(f"> 最高优先级事件：**{top.event_id}** — {top.title}（{_dt_str(top.start_time)} ~ {_dt_str(top.end_time)}）")
    app(f"")

    # ── 异常统计 ──────────────────────────────────────────────────────────────
    app(f"## 异常统计")
    app(f"")
    app(f"| 异常类型 | 命中点数 | 占比 |")
    app(f"|----------|----------|------|")
    _LABELS = {
        "suspected_excavation_resistance": "疑似掘进阻力异常",
        "low_efficiency_excavation":       "低效掘进",
        "attitude_or_bias_risk":           "姿态偏斜风险",
        "hydraulic_instability":           "液压系统不稳定",
    }
    total = dr.total_rows
    for name, label in _LABELS.items():
        hits = dr.hit_counts.get(name, 0)
        pct  = hits / total * 100 if total > 0 else 0.0
        app(f"| {label} | {hits:,} | {pct:.1f}% |")
    app(f"")

    # ── 事件列表 ──────────────────────────────────────────────────────────────
    app(f"## 事件列表")
    app(f"")
    if not bundle.events:
        app(f"无有效事件。")
    else:
        app(f"| 事件ID | 类型 | 开始时间 | 结束时间 | 时长(点) | 峰值分 | 严重度 |")
        app(f"|--------|------|----------|----------|----------|--------|--------|")
        sev_map = {e.event_id: e.severity_label for e in exps}
        ev_semantic = {ev.event_id: (ev.semantic_event_type or "") for ev in bundle.evidences}
        _SEMANTIC_LABELS_MD = {
            "stoppage_segment":                 "停机片段",
            "excavation_resistance_under_load": "重载推进下的掘进阻力异常",
        }
        for e in bundle.events:
            sem = ev_semantic.get(e.event_id, e.event_type)
            label = _SEMANTIC_LABELS_MD.get(sem, _LABELS.get(sem, _LABELS.get(e.event_type, e.event_type)))
            sev   = sev_map.get(e.event_id, "—")
            app(f"| {e.event_id} | {label} | {_dt_str(e.start_time) or '—'} | "
                f"{_dt_str(e.end_time) or '—'} | {e.duration_points} | "
                f"{e.peak_score:.3f} | {sev} |")
    app(f"")

    # ── 事件解释 ──────────────────────────────────────────────────────────────
    _SEVERITY_ICON = {"高风险": "🔴", "中风险": "🟡", "低风险": "🟢", "观察": "⚪"}
    title_suffix = "（全部）" if verbose else "（Top 3）"
    app(f"## 事件解释{title_suffix}")
    app(f"")

    if not show_exps:
        app(f"无有效事件解释。")
    else:
        for exp in show_exps:
            icon = _SEVERITY_ICON.get(exp.severity_label, "")
            app(f"### {exp.event_id} — {exp.title} {icon}{exp.severity_label}")
            app(f"")
            app(f"- **时间范围**：{_dt_str(exp.start_time)} ~ {_dt_str(exp.end_time)}")
            app(f"- **总结**：{exp.summary}")
            if exp.state_context:
                app(f"- **状态上下文**：{exp.state_context}")
            app(f"")
            app(f"**证据**")
            app(f"")
            for b in exp.evidence_bullets:
                app(f"- {b}")
            app(f"")
            app(f"**可能原因**")
            app(f"")
            for c in exp.possible_causes:
                app(f"- {c}")
            app(f"")
            app(f"**建议关注**")
            app(f"")
            for a in exp.suggested_actions:
                app(f"- {a}")
            app(f"")
            app(f"---")
            app(f"")

    # ── LLM 跨事件总结（可选）────────────────────────────────────────────────
    if bundle.llm_summary is not None:
        ls = bundle.llm_summary
        app(f"## LLM 跨事件总结")
        app(f"")
        app(f"> 模型：{ls.model_used}  |  生成时间：{ls.generated_at[:19]}")
        app(f"")
        app(f"**整体评估**")
        app(f"")
        app(ls.overall_summary)
        app(f"")
        if ls.top_risks:
            app(f"**主要风险**")
            app(f"")
            for risk in ls.top_risks:
                app(f"- {risk}")
            app(f"")
        if ls.suggested_actions:
            app(f"**建议关注**")
            app(f"")
            for action in ls.suggested_actions:
                app(f"- {action}")
            app(f"")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info("Markdown report exported → %s", path)


def to_events_csv(bundle: ResultBundle, path: Path) -> None:
    """
    导出事件表 CSV（utf-8-sig，兼容 Windows Excel）。

    列：event_id / event_type / start_time / end_time /
        duration_points / duration_seconds / peak_score /
        mean_score / severity_label / summary
    """
    _ensure_dir(path)

    sev_map     = {e.event_id: e.severity_label for e in bundle.explanations}
    summary_map = {e.event_id: e.summary        for e in bundle.explanations}
    _LABELS = {
        "suspected_excavation_resistance": "疑似掘进阻力异常",
        "low_efficiency_excavation":       "低效掘进",
        "attitude_or_bias_risk":           "姿态偏斜风险",
        "hydraulic_instability":           "液压系统不稳定",
    }
    _STATE_LABELS = {
        "stopped":               "停机/静止",
        "low_load_operation":    "低负载运行",
        "normal_excavation":     "正常推进",
        "heavy_load_excavation": "重载推进",
    }

    # 从 evidences 建立 dominant_state 查找表
    state_map = {ev.event_id: ev.dominant_state for ev in bundle.evidences if ev.dominant_state}
    semantic_map = {ev.event_id: (ev.semantic_event_type or "") for ev in bundle.evidences}
    _SEMANTIC_LABELS_CSV = {
        "stoppage_segment":                 "停机片段",
        "excavation_resistance_under_load": "重载推进下的掘进阻力异常",
    }

    fieldnames = [
        "event_id", "event_type", "semantic_event_type", "start_time", "end_time",
        "duration_points", "duration_seconds",
        "peak_score", "mean_score", "severity_label", "dominant_state", "summary",
    ]

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in bundle.events:
            ds_key = state_map.get(e.event_id, "")
            sem = semantic_map.get(e.event_id, "")
            writer.writerow({
                "event_id":             e.event_id,
                "event_type":           _SEMANTIC_LABELS_CSV.get(sem, _LABELS.get(sem, _LABELS.get(e.event_type, e.event_type))),
                "semantic_event_type":  sem,
                "start_time":           _dt_str(e.start_time) or "",
                "end_time":             _dt_str(e.end_time)   or "",
                "duration_points":      e.duration_points,
                "duration_seconds":     e.duration_seconds if e.duration_seconds is not None else "",
                "peak_score":           e.peak_score,
                "mean_score":           e.mean_score,
                "severity_label":       sev_map.get(e.event_id, ""),
                "dominant_state":       _STATE_LABELS.get(ds_key, ds_key),
                "summary":              summary_map.get(e.event_id, ""),
            })

    logger.info("Events CSV exported → %s", path)
