"""Verifier for the closed-loop diagnosis environment."""

from __future__ import annotations

from dataclasses import dataclass

from tbm_diag.domain.models import ProjectProfile
from tbm_diag.react_env.state import EnvironmentState


@dataclass(frozen=True)
class VerificationResult:
    supported_levels: list[str]
    max_level: str
    blockers: list[str]
    can_finalize: bool
    stop_reason: str


def verify_state(state: EnvironmentState, profile: ProjectProfile) -> VerificationResult:
    """Evaluate what the current state is allowed to claim."""

    supported: list[str] = []
    for level in profile.claim_policy.claim_levels:
        required = set(level.required_evidence)
        if not required.issubset(state.evidence_keys):
            continue
        if level.level_id == "L2_project_risk_candidate" and not state.risk_candidates:
            continue
        supported.append(level.level_id)

    max_level = supported[-1] if supported else ""
    blockers: list[str] = []

    if state.detection_done and not state.event_count:
        blockers.append("CSV 未形成可分段异常事件；当前只能报告数据检查和未见明显事件。")
    if state.risk_candidates and "site_operation_log" not in state.evidence_keys:
        blockers.append("缺少施工/操作日志，不能确认计划停机、维修停机或现场处置事实。")
    if state.risk_candidates and "monitoring_report_or_alarm" not in state.evidence_keys:
        blockers.append("缺少监测日报/报警记录，不能确认沉降、隆起、报警处置或外部环境影响。")

    external_keys = {"site_operation_log", "monitoring_report_or_alarm"}
    if state.risk_candidates and not external_keys.intersection(state.evidence_keys):
        stop_reason = "已达到当前 CSV + project profile 可支持的最高等级；继续提升需要外部现场记录。"
        can_finalize = state.gaps_identified
    elif state.detection_done and not state.event_count:
        stop_reason = "未发现可分段异常事件，环境可终止。"
        can_finalize = state.gaps_identified
    else:
        stop_reason = ""
        can_finalize = state.gaps_identified

    return VerificationResult(
        supported_levels=supported,
        max_level=max_level,
        blockers=blockers,
        can_finalize=can_finalize,
        stop_reason=stop_reason,
    )
