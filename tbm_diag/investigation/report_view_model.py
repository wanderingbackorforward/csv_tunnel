"""report_view_model.py — 统一报告可见文本的唯一合法来源。

所有 investigation_report.md 中的用户可见文本必须从 ReportViewModel 生成。
report.py 只负责将 ViewModel 格式化为 Markdown，不做任何文本生成。

禁止进入 ViewModel 的 raw source（必须经过 sanitizer）：
- state.final_conclusion.*
- state.executive_summary.recommendation_for_user
- state.actions_taken.rationale
- state.llm_calls.thought_summary
- state.investigation_questions.findings / reason_if_unanswered
- state.case_classifications.reasons
- raw observation SER/HYD 因果文本
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tbm_diag.investigation.state import InvestigationState, compute_drilldown_coverage


# ── View dataclasses ──

@dataclass
class TopCaseView:
    case_id: str
    start_time: str
    end_time: str
    duration_min: float
    csv_observation: str
    nature_status: str


@dataclass
class ReactTraceRow:
    round_num: int
    planner_label: str
    llm_status: str
    sanitized_reason: str
    action: str
    sanitized_observation: str
    evidence_gate: str


@dataclass
class LlmCallRow:
    round_num: int
    status: str
    selected_action: str
    latency_s: float
    sanitized_thought: str


@dataclass
class ConsistencyItem:
    category: str  # correction | warning | drilled_former_unverified | not_drilled_unverified
    safe_text: str


@dataclass
class AuditCaseDetail:
    case_id: str
    case_type_label: str
    confidence: float
    safe_reasons: list[str]
    pre_event_count: int
    post_event_count: int


@dataclass
class QuestionView:
    qid: str
    text: str
    status_label: str
    tools_called: str
    safe_findings: str
    needs_manual_check: bool


@dataclass
class DrilldownView:
    """Sanitized drilldown result for report rendering."""
    target_id: str
    # Compact table fields (sanitized)
    compact_pre: str
    compact_during: str
    compact_post: str
    safe_hint: str  # sanitized interpretation_hint
    # Structured data for detail rendering (numbers only, no free text)
    target_event_info: dict = field(default_factory=dict)
    semantic_overlap: dict = field(default_factory=dict)
    pre_summary: dict = field(default_factory=dict)
    during_summary: dict = field(default_factory=dict)
    post_summary: dict = field(default_factory=dict)
    # Sanitized text fields
    safe_divergence_notes: list[str] = field(default_factory=list)
    safe_transition_findings: list[str] = field(default_factory=list)


@dataclass
class ReportViewModel:
    """Single source of truth for all visible report text."""

    # Section 1
    conclusion_text: str = ""
    key_findings: list[str] = field(default_factory=list)

    # Section 4.2 SER
    ser_text_lines: list[str] = field(default_factory=list)

    # Section 4.3 HYD
    hyd_text: str = ""

    # Section 4.4 Fragmentation
    frag_text_lines: list[str] = field(default_factory=list)

    # Section 3 & 7 audit top cases
    top_cases: list[TopCaseView] = field(default_factory=list)
    audit_top_cases: list[AuditCaseDetail] = field(default_factory=list)

    # Section 5
    unresolved_items: list[str] = field(default_factory=list)

    # Section 6
    next_steps: list[str] = field(default_factory=list)

    # Section 7 trace
    trace_rows: list[ReactTraceRow] = field(default_factory=list)
    llm_call_rows: list[LlmCallRow] = field(default_factory=list)

    # Section 7.4 drilldown (sanitized)
    drilldown_views: list[DrilldownView] = field(default_factory=list)

    # Section 7 consistency
    consistency_items: list[ConsistencyItem] = field(default_factory=list)

    # Section 7 questions
    question_views: list[QuestionView] = field(default_factory=list)

    # Planner audit stats (safe — counts, not LLM text)
    planner_type_label: str = ""
    planner_description: str = ""
    llm_call_count: int = 0
    llm_success_count: int = 0
    llm_fallback_count: int = 0
    llm_model: str = ""

    # Section 7.9 cross-file
    cross_file_patterns_safe: list[str] = field(default_factory=list)

    # For report_checker
    drilled_case_ids: set[str] = field(default_factory=set)
    full_coverage: bool = False
    completeness_status: str = ""


# ── Constants ──

_PLANNER_LABELS = {
    "rule": "规则", "llm": "LLM",
    "hybrid_rule": "混合/规则", "hybrid_llm": "混合/LLM",
}

_PLANNER_TYPE_LABELS = {
    "rule": "规则 planner（未调用 LLM API）",
    "llm": "LLM planner（每轮调用 LLM API）",
    "hybrid": "混合 planner（关键分支调用 LLM）",
}

_Q_STATUS_LABELS = {
    "unanswered": "未回答", "partially_answered": "部分回答",
    "answered": "已回答", "blocked_by_missing_data": "缺少数据",
}

_CASE_TYPE_LABELS = {
    "abnormal_like_stoppage": "异常停机线索（需日志确认）",
    "event_level_abnormal_unverified": "事件级异常线索，待验证",
    "planned_like_stoppage": "性质待施工日志确认",
    "uncertain_stoppage": "性质待施工日志确认",
    "normal_like_stoppage": "性质待施工日志确认",
    "boundary_stoppage": "窗口不完整，性质待施工日志确认",
    "short_operational_pause": "短暂运行暂停",
}


# ── Sanitizers ──

_UNSAFE_REASON_PATTERNS = [
    (r"电阻\s*/\s*SER", "掘进阻力异常 SER"),
    (r"电阻/SER", "掘进阻力异常 SER"),
    (r"揭示停机主因", "分析异常线索"),
    (r"SER[^，。；]*?触发停机[^，。；]*?机制", "分析 SER 与停机的关联"),
    (r"SER是主因", "SER 是重要线索"),
    (r"找出SER[^，。；]*?触发[^，。；]*?机制", "分析 SER 与停机的关联"),
    (r"找出触发机制", "分析异常线索与停机的关联"),
    (r"(\d+)个案例有掘进阻力异常", r"\1个事件有掘进阻力异常"),
    (r"耗时过长", ""),
    (r"耗时[^，。；]*?过长", ""),
    (r"批量钻取\d+个案例[^，。；]*?耗时[^，。；]*", "批量检查剩余停机案例"),
    (r"可能为启停伴随", "需核查统计口径"),
    (r"与\s*SER\s*(?:时间有重叠|同步)", "需核查统计口径"),
    (r"靠近停机边界[，,]?\s*", ""),
    (r"多为孤立短时波动", "需核查统计口径"),
]

_UNSAFE_FINDINGS_PATTERNS = [
    (r"可能为启停伴随", "需先核查统计口径"),
    (r"与\s*SER\s*(?:时间有重叠|同步)", "需先核查统计口径"),
    (r"靠近停机边界[，,]?\s*", ""),
    (r"多为孤立短时波动", "需先核查统计口径"),
]

_FORBIDDEN_NATURE_LABELS = [
    "确认计划停机", "确认为计划停机", "典型正常操作停顿",
    "计划停机（疑似）", "待确认停机",
]


def sanitize_reason(raw: str, action: str, args: dict,
                    executed_targets: set[str] | None = None) -> str:
    """Sanitize LLM planner raw reason for display."""
    text = raw
    for pat, repl in _UNSAFE_REASON_PATTERNS:
        text = re.sub(pat, repl, text)
    if not any(s in text for s in ("未证明为主因", "不作为主因", "未确认为主因")):
        text = re.sub(r"停机主因", "停机线索", text)
        text = re.sub(r"主因应", "线索应", text)
    if action in ("drilldown_time_window", "drilldown_time_windows_batch") and executed_targets:
        mentioned = set(re.findall(r"\bSC_\d+\b", raw))
        if mentioned and executed_targets and mentioned != executed_targets:
            text = f"[已修正] → {', '.join(sorted(executed_targets))}"
    text = re.sub(r"(需先?核查统计口径[，,]?){2,}", "需核查统计口径", text)
    return text.replace("|", "/").strip("，、, ")[:50]


def sanitize_findings(text: str) -> str:
    """Sanitize HYD/SER causal language from findings/observation text."""
    for pat, repl in _UNSAFE_FINDINGS_PATTERNS:
        text = re.sub(pat, repl, text)
    text = re.sub(r"(需先?核查统计口径[，,]?){2,}", "需核查统计口径", text)
    return text.strip("，、, ")


def sanitize_thought(raw: str) -> str:
    """Sanitize LLM call thought_summary for audit display."""
    return sanitize_reason(raw, "", {})


# ── Helpers ──

def _collect_drilled_ids(state: InvestigationState) -> set[str]:
    ids: set[str] = set()
    for obs in state.observations:
        if obs.action == "drilldown_time_window":
            tid = obs.data.get("target_id", "")
            if tid:
                ids.add(tid)
        elif obs.action == "drilldown_time_windows_batch":
            for tid in (obs.data.get("target_ids") or []):
                if isinstance(tid, str):
                    ids.add(tid)
            for pt in (obs.data.get("per_target") or []):
                tid = pt.get("target_id", "")
                if tid:
                    ids.add(tid)
    return ids


def _build_drilldown_map(state: InvestigationState) -> dict[str, dict]:
    m: dict[str, dict] = {}
    for obs in state.observations:
        if obs.action == "drilldown_time_window":
            tid = obs.data.get("target_id", "")
            if tid:
                m[tid] = obs.data
        elif obs.action == "drilldown_time_windows_batch":
            for pt in (obs.data.get("per_target") or []):
                tid = pt.get("target_id", "")
                if tid:
                    m[tid] = pt
    return m


def _build_drilldown_views(state: InvestigationState) -> list[DrilldownView]:
    """Build sanitized drilldown views from observations — no raw free-text leaks."""
    views: list[DrilldownView] = []
    for obs in state.observations:
        if obs.action == "drilldown_time_window":
            dv = _make_drilldown_view(obs.data or {})
            if dv:
                views.append(dv)
        elif obs.action == "drilldown_time_windows_batch":
            for pt in (obs.data.get("per_target") or []):
                dv = _make_drilldown_view(pt)
                if dv:
                    views.append(dv)
    return views


def _make_drilldown_view(data: dict) -> DrilldownView | None:
    """Sanitize a single drilldown result into a safe view."""
    tid = data.get("target_id", "")
    if not tid:
        return None

    def _compact(field: str) -> str:
        return (data.get(field, "") or "").replace("|", "/")[:40]

    def _sanitize_hint(raw: str) -> str:
        text = sanitize_findings(raw).replace("|", "/")
        for bad in _FORBIDDEN_NATURE_LABELS:
            text = text.replace(bad, "")
        return text.strip("，、, ")[:80]

    return DrilldownView(
        target_id=tid,
        compact_pre=_compact("compact_pre"),
        compact_during=_compact("compact_during"),
        compact_post=_compact("compact_post"),
        safe_hint=_sanitize_hint(data.get("interpretation_hint", "") or ""),
        target_event_info=data.get("target_event_info", {}) or {},
        semantic_overlap=data.get("semantic_overlap", {}) or {},
        pre_summary=data.get("pre_summary", {}) or {},
        during_summary=data.get("during_summary", {}) or {},
        post_summary=data.get("post_summary", {}) or {},
        safe_divergence_notes=[
            sanitize_findings(n).replace("|", "/")
            for n in (data.get("divergence_notes") or [])
        ],
        safe_transition_findings=[
            sanitize_findings(f).replace("|", "/")
            for f in (data.get("transition_findings") or [])
        ],
    )


def _safe_csv_observation(hint: str, case_type: str) -> str:
    """Extract CSV-visible facts only. No nature/classification labels."""
    facts: list[str] = []
    if hint:
        cleaned = hint
        for bad in _FORBIDDEN_NATURE_LABELS + [
            "性质待施工日志确认", "待施工日志确认", "性质待确认",
            "疑似计划", "疑似异常", "（疑似，需结合施工日志确认）",
        ]:
            cleaned = cleaned.replace(bad, "")
        cleaned = cleaned.strip("，、, ")
        if cleaned:
            facts.append(cleaned)
    if case_type == "abnormal_like_stoppage" and not facts:
        facts.append("停机前存在异常前兆")
    elif case_type in ("normal_like_stoppage", "planned_like_stoppage",
                       "uncertain_stoppage") and not facts:
        facts.append("停机前后未见明显异常")
    elif case_type == "boundary_stoppage":
        facts.append("起始缺前窗口")
    if not facts:
        facts.append("停机前后未见明显异常")
    return "；".join(facts)


def _safe_nature_status(case_type: str) -> str:
    if case_type == "abnormal_like_stoppage":
        return "停机前存在异常前兆，需确认是否为异常停机"
    if case_type == "boundary_stoppage":
        return "窗口不完整，性质待施工日志确认"
    return "性质待施工日志确认"


# ── Section builders ──

def _build_conclusion_and_findings(claims, ledger) -> tuple[str, list[str]]:
    """Section 1: ONLY from compiled_claims — never from final_conclusion."""
    text = ""
    findings: list[str] = []
    if claims and claims.one_sentence_conclusion:
        text = claims.one_sentence_conclusion
    if claims and claims.key_findings:
        findings = list(claims.key_findings)
    return text, findings


def _build_hyd_text(ledger) -> str:
    """Section 4.3: HYD safe text based on analysis status."""
    if ledger is None:
        return "未执行液压分析。"
    if not ledger.hyd_analysis_executed:
        return "本轮未执行独立液压模式分析，停机窗口中未见明显 HYD 行级命中，暂不作为主因判断。"
    if ledger.hyd_duration_hours == 0.0 and ledger.hyd_event_count > 0:
        return (
            f"HYD 有 {ledger.hyd_event_count} 次记录，但总时长显示为 0.0h，"
            "需先核查统计口径；暂不作为主因或伴随因果判断。"
        )
    if ledger.hyd_event_count > 0:
        return f"HYD 事件 {ledger.hyd_event_count} 个，需进一步核查。"
    return "液压分析已执行，未发现明显异常。"


def _build_ser_text(state: InvestigationState) -> list[str]:
    """Section 4.2: SER safe text from observations."""
    lines: list[str] = []
    for obs in state.observations:
        if obs.action != "analyze_resistance_pattern":
            continue
        data = obs.data or {}
        in_adv = data.get("in_advancing_ratio", 0)
        # overwrite: keep only the last observation's text
        lines = [
            f"- SER 事件数：{data.get('ser_count', 0)} 次",
            f"- SER 总时长：{data.get('ser_total_duration_h', 0)}h",
            f"- 其中推进中发生：{in_adv:.0%}",
        ]
        if data.get("all_stopped_overlap"):
            lines.append("- 当前判断：SER 事件多出现在停机期间，暂不能证明是推进中真实阻力异常")
        elif in_adv > 0.5 and data.get("near_stoppage"):
            lines.append("- 当前判断：推进中存在 SER，且与停机时段相邻，当前未证明为停机原因，需结合地质/操作记录核查")
        elif in_adv > 0.5:
            lines.append("- 当前判断：推进中存在 SER，但与停机的关联不明确")
        else:
            lines.append("- 当前判断：SER 主要不在推进中发生，暂不能证明为停机原因")
    return lines


def _build_frag_text(state: InvestigationState) -> list[str]:
    """Section 4.4: Fragmentation safe text."""
    lines: list[str] = []
    for obs in state.observations:
        if obs.action != "analyze_event_fragmentation":
            continue
        data = obs.data or {}
        short_r = data.get("short_event_ratio", 0)
        frag = data.get("fragmentation_risk", False)
        lines.append(f"- 短事件占比：{short_r:.0%}")
        if frag:
            lines.append("- 碎片化风险较高，部分异常事件可能是同一段异常被拆分，结论可能受影响")
        else:
            lines.append("- 碎片化风险低，事件统计可信")
    return lines


def _build_top_cases(state, cov, drilled_ids, corrected_types) -> tuple[list[TopCaseView], list[AuditCaseDetail]]:
    """Section 3 & audit: top cases with safe CSV observation and nature status."""
    all_cases = []
    for fp, cases in state.stoppage_cases.items():
        for c in cases:
            cls = state.case_classifications.get(c.case_id)
            all_cases.append((c, cls))
    all_cases.sort(key=lambda x: -x[0].duration_seconds)

    drilldown_map = _build_drilldown_map(state)
    top: list[TopCaseView] = []
    audit: list[AuditCaseDetail] = []

    for c, cls in all_cases[:10]:
        ct = corrected_types.get(c.case_id, cls.case_type if cls else "")
        # CSV observation
        hint = ""
        dd = drilldown_map.get(c.case_id)
        if dd:
            hint = (dd.get("interpretation_hint") or "").replace("|", "/")
        csv_obs = _safe_csv_observation(hint, ct)
        nature = _safe_nature_status(ct)

        top.append(TopCaseView(
            case_id=c.case_id, start_time=c.start_time, end_time=c.end_time,
            duration_min=c.duration_seconds / 60,
            csv_observation=csv_obs, nature_status=nature,
        ))

        # Audit detail
        safe_reasons = []
        if cls and cls.reasons:
            for r in cls.reasons:
                sr = sanitize_findings(r)
                if sr:
                    safe_reasons.append(sr)
        ta = state.transition_analyses.get(c.case_id)
        audit.append(AuditCaseDetail(
            case_id=c.case_id,
            case_type_label=_CASE_TYPE_LABELS.get(ct, ct),
            confidence=cls.confidence if cls else 0,
            safe_reasons=safe_reasons,
            pre_event_count=len(ta.pre_events) if ta else 0,
            post_event_count=len(ta.post_events) if ta else 0,
        ))

    return top, audit


def _build_unresolved(claims, state, cov, drilled_ids) -> list[str]:
    """Section 5: ONLY from compiled_claims + drilled-aware checks."""
    items: list[str] = []
    if claims and claims.unresolved_items:
        items.extend(claims.unresolved_items)

    # Drilled former-unverified cases
    for cid, cls in state.case_classifications.items():
        if cls.case_type == "event_level_abnormal_unverified" and cid in drilled_ids:
            items.append(
                f"{cid}：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；"
                "性质仍需施工日志确认"
            )

    # Still-unverified cases (not drilled)
    not_drilled_uv = [
        cid for cid, cls in state.case_classifications.items()
        if cls.case_type == "event_level_abnormal_unverified" and cid not in drilled_ids
    ]
    if not_drilled_uv:
        items.append(f"以下案例有异常线索但未深入验证：{', '.join(not_drilled_uv)}")

    # Case time ranges for manual check
    for cid, cls in state.case_classifications.items():
        if cls.case_type in ("abnormal_like_stoppage", "uncertain_stoppage"):
            for cases in state.stoppage_cases.values():
                for c in cases:
                    if c.case_id == cid:
                        items.append(f"施工日志确认：{c.start_time} ~ {c.end_time}（{cid}）")

    return items


def _build_next_steps(claims, state, cov, ledger) -> list[str]:
    """Section 6: from claims + computed. Never from executive_summary."""
    steps: list[str] = []

    # 1. Stoppage nature check
    all_cases = []
    for fp, cases in state.stoppage_cases.items():
        all_cases.extend(cases)
    if all_cases:
        all_cases.sort(key=lambda x: -x.duration_seconds)
        ids = [c.case_id for c in all_cases[:5]]
        steps.append(
            f"确认停机性质（{'、'.join(ids)}等）："
            "计划安排、检修/换刀、等待、交接班、外部调度或异常停机"
        )

    # 2. SER
    for obs in state.observations:
        if obs.action == "analyze_resistance_pattern":
            data = obs.data or {}
            if data.get("ser_count", 0) > 0:
                steps.append("核查 SER 高发时段对应的地层和操作记录，判断是否为地层变化导致")
                break

    # 3. HYD
    if ledger and not ledger.hyd_analysis_executed and ledger.total_stoppage_cases > 0:
        steps.append("补充液压分析（本次未执行）")

    # 4. From compiled_claims (dedup)
    if claims and claims.next_manual_checks:
        for c in claims.next_manual_checks:
            overlap = False
            for s in steps:
                for kw in ("施工日志", "SER", "液压", "HYD", "增加调查"):
                    if kw in s and kw in c:
                        overlap = True
                        break
                if overlap:
                    break
            if not overlap and c not in steps:
                steps.append(c)

    return steps


def _build_trace(state) -> tuple[list[ReactTraceRow], list[LlmCallRow]]:
    """Section 7: sanitized ReAct trace and LLM calls."""
    trace: list[ReactTraceRow] = []
    llm_calls: list[LlmCallRow] = []

    for action_rec in state.actions_taken:
        obs = None
        for o in state.observations:
            if o.round_num == action_rec.round_num:
                obs = o
                break

        obs_text = (obs.result_summary[:60] if obs else "无").replace("|", "/")
        obs_text = sanitize_findings(obs_text)

        # Compute executed targets for mismatch detection
        executed_targets: set[str] = set()
        args = action_rec.arguments or {}
        if action_rec.action == "drilldown_time_window":
            tid = args.get("target_id", "")
            if tid:
                executed_targets.add(tid)
        elif action_rec.action == "drilldown_time_windows_batch":
            for tid in args.get("target_ids", []):
                if isinstance(tid, str):
                    executed_targets.add(tid)

        reason = sanitize_reason(
            action_rec.rationale or "", action_rec.action, args, executed_targets
        )
        pt = _PLANNER_LABELS.get(action_rec.planner_type, action_rec.planner_type)
        llm_col = action_rec.llm_status if action_rec.llm_called else "—"

        eg_col = "—"
        if action_rec.evidence_gate_override:
            eg_col = f"override: {action_rec.evidence_gate_original_action}→{action_rec.action}"

        trace.append(ReactTraceRow(
            round_num=action_rec.round_num, planner_label=pt,
            llm_status=llm_col, sanitized_reason=reason,
            action=action_rec.action, sanitized_observation=obs_text,
            evidence_gate=eg_col,
        ))

    # LLM calls
    for c in state.llm_calls:
        if c.status == "skipped":
            continue
        thought = sanitize_thought((c.thought_summary or c.error_message or ""))
        llm_calls.append(LlmCallRow(
            round_num=c.round_num, status=c.status,
            selected_action=c.selected_action or "—",
            latency_s=c.latency_seconds,
            sanitized_thought=thought.replace("|", "/")[:40],
        ))

    return trace, llm_calls


def _build_consistency(state, drilled_ids) -> tuple[list[ConsistencyItem], dict[str, str]]:
    """Compute consistency corrections without mutating state."""
    items: list[ConsistencyItem] = []
    corrected_types: dict[str, str] = {}

    drilldown_map = _build_drilldown_map(state)

    for case_id, cls in state.case_classifications.items():
        dd = drilldown_map.get(case_id)
        if dd is None:
            continue

        pre = dd.get("pre_summary", {})
        post = dd.get("post_summary", {})
        hint = dd.get("interpretation_hint", "")

        pre_ser = pre.get("ser_ratio", 0) if isinstance(pre, dict) else 0
        pre_hyd = pre.get("hyd_hits", 0) if isinstance(pre, dict) else 0
        post_empty = post.get("empty", True) if isinstance(post, dict) else True
        post_ser = post.get("ser_ratio", 0) if isinstance(post, dict) else 0
        post_hyd = post.get("hyd_hits", 0) if isinstance(post, dict) else 0

        clean_pre = pre_ser <= 0.05 and pre_hyd == 0
        clean_post = post_empty or (post_ser <= 0.05 and post_hyd == 0)

        for r in cls.reasons:
            if "停机前存在" in r and "SER" in r and clean_pre:
                items.append(ConsistencyItem("correction",
                    f"{case_id}: 分类依据「{r}」已按 drilldown 修正——"
                    f"停机前 SER 未被窗口证据支持（pre SER ratio={pre_ser:.3f}）"))
            elif "停机前存在" in r and "HYD" in r and clean_pre:
                items.append(ConsistencyItem("correction",
                    f"{case_id}: 分类依据「{r}」已按 drilldown 修正——"
                    f"停机前 HYD 未被窗口证据支持（pre HYD hits={pre_hyd}）"))
            elif "恢复后仍有异常" in r and clean_post:
                items.append(ConsistencyItem("correction",
                    f"{case_id}: 分类依据「{r}」已按 drilldown 修正——恢复后窗口未检测到异常"))

        if cls.case_type in ("abnormal_like_stoppage", "event_level_abnormal_unverified") and clean_pre and clean_post:
            if "停机前未见明显异常" in hint:
                corrected_types[case_id] = "planned_like_stoppage"
                items.append(ConsistencyItem("correction",
                    f"{case_id}: 分类从 {cls.case_type} 降级为 planned_like_stoppage——"
                    f"drilldown 显示「{hint}」，与异常线索矛盾"))

    # SER warnings
    for obs in state.observations:
        if obs.action == "analyze_resistance_pattern":
            if obs.data.get("all_stopped_overlap"):
                items.append(ConsistencyItem("warning",
                    "当前 SER 事件多与停机片段重叠，暂不能证明推进中的掘进阻力异常，"
                    "需要重新区分停机期伪异常与推进期 SER"))
        if obs.action == "drilldown_time_window":
            tid = obs.data.get("target_id", "")
            if tid.startswith("SER_"):
                during = obs.data.get("during_summary", {})
                if isinstance(during, dict):
                    stopped = during.get("state_distribution", {}).get("stopped", 0)
                    speed = during.get("avg_advance_speed", 0)
                    if stopped > 80 and speed < 1:
                        items.append(ConsistencyItem("warning",
                            f"{tid}: 事件期间 stopped={stopped:.0f}%、速度={speed}，"
                            "实为停机窗口，不代表推进中 SER"))

    # Former unverified that are now drilled
    for cid, cls in state.case_classifications.items():
        if cls.case_type == "event_level_abnormal_unverified" and cid in drilled_ids:
            items.append(ConsistencyItem("drilled_former_unverified",
                f"{cid}：事件级曾提示异常线索，但窗口钻取后未见明显 SER/HYD 行级异常；"
                "性质仍需施工日志确认"))

    # Still-unverified (not drilled)
    for cid, cls in state.case_classifications.items():
        if cls.case_type == "event_level_abnormal_unverified" and cid not in drilled_ids:
            items.append(ConsistencyItem("not_drilled_unverified",
                f"{cid}：事件级证据显示异常迹象，未运行 drilldown 验证"))

    return items, corrected_types


def _build_questions(state, ledger) -> list[QuestionView]:
    """Section 7: all question findings regenerated from rules, not from raw findings."""
    views: list[QuestionView] = []
    for q in state.investigation_questions:
        safe_fs = _safe_question_finding(q, state, ledger)
        views.append(QuestionView(
            qid=q.qid, text=q.text,
            status_label=_Q_STATUS_LABELS.get(q.status, q.status),
            tools_called=", ".join(q.tools_called) if q.tools_called else "—",
            safe_findings=safe_fs,
            needs_manual_check=q.needs_manual_check,
        ))
    return views


def _safe_question_finding(q, state, ledger) -> str:
    """Generate safe findings text per question based on rules, never raw findings."""
    text_lower = q.text.lower()

    # HYD-related questions
    if any(kw in text_lower for kw in ("hyd", "液压", "hydraulic")):
        if ledger is None or not ledger.hyd_analysis_executed:
            return "本轮未执行独立 HYD 模式分析；暂不作为主因判断。"
        if ledger.hyd_duration_hours == 0.0 and ledger.hyd_event_count > 0:
            return "HYD 有记录但总时长为 0.0h，需核查统计口径；暂不作为主因判断。"
        if ledger.hyd_event_count > 0:
            return f"HYD 事件 {ledger.hyd_event_count} 个，需进一步核查。"
        return "液压分析已执行，未发现明显异常。"

    # SER-related questions
    if any(kw in text_lower for kw in ("ser", "掘进阻力", "resistance")):
        for obs in state.observations:
            if obs.action == "analyze_resistance_pattern":
                data = obs.data or {}
                ratio = data.get("in_advancing_ratio", 0)
                return f"SER 推进中占比 {ratio:.0%}，当前未证明为停机原因。"
        return "未执行掘进阻力分析。"

    # Stoppage-related questions
    if any(kw in text_lower for kw in ("停机", "stoppage")):
        cov = compute_drilldown_coverage(state)
        total = cov["total_count"]
        covered = cov["covered_count"]
        if total > 0:
            return f"共识别 {total} 段停机，已逐案检查 {covered}/{total}。"
        return "未检测到停机事件。"

    # Fragmentation-related questions
    if any(kw in text_lower for kw in ("碎片化", "fragmentation")):
        for obs in state.observations:
            if obs.action == "analyze_event_fragmentation":
                data = obs.data or {}
                short_r = data.get("short_event_ratio", 0)
                frag = data.get("fragmentation_risk", False)
                risk = "高" if frag else "低"
                return f"短事件占比 {short_r:.0%}，碎片化风险{risk}。"
        return "未执行碎片化分析。"

    # Default: answer from tools_called + status, never raw findings
    if q.status == "unanswered":
        return "未获得足够证据回答此问题。"
    if q.status == "blocked_by_missing_data":
        return "缺少必要数据，无法回答。"
    # For answered/partially_answered: summarize from tools called, not raw text
    if q.tools_called:
        return f"已调用 {', '.join(q.tools_called[:3])} 分析，详见报告正文。"
    return "—".replace("|", "/")


def _build_planner_audit(state) -> dict:
    """Planner stats (safe — structured counts)."""
    pt = state.planner_type
    llm_attempted = sum(1 for c in state.llm_calls if c.status != "skipped")

    desc = ""
    if pt == "rule":
        desc = "本次使用规则 planner，未调用 LLM API。"
    elif llm_attempted > 0 and state.llm_success_count == llm_attempted:
        desc = f"本次使用 {pt} planner，共 {llm_attempted} 次 LLM planner 调用，全部成功。"
    elif llm_attempted > 0:
        desc = (f"本次使用 {pt} planner，共 {llm_attempted} 次 LLM 调用，"
                f"{state.llm_success_count} 次成功，"
                f"{state.llm_fallback_count} 次 fallback 到规则。")
    elif pt in ("llm", "hybrid"):
        no_key = any(c.status == "no_key" for c in state.llm_calls)
        if no_key:
            desc = "未检测到 API Key，所有轮次 fallback 到规则 planner。"
        else:
            desc = "LLM 调用全部跳过或失败，已 fallback 到规则 planner。"

    return {
        "type_label": _PLANNER_TYPE_LABELS.get(pt, pt),
        "description": desc,
        "call_count": llm_attempted,
        "success_count": state.llm_success_count,
        "fallback_count": state.llm_fallback_count,
        "model": state.llm_model or "",
    }


# ── Main builder ──

def build_report_view_model(state: InvestigationState) -> ReportViewModel:
    """Build the single source of truth for all visible report text."""
    vm = ReportViewModel()
    ledger = state.evidence_ledger
    claims = state.compiled_claims
    cov = compute_drilldown_coverage(state)

    # Drilled IDs
    vm.drilled_case_ids = _collect_drilled_ids(state)

    # Coverage
    vm.full_coverage = (
        ledger is not None
        and ledger.total_stoppage_cases > 0
        and ledger.actual_stoppage_coverage_count >= ledger.total_stoppage_cases
    )
    vm.completeness_status = ledger.completeness_status if ledger else ""

    # Section 1
    vm.conclusion_text, vm.key_findings = _build_conclusion_and_findings(claims, ledger)

    # Section 4.2
    vm.ser_text_lines = _build_ser_text(state)

    # Section 4.3
    vm.hyd_text = _build_hyd_text(ledger)

    # Section 4.4
    vm.frag_text_lines = _build_frag_text(state)

    # Consistency (must run before top_cases to get corrected_types)
    consistency_items, corrected_types = _build_consistency(state, vm.drilled_case_ids)
    vm.consistency_items = consistency_items

    # Section 3 & audit
    vm.top_cases, vm.audit_top_cases = _build_top_cases(state, cov, vm.drilled_case_ids, corrected_types)

    # Section 5
    vm.unresolved_items = _build_unresolved(claims, state, cov, vm.drilled_case_ids)

    # Section 6
    vm.next_steps = _build_next_steps(claims, state, cov, ledger)

    # Section 7 trace
    vm.trace_rows, vm.llm_call_rows = _build_trace(state)

    # Section 7.4 drilldown (sanitized)
    vm.drilldown_views = _build_drilldown_views(state)

    # Section 7 questions
    vm.question_views = _build_questions(state, ledger)

    # Planner audit
    pa = _build_planner_audit(state)
    vm.planner_type_label = pa["type_label"]
    vm.planner_description = pa["description"]
    vm.llm_call_count = pa["call_count"]
    vm.llm_success_count = pa["success_count"]
    vm.llm_fallback_count = pa["fallback_count"]
    vm.llm_model = pa["model"]

    # Cross-file patterns (sanitized)
    vm.cross_file_patterns_safe = [
        sanitize_findings(p) for p in (state.cross_file_patterns or [])
    ]

    return vm
