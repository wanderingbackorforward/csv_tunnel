"""quality_gate.py — 调查报告质量门禁"""

from __future__ import annotations

from typing import Any

from tbm_diag.investigation.state import (
    InvestigationState, ReportQualityIssue, compute_drilldown_coverage,
)


def validate_report_quality(state: InvestigationState, planner_mode: str = "rule") -> None:
    """检查调查报告质量，结果写入 state.report_quality_status 和 state.report_quality_issues。"""
    issues: list[ReportQualityIssue] = []
    cov = compute_drilldown_coverage(state)

    # 1. LLM 质量
    if planner_mode in ("llm", "hybrid") and state.llm_success_count == 0 and state.llm_call_count > 0:
        issues.append(ReportQualityIssue(
            severity="critical",
            code="llm_planner_zero_success",
            message=f"LLM planner {state.llm_call_count} 次调用全部失败，所有决策由规则 fallback 完成",
        ))

    # 2. coverage 一致性
    es = state.executive_summary
    if es and cov["total_count"] > 0:
        expected_cov_text = f"drilldown 覆盖 {cov['covered_count']}/{cov['total_count']}"
        if es.coverage_summary and es.coverage_summary != expected_cov_text:
            if str(cov["covered_count"]) not in es.coverage_summary or str(cov["total_count"]) not in es.coverage_summary:
                issues.append(ReportQualityIssue(
                    severity="warning",
                    code="coverage_mismatch",
                    message=f"coverage 口径不一致: executive_summary='{es.coverage_summary}', "
                            f"实际 computed='{expected_cov_text}'",
                ))

    # 3. 停机计数一致性
    total_cases = cov["total_count"]
    if total_cases > 0:
        classified = state.case_classifications
        classified_total = sum(1 for _ in classified.values())
        if classified_total > total_cases:
            issues.append(ReportQualityIssue(
                severity="critical",
                code="classification_overflow",
                message=f"分类总数 {classified_total} 超过停机案例总数 {total_cases}",
            ))

    # 4. HYD 0.0h 检查
    for obs in state.observations:
        if obs.action == "analyze_hydraulic_pattern":
            data = obs.data or {}
            if data.get("hyd_total_duration_h", 0) == 0.0:
                issues.append(ReportQualityIssue(
                    severity="warning",
                    code="hyd_zero_duration",
                    message="HYD 事件时长统计为 0.0h，疑似显示精度或聚合口径问题",
                ))

    # 5. P1 completed 但 coverage < 100%
    plan = state.investigation_plan
    if plan:
        p1 = next((item for item in plan.plan_items if item.plan_id == "P1"), None)
        if p1 and p1.status == "completed" and cov["total_count"] > 0 and cov["covered_count"] < cov["total_count"]:
            issues.append(ReportQualityIssue(
                severity="warning",
                code="p1_completed_but_coverage_partial",
                message=f"P1 标记已完成但 drilldown 覆盖 {cov['covered_count']}/{cov['total_count']} < 100%",
            ))

    # 6. Evidence ledger validation (if available)
    if state.evidence_ledger:
        from tbm_diag.investigation.evidence_ledger import validate_evidence_ledger
        ledger_errors = validate_evidence_ledger(state.evidence_ledger)
        for err in ledger_errors:
            issues.append(ReportQualityIssue(
                severity="critical",
                code="ledger_validation_failed",
                message=f"证据账本校验失败: {err}",
            ))

    # 7. Claim compiler used
    if not state.compiled_claims:
        issues.append(ReportQualityIssue(
            severity="warning",
            code="claim_compiler_not_used",
            message="未使用 Claim Compiler 生成结论",
        ))

    # 判定质量状态
    has_critical = any(i.severity == "critical" for i in issues)
    has_warning = any(i.severity == "warning" for i in issues)

    if has_critical:
        state.report_quality_status = "failed"
    elif has_warning:
        state.report_quality_status = "warning"
    else:
        state.report_quality_status = "passed"

    state.report_quality_issues = issues
