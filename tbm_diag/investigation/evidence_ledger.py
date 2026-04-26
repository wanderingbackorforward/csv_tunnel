"""evidence_ledger.py — 结构化证据账本，从 ReAct 调查状态提取事实。

ReAct 负责调查取证，Evidence Ledger 负责记录结构化事实。
Ledger 不做推断，只记录观察结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tbm_diag.investigation.state import (
    InvestigationState,
    compute_drilldown_coverage,
)


@dataclass
class EvidenceLedger:
    # ── A. CSV / drilldown 观察状态 ──
    total_stoppage_cases: int = 0
    drilled_stoppage_cases: int = 0
    undrilled_stoppage_cases: int = 0
    drilled_case_ids: list[str] = field(default_factory=list)
    undrilled_case_ids: list[str] = field(default_factory=list)
    drilled_cases_no_pre_ser_hyd: int = 0
    drilled_cases_with_pre_ser_or_hyd: int = 0
    drilled_cases_inconclusive: int = 0
    drilled_cases_recovered_after: int = 0

    # ── B. 停机性质状态 ──
    confirmed_planned_by_external_log: int = 0
    confirmed_abnormal_by_external_log: int = 0
    nature_unknown_count: int = 0
    external_log_available: bool = False

    # ── SER ──
    ser_event_count: int = 0
    ser_duration_hours: float = 0.0
    ser_drilldown_completed: bool = False
    ser_causality_status: str = "insufficient_evidence"

    # ── HYD ──
    hyd_event_count: int = 0
    hyd_duration_hours: float = 0.0
    hyd_status: str = "insufficient_evidence"

    # ── 校验结果 ──
    validation_errors: list[str] = field(default_factory=list)
    validation_passed: bool = False

    # ── D. 调查充分性 ──
    investigation_depth: str = "standard"
    target_stoppage_coverage_count: int = 0
    actual_stoppage_coverage_count: int = 0
    completeness_status: str = ""
    completeness_reason: str = ""

    # ── E. Exhaustive SER extra ──
    ser_extra_required: bool = False
    target_ser_drilldown_count: int = 0
    actual_ser_drilldown_count: int = 0
    ser_drilldown_ids: list[str] = field(default_factory=list)
    ser_extra_completeness_status: str = ""  # complete / incomplete / not_applicable_no_ser


def build_evidence_ledger(state: InvestigationState) -> EvidenceLedger:
    """从调查状态构建证据账本。只记录事实，不做推断。"""
    ledger = EvidenceLedger()
    cov = compute_drilldown_coverage(state)

    # ── A. Stoppage basics ──
    ledger.total_stoppage_cases = cov["total_count"]
    ledger.drilled_stoppage_cases = cov["covered_count"]
    ledger.undrilled_stoppage_cases = len(cov["uncovered_case_ids"])
    ledger.drilled_case_ids = sorted(cov["covered_case_ids"])
    ledger.undrilled_case_ids = sorted(cov["uncovered_case_ids"])

    # Count drilldown outcomes — only for stoppage case IDs
    stoppage_id_set = set(cov["covered_case_ids"])
    no_pre_ids: set[str] = set()
    recovered_ids: set[str] = set()

    for obs in state.observations:
        if obs.action == "drilldown_time_window":
            tid = obs.data.get("target_id", "")
            if not tid or obs.data.get("status") == "error":
                continue
            if tid not in stoppage_id_set:
                continue
            hint = obs.data.get("interpretation_hint", "")
            if "停机前未见明显异常" in hint:
                no_pre_ids.add(tid)
            if "停机后恢复正常" in hint:
                recovered_ids.add(tid)
        elif obs.action == "drilldown_time_windows_batch":
            if obs.data.get("status") == "error":
                continue
            for pt in obs.data.get("per_target", []):
                tid = pt.get("target_id", "")
                if not tid or pt.get("status") == "error":
                    continue
                if tid not in stoppage_id_set:
                    continue
                hint = pt.get("interpretation_hint", "")
                if "停机前未见明显异常" in hint:
                    no_pre_ids.add(tid)
                if "停机后恢复正常" in hint:
                    recovered_ids.add(tid)

    ledger.drilled_cases_no_pre_ser_hyd = len(no_pre_ids)
    ledger.drilled_cases_recovered_after = len(recovered_ids)

    # Cases with pre-stoppage anomalies (from classifications, drilled only)
    for cid, cls in state.case_classifications.items():
        if cls.case_type == "abnormal_like_stoppage" and cid in cov["covered_case_ids"]:
            ledger.drilled_cases_with_pre_ser_or_hyd += 1

    ledger.drilled_cases_inconclusive = max(
        0,
        ledger.drilled_stoppage_cases
        - ledger.drilled_cases_no_pre_ser_hyd
        - ledger.drilled_cases_with_pre_ser_or_hyd,
    )

    # ── B. Nature — no external logs ever available from CSV ──
    ledger.external_log_available = False
    ledger.confirmed_planned_by_external_log = 0
    ledger.confirmed_abnormal_by_external_log = 0
    ledger.nature_unknown_count = ledger.total_stoppage_cases

    # ── SER ──
    for obs in state.observations:
        if obs.action == "analyze_resistance_pattern":
            data = obs.data or {}
            ledger.ser_event_count = data.get("ser_count", 0)
            ledger.ser_duration_hours = data.get("ser_total_duration_h", 0.0)
            ledger.ser_drilldown_completed = True
            ledger.ser_causality_status = "not_proven"

    # ── HYD ──
    for obs in state.observations:
        if obs.action == "analyze_hydraulic_pattern":
            data = obs.data or {}
            ledger.hyd_event_count = data.get("hyd_count", 0)
            ledger.hyd_duration_hours = data.get("hyd_total_duration_h", 0.0)
            if ledger.hyd_duration_hours == 0.0 and ledger.hyd_event_count > 0:
                ledger.hyd_status = "metric_warning"
            else:
                ledger.hyd_status = "insufficient_evidence"

    # ── D. Completeness ──
    from tbm_diag.investigation.investigation_depth import (
        compute_stoppage_coverage_target,
        compute_completeness_status,
    )
    depth = getattr(state, "investigation_depth", "standard") or "standard"
    ledger.investigation_depth = depth
    ledger.actual_stoppage_coverage_count = ledger.drilled_stoppage_cases
    cov_target = compute_stoppage_coverage_target(ledger.total_stoppage_cases, depth)
    ledger.target_stoppage_coverage_count = cov_target.target_count
    comp_status, comp_msg = compute_completeness_status(
        ledger.actual_stoppage_coverage_count, cov_target, remaining_rounds=0,
    )
    ledger.completeness_status = comp_status
    ledger.completeness_reason = comp_msg

    # ── E. Exhaustive SER extra ──
    if depth == "exhaustive":
        ledger.ser_extra_required = True
        ser_target_count = min(3, ledger.ser_event_count) if ledger.ser_event_count > 0 else 0
        ledger.target_ser_drilldown_count = ser_target_count
        # Count actual SER drilldowns from observations
        ser_drilled: list[str] = []
        for obs in state.observations:
            if obs.action == "drilldown_time_window":
                tid = obs.data.get("target_id", "")
                if tid.startswith("SER_") and obs.data.get("status") != "error":
                    ser_drilled.append(tid)
        ser_drilled_unique = sorted(set(ser_drilled))
        ledger.actual_ser_drilldown_count = len(ser_drilled_unique)
        ledger.ser_drilldown_ids = ser_drilled_unique
        if ser_target_count == 0:
            ledger.ser_extra_completeness_status = "not_applicable_no_ser"
        elif len(ser_drilled_unique) >= ser_target_count:
            ledger.ser_extra_completeness_status = "complete"
        else:
            ledger.ser_extra_completeness_status = "incomplete"
        # Downgrade completeness if SER incomplete
        if ledger.ser_extra_completeness_status == "incomplete":
            if ledger.completeness_status == "complete_for_depth":
                ledger.completeness_status = "incomplete_due_to_budget"
                ledger.completeness_reason = (
                    f"停机 coverage 已完成，但 SER extra 未完成 "
                    f"({len(ser_drilled_unique)}/{ser_target_count})"
                )

    return ledger


def validate_evidence_ledger(ledger: EvidenceLedger) -> list[str]:
    """校验证据账本内部一致性。返回错误列表，空则通过。"""
    errors: list[str] = []

    # 1. total = drilled + undrilled
    if ledger.total_stoppage_cases != ledger.drilled_stoppage_cases + ledger.undrilled_stoppage_cases:
        errors.append(
            f"total({ledger.total_stoppage_cases}) != "
            f"drilled({ledger.drilled_stoppage_cases}) + "
            f"undrilled({ledger.undrilled_stoppage_cases})"
        )

    # 2. drilled count matches IDs
    if ledger.drilled_stoppage_cases != len(ledger.drilled_case_ids):
        errors.append(
            f"drilled_stoppage_cases({ledger.drilled_stoppage_cases}) != "
            f"len(drilled_case_ids)({len(ledger.drilled_case_ids)})"
        )

    # 3. undrilled count matches IDs
    if ledger.undrilled_stoppage_cases != len(ledger.undrilled_case_ids):
        errors.append(
            f"undrilled_stoppage_cases({ledger.undrilled_stoppage_cases}) != "
            f"len(undrilled_case_ids)({len(ledger.undrilled_case_ids)})"
        )

    # 4. drilled sub-categories sum <= drilled total
    drilled_sub = (
        ledger.drilled_cases_no_pre_ser_hyd
        + ledger.drilled_cases_with_pre_ser_or_hyd
        + ledger.drilled_cases_inconclusive
    )
    if drilled_sub > ledger.drilled_stoppage_cases:
        errors.append(
            f"drilled sub-categories sum({drilled_sub}) > "
            f"drilled_stoppage_cases({ledger.drilled_stoppage_cases})"
        )

    # 5. No external log → confirmed counts must be 0, unknown = total
    if not ledger.external_log_available:
        if ledger.confirmed_planned_by_external_log != 0:
            errors.append(
                f"confirmed_planned_by_external_log({ledger.confirmed_planned_by_external_log}) "
                f"must be 0 when external_log_available=false"
            )
        if ledger.confirmed_abnormal_by_external_log != 0:
            errors.append(
                f"confirmed_abnormal_by_external_log({ledger.confirmed_abnormal_by_external_log}) "
                f"must be 0 when external_log_available=false"
            )
        if ledger.nature_unknown_count != ledger.total_stoppage_cases:
            errors.append(
                f"nature_unknown_count({ledger.nature_unknown_count}) != "
                f"total_stoppage_cases({ledger.total_stoppage_cases}) "
                f"when external_log_available=false"
            )

    # 6. HYD 0.0h with events → must be metric_warning
    if ledger.hyd_duration_hours == 0.0 and ledger.hyd_event_count > 0:
        if ledger.hyd_status != "metric_warning":
            errors.append(
                f"hyd_status must be metric_warning when duration=0.0, got {ledger.hyd_status}"
            )

    # 7. SER not drilled → cannot be proven
    if not ledger.ser_drilldown_completed and ledger.ser_causality_status == "proven":
        errors.append("ser_causality_status cannot be proven when ser_drilldown_completed=false")

    # 8. Completeness consistency
    if ledger.completeness_status == "complete_for_depth":
        if ledger.actual_stoppage_coverage_count < ledger.target_stoppage_coverage_count:
            errors.append(
                f"completeness_status=complete_for_depth but actual("
                f"{ledger.actual_stoppage_coverage_count}) < target({ledger.target_stoppage_coverage_count})"
            )

    ledger.validation_errors = errors
    ledger.validation_passed = len(errors) == 0
    return errors
