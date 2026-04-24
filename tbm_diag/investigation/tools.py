"""tools.py — Investigation 工具集

每个工具返回结构化 dict，不返回长文本。
LLM 不直接读原始 CSV，只通过这些工具获取结构化观察。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from tbm_diag.investigation.state import (
    CaseClassification,
    FileOverview,
    EventSummary,
    StoppageCase,
    TransitionAnalysis,
)

logger = logging.getLogger(__name__)

_CACHE: dict[str, dict[str, Any]] = {}


def _run_pipeline(file_path: str) -> dict[str, Any]:
    """运行完整检测流水线并缓存结果。"""
    key = str(Path(file_path).resolve())
    if key in _CACHE:
        return _CACHE[key]

    from tbm_diag.ingestion import load_csv
    from tbm_diag.cleaning import clean
    from tbm_diag.feature_engine import enrich_features
    from tbm_diag.detector import detect
    from tbm_diag.segmenter import segment_events
    from tbm_diag.state_engine import classify_states, summarize_event_state
    from tbm_diag.evidence import extract_evidence
    from tbm_diag.semantic_layer import apply_to_evidences
    from tbm_diag.config import DiagConfig

    cfg = DiagConfig()
    result = load_csv(file_path)
    df, report = clean(
        result.df,
        resample_freq=cfg.cleaning.resample,
        spike_k=cfg.cleaning.spike_k,
        fill_method=cfg.cleaning.fill,
        max_gap_fill=cfg.cleaning.max_gap,
    )
    enriched = enrich_features(df, window=cfg.feature.rolling_window)
    det_result = detect(enriched, config=cfg.detector)
    events = segment_events(det_result.df, config=cfg.segmenter)

    event_states: dict = {}
    if events:
        enriched = classify_states(enriched, config=cfg.state)
        event_states = {
            e.event_id: summarize_event_state(enriched, e) for e in events
        }

    evidences = extract_evidence(enriched, events, event_states=event_states)
    apply_to_evidences(evidences)

    cached = {
        "ingestion": result,
        "cleaning": report,
        "enriched": enriched,
        "det_result": det_result,
        "events": events,
        "event_states": event_states,
        "evidences": evidences,
    }
    _CACHE[key] = cached
    return cached


# ── Tool 1: inspect_file_overview ─────────────────────────────────────────────

def inspect_file_overview(file_path: str) -> dict[str, Any]:
    """复用 inspect/detect 基础能力，返回文件概览。"""
    try:
        cached = _run_pipeline(file_path)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    enriched: pd.DataFrame = cached["enriched"]
    events = cached["events"]
    evidences = cached["evidences"]
    event_states = cached["event_states"]

    time_start = time_end = ""
    if "timestamp" in enriched.columns:
        ts = enriched["timestamp"].dropna()
        if not ts.empty:
            time_start = str(ts.iloc[0])[:19]
            time_end = str(ts.iloc[-1])[:19]

    state_dist: dict[str, float] = {}
    if "machine_state" in enriched.columns:
        counts = enriched["machine_state"].value_counts()
        total = len(enriched)
        for s, n in counts.items():
            state_dist[s] = round(n / total * 100, 1)

    sem_dist: dict[str, int] = {}
    for ev in evidences:
        sem = ev.semantic_event_type or ev.event_type
        sem_dist[sem] = sem_dist.get(sem, 0) + 1

    overview = FileOverview(
        file_path=file_path,
        total_rows=len(enriched),
        time_start=time_start,
        time_end=time_end,
        state_distribution=state_dist,
        event_count=len(events),
        semantic_event_distribution=sem_dist,
    )

    return {
        "status": "ok",
        "file_path": overview.file_path,
        "total_rows": overview.total_rows,
        "time_start": overview.time_start,
        "time_end": overview.time_end,
        "state_distribution": overview.state_distribution,
        "event_count": overview.event_count,
        "semantic_event_distribution": overview.semantic_event_distribution,
    }


# ── Tool 2: load_event_summary ───────────────────────────────────────────────

def load_event_summary(file_path: str) -> dict[str, Any]:
    """返回事件摘要。"""
    try:
        cached = _run_pipeline(file_path)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    events = cached["events"]
    evidences = cached["evidences"]
    event_states = cached["event_states"]

    type_dist: dict[str, int] = {}
    sem_dist: dict[str, int] = {}
    for ev in evidences:
        type_dist[ev.event_type] = type_dist.get(ev.event_type, 0) + 1
        sem = ev.semantic_event_type or ev.event_type
        sem_dist[sem] = sem_dist.get(sem, 0) + 1

    from tbm_diag.state_engine import STATE_LABELS
    top_events = []
    for e in events[:10]:
        ds_key = event_states[e.event_id].dominant_state if e.event_id in event_states else ""
        top_events.append({
            "event_id": e.event_id,
            "event_type": e.event_type,
            "start": str(e.start_time)[:19] if e.start_time else "",
            "end": str(e.end_time)[:19] if e.end_time else "",
            "duration_s": round(e.duration_seconds) if e.duration_seconds else 0,
            "peak_score": e.peak_score,
            "dominant_state": STATE_LABELS.get(ds_key, ds_key),
        })

    return {
        "status": "ok",
        "event_count": len(events),
        "event_type_distribution": type_dist,
        "semantic_event_distribution": sem_dist,
        "top_events": top_events,
    }


# ── Tool 3: merge_stoppage_cases ──────────────────────────────────────────────

def merge_stoppage_cases(
    file_path: str,
    gap_threshold_seconds: float = 300,
    min_case_duration_seconds: float = 600,
) -> dict[str, Any]:
    """合并 stoppage_segment 事件为停机案例。"""
    try:
        cached = _run_pipeline(file_path)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    evidences = cached["evidences"]
    events = cached["events"]

    sem_map = {ev.event_id: ev.semantic_event_type for ev in evidences}
    stoppage_events = [
        e for e in events if sem_map.get(e.event_id) == "stoppage_segment"
    ]

    if not stoppage_events:
        return {
            "status": "ok",
            "original_stoppage_events": 0,
            "merged_cases": 0,
            "cases": [],
        }

    stoppage_events.sort(key=lambda e: e.start_time or pd.Timestamp.min)

    cases: list[StoppageCase] = []
    current_ids = [stoppage_events[0].event_id]
    current_start = stoppage_events[0].start_time
    current_end = stoppage_events[0].end_time

    for e in stoppage_events[1:]:
        gap = 0.0
        if current_end and e.start_time:
            gap = (e.start_time - current_end).total_seconds()

        if gap <= gap_threshold_seconds:
            current_ids.append(e.event_id)
            if e.end_time and (current_end is None or e.end_time > current_end):
                current_end = e.end_time
        else:
            dur = (current_end - current_start).total_seconds() if current_start and current_end else 0
            if dur >= min_case_duration_seconds:
                cases.append(StoppageCase(
                    case_id=f"SC_{len(cases)+1:03d}",
                    file_path=file_path,
                    start_time=str(current_start)[:19] if current_start else "",
                    end_time=str(current_end)[:19] if current_end else "",
                    duration_seconds=dur,
                    merged_event_count=len(current_ids),
                    merged_event_ids=current_ids,
                ))
            current_ids = [e.event_id]
            current_start = e.start_time
            current_end = e.end_time

    dur = (current_end - current_start).total_seconds() if current_start and current_end else 0
    if dur >= min_case_duration_seconds:
        cases.append(StoppageCase(
            case_id=f"SC_{len(cases)+1:03d}",
            file_path=file_path,
            start_time=str(current_start)[:19] if current_start else "",
            end_time=str(current_end)[:19] if current_end else "",
            duration_seconds=dur,
            merged_event_count=len(current_ids),
            merged_event_ids=current_ids,
        ))

    cases.sort(key=lambda c: -c.duration_seconds)

    return {
        "status": "ok",
        "original_stoppage_events": len(stoppage_events),
        "merged_cases": len(cases),
        "cases": [
            {
                "case_id": c.case_id,
                "start_time": c.start_time,
                "end_time": c.end_time,
                "duration_seconds": c.duration_seconds,
                "duration_display": f"{c.duration_seconds/60:.0f}min",
                "merged_event_count": c.merged_event_count,
            }
            for c in cases
        ],
        "_case_objects": cases,
    }


# ── Tool 4: inspect_transition_window ─────────────────────────────────────────

def inspect_transition_window(
    file_path: str,
    case_id: str,
    pre_minutes: float = 10,
    post_minutes: float = 10,
    state: Any = None,
) -> dict[str, Any]:
    """检查停机 case 前后窗口的事件和状态。"""
    if state is None:
        return {"status": "error", "error": "需要传入 state 以获取 case 信息"}

    cases_for_file = state.stoppage_cases.get(file_path, [])
    target_case = None
    for c in cases_for_file:
        if c.case_id == case_id:
            target_case = c
            break

    if target_case is None:
        return {"status": "error", "error": f"case {case_id} not found"}

    try:
        cached = _run_pipeline(file_path)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    enriched: pd.DataFrame = cached["enriched"]
    events = cached["events"]
    evidences = cached["evidences"]
    event_states = cached["event_states"]

    case_start = pd.Timestamp(target_case.start_time)
    case_end = pd.Timestamp(target_case.end_time)
    pre_start = case_start - pd.Timedelta(minutes=pre_minutes)
    post_end = case_end + pd.Timedelta(minutes=post_minutes)

    sem_map = {ev.event_id: ev.semantic_event_type or ev.event_type for ev in evidences}

    from tbm_diag.state_engine import STATE_LABELS

    pre_events = []
    post_events = []
    for e in events:
        if e.start_time is None:
            continue
        if pre_start <= e.start_time < case_start:
            ds = event_states[e.event_id].dominant_state if e.event_id in event_states else ""
            pre_events.append({
                "event_id": e.event_id,
                "semantic_type": sem_map.get(e.event_id, e.event_type),
                "start": str(e.start_time)[:19],
                "duration_s": round(e.duration_seconds) if e.duration_seconds else 0,
                "dominant_state": STATE_LABELS.get(ds, ds),
            })
        elif case_end < e.start_time <= post_end:
            ds = event_states[e.event_id].dominant_state if e.event_id in event_states else ""
            post_events.append({
                "event_id": e.event_id,
                "semantic_type": sem_map.get(e.event_id, e.event_type),
                "start": str(e.start_time)[:19],
                "duration_s": round(e.duration_seconds) if e.duration_seconds else 0,
                "dominant_state": STATE_LABELS.get(ds, ds),
            })

    pre_sem_types = {ev["semantic_type"] for ev in pre_events}
    post_sem_types = {ev["semantic_type"] for ev in post_events}

    pre_state_dist: dict[str, float] = {}
    post_state_dist: dict[str, float] = {}
    if "timestamp" in enriched.columns and "machine_state" in enriched.columns:
        ts = enriched["timestamp"]
        pre_mask = (ts >= pre_start) & (ts < case_start)
        post_mask = (ts > case_end) & (ts <= post_end)
        for mask, dist in [(pre_mask, pre_state_dist), (post_mask, post_state_dist)]:
            subset = enriched.loc[mask, "machine_state"]
            if not subset.empty:
                counts = subset.value_counts()
                total = len(subset)
                for s, n in counts.items():
                    dist[s] = round(n / total * 100, 1)

    analysis = TransitionAnalysis(
        case_id=case_id,
        pre_events=pre_events,
        post_events=post_events,
        pre_has_ser="suspected_excavation_resistance" in pre_sem_types
                    or "excavation_resistance_under_load" in pre_sem_types,
        pre_has_hyd="hydraulic_instability" in pre_sem_types,
        pre_has_heavy_load=pre_state_dist.get("heavy_load_excavation", 0) > 20,
        post_has_anomaly=bool(post_events),
        pre_state_distribution=pre_state_dist,
        post_state_distribution=post_state_dist,
    )

    return {
        "status": "ok",
        "case_id": case_id,
        "case_duration_s": target_case.duration_seconds,
        "pre_window_minutes": pre_minutes,
        "post_window_minutes": post_minutes,
        "pre_events_count": len(pre_events),
        "post_events_count": len(post_events),
        "pre_has_ser": analysis.pre_has_ser,
        "pre_has_hyd": analysis.pre_has_hyd,
        "pre_has_heavy_load": analysis.pre_has_heavy_load,
        "post_has_anomaly": analysis.post_has_anomaly,
        "pre_state_distribution": pre_state_dist,
        "post_state_distribution": post_state_dist,
        "_analysis_object": analysis,
    }


# ── Tool 5: classify_stoppage_case ─────────────────────────────────────────────

def classify_stoppage_case(
    case_id: str,
    state: Any = None,
) -> dict[str, Any]:
    """基于 case + transition analysis 分类停机案例。"""
    if state is None:
        return {"status": "error", "error": "需要传入 state"}

    ta = state.transition_analyses.get(case_id)
    target_case = None
    for cases in state.stoppage_cases.values():
        for c in cases:
            if c.case_id == case_id:
                target_case = c
                break

    if target_case is None:
        return {"status": "error", "error": f"case {case_id} not found in state"}

    reasons: list[str] = []
    score = 0.0
    evidence_count = 0

    dur = target_case.duration_seconds
    if dur > 3600:
        reasons.append(f"长停机 ({dur/60:.0f}min)")
        score += 0.15
    elif dur < 600:
        reasons.append(f"短暂停 ({dur/60:.0f}min)")
        score -= 0.1

    if ta:
        if ta.pre_has_ser:
            reasons.append("停机前存在掘进阻力异常 (SER)")
            score += 0.25
            evidence_count += 1
        if ta.pre_has_hyd:
            reasons.append("停机前存在液压不稳定 (HYD)")
            score += 0.2
            evidence_count += 1
        if ta.pre_has_heavy_load:
            reasons.append("停机前处于重载推进状态")
            score += 0.15
            evidence_count += 1
        if ta.post_has_anomaly:
            reasons.append("恢复后仍有异常事件")
            score += 0.1
            evidence_count += 1
        if not ta.pre_events and not ta.post_events:
            reasons.append("前后窗口无异常事件，更像计划停机")
            score -= 0.25

    if score >= 0.3:
        case_type = "abnormal_like_stoppage"
        confidence = min(0.4 + evidence_count * 0.12 + score * 0.3, 0.85)
        reasons.append("（疑似，需结合施工日志确认）")
    elif score <= -0.1:
        case_type = "planned_like_stoppage"
        confidence = min(0.45 + abs(score) * 0.5, 0.8)
        reasons.append("（疑似，需结合施工日志确认）")
    elif dur < 600:
        case_type = "short_operational_pause"
        confidence = 0.55
    else:
        case_type = "uncertain_stoppage"
        confidence = 0.35
        reasons.append("（证据不足，建议人工核查）")

    classification = CaseClassification(
        case_id=case_id,
        case_type=case_type,
        confidence=round(confidence, 2),
        reasons=reasons,
    )

    return {
        "status": "ok",
        "case_id": case_id,
        "case_type": classification.case_type,
        "confidence": classification.confidence,
        "reasons": classification.reasons,
        "_classification_object": classification,
    }


# ── Tool 6: compare_cases_across_files ────────────────────────────────────────

def compare_cases_across_files(
    files: list[str],
    state: Any = None,
) -> dict[str, Any]:
    """跨文件比较停机案例模式。"""
    if state is None:
        return {"status": "error", "error": "需要传入 state"}

    file_stats = []
    total_cases = 0
    total_abnormal = 0
    total_planned = 0
    total_duration = 0.0

    for fp in files:
        cases = state.stoppage_cases.get(fp, [])
        n_cases = len(cases)
        total_cases += n_cases
        file_dur = sum(c.duration_seconds for c in cases)
        total_duration += file_dur

        n_abnormal = sum(
            1 for c in cases
            if state.case_classifications.get(c.case_id, CaseClassification()).case_type == "abnormal_like_stoppage"
        )
        n_planned = sum(
            1 for c in cases
            if state.case_classifications.get(c.case_id, CaseClassification()).case_type == "planned_like_stoppage"
        )
        total_abnormal += n_abnormal
        total_planned += n_planned

        overview = state.file_overviews.get(fp)
        total_rows = overview.total_rows if overview else 0
        stoppage_pct = round(file_dur / total_rows * 100, 1) if total_rows > 0 else 0

        file_stats.append({
            "file": Path(fp).name,
            "cases": n_cases,
            "abnormal": n_abnormal,
            "planned": n_planned,
            "total_stoppage_seconds": file_dur,
            "stoppage_pct_of_rows": stoppage_pct,
        })

    patterns = []
    if total_abnormal > total_planned:
        patterns.append("异常停机多于计划停机，需重点关注")
    if total_cases > 0 and total_abnormal / total_cases > 0.5:
        patterns.append(f"异常停机占比 {total_abnormal/total_cases*100:.0f}%，偏高")
    if len(files) > 1:
        durations = [sum(c.duration_seconds for c in state.stoppage_cases.get(fp, [])) for fp in files]
        if max(durations) > 2 * min(durations) and min(durations) > 0:
            patterns.append("各文件停机时长差异显著")

    return {
        "status": "ok",
        "files_compared": len(files),
        "total_cases": total_cases,
        "total_abnormal": total_abnormal,
        "total_planned": total_planned,
        "total_stoppage_seconds": total_duration,
        "file_stats": file_stats,
        "patterns": patterns,
    }


# ── Tool 7: retrieve_operation_context ────────────────────────────────────────

def retrieve_operation_context(
    time_range: tuple[str, str] | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    """从 context/ 目录检索施工日志上下文。"""
    from tbm_diag.investigation.context_retriever import search_context
    return search_context(time_range=time_range, keywords=keywords)


# ── Tool 8: generate_investigation_report ─────────────────────────────────────

def generate_investigation_report(state: Any) -> dict[str, Any]:
    """根据 state 生成最终报告。"""
    from tbm_diag.investigation.report import build_report
    return build_report(state)


# ── 工具注册表 ────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "inspect_file_overview": {
        "fn": inspect_file_overview,
        "description": "获取文件概览：行数、时间范围、状态分布、事件数",
        "params": ["file_path"],
    },
    "load_event_summary": {
        "fn": load_event_summary,
        "description": "获取事件摘要：事件数、类型分布、Top事件",
        "params": ["file_path"],
    },
    "merge_stoppage_cases": {
        "fn": merge_stoppage_cases,
        "description": "合并 stoppage_segment 事件为停机案例",
        "params": ["file_path", "gap_threshold_seconds", "min_case_duration_seconds"],
    },
    "inspect_transition_window": {
        "fn": inspect_transition_window,
        "description": "检查停机案例前后窗口的事件和状态",
        "params": ["file_path", "case_id", "pre_minutes", "post_minutes"],
    },
    "classify_stoppage_case": {
        "fn": classify_stoppage_case,
        "description": "分类停机案例：计划/异常/不确定/短暂停",
        "params": ["case_id"],
    },
    "compare_cases_across_files": {
        "fn": compare_cases_across_files,
        "description": "跨文件比较停机案例模式",
        "params": ["files"],
    },
    "retrieve_operation_context": {
        "fn": retrieve_operation_context,
        "description": "从施工日志检索上下文信息",
        "params": ["time_range", "keywords"],
    },
    "generate_investigation_report": {
        "fn": generate_investigation_report,
        "description": "生成最终调查报告",
        "params": [],
    },
}



