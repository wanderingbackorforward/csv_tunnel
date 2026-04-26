"""report_checker.py — 校验已生成的调查报告是否符合证据账本约束。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tbm_diag.investigation.evidence_ledger import (
    EvidenceLedger,
    validate_evidence_ledger,
)
from tbm_diag.investigation.claim_compiler import CompiledClaims


_FORBIDDEN_PATTERNS = [
    (r"(?<!已由外部日志)(?<!日志)确认计划停机", "确认计划停机（非外部日志声明）"),
    (r"确认为计划停机", "确认为计划停机"),
    (r"典型正常操作停顿", "典型正常操作停顿"),
    (r"主要原因为计划", "主要原因为计划"),
    (r"外部触发因素为主因", "外部触发因素为主因"),
    (r"未发现需关注异常", "未发现需关注异常"),
    (r"已排除\s*SER", "已排除 SER"),
    (r"已排除\s*HYD", "已排除 HYD"),
    (r"SER\s*无关", "SER 无关"),
    (r"HYD\s*无关", "HYD 无关"),
    (r"计划停机（疑似）", "计划停机（疑似）— 应为'性质待施工日志确认'"),
    (r"待确认停机", "待确认停机 — 应为'性质待施工日志确认'"),
]


@dataclass
class ReportCheckResult:
    passed: bool = False
    ledger_validation_passed: bool = False
    ledger_errors: list[str] = field(default_factory=list)
    forbidden_found: list[str] = field(default_factory=list)
    coverage_mismatch: str = ""
    p1_status_issue: str = ""
    generalization_issue: str = ""
    hyd_conclusion_issue: str = ""
    duplicate_stoppage_drilldown_count: int = 0
    duplicate_stoppage_drilldown_ids: list[str] = field(default_factory=list)
    completeness_info: dict = field(default_factory=dict)
    stale_ratio_issue: str = ""
    uncovered_claim_issue: str = ""
    first_screen_issue: str = ""
    terminology_issue: str = ""
    reason_target_mismatch: str = ""
    hyd_causal_language_issue: str = ""
    drilldown_detail_incomplete: str = ""
    details: list[str] = field(default_factory=list)


def validate_rendered_report(
    report_text: str,
    ledger: EvidenceLedger,
) -> ReportCheckResult:
    """校验已渲染的报告文本是否符合证据账本约束。"""
    result = ReportCheckResult()

    # 1. Ledger validation
    result.ledger_errors = validate_evidence_ledger(ledger)
    result.ledger_validation_passed = ledger.validation_passed
    if result.ledger_errors:
        result.details.append(f"Ledger 校验失败: {'; '.join(result.ledger_errors)}")
        result.passed = False
        return result

    result.details.append("Ledger 校验通过")

    # Only check business sections (1-6), skip section 7 (audit appendix)
    business_text = report_text.split("## 7.")[0] if "## 7." in report_text else report_text

    # 2. Forbidden patterns
    for pattern, label in _FORBIDDEN_PATTERNS:
        if re.search(pattern, business_text):
            result.forbidden_found.append(label)
    if result.forbidden_found:
        result.details.append(f"发现禁止措辞: {', '.join(result.forbidden_found)}")

    # 3. Coverage numbers match ledger
    total_match = re.search(r"停机案例总数[：:]\s*(\d+)", business_text)
    if total_match:
        report_total = int(total_match.group(1))
        if report_total != ledger.total_stoppage_cases:
            result.coverage_mismatch = (
                f"报告 total={report_total}, ledger total={ledger.total_stoppage_cases}"
            )
            result.details.append(result.coverage_mismatch)

    # 4. P1 status (check full report since plan table is in section 7)
    p1_done_match = re.search(r"\|\s*P1[^|]*\|[^|]*\|\s*已完成\s*\|", report_text)
    if p1_done_match and ledger.drilled_stoppage_cases < ledger.total_stoppage_cases:
        result.p1_status_issue = (
            f"P1 显示已完成但 coverage {ledger.drilled_stoppage_cases}/"
            f"{ledger.total_stoppage_cases} < 100%"
        )
        result.details.append(result.p1_status_issue)

    # 5. Generalization when coverage < 100%
    if ledger.drilled_stoppage_cases < ledger.total_stoppage_cases:
        gen_patterns = [r"本[日天]停机均", r"整体停机性质", r"所有停机[^(未]"]
        for pat in gen_patterns:
            m = re.search(pat, business_text)
            if m:
                result.generalization_issue = f"coverage < 100% 但报告泛化: '{m.group()}'"
                result.details.append(result.generalization_issue)
                break

    # 6. HYD 0.0h not used as business conclusion
    if ledger.hyd_status == "metric_warning":
        hyd_causal = re.search(r"(?<!不支持\s)HYD[^。，；]*?(?:是主因|导致停机|构成证据|已确认)", business_text)
        if hyd_causal:
            result.hyd_conclusion_issue = f"HYD metric_warning 被当成业务结论: '{hyd_causal.group()}'"
            result.details.append(result.hyd_conclusion_issue)

    # 7. Stale sample ratio check — ratio in report must match ledger
    full_coverage = (
        ledger.total_stoppage_cases > 0
        and ledger.actual_stoppage_coverage_count >= ledger.total_stoppage_cases
    )
    complete = ledger.completeness_status == "complete_for_depth"
    ratio_pattern = re.compile(r"(\d+)\s*/\s*(\d+)")
    for m in ratio_pattern.finditer(business_text):
        r_actual, r_total = int(m.group(1)), int(m.group(2))
        if r_total == ledger.total_stoppage_cases and r_actual != ledger.actual_stoppage_coverage_count:
            result.stale_ratio_issue = (
                f"报告含过时比例 {r_actual}/{r_total}，"
                f"ledger 实际为 {ledger.actual_stoppage_coverage_count}/{ledger.total_stoppage_cases}"
            )
            result.details.append(result.stale_ratio_issue)
            break

    # 8. No uncovered claim when complete
    if full_coverage and complete:
        uncovered_patterns = [
            (r"样本量仅", "样本量仅"),
            (r"样本量不足", "样本量不足"),
            (r"未覆盖案例", "未覆盖案例"),
            (r"未\s*drilldown\s*案例", "未 drilldown 案例"),
            (r"未逐案钻取的停机案例", "未逐案钻取的停机案例"),
            (r"增加调查轮数", "增加调查轮数"),
            (r"针对未覆盖案例", "针对未覆盖案例"),
            (r"\d+个[^\s]*案例能否代表全部\d+个", "X个案例能否代表全部Y个"),
        ]
        for pat, label in uncovered_patterns:
            if re.search(pat, business_text):
                result.uncovered_claim_issue = f"coverage 已达标但报告含: '{label}'"
                result.details.append(result.uncovered_claim_issue)
                break

    # 9. First screen business-first check (first 30 lines)
    first_screen_lines = report_text.split("\n")[:30]
    first_screen = "\n".join(first_screen_lines)
    tech_terms = [
        (r"\bplanner\b", "planner"),
        (r"LLM\s*成功率", "LLM 成功率"),
        (r"\bfallback\b", "fallback"),
        (r"\barg_resolver\b", "arg_resolver"),
        (r"\bJSON\b", "JSON"),
        (r"planner\s*audit", "planner audit"),
    ]
    # Check if conclusion appears before tech terms
    conclusion_line = None
    tech_line = None
    for i, line in enumerate(first_screen_lines):
        if conclusion_line is None and (
            "**结论：**" in line or "**结论:**" in line
            or "## 1. 一句话结论" in line or "## 1. 结论" in line
        ):
            conclusion_line = i
        if tech_line is None:
            for pat, label in tech_terms:
                if re.search(pat, line):
                    tech_line = i
                    break
    if tech_line is not None and (conclusion_line is None or tech_line < conclusion_line):
        result.first_screen_issue = (
            f"技术术语出现在业务结论之前（第 {tech_line + 1} 行）"
        )
        result.details.append(result.first_screen_issue)

    # 10. Terminology check (first 60 lines)
    first_60 = "\n".join(report_text.split("\n")[:60])
    dd_count = len(re.findall(r"\bdrilldown\b", first_60))
    if dd_count > 1:
        result.terminology_issue = f"前 60 行 drilldown 出现 {dd_count} 次（限 1 次）"
        result.details.append(result.terminology_issue)
    planner_in_60 = re.findall(r"\bplanner\b", first_60)
    if planner_in_60:
        result.terminology_issue += f"; 前 60 行含 planner ({len(planner_in_60)} 次)"
        result.details.append(result.terminology_issue)

    # 11. Reason target vs executed target mismatch (audit section only)
    audit_text = report_text.split("## 7.")[1] if "## 7." in report_text else ""
    trace_lines = [l for l in audit_text.split("\n") if l.startswith("|") and "drilldown_time_window" in l]
    for tl in trace_lines:
        # Extract mentioned SC_* from reason column (4th column)
        cols = [c.strip() for c in tl.split("|")]
        if len(cols) < 6:
            continue
        reason_col = cols[4] if len(cols) > 4 else ""
        action_col = cols[5] if len(cols) > 5 else ""
        obs_col = cols[6] if len(cols) > 6 else ""
        reason_targets = set(re.findall(r"\bSC_\d+\b", reason_col))
        # Only flag if reason mentions a specific target that differs from observation
        if reason_targets and "[已修正]" not in reason_col:
            obs_targets = set(re.findall(r"\bSC_\d+\b", obs_col))
            if obs_targets and reason_targets != obs_targets:
                mismatch_ids = reason_targets - obs_targets
                result.reason_target_mismatch = (
                    f"ReAct 轨迹中 reason 提到 {mismatch_ids} 但 observation 实际执行不同目标"
                )
                result.details.append(result.reason_target_mismatch)
                break

    # 12. HYD 0.0h causal language — anywhere in report
    # Only flag specific causal phrases that assert causation without qualification
    if ledger.hyd_status == "metric_warning":
        hyd_causal_patterns = [
            (r"启停伴随", "启停伴随"),
            (r"与\s*SER\s*同步(?!构成证据)", "与 SER 同步"),
            (r"靠近停机边界[，,]\s*(?:可能|可)?(?:是|为)(?:诱因|主因|原因)", "靠近停机边界+因果判断"),
        ]
        for pat, label in hyd_causal_patterns:
            m = re.search(pat, report_text)
            if m:
                result.hyd_causal_language_issue = (
                    f"HYD 0.0h (metric_warning) 出现因果判断: '{m.group()}'"
                )
                result.details.append(result.hyd_causal_language_issue)
                break

    # 13. Drilldown detail completeness
    if full_coverage and complete:
        detail_section = audit_text.split("### drilldown 明细")[1] if "### drilldown 明细" in audit_text else ""
        detail_targets = set(re.findall(r"\|\s*(SC_\d+)\s*\|", detail_section))
        if len(detail_targets) < ledger.total_stoppage_cases:
            result.drilldown_detail_incomplete = (
                f"报告声称 {ledger.actual_stoppage_coverage_count}/{ledger.total_stoppage_cases} 覆盖，"
                f"但 drilldown 明细表只有 {len(detail_targets)} 个目标"
            )
            result.details.append(result.drilldown_detail_incomplete)

    # Final pass/fail
    has_error = (
        bool(result.forbidden_found)
        or bool(result.coverage_mismatch)
        or bool(result.p1_status_issue)
        or bool(result.generalization_issue)
        or bool(result.hyd_conclusion_issue)
        or bool(result.stale_ratio_issue)
        or bool(result.uncovered_claim_issue)
        or bool(result.hyd_causal_language_issue)
    )
    result.passed = not has_error
    if result.passed:
        result.details.append("报告校验通过")
    return result


def run_report_check(investigation_dir: str | Path) -> ReportCheckResult:
    """从目录读取报告和 state，运行完整校验。"""
    inv_dir = Path(investigation_dir)
    report_path = inv_dir / "investigation_report.md"
    state_path = inv_dir / "investigation_state.json"

    if not report_path.exists():
        result = ReportCheckResult()
        result.details.append(f"报告文件不存在: {report_path}")
        return result
    if not state_path.exists():
        result = ReportCheckResult()
        result.details.append(f"state 文件不存在: {state_path}")
        return result

    report_text = report_path.read_text(encoding="utf-8")
    state_dict = json.loads(state_path.read_text(encoding="utf-8"))

    # Reconstruct ledger from state
    ledger_dict = state_dict.get("evidence_ledger")
    if not ledger_dict:
        # Build ledger from state if not stored
        from tbm_diag.investigation.evidence_ledger import build_evidence_ledger
        from tbm_diag.investigation.state import InvestigationState
        # Fallback: rebuild from observations stored in state
        result = ReportCheckResult()
        result.details.append("state.json 中无 evidence_ledger，跳过报告校验")
        result.passed = True
        return result

    ledger = EvidenceLedger(**{k: v for k, v in ledger_dict.items()
                               if k in EvidenceLedger.__dataclass_fields__})

    result = validate_rendered_report(report_text, ledger)

    # Add completeness info from ledger
    result.completeness_info = {
        "depth": ledger.investigation_depth,
        "total": ledger.total_stoppage_cases,
        "target": ledger.target_stoppage_coverage_count,
        "actual": ledger.actual_stoppage_coverage_count,
        "status": ledger.completeness_status,
        "message": ledger.completeness_reason,
    }

    # Add exhaustive SER info
    if ledger.ser_extra_required:
        result.completeness_info["ser_extra_required"] = True
        result.completeness_info["target_ser"] = ledger.target_ser_drilldown_count
        result.completeness_info["actual_ser"] = ledger.actual_ser_drilldown_count
        result.completeness_info["ser_status"] = ledger.ser_extra_completeness_status

    # Detect duplicate stoppage drilldowns from actions
    from collections import Counter
    sc_ids: list[str] = []
    for a_data in state_dict.get("actions_taken", []):
        args = a_data.get("arguments", {})
        if a_data.get("action") == "drilldown_time_window":
            tid = args.get("target_id", "")
            if tid.startswith("SC_"):
                sc_ids.append(tid)
        elif a_data.get("action") == "drilldown_time_windows_batch":
            for tid in args.get("target_ids", []):
                if isinstance(tid, str) and tid.startswith("SC_"):
                    sc_ids.append(tid)
    dups = {k: v for k, v in Counter(sc_ids).items() if v > 1}
    result.duplicate_stoppage_drilldown_count = sum(v - 1 for v in dups.values())
    result.duplicate_stoppage_drilldown_ids = sorted(dups.keys())
    if dups:
        result.details.append(
            f"重复 drilldown: {', '.join(f'{k}×{v}' for k, v in sorted(dups.items()))}"
        )

    return result
