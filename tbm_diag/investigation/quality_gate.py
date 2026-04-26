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

    # 2. coverage 一致性 — 检查 executive_summary 中的 coverage 和实际 state 一致
    es = state.executive_summary
    if es and cov["total_count"] > 0:
        # 覆盖率文本应该与实际 computed coverage 一致
        expected_cov_text = f"drilldown 覆盖 {cov['covered_count']}/{cov['total_count']}"
        if es.coverage_summary and es.coverage_summary != expected_cov_text:
            # 检查数字是否一致
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
        abnormal_count = sum(1 for cls in classified.values() if cls.case_type == "abnormal_like_stoppage")
        planned_count = sum(1 for cls in classified.values() if cls.case_type == "planned_like_stoppage")
        unverified_count = sum(1 for cls in classified.values() if cls.case_type == "event_level_abnormal_unverified")
        uncertain_count = sum(1 for cls in classified.values() if cls.case_type == "uncertain_stoppage")
        short_pause_count = sum(1 for cls in classified.values() if cls.case_type == "short_operational_pause")
        classified_total = abnormal_count + planned_count + unverified_count + uncertain_count + short_pause_count
        # 每个案例只能有一个分类，分类总数不应超过 total_cases
        if classified_total > total_cases:
            issues.append(ReportQualityIssue(
                severity="critical",
                code="classification_overflow",
                message=f"分类总数 {classified_total} (abnormal={abnormal_count}+planned={planned_count}"
                        f"+unverified={unverified_count}+uncertain={uncertain_count}"
                        f"+short_pause={short_pause_count}) "
                        f"超过停机案例总数 {total_cases}，存在重叠口径未说明",
            ))

    # 4. HYD 0.0h 检查
    for obs in state.observations:
        if obs.action == "analyze_hydraulic_pattern":
            data = obs.data or {}
            hyd_duration = data.get("hyd_total_duration_h", 0)
            if hyd_duration == 0.0:
                issues.append(ReportQualityIssue(
                    severity="warning",
                    code="hyd_zero_duration",
                    message="HYD 事件时长统计为 0.0h，疑似显示精度或聚合口径问题，不允许作为强业务结论依据",
                ))

    # 5. batch drilldown 声明一致性
    has_batch_claim = any(
        obs.action == "drilldown_time_windows_batch"
        for obs in state.observations
    )
    if has_batch_claim:
        batch_success = any(
            obs.action == "drilldown_time_windows_batch"
            and obs.data.get("status") != "error"
            for obs in state.observations
        )
        if not batch_success:
            issues.append(ReportQualityIssue(
                severity="critical",
                code="batch_drilldown_claim_without_result",
                message="报告声称使用了 drilldown_time_windows_batch，但无成功执行记录",
            ))

    # 6. P1 completed 但无 SC drilldown
    plan = state.investigation_plan
    if plan:
        p1 = next((item for item in plan.plan_items if item.plan_id == "P1"), None)
        if p1 and p1.status == "completed" and cov["covered_count"] == 0 and cov["total_count"] > 0:
            issues.append(ReportQualityIssue(
                severity="critical",
                code="p1_completed_without_drilldown",
                message="P1 标记为已完成，但没有任何 SC drilldown 覆盖",
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
