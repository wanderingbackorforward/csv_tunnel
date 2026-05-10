"""State and trace objects for the closed-loop diagnosis environment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Observation:
    """Structured result returned by an environment action."""

    status: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceRecord:
    """One reason-act-observe transition."""

    round_num: int
    action: str
    arguments: dict[str, Any]
    observation_status: str
    observation_summary: str
    evidence_keys_after: list[str]
    max_claim_level_after: str = ""
    stop_after: bool = False


@dataclass
class EnvironmentState:
    """Current state of the constrained ReAct environment."""

    input_file: str
    profile_id: str
    policy_type: str = "rule"
    round_num: int = 0

    evidence_keys: set[str] = field(default_factory=set)
    fields_present: set[str] = field(default_factory=set)
    unrecognized_fields: list[str] = field(default_factory=list)
    suspicious_unit_fields: list[str] = field(default_factory=list)

    schema_inspected: bool = False
    detection_done: bool = False
    risk_mapped: bool = False
    claim_checked: bool = False
    gaps_identified: bool = False
    finalized: bool = False

    row_count: int = 0
    event_count: int = 0
    event_type_counts: dict[str, int] = field(default_factory=dict)
    semantic_type_counts: dict[str, int] = field(default_factory=dict)
    skipped_rules: dict[str, list[str]] = field(default_factory=dict)
    top_events: list[dict[str, Any]] = field(default_factory=list)

    risk_candidates: list[dict[str, Any]] = field(default_factory=list)
    evidence_gaps: list[dict[str, Any]] = field(default_factory=list)
    supported_claim_levels: list[str] = field(default_factory=list)
    max_claim_level: str = ""
    verifier_blockers: list[str] = field(default_factory=list)
    stop_reason: str = ""
    final_summary: str = ""

    trace: list[TraceRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_file": self.input_file,
            "profile_id": self.profile_id,
            "policy_type": self.policy_type,
            "round_num": self.round_num,
            "evidence_keys": sorted(self.evidence_keys),
            "fields_present": sorted(self.fields_present),
            "unrecognized_fields": self.unrecognized_fields,
            "suspicious_unit_fields": self.suspicious_unit_fields,
            "schema_inspected": self.schema_inspected,
            "detection_done": self.detection_done,
            "risk_mapped": self.risk_mapped,
            "claim_checked": self.claim_checked,
            "gaps_identified": self.gaps_identified,
            "finalized": self.finalized,
            "row_count": self.row_count,
            "event_count": self.event_count,
            "event_type_counts": self.event_type_counts,
            "semantic_type_counts": self.semantic_type_counts,
            "skipped_rules": self.skipped_rules,
            "top_events": self.top_events,
            "risk_candidates": self.risk_candidates,
            "evidence_gaps": self.evidence_gaps,
            "supported_claim_levels": self.supported_claim_levels,
            "max_claim_level": self.max_claim_level,
            "verifier_blockers": self.verifier_blockers,
            "stop_reason": self.stop_reason,
            "final_summary": self.final_summary,
            "trace": [
                {
                    "round_num": item.round_num,
                    "action": item.action,
                    "arguments": item.arguments,
                    "observation_status": item.observation_status,
                    "observation_summary": item.observation_summary,
                    "evidence_keys_after": item.evidence_keys_after,
                    "max_claim_level_after": item.max_claim_level_after,
                    "stop_after": item.stop_after,
                }
                for item in self.trace
            ],
        }
