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
    use_agent: bool = False
    overwrite: bool = False
    min_severity: str = ""
    require_llm: bool = False


# ── 工具轨迹与证据链 ──────────────────────────────────────────────────────────

@dataclass
class ReviewToolTrace:
    """单次工具调用记录。"""
    tool_name: str
    purpose_zh: str
    input_summary: str
    output_summary: str
    evidence_ids: list = field(default_factory=list)


@dataclass
class ReviewEvidenceItem:
    """单条证据。"""
    evidence_id: str
    source_tool: str
    title: str
    value: Any
    interpretation: str
    reliability: str  # direct_stat / derived_stat / llm_inference / needs_external_confirmation


@dataclass
class StoppageTimePattern:
    """停机时间模式分析结果。"""
    stoppage_count: int = 0
    total_duration_seconds: float = 0.0
    max_single_duration_seconds: float = 0.0
    window_noon: float = 0.0       # 11:30-13:30
    window_evening: float = 0.0    # 17:00-20:30
    window_night: float = 0.0      # 22:00-06:00
    window_other: float = 0.0
    labels: list = field(default_factory=list)


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
    summary_source: str = "none"
    llm_status: str = "not_requested"
    llm_error_message: str = ""
    llm_model: str = ""
    llm_provider: str = ""
    tool_traces: list = field(default_factory=list)
    evidence_items: list = field(default_factory=list)
    stoppage_pattern: Optional[StoppageTimePattern] = None
    hypothesis_board: Optional[HypothesisBoard] = None


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


def analyze_stoppage_time_pattern(
    evidences: list,
    events: list,
) -> StoppageTimePattern:
    """分析停机片段的时间分布模式。只输出疑似标签，不做确定性判断。"""
    import pandas as pd

    dur_map = {e.event_id: e for e in events}
    result = StoppageTimePattern()

    for ev in evidences:
        sem = getattr(ev, "semantic_event_type", None) or ev.event_type
        if sem != "stoppage_segment":
            continue
        event = dur_map.get(ev.event_id)
        if event is None:
            continue
        dur = event.duration_seconds or 0.0
        result.stoppage_count += 1
        result.total_duration_seconds += dur
        if dur > result.max_single_duration_seconds:
            result.max_single_duration_seconds = dur

        start = getattr(event, "start_time", None)
        if start is None:
            result.window_other += dur
            continue
        try:
            ts = pd.Timestamp(start)
        except Exception:
            result.window_other += dur
            continue
        h, m = ts.hour, ts.minute
        t = h * 60 + m
        if 690 <= t <= 810:       # 11:30-13:30
            result.window_noon += dur
        elif 1020 <= t <= 1230:   # 17:00-20:30
            result.window_evening += dur
        elif t >= 1320 or t <= 360:  # 22:00-06:00
            result.window_night += dur
        else:
            result.window_other += dur

    if result.stoppage_count == 0:
        result.labels = ["no_stoppage_events"]
        return result

    total = result.total_duration_seconds or 1.0
    if result.window_noon / total >= 0.15:
        result.labels.append("possible_meal_break_pattern")
    if result.window_evening / total >= 0.15:
        result.labels.append("possible_shift_or_evening_stop_pattern")
    if result.window_night / total >= 0.15:
        result.labels.append("possible_overnight_stop_pattern")
    if not result.labels:
        result.labels.append("no_clear_time_pattern")

    return result


def _build_evidence_items(
    row: dict,
    semantic_stats: dict,
    state_dist: dict,
    explanations: list,
    events: list,
    stoppage_pattern: StoppageTimePattern,
    llm_result,
) -> list[ReviewEvidenceItem]:
    """为单个文件构建 E1-E6 证据项。"""
    items: list[ReviewEvidenceItem] = []

    # E1: scan_index 基础信息
    items.append(ReviewEvidenceItem(
        evidence_id="E1",
        source_tool="scan_index_reader",
        title="扫描索引基础信息",
        value={
            "risk_rank_score": row.get("risk_rank_score", 0),
            "event_count": row.get("event_count", 0),
            "max_severity_label": row.get("max_severity_label", ""),
        },
        interpretation=f"风险分 {row.get('risk_rank_score', 0):.0f}，事件数 {row.get('event_count', 0)}，最高 {row.get('max_severity_label', '无')}",
        reliability="direct_stat",
    ))

    # E2: semantic_event_summary
    sem_summary = {}
    for sem, stats in sorted(semantic_stats.items(), key=lambda x: -x[1].get("total_seconds", 0)):
        dur_s = stats.get("total_seconds", 0)
        dur_str = f"{dur_s/3600:.1f}h" if dur_s >= 3600 else f"{dur_s/60:.0f}min"
        sem_summary[_SEM_LABELS_ZH.get(sem, sem)] = {"count": stats["count"], "duration": dur_str}
    items.append(ReviewEvidenceItem(
        evidence_id="E2",
        source_tool="semantic_event_summary",
        title="语义事件分类统计",
        value=sem_summary,
        interpretation="，".join(f"{k} {v['count']}个/{v['duration']}" for k, v in sem_summary.items()),
        reliability="direct_stat",
    ))

    # E3: state_distribution
    items.append(ReviewEvidenceItem(
        evidence_id="E3",
        source_tool="state_distribution",
        title="工况分布",
        value=state_dist,
        interpretation="，".join(f"{k} {v}" for k, v in state_dist.items()) if state_dist else "无工况数据",
        reliability="direct_stat",
    ))

    # E4: top_events_summary
    top_events = sorted(explanations, key=lambda e: e.severity_score, reverse=True)[:5]
    dur_map = {e.event_id: e.duration_seconds for e in events}
    top_ev_data = []
    for exp in top_events:
        dur = dur_map.get(exp.event_id, 0) or 0
        top_ev_data.append({
            "event_id": exp.event_id,
            "type": exp.title,
            "severity": exp.severity_label,
            "duration_s": dur,
        })
    items.append(ReviewEvidenceItem(
        evidence_id="E4",
        source_tool="top_events_summary",
        title="Top 事件摘要",
        value=top_ev_data,
        interpretation=f"Top {len(top_ev_data)} 事件：" + "，".join(f"{e['type']}({e['severity']})" for e in top_ev_data),
        reliability="direct_stat",
    ))

    # E5: llm_summary_status
    llm_info = {
        "summary_source": "none",
        "llm_status": "not_requested",
        "model": "",
    }
    if llm_result:
        llm_info = {
            "summary_source": llm_result.summary_source,
            "llm_status": llm_result.llm_status,
            "model": llm_result.model_used,
        }
    items.append(ReviewEvidenceItem(
        evidence_id="E5",
        source_tool="llm_summary",
        title="LLM 总结状态",
        value=llm_info,
        interpretation=f"总结来源={llm_info['summary_source']}，状态={llm_info['llm_status']}，模型={llm_info['model'] or '无'}",
        reliability="direct_stat",
    ))

    # E6: stoppage_time_pattern
    pat = stoppage_pattern
    pat_value = {
        "stoppage_count": pat.stoppage_count,
        "total_duration_h": round(pat.total_duration_seconds / 3600, 1),
        "max_single_h": round(pat.max_single_duration_seconds / 3600, 2),
        "window_noon_h": round(pat.window_noon / 3600, 1),
        "window_evening_h": round(pat.window_evening / 3600, 1),
        "window_night_h": round(pat.window_night / 3600, 1),
        "labels": pat.labels,
    }
    label_zh = {
        "possible_meal_break_pattern": "疑似午间停机特征",
        "possible_shift_or_evening_stop_pattern": "疑似晚间/交接停机特征",
        "possible_overnight_stop_pattern": "疑似夜间停机特征",
        "no_clear_time_pattern": "无明显时间规律",
        "no_stoppage_events": "无停机事件",
    }
    interp_parts = [f"停机 {pat.stoppage_count} 次，共 {pat_value['total_duration_h']}h"]
    for lb in pat.labels:
        interp_parts.append(label_zh.get(lb, lb))
    if pat.stoppage_count > 0:
        interp_parts.append("（需施工日志确认）")
    items.append(ReviewEvidenceItem(
        evidence_id="E6",
        source_tool="stoppage_time_pattern",
        title="停机时间模式分析",
        value=pat_value,
        interpretation="，".join(interp_parts),
        reliability="needs_external_confirmation" if pat.stoppage_count > 0 else "direct_stat",
    ))

    return items


def _build_tool_traces(evidence_items: list[ReviewEvidenceItem]) -> list[ReviewToolTrace]:
    """从 evidence items 构建工具调用轨迹。"""
    tool_defs = {
        "scan_index_reader": "读取扫描索引",
        "semantic_event_summary": "统计业务语义事件",
        "state_distribution": "统计工况分布",
        "top_events_summary": "提取 Top 事件",
        "stoppage_time_pattern": "分析停机时间分布",
        "llm_summary": "生成 AI 总结",
    }
    tool_to_evidences: dict[str, list[ReviewEvidenceItem]] = {}
    for ei in evidence_items:
        tool_to_evidences.setdefault(ei.source_tool, []).append(ei)

    traces = []
    for tool_name in ["scan_index_reader", "semantic_event_summary", "state_distribution",
                      "top_events_summary", "stoppage_time_pattern", "llm_summary"]:
        eis = tool_to_evidences.get(tool_name, [])
        if not eis:
            continue
        traces.append(ReviewToolTrace(
            tool_name=tool_name,
            purpose_zh=tool_defs.get(tool_name, tool_name),
            input_summary="单文件检测结果",
            output_summary=eis[0].interpretation[:80],
            evidence_ids=[e.evidence_id for e in eis],
        ))
    return traces


# ── 诊断假设收敛层 ──────────────────────────────────────────────────────────

@dataclass
class EvidenceDelta:
    evidence_id: str
    delta: int
    reason: str
    reliability: str

@dataclass
class HypothesisScore:
    hypothesis_id: str
    hypothesis_name_zh: str
    initial_score: int = 0
    evidence_deltas: list = field(default_factory=list)
    final_score: int = 0
    confidence_label: str = "low"
    conclusion: str = ""
    missing_evidence: list = field(default_factory=list)

@dataclass
class HypothesisBoard:
    file_name: str
    hypotheses: list = field(default_factory=list)
    top_hypothesis: str = ""
    second_hypothesis: str = ""
    score_margin: int = 0
    convergence_status: str = "not_converged"
    board_summary: str = ""
    missing_evidence: list = field(default_factory=list)


_HYPOTHESIS_DEFS = [
    ("H1", "计划性停机 / 班次或检修安排"),
    ("H2", "疑似异常停机 / 设备或地层导致停机"),
    ("H3", "推进中掘进阻力异常 / 地层或刀盘负载问题"),
    ("H4", "推进参数不匹配 / 操作策略问题"),
    ("H5", "液压系统问题"),
    ("H6", "事件切片或规则放大"),
]


def _clamp(v: int, lo: int = -100, hi: int = 100) -> int:
    return max(lo, min(hi, v))


def _get_sem(stats: dict, key: str) -> dict:
    return stats.get(key, {"count": 0, "total_seconds": 0.0})


def score_hypotheses(
    semantic_stats: dict,
    stoppage_pattern: StoppageTimePattern,
    evidence_items: list[ReviewEvidenceItem],
) -> HypothesisBoard:
    """基于 E1-E6 证据对 H1-H6 假设进行规则评分。"""

    stop = _get_sem(semantic_stats, "stoppage_segment")
    ser = _get_sem(semantic_stats, "suspected_excavation_resistance")
    ler = _get_sem(semantic_stats, "excavation_resistance_under_load")
    lee = _get_sem(semantic_stats, "low_efficiency_excavation")
    hyd = _get_sem(semantic_stats, "hydraulic_instability")

    total_events = sum(v["count"] for v in semantic_stats.values()) or 1
    total_seconds = sum(v["total_seconds"] for v in semantic_stats.values()) or 1.0

    stop_dur_h = stop["total_seconds"] / 3600
    ser_dur_h = ser["total_seconds"] / 3600
    lee_dur_h = lee["total_seconds"] / 3600
    hyd_dur_h = hyd["total_seconds"] / 3600

    pat = stoppage_pattern
    has_time_pattern = any(lb.startswith("possible_") for lb in pat.labels)
    has_noon = "possible_meal_break_pattern" in pat.labels
    has_evening = "possible_shift_or_evening_stop_pattern" in pat.labels
    has_night = "possible_overnight_stop_pattern" in pat.labels

    avg_lee_dur = (lee["total_seconds"] / lee["count"]) if lee["count"] > 0 else 0
    avg_event_dur = total_seconds / total_events

    scores: dict[str, HypothesisScore] = {}
    for hid, name_zh in _HYPOTHESIS_DEFS:
        scores[hid] = HypothesisScore(hypothesis_id=hid, hypothesis_name_zh=name_zh)

    def _add(hid: str, eid: str, delta: int, reason: str, rel: str = "direct_stat"):
        h = scores[hid]
        h.evidence_deltas.append(EvidenceDelta(eid, delta, reason, rel))

    # ── H1 planned_stoppage ──────────────────────────────────────────────────
    if stop_dur_h >= 2:
        _add("H1", "E2", 20, f"停机总时长 {stop_dur_h:.1f}h，较高")
    if has_time_pattern:
        bonus = 15
        if has_noon:
            bonus = 25
        elif has_night:
            bonus = 20
        elif has_evening:
            bonus = 20
        parts = []
        if has_noon: parts.append("午间")
        if has_evening: parts.append("晚间")
        if has_night: parts.append("夜间")
        _add("H1", "E6", bonus, f"停机具有{'、'.join(parts)}规律性特征", "needs_external_confirmation")
    if ser_dur_h >= 2 or hyd["count"] >= 10:
        _add("H1", "E2", -20, "停机前后存在阻力/液压异常，不像纯计划停机")
    scores["H1"].missing_evidence = ["施工日志", "班次记录"]

    # ── H2 abnormal_stoppage ─────────────────────────────────────────────────
    if stop_dur_h >= 2:
        _add("H2", "E2", 20, f"停机总时长 {stop_dur_h:.1f}h")
    if pat.max_single_duration_seconds >= 3600:
        _add("H2", "E6", 15, f"单次最长停机 {pat.max_single_duration_seconds/3600:.1f}h，超过 1h")
    if ser_dur_h >= 2:
        _add("H2", "E2", 25, f"掘进阻力异常 {ser_dur_h:.1f}h，停机可能与阻力相关")
    if hyd["count"] >= 10:
        _add("H2", "E2", 15, f"液压不稳定 {hyd['count']} 次，可能与停机相关")
    if has_time_pattern and ser_dur_h < 1 and hyd["count"] < 5:
        _add("H2", "E6", -15, "停机具有规律性且无前置异常，更像计划停机")
    scores["H2"].missing_evidence = ["施工日志", "停机前后窗口详细分析"]

    # ── H3 excavation_resistance ──────────────────────────────────────────────
    if ser_dur_h >= 5:
        _add("H3", "E2", 30, f"掘进阻力异常累计 {ser_dur_h:.1f}h，时长显著")
    elif ser_dur_h >= 1:
        _add("H3", "E2", 20, f"掘进阻力异常累计 {ser_dur_h:.1f}h")
    if ser["count"] >= 50:
        _add("H3", "E2", 20, f"掘进阻力异常 {ser['count']} 个事件，频次高")
    if ler["count"] >= 1:
        _add("H3", "E2", 20, f"重载推进下阻力异常 {ler['count']} 个，确认重载工况下也存在")
    if ser["count"] / total_events >= 0.3:
        _add("H3", "E2", 15, f"正常推进中也频繁出现阻力异常（占 {ser['count']/total_events*100:.0f}%）")
    scores["H3"].missing_evidence = ["地层记录", "刀盘磨损记录"]

    # ── H4 parameter_mismatch ────────────────────────────────────────────────
    if lee["count"] >= 30:
        _add("H4", "E2", 20, f"低效掘进 {lee['count']} 个事件")
    if lee_dur_h >= 2:
        _add("H4", "E2", 20, f"低效掘进累计 {lee_dur_h:.1f}h")
    elif lee["count"] >= 30 and lee_dur_h < 0.5:
        _add("H4", "E2", -10, f"低效事件多但总时长仅 {lee_dur_h:.1f}h，碎片化严重")
        _add("H6", "E2", 20, f"低效事件 {lee['count']} 个但仅 {lee_dur_h:.1f}h，疑似规则切片")
    scores["H4"].missing_evidence = ["推进参数设定记录", "地层记录"]

    # ── H5 hydraulic_issue ───────────────────────────────────────────────────
    if hyd["count"] >= 20:
        _add("H5", "E2", 15, f"液压不稳定 {hyd['count']} 次")
    if hyd_dur_h >= 0.5:
        _add("H5", "E2", 20, f"液压不稳定累计 {hyd_dur_h:.1f}h")
    elif hyd["count"] >= 5 and hyd_dur_h < 0.1:
        _add("H5", "E2", -10, f"液压事件 {hyd['count']} 次但总时长仅 {hyd_dur_h*60:.0f}min，孤立短暂")
    scores["H5"].missing_evidence = ["液压系统检修记录"]

    # ── H6 rule_fragmentation ────────────────────────────────────────────────
    if total_events >= 100 and avg_event_dur < 60:
        _add("H6", "E2", 25, f"事件数 {total_events}，平均时长仅 {avg_event_dur:.0f}s，碎片化明显")
    if lee["count"] >= 50 and avg_lee_dur < 30:
        _add("H6", "E2", 20, f"低效事件 {lee['count']} 个，平均仅 {avg_lee_dur:.0f}s")
    if stop["count"] >= 20 and stop_dur_h >= 5:
        _add("H6", "E2", 20, f"停机片段 {stop['count']} 个切分自 {stop_dur_h:.1f}h，可能过度切分")

    # ── 计算最终分 ───────────────────────────────────────────────────────────
    for h in scores.values():
        h.final_score = _clamp(h.initial_score + sum(d.delta for d in h.evidence_deltas))

    ranked = sorted(scores.values(), key=lambda h: h.final_score, reverse=True)
    top = ranked[0] if ranked else None
    second = ranked[1] if len(ranked) > 1 else None

    margin = (top.final_score - second.final_score) if top and second else 0

    # ── 收敛判断 ─────────────────────────────────────────────────────────────
    if top and top.final_score >= 60 and margin >= 20:
        convergence = "converged"
    elif top and top.final_score >= 40:
        convergence = "partially_converged"
    else:
        convergence = "not_converged"

    # planned/abnormal 停机没有施工日志时降级
    if top and top.hypothesis_id in ("H1", "H2") and convergence == "converged":
        convergence = "partially_converged"

    # ── 生成结论 ─────────────────────────────────────────────────────────────
    _CONF_MAP = {"converged": "high", "partially_converged": "medium", "not_converged": "low"}
    for h in scores.values():
        if h.final_score >= 50:
            h.confidence_label = "medium"
        if h.final_score >= 70:
            h.confidence_label = "high"
        if h.hypothesis_id in ("H1", "H2") and h.confidence_label == "high":
            h.confidence_label = "medium"

    if top:
        if convergence == "converged":
            top.conclusion = f"证据较充分支持此假设（得分 {top.final_score}）"
        elif convergence == "partially_converged":
            top.conclusion = f"证据部分支持此假设（得分 {top.final_score}），需补充关键证据确认"
        else:
            top.conclusion = f"证据不足以确认（得分 {top.final_score}），建议逐文件详查"

    all_missing = set()
    for h in scores.values():
        all_missing.update(h.missing_evidence)

    _CONV_ZH = {"converged": "已收敛", "partially_converged": "部分收敛", "not_converged": "未收敛"}
    summary_parts = [
        f"最可能：{top.hypothesis_name_zh}（{top.final_score}分）" if top else "",
        f"次可能：{second.hypothesis_name_zh}（{second.final_score}分）" if second else "",
        f"分差 {margin}，{_CONV_ZH.get(convergence, convergence)}",
    ]

    return HypothesisBoard(
        file_name="",
        hypotheses=list(scores.values()),
        top_hypothesis=top.hypothesis_id if top else "",
        second_hypothesis=second.hypothesis_id if second else "",
        score_margin=margin,
        convergence_status=convergence,
        board_summary="；".join(p for p in summary_parts if p),
        missing_evidence=sorted(all_missing),
    )


def _serialize_hypothesis(h: HypothesisScore) -> dict:
    return {
        "hypothesis_id": h.hypothesis_id,
        "hypothesis_name_zh": h.hypothesis_name_zh,
        "initial_score": h.initial_score,
        "evidence_deltas": [
            {"evidence_id": d.evidence_id, "delta": d.delta, "reason": d.reason, "reliability": d.reliability}
            for d in h.evidence_deltas
        ],
        "final_score": h.final_score,
        "confidence_label": h.confidence_label,
        "conclusion": h.conclusion,
        "missing_evidence": h.missing_evidence,
    }


def _serialize_board(board: HypothesisBoard) -> dict:
    return {
        "hypotheses": [_serialize_hypothesis(h) for h in board.hypotheses],
        "top_hypothesis": board.top_hypothesis,
        "second_hypothesis": board.second_hypothesis,
        "score_margin": board.score_margin,
        "convergence_status": board.convergence_status,
        "board_summary": board.board_summary,
        "missing_evidence": board.missing_evidence,
    }


def _format_board_for_prompt(board: HypothesisBoard) -> str:
    """将假设收敛板格式化为 LLM prompt 文本。"""
    _CONV_ZH = {"converged": "已收敛", "partially_converged": "部分收敛", "not_converged": "未收敛"}
    lines = ["[假设收敛板] 以下是规则评分系统对多个候选假设的评分结果，请基于此写总结："]
    ranked = sorted(board.hypotheses, key=lambda h: h.final_score, reverse=True)
    for h in ranked:
        delta_str = "，".join(f"{d.evidence_id}{'+' if d.delta>=0 else ''}{d.delta}" for d in h.evidence_deltas)
        lines.append(f"  {h.hypothesis_id} {h.hypothesis_name_zh}：{h.final_score}分（{delta_str or '无证据影响'}）")
    lines.append(f"  收敛状态：{_CONV_ZH.get(board.convergence_status, board.convergence_status)}")
    lines.append(f"  最可能：{board.top_hypothesis}，次可能：{board.second_hypothesis}，分差：{board.score_margin}")
    if board.missing_evidence:
        lines.append(f"  缺失证据：{'、'.join(board.missing_evidence)}")
    return "\n".join(lines)


def _run_detect_and_summarize(
    file_path: str,
    output_dir: Path,
    shared_cfg: Any,
) -> tuple:
    """运行完整检测链路 + LLM 总结。

    返回 (llm_result, fallback_str, json_path, md_path, semantic_stats,
           state_dist, explanations, events, evidences)。
    """
    from tbm_diag.cleaning import clean
    from tbm_diag.detector import detect
    from tbm_diag.evidence import extract_evidence
    from tbm_diag.explainer import TemplateExplainer
    from tbm_diag.exporter import ResultBundle, to_json, to_markdown
    from tbm_diag.feature_engine import enrich_features
    from tbm_diag.ingestion import load_csv
    from tbm_diag.segmenter import segment_events
    from tbm_diag.state_engine import STATE_LABELS, classify_states, summarize_event_state
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

    # 工况分布
    state_dist: dict[str, str] = {}
    if "machine_state" in enriched.columns:
        counts = enriched["machine_state"].value_counts()
        n_total = len(enriched)
        for key in ["stopped", "low_load_operation", "normal_excavation", "heavy_load_excavation"]:
            n = counts.get(key, 0)
            pct = n / n_total * 100 if n_total > 0 else 0.0
            label_zh = STATE_LABELS.get(key, key)
            state_dist[label_zh] = f"{pct:.1f}%"

    # 停机时间模式 + 假设收敛板（在 LLM 调用前计算，供 prompt 使用）
    stoppage_pat = analyze_stoppage_time_pattern(evidences, events)
    hyp_board = score_hypotheses(semantic_stats, stoppage_pat, [])
    hyp_board.file_name = Path(file_path).name

    llm_result = None
    if events:
        si = build_summary_input(file_path, len(enriched), explanations,
                                 evidences, events, event_states, enriched,
                                 semantic_stats=semantic_stats)
        if si:
            si.hypothesis_board_text = _format_board_for_prompt(hyp_board)
            llm_result = summarize(si, cfg.llm)

    fallback = None
    llm_ok = llm_result and llm_result.llm_status == "success"
    if not llm_ok and explanations:
        top = explanations[0]
        fallback = f"共 {len(events)} 个事件，最高 {top.severity_label}。{top.summary}"

    return (llm_result, fallback, str(json_path), str(md_path), semantic_stats,
            state_dist, explanations, events, evidences, stoppage_pat, hyp_board)


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
        (llm_result, fallback, jp, mp, sem_stats,
         state_dist, explanations, events, evidences,
         stoppage_pat, hyp_board) = _run_detect_and_summarize(
            file_path, output_dir, shared_cfg)
        rec.review_json_path = jp
        rec.review_md_path   = mp
        rec.semantic_type_counts = sem_stats
        rec.status = "ok"
        if llm_result:
            rec.llm_status = llm_result.llm_status
            rec.llm_model = llm_result.model_used
            rec.llm_provider = llm_result.llm_provider
            rec.llm_error_message = llm_result.llm_error_message
            if llm_result.llm_status == "success":
                rec.summary_source    = "llm"
                rec.ai_summary        = llm_result.overall_summary
                rec.top_risks         = llm_result.top_risks
                rec.suggested_actions = llm_result.suggested_actions
            else:
                if fallback:
                    rec.summary_source = "fallback"
                    rec.ai_summary = fallback
                else:
                    rec.summary_source = "none"
        elif fallback:
            rec.summary_source = "fallback"
            rec.llm_status = "no_events" if rec.event_count == 0 else "not_requested"
            rec.ai_summary = fallback
        else:
            rec.summary_source = "none"
            rec.llm_status = "no_events"

        # 构建证据链和工具轨迹
        rec.stoppage_pattern = stoppage_pat
        rec.evidence_items = _build_evidence_items(
            row, sem_stats, state_dist, explanations, events, stoppage_pat, llm_result)
        rec.tool_traces = _build_tool_traces(rec.evidence_items)

        # 使用完整证据重新评分假设收敛板
        board = score_hypotheses(sem_stats, stoppage_pat, rec.evidence_items)
        board.file_name = rec.file_name
        rec.hypothesis_board = board
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

    # ── 按事件数排序 ──────────────────────────────────────────────────────────
    total_events = sum(v["count"] for v in sem_agg.values())
    by_count = sorted(sem_agg.items(), key=lambda x: -x[1]["count"])
    rank_by_count = []
    for sem, v in by_count:
        pct = v["count"] / total_events * 100 if total_events else 0
        rank_by_count.append({
            "type": _SEM_LABELS_ZH.get(sem, sem),
            "count": v["count"],
            "pct": round(pct, 1),
        })

    # ── 按持续时长排序 ────────────────────────────────────────────────────────
    total_seconds = sum(v["total_seconds"] for v in sem_agg.values())
    by_duration = sorted(sem_agg.items(), key=lambda x: -x[1]["total_seconds"])
    rank_by_duration = []
    for sem, v in by_duration:
        pct = v["total_seconds"] / total_seconds * 100 if total_seconds else 0
        rank_by_duration.append({
            "type": _SEM_LABELS_ZH.get(sem, sem),
            "duration": _fmt_hours(v["total_seconds"]),
            "duration_seconds": v["total_seconds"],
            "pct": round(pct, 1),
        })

    # ── 综合判断（事件数 + 时长 + 文件数 + 高风险数）─────────────────────────
    high_risk_count = sum(1 for r in ok if r.max_severity_label == "高风险")

    def _composite_score(sem_key: str) -> float:
        v = sem_agg.get(sem_key, {})
        cnt = v.get("count", 0)
        dur = v.get("total_seconds", 0)
        fc = v.get("file_count", 0)
        cnt_norm = cnt / total_events if total_events else 0
        dur_norm = dur / total_seconds if total_seconds else 0
        fc_norm = fc / len(ok) if ok else 0
        return cnt_norm * 0.3 + dur_norm * 0.5 + fc_norm * 0.2

    scored = [(sem, _composite_score(sem)) for sem in sem_agg]
    scored.sort(key=lambda x: -x[1])

    top_sem = scored[0][0] if scored else ""
    top_label = _SEM_LABELS_ZH.get(top_sem, top_sem)

    # 构建综合判断文本
    count_top = rank_by_count[0]["type"] if rank_by_count else "无"
    dur_top = rank_by_duration[0]["type"] if rank_by_duration else "无"

    if count_top == dur_top:
        composite_judgment = f"按事件数和持续时长看，{count_top}均为最突出问题"
    else:
        composite_judgment = (
            f"按事件数看，{count_top}较多；"
            f"按持续时长看，{dur_top}影响更大。"
            f'综合判断：本批文件的核心问题更应关注“{top_label}”的影响'
        )

    # ── 优先级排序 ────────────────────────────────────────────────────────────
    priority = sorted(ok, key=lambda r: r.risk_rank_score, reverse=True)

    # ── 假设分布（跨文件）────────────────────────────────────────────────────
    hyp_top_dist: dict[str, int] = {}
    conv_dist: dict[str, int] = {}
    cross_missing: set[str] = set()
    for r in ok:
        if r.hypothesis_board:
            th = r.hypothesis_board.top_hypothesis
            hyp_top_dist[th] = hyp_top_dist.get(th, 0) + 1
            cs = r.hypothesis_board.convergence_status
            conv_dist[cs] = conv_dist.get(cs, 0) + 1
            cross_missing.update(r.hypothesis_board.missing_evidence)

    hyp_name_map = dict(_HYPOTHESIS_DEFS)

    return {
        "total_reviewed": len(ok),
        "high_risk_count": high_risk_count,
        "severity_distribution": sev_counts,
        "semantic_event_breakdown": {
            sem: {
                "label_zh": _SEM_LABELS_ZH.get(sem, sem),
                "total_count": v["count"],
                "total_duration": _fmt_hours(v["total_seconds"]),
                "total_duration_seconds": v["total_seconds"],
                "file_count": v["file_count"],
            }
            for sem, v in sorted(sem_agg.items(), key=lambda x: -x[1]["count"])
        },
        "rank_by_count": rank_by_count,
        "rank_by_duration": rank_by_duration,
        "composite_judgment": composite_judgment,
        "dominant_issue": composite_judgment,
        "hypothesis_distribution": {
            hid: {"name_zh": hyp_name_map.get(hid, hid), "file_count": cnt}
            for hid, cnt in sorted(hyp_top_dist.items(), key=lambda x: -x[1])
        },
        "convergence_distribution": conv_dist,
        "cross_missing_evidence": sorted(cross_missing),
        "priority_order": [
            {"rank": i + 1, "file": r.file_name, "score": r.risk_rank_score,
             "events": r.event_count, "severity": r.max_severity_label}
            for i, r in enumerate(priority)
        ],
    }


# ── 写汇总报告 ─────────────────────────────────────────────────────────────────

def _serialize_evidence(ei: ReviewEvidenceItem) -> dict:
    return {
        "evidence_id": ei.evidence_id,
        "source_tool": ei.source_tool,
        "title": ei.title,
        "value": ei.value,
        "interpretation": ei.interpretation,
        "reliability": ei.reliability,
    }


def _serialize_tool_trace(tt: ReviewToolTrace) -> dict:
    return {
        "tool_name": tt.tool_name,
        "purpose_zh": tt.purpose_zh,
        "input_summary": tt.input_summary,
        "output_summary": tt.output_summary,
        "evidence_ids": tt.evidence_ids,
    }


def _hypothesis_name_zh(board: HypothesisBoard, hid: str) -> str:
    for h in board.hypotheses:
        if h.hypothesis_id == hid:
            return h.hypothesis_name_zh
    return ""


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
             "summary_source": r.summary_source, "llm_status": r.llm_status,
             "llm_error_message": r.llm_error_message, "llm_model": r.llm_model,
             "top_risks": r.top_risks, "suggested_actions": r.suggested_actions,
             "semantic_type_counts": r.semantic_type_counts,
             "error_message": r.error_message,
             "review_json_path": r.review_json_path, "review_md_path": r.review_md_path,
             "tool_traces": [_serialize_tool_trace(t) for t in r.tool_traces],
             "evidence_items": [_serialize_evidence(e) for e in r.evidence_items],
             "hypothesis_board": _serialize_board(r.hypothesis_board) if r.hypothesis_board else None,
             }
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
    _SRC_LABELS = {"llm": "LLM 成功", "fallback": "规则降级", "none": "未生成"}
    for i, r in enumerate(records, 1):
        icon = _SEV_ICON.get(r.max_severity_label, "")
        lines += [f"### {i}. {r.file_name}  {icon}", "",
                  f"- 风险分：{r.risk_rank_score:.0f}  |  事件数：{r.event_count}  |  状态：{r.status}"]
        src_label = _SRC_LABELS.get(r.summary_source, r.summary_source)
        src_line = f"- 总结来源：{src_label}"
        if r.summary_source == "llm" and r.llm_model:
            src_line += f"  |  模型：{r.llm_model}"
        if r.summary_source != "llm" and r.llm_error_message:
            src_line += f"  |  原因：{r.llm_error_message}"
        lines.append(src_line)
        if r.semantic_type_counts:
            sem_parts = []
            for sem, stats in sorted(r.semantic_type_counts.items(), key=lambda x: -x[1]["count"]):
                label = _SEM_LABELS_ZH.get(sem, sem)
                dur = _fmt_hours(stats.get("total_seconds", 0))
                sem_parts.append(f"{label} {stats['count']} 个/{dur}")
            lines.append(f"- 语义事件分布：{'，'.join(sem_parts)}")

        # 工具调用与证据链
        if r.tool_traces:
            lines += ["", "#### 工具调用与证据链", "",
                      "| 工具 | 作用 | 关键输出 | 证据 |",
                      "|------|------|----------|------|"]
            for tt in r.tool_traces:
                lines.append(f"| {tt.tool_name} | {tt.purpose_zh} | {tt.output_summary[:50]} | {', '.join(tt.evidence_ids)} |")
            lines.append("")

        # 诊断假设收敛
        if r.hypothesis_board and r.hypothesis_board.hypotheses:
            board = r.hypothesis_board
            _CONV_ZH = {"converged": "已收敛", "partially_converged": "部分收敛", "not_converged": "未收敛"}
            lines += ["#### 诊断假设收敛", "",
                      "| 假设 | 初始分 | 证据影响 | 最终分 | 置信度 | 结论 |",
                      "|------|-------:|----------|-------:|--------|------|"]
            for h in sorted(board.hypotheses, key=lambda x: x.final_score, reverse=True):
                delta_parts = []
                for d in h.evidence_deltas:
                    sign = "+" if d.delta >= 0 else ""
                    delta_parts.append(f"{d.evidence_id} {sign}{d.delta}：{d.reason[:20]}")
                delta_str = "；".join(delta_parts) if delta_parts else "无"
                conf_zh = {"high": "高", "medium": "中", "low": "低", "unresolved": "待定"}.get(h.confidence_label, h.confidence_label)
                lines.append(f"| {h.hypothesis_id} {h.hypothesis_name_zh} | {h.initial_score} | {delta_str} | {h.final_score} | {conf_zh} | {h.conclusion} |")
            lines += ["",
                      f"综合收敛判断：",
                      f"- 最可能解释：{board.top_hypothesis} {_hypothesis_name_zh(board, board.top_hypothesis)}",
                      f"- 次可能解释：{board.second_hypothesis} {_hypothesis_name_zh(board, board.second_hypothesis)}",
                      f"- 分差：{board.score_margin}",
                      f"- 收敛状态：{_CONV_ZH.get(board.convergence_status, board.convergence_status)}",
                      f"- 缺失证据：{'、'.join(board.missing_evidence) if board.missing_evidence else '无'}",
                      ""]

        if r.ai_summary:
            lines += ["#### AI 复核结论", ""]
            lines.append(f"{r.ai_summary}")
            lines.append("")
        if r.top_risks:
            lines.append("主要风险：")
            for risk in r.top_risks[:5]:
                if isinstance(risk, dict):
                    text = risk.get("text", str(risk))
                    eids = risk.get("evidence_ids", [])
                    conf = risk.get("confidence", "")
                    eid_str = f"  （证据：{', '.join(eids)}）" if eids else ""
                    conf_str = f"  [{conf}]" if conf else ""
                    lines.append(f"- {text}{eid_str}{conf_str}")
                else:
                    lines.append(f"- {risk}")
            lines.append("")
        if r.suggested_actions:
            lines.append("建议：")
            for act in r.suggested_actions[:5]:
                if isinstance(act, dict):
                    text = act.get("text", str(act))
                    eids = act.get("evidence_ids", [])
                    eid_str = f"  （证据：{', '.join(eids)}）" if eids else ""
                    lines.append(f"- {text}{eid_str}")
                else:
                    lines.append(f"- {act}")
            lines.append("")

        # 停机时间模式
        if r.stoppage_pattern and r.stoppage_pattern.stoppage_count > 0:
            pat = r.stoppage_pattern
            label_zh = {
                "possible_meal_break_pattern": "疑似午间停机特征",
                "possible_shift_or_evening_stop_pattern": "疑似晚间/交接停机特征",
                "possible_overnight_stop_pattern": "疑似夜间停机特征",
                "no_clear_time_pattern": "无明显时间规律",
            }
            lines.append(f"停机时间模式（证据：E6）：停机 {pat.stoppage_count} 次，"
                         f"共 {pat.total_duration_seconds/3600:.1f}h，"
                         f"最长单次 {pat.max_single_duration_seconds/3600:.2f}h")
            for lb in pat.labels:
                lines.append(f"- {label_zh.get(lb, lb)}")
            if any(lb.startswith("possible_") for lb in pat.labels):
                lines.append("- 性质：需要施工日志确认")
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

    # 按事件数排序
    rank_count = cross.get("rank_by_count", [])
    if rank_count:
        lines += ["**按事件数排序**", ""]
        for item in rank_count:
            lines.append(f"- {item['type']}：{item['count']} 个（{item['pct']}%）")
        lines.append("")

    # 按持续时长排序
    rank_dur = cross.get("rank_by_duration", [])
    if rank_dur:
        lines += ["**按持续时长排序**", ""]
        for item in rank_dur:
            lines.append(f"- {item['type']}：{item['duration']}（{item['pct']}%）")
        lines.append("")

    # 综合判断
    if cross.get("composite_judgment"):
        lines += [f"> **综合判断**：{cross['composite_judgment']}", ""]

    # 跨文件假设分布
    hyp_dist = cross.get("hypothesis_distribution", {})
    conv_dist = cross.get("convergence_distribution", {})
    cross_missing = cross.get("cross_missing_evidence", [])
    if hyp_dist:
        _CONV_ZH = {"converged": "已收敛", "partially_converged": "部分收敛", "not_converged": "未收敛"}
        lines += ["**跨文件假设分布**", ""]
        for hid, info in hyp_dist.items():
            lines.append(f"- {hid} {info['name_zh']}：{info['file_count']} 个文件为 Top 假设")
        lines.append("")
        if conv_dist:
            conv_parts = [f"{_CONV_ZH.get(k, k)} {v} 个" for k, v in conv_dist.items()]
            lines.append(f"收敛状态分布：{'，'.join(conv_parts)}")
            lines.append("")
        if cross_missing:
            lines.append(f"共同缺失证据：{'、'.join(cross_missing)}")
            lines.append("")

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
            if rec.summary_source == "llm":
                print(f" OK  (LLM成功)")
            elif rec.summary_source == "fallback":
                reason = rec.llm_error_message or rec.llm_status
                print(f" OK  (规则降级: {reason})")
            else:
                print(f" OK  (无事件/未请求LLM)")
        else:
            print(f" FAIL  {rec.error_message[:60]}")

    json_path, md_path = _write_review_summary(records, targets, review_cfg, output_dir)

    ok_n  = sum(1 for r in records if r.status == "ok")
    err_n = sum(1 for r in records if r.status == "error")
    llm_ok = sum(1 for r in records if r.summary_source == "llm")
    llm_fb = sum(1 for r in records if r.summary_source == "fallback")
    print(f"\n[review] 完成  OK={ok_n}  失败={err_n}  LLM成功={llm_ok}  规则降级={llm_fb}")
    print(f"[review] 总结 JSON : {json_path}")
    print(f"[review] 总结 MD   : {md_path}")

    if review_cfg.require_llm and llm_ok < ok_n:
        print(f"\n⚠ --require-llm: {ok_n - llm_ok} 个文件 LLM 未成功", file=sys.stderr)

    return records

