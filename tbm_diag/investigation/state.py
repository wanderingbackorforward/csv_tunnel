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
