"""state.py — Investigation 状态数据结构"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FileOverview:
    file_path: str = ""
    total_rows: int = 0
    time_start: str = ""
    time_end: str = ""
    state_distribution: dict[str, float] = field(default_factory=dict)
    event_count: int = 0
    semantic_event_distribution: dict[str, int] = field(default_factory=dict)


@dataclass
class EventSummary:
    file_path: str = ""
    event_count: int = 0
    event_type_distribution: dict[str, int] = field(default_factory=dict)
    semantic_event_distribution: dict[str, int] = field(default_factory=dict)
    top_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StoppageCase:
    case_id: str = ""
    file_path: str = ""
    start_time: str = ""
    end_time: str = ""
    duration_seconds: float = 0.0
    merged_event_count: int = 0
    merged_event_ids: list[str] = field(default_factory=list)


@dataclass
class TransitionAnalysis:
    case_id: str = ""
    pre_events: list[dict[str, Any]] = field(default_factory=list)
    post_events: list[dict[str, Any]] = field(default_factory=list)
    pre_has_ser: bool = False
    pre_has_hyd: bool = False
    pre_has_heavy_load: bool = False
    post_has_anomaly: bool = False
    pre_state_distribution: dict[str, float] = field(default_factory=dict)
    post_state_distribution: dict[str, float] = field(default_factory=dict)


@dataclass
class CaseClassification:
    case_id: str = ""
    case_type: str = "uncertain_stoppage"
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class EvidenceGateOverride:
    round_num: int = 0
    llm_selected_action: str = ""
    final_selected_action: str = ""
    override_reason: str = ""
    target_id: str = ""


@dataclass
class OpenQuestion:
    qid: str = ""
    text: str = ""
    priority: str = "medium"  # high / medium / low
    status: str = "unanswered"  # unanswered / partially_answered / answered / blocked_by_missing_data
    relevant_tools: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    needs_manual_check: bool = False
    reason_if_unanswered: str = ""


@dataclass
class PlanItem:
    plan_id: str = ""
    question: str = ""
    priority: str = "high"  # high / medium / low
    required_tools: list[str] = field(default_factory=list)
    target_ids: list[str] = field(default_factory=list)
    status: str = "pending"  # pending / in_progress / completed / skipped_due_to_budget
    estimated_rounds: int = 1


@dataclass
class InvestigationPlan:
    plan_items: list[PlanItem] = field(default_factory=list)
    estimated_required_rounds: int = 0
    recommended_max_iterations: int = 20
    budget_warning: str = ""


@dataclass
class ActionRecord:
    round_num: int = 0
    action: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    observation_summary: str = ""
    planner_type: str = "rule"  # rule / llm / hybrid_rule / hybrid_llm
    llm_called: bool = False
    llm_status: str = ""  # success / no_key / api_error / timeout / parse_error / skipped
    fallback_used: bool = False
    evidence_gate_override: bool = False
    evidence_gate_original_action: str = ""
    evidence_gate_reason: str = ""


@dataclass
class Observation:
    round_num: int = 0
    action: str = ""
    result_summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Hypothesis:
    text: str = ""
    confidence: float = 0.0
    supporting_evidence: list[str] = field(default_factory=list)


@dataclass
class LlmCallRecord:
    round_num: int = 0
    model: str = ""
    base_url_host: str = ""
    status: str = ""  # success / no_key / no_sdk / api_error / timeout / parse_error / skipped
    selected_action: str = ""
    selected_reason: str = ""
    thought_summary: str = ""
    raw_preview: str = ""
    error_message: str = ""
    latency_seconds: float = 0.0
    parse_strategy: str = ""
    cleaned_preview: str = ""


@dataclass
class PlannerAuditRecord:
    round_num: int = 0
    current_file: str = ""
    current_observation_summary: str = ""
    open_questions: list[str] = field(default_factory=list)
    candidate_actions: list[str] = field(default_factory=list)
    candidate_reasons: list[str] = field(default_factory=list)
    rejected_actions: list[str] = field(default_factory=list)
    rejected_reasons: list[str] = field(default_factory=list)
    selected_action: str = ""
    selected_reason: str = ""
    is_rule_based: bool = True
    state_snapshot: dict[str, Any] = field(default_factory=dict)
    triggered_by_field: str = ""
    observation_used: str = ""


@dataclass
class PlannerParseResult:
    status: str = ""  # success / empty_content / tool_call_found / json_not_found / json_invalid / schema_invalid
    parsed: Optional[dict[str, Any]] = None
    raw_content: str = ""
    cleaned_content: str = ""
    raw_preview: str = ""
    error_message: str = ""
    parse_strategy: str = ""  # tool_call / direct_json / code_fence / balanced_scan


@dataclass
class ReportQualityIssue:
    severity: str = ""  # critical / warning / info
    code: str = ""
    message: str = ""


@dataclass
class ExecutiveSummary:
    status_label_zh: str = ""
    confidence_label_zh: str = ""
    one_sentence_conclusion: str = ""
    main_problem_type: str = ""
    key_findings: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)
    next_manual_checks: list[str] = field(default_factory=list)
    coverage_summary: str = ""
    recommendation_for_user: str = ""
    run_status: str = ""  # success / partial / failed_degraded
    actual_planner_label: str = ""  # LLM planner / LLM planner 不稳定 / rule fallback / rule planner
    llm_success_ratio_text: str = ""  # "3/10"
    report_quality_status: str = ""  # passed / warning / failed


@dataclass
class FinalConclusion:
    convergence_status: str = "not_converged"  # converged / partially_converged / not_converged
    stop_reason: str = ""
    primary_conclusion_zh: str = ""
    secondary_findings_zh: list[str] = field(default_factory=list)
    ruled_out_zh: list[str] = field(default_factory=list)
    unresolved_questions_zh: list[str] = field(default_factory=list)
    confidence_label: str = "low"  # high / medium / low
    confidence_reason_zh: str = ""
    next_manual_checks: list[str] = field(default_factory=list)
    finalizer_type: str = "rule"  # rule / llm / fallback
    finalizer_llm_status: str = ""
    finalizer_model: str = ""
    finalizer_error_message: str = ""
    # validation fields
    validator_applied: bool = False
    validation_warnings: list[str] = field(default_factory=list)
    downgraded_fields: list[str] = field(default_factory=list)
    original_convergence_status: str = ""
    original_confidence_label: str = ""


@dataclass
class InvestigationState:
    task_id: str = ""
    mode: str = "single_file"
    input_files: list[str] = field(default_factory=list)
    current_file: str = ""
    file_overviews: dict[str, FileOverview] = field(default_factory=dict)
    event_summaries: dict[str, EventSummary] = field(default_factory=dict)
    stoppage_cases: dict[str, list[StoppageCase]] = field(default_factory=dict)
    transition_analyses: dict[str, TransitionAnalysis] = field(default_factory=dict)
    case_classifications: dict[str, CaseClassification] = field(default_factory=dict)
    cross_file_patterns: list[str] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    actions_taken: list[ActionRecord] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    iteration_count: int = 0
    stop_reason: str = ""
    audit_log: list[PlannerAuditRecord] = field(default_factory=list)
    focus: str = "auto"  # auto / stoppage / resistance / hydraulic / fragmentation
    planner_type: str = "rule"  # rule / llm / hybrid
    llm_call_count: int = 0
    llm_success_count: int = 0
    llm_fallback_count: int = 0
    llm_model: str = ""
    llm_calls: list[LlmCallRecord] = field(default_factory=list)
    final_conclusion: Optional[FinalConclusion] = None
    evidence_gate_overrides: list[EvidenceGateOverride] = field(default_factory=list)
    investigation_questions: list[OpenQuestion] = field(default_factory=list)
    investigation_plan: Optional[InvestigationPlan] = None
    executive_summary: Optional[ExecutiveSummary] = None
    planner_runtime_status: str = ""  # "" / llm_ok / llm_unstable / llm_unavailable
    report_quality_status: str = ""  # passed / warning / failed
    report_quality_issues: list[ReportQualityIssue] = field(default_factory=list)


def compute_drilldown_coverage(state: InvestigationState) -> dict[str, Any]:
    """统一计算 SC drilldown 覆盖率（含单次和批量）。"""
    single_ids: set[str] = set()
    batch_ids: set[str] = set()

    for obs in state.observations:
        if obs.action == "drilldown_time_window":
            tid = obs.data.get("target_id", "")
            if tid.startswith("SC_") and obs.data.get("status") != "error":
                single_ids.add(tid)
        elif obs.action == "drilldown_time_windows_batch":
            if obs.data.get("status") == "error":
                continue
            for pt in obs.data.get("per_target", []):
                tid = pt.get("target_id", "")
                if tid.startswith("SC_") and pt.get("status") != "error":
                    batch_ids.add(tid)

    covered = single_ids | batch_ids
    all_case_ids: list[str] = []
    for cases in state.stoppage_cases.values():
        for c in cases:
            all_case_ids.append(c.case_id)
    total = len(all_case_ids)
    uncovered = sorted(set(all_case_ids) - covered)

    return {
        "total_count": total,
        "covered_count": len(covered),
        "coverage_ratio": len(covered) / total if total > 0 else 0,
        "covered_case_ids": sorted(covered),
        "uncovered_case_ids": uncovered,
        "single_drilldown_case_ids": sorted(single_ids),
        "batch_drilldown_case_ids": sorted(batch_ids),
    }
