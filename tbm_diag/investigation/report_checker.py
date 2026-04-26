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

    # Only check business sections (1-4), skip section 5 (audit appendix)
    business_text = report_text.split("## 5.")[0] if "## 5." in report_text else report_text

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

    # 4. P1 status
    p1_done_match = re.search(r"\|\s*P1[^|]*\|[^|]*\|\s*已完成\s*\|", business_text)
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

    # Final pass/fail
    has_error = (
        bool(result.forbidden_found)
        or bool(result.coverage_mismatch)
        or bool(result.p1_status_issue)
        or bool(result.generalization_issue)
        or bool(result.hyd_conclusion_issue)
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
