"""report_checker.py — 校验已生成的调查报告是否符合证据账本约束。

扫描全文（包括技术附录），确保：
1. 无禁止措辞
2. HYD 口径一致
3. 已钻取案例不出现 "未运行 drilldown 验证"
4. 无 unsafe reason 文案
5. 全覆盖时不出现"未覆盖/未逐案检查"
"""

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

_UNSAFE_REASON_PATTERNS = [
    (r"电阻\s*/\s*SER", "电阻/SER"),
    (r"SER[^，。；]*?触发停机[^，。；]*?机制", "SER触发停机机制"),
    (r"SER是主因", "SER是主因"),
    (r"找出触发机制", "找出触发机制"),
    (r"揭示停机主因", "揭示停机主因"),
    (r"(\d+)个案例有掘进阻力异常", "N个案例有掘进阻力异常"),
]

_HYD_CAUSAL_PATTERNS = [
    (r"启停伴随", "启停伴随"),
    (r"与\s*SER\s*同步(?!构成证据)", "与 SER 同步"),
    (r"靠近停机边界[，,]\s*(?:可能|可)?(?:是|为)(?:诱因|主因|原因)", "靠近停机边界+因果判断"),
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
    hyd_unanswered_conflict: str = ""
    drilled_case_stale_issue: str = ""
    unsafe_reason_text_issue: str = ""
    hyd_zero_duration_issue: str = ""
    complete_coverage_no_uncovered_issue: str = ""
    details: list[str] = field(default_factory=list)


def validate_rendered_report(
    report_text: str,
    ledger: EvidenceLedger,
) -> ReportCheckResult:
    """校验已渲染的报告文本是否符合证据账本约束。扫描全文。"""
    result = ReportCheckResult()

    # 1. Ledger validation
    result.ledger_errors = validate_evidence_ledger(ledger)
    result.ledger_validation_passed = ledger.validation_passed
    if result.ledger_errors:
        result.details.append(f"Ledger 校验失败: {'; '.join(result.ledger_errors)}")
        result.passed = False
        return result
    result.details.append("Ledger 校验通过")

    full_text = report_text
    business_text = full_text.split("## 7.")[0] if "## 7." in full_text else full_text

    # 2. Forbidden patterns (full text)
    for pattern, label in _FORBIDDEN_PATTERNS:
        if re.search(pattern, full_text):
            result.forbidden_found.append(label)
    if result.forbidden_found:
        result.details.append(f"发现禁止措辞: {', '.join(result.forbidden_found)}")

    # 3. Coverage numbers match ledger (business sections)
    total_match = re.search(r"停机案例总数[：:]\s*(\d+)", business_text)
    if total_match:
        report_total = int(total_match.group(1))
        if report_total != ledger.total_stoppage_cases:
            result.coverage_mismatch = (
                f"报告 total={report_total}, ledger total={ledger.total_stoppage_cases}"
            )
            result.details.append(result.coverage_mismatch)

    # 4. P1 status
    p1_done_match = re.search(r"\|\s*P1[^|]*\|[^|]*\|\s*已完成\s*\|", full_text)
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

    # 7. Stale sample ratio
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

    # 8. No uncovered claim when complete (business sections)
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

    # 9. First screen business-first check
    first_screen_lines = full_text.split("\n")[:30]
    first_screen = "\n".join(first_screen_lines)
    tech_terms = [
        (r"\bplanner\b", "planner"),
        (r"LLM\s*成功率", "LLM 成功率"),
        (r"\bfallback\b", "fallback"),
        (r"\barg_resolver\b", "arg_resolver"),
        (r"\bJSON\b", "JSON"),
        (r"planner\s*audit", "planner audit"),
    ]
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
        result.first_screen_issue = f"技术术语出现在业务结论之前（第 {tech_line + 1} 行）"
        result.details.append(result.first_screen_issue)

    # 10. Terminology check (first 60 lines)
    first_60 = "\n".join(full_text.split("\n")[:60])
    dd_count = len(re.findall(r"\bdrilldown\b", first_60))
    if dd_count > 1:
        result.terminology_issue = f"前 60 行 drilldown 出现 {dd_count} 次（限 1 次）"
        result.details.append(result.terminology_issue)
    planner_in_60 = re.findall(r"\bplanner\b", first_60)
    if planner_in_60:
        result.terminology_issue += f"; 前 60 行含 planner ({len(planner_in_60)} 次)"
        result.details.append(result.terminology_issue)

    # 11. Reason target vs executed target mismatch (audit section)
    audit_text = full_text.split("## 7.")[1] if "## 7." in full_text else ""
    trace_lines = [l for l in audit_text.split("\n") if l.startswith("|") and "drilldown_time_window" in l]
    for tl in trace_lines:
        cols = [c.strip() for c in tl.split("|")]
        if len(cols) < 6:
            continue
        reason_col = cols[4] if len(cols) > 4 else ""
        obs_col = cols[6] if len(cols) > 6 else ""
        reason_targets = set(re.findall(r"\bSC_\d+\b", reason_col))
        if reason_targets and "[已修正]" not in reason_col:
            obs_targets = set(re.findall(r"\bSC_\d+\b", obs_col))
            if obs_targets and reason_targets != obs_targets:
                mismatch_ids = reason_targets - obs_targets
                result.reason_target_mismatch = (
                    f"ReAct 轨迹中 reason 提到 {mismatch_ids} 但 observation 实际执行不同目标"
                )
                result.details.append(result.reason_target_mismatch)
                break

    # 12. HYD causal language (full text)
    if ledger.hyd_status == "metric_warning":
        for pat, label in _HYD_CAUSAL_PATTERNS:
            m = re.search(pat, full_text)
            if m:
                result.hyd_causal_language_issue = f"HYD 0.0h (metric_warning) 出现因果判断: '{m.group()}'"
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

    # ── NEW: Full-text consistency checks ──

    # 14. HYD unanswered conflict: if HYD analysis not executed, must not assert HYD causation
    if not ledger.hyd_analysis_executed:
        hyd_assert_patterns = [
            r"不支持\s*HYD\s*直接触发停机",
            r"不支持\s*SER/HYD\s*直接触发停机",
            r"不支持\s*SER.*HYD\s*直接触发",
        ]
        for pat in hyd_assert_patterns:
            m = re.search(pat, full_text)
            if m:
                result.hyd_unanswered_conflict = (
                    f"HYD 分析未执行但报告断言 HYD 因果: '{m.group()}'"
                )
                result.details.append(result.hyd_unanswered_conflict)
                break

    # 15. HYD zero-duration check: if duration=0.0 and count>0, must mention 统计口径
    if ledger.hyd_duration_hours == 0.0 and ledger.hyd_event_count > 0 and ledger.hyd_analysis_executed:
        hyd_section = full_text.split("### 4.3")[1].split("###")[0] if "### 4.3" in full_text else ""
        if "统计口径" not in hyd_section and "口径" not in hyd_section:
            result.hyd_zero_duration_issue = "HYD 0.0h 但 4.3 节未提及统计口径"
            result.details.append(result.hyd_zero_duration_issue)

    # 16. Drilled case stale claim: if case in drilldown detail, must not say "未运行 drilldown 验证"
    detail_section = full_text.split("### drilldown 明细")[1] if "### drilldown 明细" in full_text else ""
    detail_targets = set(re.findall(r"\|\s*(SC_\d+)\s*\|", detail_section))
    for cid in sorted(detail_targets):
        stale_pat = re.compile(rf"{re.escape(cid)}[^。\n]*未运行\s*drilldown\s*验证")
        if stale_pat.search(full_text):
            result.drilled_case_stale_issue = (
                f"{cid} 已在 drilldown 明细中出现，但报告仍称'未运行 drilldown 验证'"
            )
            result.details.append(result.drilled_case_stale_issue)
            break

    # 17. Unsafe reason text (full text, including audit)
    for pat, label in _UNSAFE_REASON_PATTERNS:
        m = re.search(pat, full_text)
        if m:
            result.unsafe_reason_text_issue = f"报告含越界文案: '{m.group()}' ({label})"
            result.details.append(result.unsafe_reason_text_issue)
            break

    # 18. Complete coverage no uncovered check (full text)
    if full_coverage and complete:
        full_uncovered_patterns = [
            r"未覆盖案例",
            r"未逐案检查",
            r"未\s*drilldown",
            r"增加调查轮数",
            r"样本量不足",
        ]
        for pat in full_uncovered_patterns:
            m = re.search(pat, full_text)
            if m:
                result.complete_coverage_no_uncovered_issue = (
                    f"10/10 全覆盖但报告含: '{m.group()}'"
                )
                result.details.append(result.complete_coverage_no_uncovered_issue)
                break

    # ── Final pass/fail ──
    has_error = (
        bool(result.forbidden_found)
        or bool(result.coverage_mismatch)
        or bool(result.p1_status_issue)
        or bool(result.generalization_issue)
        or bool(result.hyd_conclusion_issue)
        or bool(result.stale_ratio_issue)
        or bool(result.uncovered_claim_issue)
        or bool(result.hyd_causal_language_issue)
        or bool(result.hyd_unanswered_conflict)
        or bool(result.drilled_case_stale_issue)
        or bool(result.unsafe_reason_text_issue)
        or bool(result.hyd_zero_duration_issue)
        or bool(result.complete_coverage_no_uncovered_issue)
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

    ledger_dict = state_dict.get("evidence_ledger")
    if not ledger_dict:
        result = ReportCheckResult()
        result.details.append("state.json 中无 evidence_ledger，跳过报告校验")
        result.passed = True
        return result

    ledger = EvidenceLedger(**{k: v for k, v in ledger_dict.items()
                               if k in EvidenceLedger.__dataclass_fields__})

    result = validate_rendered_report(report_text, ledger)

    # Add completeness info
    result.completeness_info = {
        "depth": ledger.investigation_depth,
        "total": ledger.total_stoppage_cases,
        "target": ledger.target_stoppage_coverage_count,
        "actual": ledger.actual_stoppage_coverage_count,
        "status": ledger.completeness_status,
        "message": ledger.completeness_reason,
    }
    if ledger.ser_extra_required:
        result.completeness_info["ser_extra_required"] = True
        result.completeness_info["target_ser"] = ledger.target_ser_drilldown_count
        result.completeness_info["actual_ser"] = ledger.actual_ser_drilldown_count
        result.completeness_info["ser_status"] = ledger.ser_extra_completeness_status

    # Detect duplicate stoppage drilldowns
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
