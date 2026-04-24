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
