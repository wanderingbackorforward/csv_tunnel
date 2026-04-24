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
    """基于 drilldown（最高优先级）+ transition analysis 分类停机案例。"""
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

    # drilldown 证据优先：从 observations 中找到对应 case 的 drilldown 结果
    drilldown_data = None
    for obs in state.observations:
        if obs.action == "drilldown_time_window":
            if obs.data.get("target_id") == case_id:
                drilldown_data = obs.data
                break

    reasons: list[str] = []
    score = 0.0

    dur = target_case.duration_seconds
    if dur > 3600:
        reasons.append(f"长停机 ({dur/60:.0f}min)")
        score += 0.15
    elif dur < 600:
        reasons.append(f"短暂停 ({dur/60:.0f}min)")
        score -= 0.1

    if drilldown_data:
        # drilldown 提供了最精确的窗口证据，以它为准
        pre = drilldown_data.get("pre_summary", {})
        post = drilldown_data.get("post_summary", {})
        pre_ser_ratio = pre.get("ser_ratio", 0) if isinstance(pre, dict) else 0
        pre_hyd_count = pre.get("hyd_hits", 0) if isinstance(pre, dict) else 0
        post_ser_ratio = post.get("ser_ratio", 0) if isinstance(post, dict) else 0
        post_hyd_count = post.get("hyd_hits", 0) if isinstance(post, dict) else 0
        pre_empty = pre.get("empty", True) if isinstance(pre, dict) else True
        post_empty = post.get("empty", True) if isinstance(post, dict) else True

        if pre_ser_ratio > 0.05:
            reasons.append(f"停机前窗口存在 SER（占比 {pre_ser_ratio:.1%}，drilldown 证据）")
            score += 0.25
        if pre_hyd_count > 0:
            reasons.append(f"停机前窗口存在 HYD（{pre_hyd_count} 次，drilldown 证据）")
            score += 0.2
        if not post_empty and (post_ser_ratio > 0.05 or post_hyd_count > 0):
            reasons.append("恢复后窗口仍有异常（drilldown 证据）")
            score += 0.1

        hint = drilldown_data.get("interpretation_hint", "")
        if "停机前未见明显异常" in hint and "停机后恢复正常" in hint:
            reasons.append("停机前后窗口未见明显异常（drilldown 证据），疑似计划性/管理性停机")
            score -= 0.25
        elif "停机前未见明显异常" in hint:
            reasons.append("停机前窗口未见异常（drilldown 证据）")
            score -= 0.15
        elif "停机前存在异常迹象" in hint:
            score += 0.1

        if not pre_empty and pre_ser_ratio == 0 and pre_hyd_count == 0:
            pre_heavy = pre.get("state_distribution", {}).get("heavy_load_excavation", 0)
            if pre_heavy > 20:
                reasons.append("停机前处于重载推进状态")
                score += 0.15
    elif ta:
        # 无 drilldown 时回退到 TransitionAnalysis（事件级检查）
        if ta.pre_has_ser:
            reasons.append("停机前存在掘进阻力异常 (SER)（事件级证据，未经 drilldown 验证）")
            score += 0.15
        if ta.pre_has_hyd:
            reasons.append("停机前存在液压不稳定 (HYD)（事件级证据，未经 drilldown 验证）")
            score += 0.1
        if ta.pre_has_heavy_load:
            reasons.append("停机前处于重载推进状态")
            score += 0.15
        if ta.post_has_anomaly:
            reasons.append("恢复后仍有异常事件（事件级证据，未经 drilldown 验证）")
            score += 0.05
        if not ta.pre_events and not ta.post_events:
            reasons.append("前后窗口无异常事件，更像计划停机")
            score -= 0.25

    if score >= 0.3:
        case_type = "abnormal_like_stoppage"
        confidence = min(0.4 + score * 0.3, 0.85)
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


# ── Tool 9: analyze_stoppage_cases ───────────────────────────────────────────

def analyze_stoppage_cases(file_path: str, state: Any = None) -> dict[str, Any]:
    """综合停机分析：合并 → 检查前后窗口 → 分类 Top cases。"""
    merge_result = merge_stoppage_cases(file_path)
    if merge_result.get("status") != "ok" or merge_result.get("merged_cases", 0) == 0:
        return {
            "status": "ok",
            "stoppage_count": 0,
            "merged_cases": 0,
            "summary": "无停机案例",
            "cases": [],
        }

    case_objects = merge_result.get("_case_objects", [])
    if state is not None:
        state.stoppage_cases[file_path] = case_objects

    top_cases = case_objects[:3]
    case_summaries = []
    for c in top_cases:
        if state is not None:
            tw_result = inspect_transition_window(
                file_path, c.case_id, state=state)
            if tw_result.get("status") == "ok":
                analysis = tw_result.get("_analysis_object")
                if analysis:
                    state.transition_analyses[c.case_id] = analysis
            cls_result = classify_stoppage_case(c.case_id, state=state)
            if cls_result.get("status") == "ok":
                cls_obj = cls_result.get("_classification_object")
                if cls_obj:
                    state.case_classifications[c.case_id] = cls_obj

        cls = state.case_classifications.get(c.case_id) if state else None
        case_summaries.append({
            "case_id": c.case_id,
            "start_time": c.start_time,
            "end_time": c.end_time,
            "duration_min": round(c.duration_seconds / 60, 1),
            "case_type": cls.case_type if cls else "unclassified",
            "confidence": cls.confidence if cls else 0,
            "reasons": cls.reasons if cls else [],
        })

    total_dur = sum(c.duration_seconds for c in case_objects)
    return {
        "status": "ok",
        "stoppage_count": merge_result.get("original_stoppage_events", 0),
        "merged_cases": len(case_objects),
        "total_duration_h": round(total_dur / 3600, 1),
        "top_cases": case_summaries,
        "summary": f"{len(case_objects)} 个停机案例，共 {total_dur/3600:.1f}h",
    }


# ── Tool 10: analyze_resistance_pattern ──────────────────────────────────────

def analyze_resistance_pattern(file_path: str) -> dict[str, Any]:
    """分析掘进阻力异常 (SER) 模式。"""
    try:
        cached = _run_pipeline(file_path)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    events = cached["events"]
    evidences = cached["evidences"]
    enriched = cached["enriched"]
    event_states = cached["event_states"]

    sem_map = {ev.event_id: ev.semantic_event_type or ev.event_type for ev in evidences}
    ser_types = {"suspected_excavation_resistance", "excavation_resistance_under_load"}
    ser_events = [e for e in events if sem_map.get(e.event_id) in ser_types]

    if not ser_events:
        return {
            "status": "ok",
            "ser_count": 0,
            "summary": "无掘进阻力异常事件",
        }

    total_dur = sum(e.duration_seconds or 0 for e in ser_events)

    from tbm_diag.state_engine import STATE_LABELS
    state_counts: dict[str, int] = {}
    for e in ser_events:
        es = event_states.get(e.event_id)
        if es:
            ds = es.dominant_state
            state_counts[STATE_LABELS.get(ds, ds)] = state_counts.get(STATE_LABELS.get(ds, ds), 0) + 1

    timestamps = [e.start_time for e in ser_events if e.start_time is not None]
    concentrated = False
    if len(timestamps) >= 3:
        sorted_ts = sorted(timestamps)
        span = (sorted_ts[-1] - sorted_ts[0]).total_seconds()
        concentrated = span < total_dur * 3

    stoppage_events = [e for e in events if sem_map.get(e.event_id) == "stoppage_segment"]
    near_stoppage = False
    if stoppage_events and ser_events:
        for se in ser_events[:3]:
            if se.end_time is None:
                continue
            for st_ev in stoppage_events:
                if st_ev.start_time is None:
                    continue
                gap = abs((st_ev.start_time - se.end_time).total_seconds())
                if gap < 600:
                    near_stoppage = True
                    break

    in_advancing = sum(1 for e in ser_events
                       if event_states.get(e.event_id) and
                       event_states[e.event_id].dominant_state in
                       ("normal_excavation", "heavy_load_excavation"))

    # 过滤 top SER 目标：排除主要在停机期的事件
    valid_ser = []
    invalid_ser = []
    for e in sorted(ser_events, key=lambda e: -(e.duration_seconds or 0)):
        es = event_states.get(e.event_id)
        if es and es.dominant_state == "stopped":
            invalid_ser.append(e.event_id)
        else:
            valid_ser.append(e)
    top_ser = valid_ser[:3]
    top_ser_event_ids = [e.event_id for e in top_ser]

    all_stopped_overlap = len(valid_ser) == 0 and len(invalid_ser) > 0

    summary_parts = [
        f"SER 事件 {len(ser_events)} 个，共 {total_dur/3600:.1f}h，"
        f"推进中占比 {in_advancing/len(ser_events)*100:.0f}%"
    ]
    if concentrated:
        summary_parts.append("时间集中")
    if near_stoppage:
        summary_parts.append("靠近停机")
    if all_stopped_overlap:
        summary_parts.append("所有 SER 均与停机重叠")

    return {
        "status": "ok",
        "ser_count": len(ser_events),
        "ser_total_duration_h": round(total_dur / 3600, 1),
        "dominant_states": state_counts,
        "concentrated_in_time": concentrated,
        "near_stoppage": near_stoppage,
        "in_advancing_count": in_advancing,
        "in_advancing_ratio": round(in_advancing / len(ser_events), 2) if ser_events else 0,
        "top_ser_event_ids": top_ser_event_ids,
        "invalid_ser_count": len(invalid_ser),
        "all_stopped_overlap": all_stopped_overlap,
        "summary": "，".join(summary_parts),
    }


# ── Tool 11: analyze_hydraulic_pattern ───────────────────────────────────────

def analyze_hydraulic_pattern(file_path: str) -> dict[str, Any]:
    """分析液压不稳定 (HYD) 事件模式。"""
    try:
        cached = _run_pipeline(file_path)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    events = cached["events"]
    evidences = cached["evidences"]
    event_states = cached["event_states"]

    sem_map = {ev.event_id: ev.semantic_event_type or ev.event_type for ev in evidences}
    hyd_events = [e for e in events if sem_map.get(e.event_id) == "hydraulic_instability"]

    if not hyd_events:
        return {"status": "ok", "hyd_count": 0, "summary": "无液压不稳定事件"}

    total_dur = sum(e.duration_seconds or 0 for e in hyd_events)

    ser_types = {"suspected_excavation_resistance", "excavation_resistance_under_load"}
    ser_events = [e for e in events if sem_map.get(e.event_id) in ser_types]
    sync_with_ser = False
    if ser_events and hyd_events:
        for he in hyd_events[:5]:
            if he.start_time is None:
                continue
            for se in ser_events:
                if se.start_time is None:
                    continue
                gap = abs((he.start_time - se.start_time).total_seconds())
                if gap < 300:
                    sync_with_ser = True
                    break

    stoppage_events = [e for e in events if sem_map.get(e.event_id) == "stoppage_segment"]
    near_stoppage_boundary = False
    if stoppage_events and hyd_events:
        for he in hyd_events[:5]:
            if he.start_time is None:
                continue
            for st_ev in stoppage_events:
                if st_ev.start_time and abs((he.start_time - st_ev.start_time).total_seconds()) < 600:
                    near_stoppage_boundary = True
                    break
                if st_ev.end_time and abs((he.start_time - st_ev.end_time).total_seconds()) < 600:
                    near_stoppage_boundary = True
                    break

    short_count = sum(1 for e in hyd_events if (e.duration_seconds or 0) < 60)
    isolated_short = short_count > len(hyd_events) * 0.7

    top_hyd = sorted(hyd_events, key=lambda e: -(e.duration_seconds or 0))[:3]
    top_hyd_event_ids = [e.event_id for e in top_hyd]

    return {
        "status": "ok",
        "hyd_count": len(hyd_events),
        "hyd_total_duration_h": round(total_dur / 3600, 1),
        "near_stoppage_boundary": near_stoppage_boundary,
        "sync_with_ser": sync_with_ser,
        "isolated_short_fluctuation": isolated_short,
        "short_event_ratio": round(short_count / len(hyd_events), 2) if hyd_events else 0,
        "top_hyd_event_ids": top_hyd_event_ids,
        "summary": (
            f"HYD 事件 {len(hyd_events)} 个，共 {total_dur/3600:.1f}h"
            + ("，与 SER 同步" if sync_with_ser else "")
            + ("，靠近停机边界" if near_stoppage_boundary else "")
            + ("，多为孤立短时波动" if isolated_short else "")
        ),
    }


# ── Tool 12: analyze_event_fragmentation ─────────────────────────────────────

def analyze_event_fragmentation(file_path: str) -> dict[str, Any]:
    """分析事件碎片化程度。"""
    try:
        cached = _run_pipeline(file_path)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    events = cached["events"]
    if not events:
        return {"status": "ok", "event_count": 0, "summary": "无事件"}

    durations = [e.duration_seconds or 0 for e in events]
    total_dur = sum(durations)
    avg_dur = total_dur / len(events)
    short_threshold = 60
    short_count = sum(1 for d in durations if d < short_threshold)
    short_ratio = short_count / len(events)

    evidences = cached["evidences"]
    sem_map = {ev.event_id: ev.semantic_event_type or ev.event_type for ev in evidences}
    low_eff_events = [e for e in events if sem_map.get(e.event_id) == "low_efficiency_excavation"]
    low_eff_dur = sum(e.duration_seconds or 0 for e in low_eff_events)

    fragmentation_risk = short_ratio > 0.5 and avg_dur < 120

    return {
        "status": "ok",
        "event_count": len(events),
        "avg_duration_s": round(avg_dur, 1),
        "short_event_count": short_count,
        "short_event_ratio": round(short_ratio, 2),
        "low_efficiency_count": len(low_eff_events),
        "low_efficiency_total_h": round(low_eff_dur / 3600, 1),
        "fragmentation_risk": fragmentation_risk,
        "summary": (
            f"事件 {len(events)} 个，平均 {avg_dur:.0f}s，"
            f"短事件占比 {short_ratio*100:.0f}%"
            + ("，存在碎片化风险" if fragmentation_risk else "")
        ),
    }


# ── Tool 13: drilldown_time_window ───────────────────────────────────────────

def _window_stats(
    enriched: pd.DataFrame,
    mask: pd.Series,
    evidences: list,
    events: list,
) -> dict[str, Any]:
    """计算单个时间窗口的统计摘要。"""
    subset = enriched.loc[mask]
    n = len(subset)
    if n == 0:
        return {"rows": 0, "empty": True}

    def _safe_mean(col: str) -> float:
        if col in subset.columns:
            v = subset[col].mean()
            return round(float(v), 2) if pd.notna(v) else 0.0
        return 0.0

    ser_col = "flag_suspected_excavation_resistance"
    lee_col = "flag_low_efficiency_excavation"
    hyd_col = "flag_hydraulic_instability"

    ser_hits = int(subset[ser_col].sum()) if ser_col in subset.columns else 0
    lee_hits = int(subset[lee_col].sum()) if lee_col in subset.columns else 0
    hyd_hits = int(subset[hyd_col].sum()) if hyd_col in subset.columns else 0

    state_dist: dict[str, float] = {}
    if "machine_state" in subset.columns:
        counts = subset["machine_state"].value_counts()
        for s, cnt in counts.items():
            state_dist[s] = round(cnt / n * 100, 1)

    return {
        "rows": n,
        "empty": False,
        "avg_advance_speed": _safe_mean("advance_speed_mm_per_min"),
        "avg_penetration_rate": _safe_mean("penetration_rate_mm_per_rev"),
        "avg_cutter_torque": _safe_mean("cutter_torque_kNm"),
        "avg_total_thrust": _safe_mean("total_thrust_kN"),
        "ser_hits": ser_hits,
        "ser_ratio": round(ser_hits / n, 3) if n else 0,
        "lee_hits": lee_hits,
        "lee_ratio": round(lee_hits / n, 3) if n else 0,
        "hyd_hits": hyd_hits,
        "hyd_ratio": round(hyd_hits / n, 3) if n else 0,
        "state_distribution": state_dist,
    }


def drilldown_time_window(
    file_path: str,
    target_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    pre_minutes: float = 10,
    post_minutes: float = 10,
    state: Any = None,
) -> dict[str, Any]:
    """对指定事件/case 做前后窗口钻取分析。"""
    try:
        cached = _run_pipeline(file_path)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    enriched: pd.DataFrame = cached["enriched"]
    events = cached["events"]
    evidences = cached["evidences"]

    if "timestamp" not in enriched.columns:
        return {"status": "error", "error": "no timestamp column"}

    ts_col = enriched["timestamp"]

    # 解析目标时间范围
    t_start = None
    t_end = None
    resolved_id = target_id or ""

    if target_id and not start_time:
        # 先从事件列表找
        for e in events:
            if e.event_id == target_id:
                t_start = e.start_time
                t_end = e.end_time
                break
        # 再从 state 的 stoppage_cases 找
        if t_start is None and state is not None:
            for fp_key, cases in state.stoppage_cases.items():
                for c in cases:
                    if c.case_id == target_id:
                        t_start = pd.Timestamp(c.start_time)
                        t_end = pd.Timestamp(c.end_time)
                        break
        if t_start is None:
            return {"status": "error", "error": f"target_id {target_id} not found"}
    elif start_time:
        t_start = pd.Timestamp(start_time)
        t_end = pd.Timestamp(end_time) if end_time else t_start + pd.Timedelta(minutes=5)
        resolved_id = resolved_id or f"{start_time}~{end_time}"
    else:
        return {"status": "error", "error": "need target_id or start_time"}

    t_start = pd.Timestamp(t_start)
    t_end = pd.Timestamp(t_end) if t_end is not None else t_start

    pre_start = t_start - pd.Timedelta(minutes=pre_minutes)
    post_end = t_end + pd.Timedelta(minutes=post_minutes)

    pre_mask = (ts_col >= pre_start) & (ts_col < t_start)
    during_mask = (ts_col >= t_start) & (ts_col <= t_end)
    post_mask = (ts_col > t_end) & (ts_col <= post_end)

    pre_stats = _window_stats(enriched, pre_mask, evidences, events)
    during_stats = _window_stats(enriched, during_mask, evidences, events)
    post_stats = _window_stats(enriched, post_mask, evidences, events)

    pre_stats["time_range"] = f"{pre_start} ~ {t_start}"
    during_stats["time_range"] = f"{t_start} ~ {t_end}"
    post_stats["time_range"] = f"{t_end} ~ {post_end}"

    # 转变检测
    transition_findings = []
    pre_stopped = pre_stats.get("state_distribution", {}).get("stopped", 0)
    pre_advancing = (
        pre_stats.get("state_distribution", {}).get("normal_excavation", 0)
        + pre_stats.get("state_distribution", {}).get("heavy_load_excavation", 0)
    )
    post_stopped = post_stats.get("state_distribution", {}).get("stopped", 0)
    post_advancing = (
        post_stats.get("state_distribution", {}).get("normal_excavation", 0)
        + post_stats.get("state_distribution", {}).get("heavy_load_excavation", 0)
    )

    if pre_advancing > 30 and during_stats.get("state_distribution", {}).get("stopped", 0) > 50:
        transition_findings.append("推进→停机转变")
    if during_stats.get("state_distribution", {}).get("stopped", 0) > 50 and post_advancing > 30:
        transition_findings.append("停机→恢复转变")

    # interpretation_hint
    hints = []
    if pre_stats.get("ser_ratio", 0) > 0.1 or pre_stats.get("hyd_ratio", 0) > 0.1:
        hints.append("停机前存在异常迹象")
    elif not pre_stats.get("empty", True):
        hints.append("停机前未见明显异常")

    if post_stats.get("empty", True):
        pass
    elif post_stats.get("ser_ratio", 0) > 0.05 or post_stats.get("hyd_ratio", 0) > 0.05:
        hints.append("停机后恢复异常")
    else:
        hints.append("停机后恢复正常")

    if not hints:
        hints.append("需要施工日志确认")

    def _compact(stats: dict) -> str:
        if stats.get("empty"):
            return "无数据"
        parts = [f"{stats['rows']}行"]
        if stats.get("avg_advance_speed", 0) > 0:
            parts.append(f"速度{stats['avg_advance_speed']}")
        if stats.get("ser_hits", 0) > 0:
            parts.append(f"SER{stats['ser_hits']}")
        if stats.get("hyd_hits", 0) > 0:
            parts.append(f"HYD{stats['hyd_hits']}")
        top_state = max(stats.get("state_distribution", {"?": 100}).items(),
                        key=lambda x: x[1], default=("?", 0))
        parts.append(f"{top_state[0]}{top_state[1]:.0f}%")
        return "，".join(parts)

    return {
        "status": "ok",
        "target_id": resolved_id,
        "pre_summary": pre_stats,
        "during_summary": during_stats,
        "post_summary": post_stats,
        "transition_findings": transition_findings,
        "interpretation_hint": "；".join(hints),
        "compact_pre": _compact(pre_stats),
        "compact_during": _compact(during_stats),
        "compact_post": _compact(post_stats),
        "summary": (
            f"[{resolved_id}] 前:{_compact(pre_stats)} | "
            f"中:{_compact(during_stats)} | "
            f"后:{_compact(post_stats)} → {'；'.join(hints)}"
        ),
    }


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
    "analyze_stoppage_cases": {
        "fn": analyze_stoppage_cases,
        "description": "综合停机分析：合并、检查前后窗口、分类 Top cases",
        "params": ["file_path"],
    },
    "analyze_resistance_pattern": {
        "fn": analyze_resistance_pattern,
        "description": "分析掘进阻力异常 (SER) 模式：事件数、时长、工况、是否集中",
        "params": ["file_path"],
    },
    "analyze_hydraulic_pattern": {
        "fn": analyze_hydraulic_pattern,
        "description": "分析液压不稳定 (HYD) 模式：是否与 SER 同步、是否靠近停机",
        "params": ["file_path"],
    },
    "analyze_event_fragmentation": {
        "fn": analyze_event_fragmentation,
        "description": "分析事件碎片化：短事件占比、平均时长、碎片化风险",
        "params": ["file_path"],
    },
    "drilldown_time_window": {
        "fn": drilldown_time_window,
        "description": "对指定事件/case 做前后窗口钻取：推进参数、异常命中、工况转变",
        "params": ["file_path", "target_id", "start_time", "end_time", "pre_minutes", "post_minutes"],
    },
}



