"""claim_compiler.py — 从证据账本生成确定性业务结论。

Claim Compiler 只从合法 ledger 生成结论，不引用 ledger 之外的信息。
LLM 只能润色 allowed_claims 内的文案，不允许新增主因判断。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tbm_diag.investigation.evidence_ledger import EvidenceLedger


@dataclass
class CompiledClaims:
    one_sentence_conclusion: str = ""
    key_findings: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)
    next_manual_checks: list[str] = field(default_factory=list)
    allowed_claims: list[str] = field(default_factory=list)
    blocked_claims: list[str] = field(default_factory=list)


def compile_claims_from_ledger(ledger: EvidenceLedger) -> CompiledClaims:
    """从证据账本生成结论，严格遵守规则。"""
    claims = CompiledClaims()

    if ledger.total_stoppage_cases == 0:
        claims.one_sentence_conclusion = "未检测到停机案例。"
        claims.allowed_claims.append("未检测到停机案例")
        return claims

    _build_allowed_claims(ledger, claims)
    _build_blocked_claims(ledger, claims)
    _build_conclusion(ledger, claims)
    _build_key_findings(ledger, claims)
    _build_unresolved(ledger, claims)
    _build_next_checks(ledger, claims)

    return claims


def _build_allowed_claims(ledger: EvidenceLedger, claims: CompiledClaims) -> None:
    if ledger.drilled_stoppage_cases > 0:
        claims.allowed_claims.append(
            f"共 {ledger.total_stoppage_cases} 个停机案例，"
            f"已 drilldown {ledger.drilled_stoppage_cases} 个，"
            f"未覆盖 {ledger.undrilled_stoppage_cases} 个"
        )
    if ledger.drilled_cases_no_pre_ser_hyd > 0:
        claims.allowed_claims.append(
            f"已 drilldown 案例中 {ledger.drilled_cases_no_pre_ser_hyd} 个停机前未见明显 SER/HYD 行级异常"
        )
    if ledger.drilled_cases_recovered_after > 0:
        claims.allowed_claims.append(
            f"已 drilldown 案例中 {ledger.drilled_cases_recovered_after} 个停机后恢复正常"
        )
    if ledger.ser_event_count > 0 and ledger.ser_causality_status != "proven":
        claims.allowed_claims.append("SER 是需要进一步核查的线索")
        claims.allowed_claims.append("当前未证明 SER 与停机存在因果关系")
    if not ledger.external_log_available:
        claims.allowed_claims.append("停机性质仍需施工日志确认")
    if ledger.hyd_status == "metric_warning":
        claims.allowed_claims.append("HYD 时长统计存在口径问题，需先核查")


def _build_blocked_claims(ledger: EvidenceLedger, claims: CompiledClaims) -> None:
    if not ledger.external_log_available:
        claims.blocked_claims.extend([
            "主要原因为计划停机",
            "确认计划停机",
            "确认为计划停机",
            "外部触发因素为主因",
            "正常操作停顿",
            "管理性停机已确认",
        ])
    if ledger.drilled_stoppage_cases < ledger.total_stoppage_cases:
        claims.blocked_claims.extend([
            "本日停机均",
            "停机主要原因",
            "整体停机性质",
            "所有停机",
        ])
    if ledger.drilled_cases_no_pre_ser_hyd > 0 and ledger.drilled_cases_with_pre_ser_or_hyd == 0:
        claims.blocked_claims.extend([
            "已确认正常",
            "已确认计划",
            "无异常停机",
        ])
    if ledger.ser_causality_status != "proven":
        claims.blocked_claims.extend([
            "SER 导致停机",
            "SER 已排除",
            "SER 无关",
        ])
    if ledger.hyd_status == "metric_warning":
        claims.blocked_claims.extend([
            "HYD 可排除",
            "HYD 只是伴随",
            "HYD 与 SER 同步构成证据",
        ])


def _build_conclusion(ledger: EvidenceLedger, claims: CompiledClaims) -> None:
    parts = ["当前 CSV 证据不支持 SER/HYD 直接触发停机"]
    if ledger.drilled_cases_no_pre_ser_hyd > 0:
        parts.append(
            f"已 drilldown 的 {ledger.drilled_stoppage_cases} 个停机案例中 "
            f"{ledger.drilled_cases_no_pre_ser_hyd} 个停机前未见明显行级异常、"
            f"停机后恢复正常"
        )
    if not ledger.external_log_available:
        parts.append("停机性质仍需施工日志确认")
    claims.one_sentence_conclusion = "；".join(parts) + "。"


def _build_key_findings(ledger: EvidenceLedger, claims: CompiledClaims) -> None:
    findings = [
        f"共发现 {ledger.total_stoppage_cases} 个停机案例，"
        f"已 drilldown {ledger.drilled_stoppage_cases} 个，"
        f"未覆盖 {ledger.undrilled_stoppage_cases} 个。",
    ]
    if ledger.drilled_cases_no_pre_ser_hyd > 0:
        findings.append(
            f"已查案例中，{ledger.drilled_cases_no_pre_ser_hyd} 个停机前未见明显 SER/HYD 行级异常。"
        )
    if ledger.ser_event_count > 0 and ledger.ser_causality_status != "proven":
        findings.append(
            f"SER 事件 {ledger.ser_event_count} 个（{ledger.ser_duration_hours}h），"
            f"是重要线索，但当前未证明其为停机原因。"
        )
    if ledger.hyd_status == "metric_warning":
        findings.append(
            f"HYD 事件 {ledger.hyd_event_count} 个，时长统计为 0.0h，"
            f"属于指标口径 warning，不作为业务主因。"
        )
    elif ledger.hyd_event_count > 0:
        findings.append(f"HYD 事件 {ledger.hyd_event_count} 个，需进一步核查。")
    claims.key_findings = findings


def _build_unresolved(ledger: EvidenceLedger, claims: CompiledClaims) -> None:
    items = []
    if ledger.undrilled_stoppage_cases > 0:
        items.append(f"未 drilldown 案例：{', '.join(ledger.undrilled_case_ids)}")
    if not ledger.external_log_available and ledger.total_stoppage_cases > 0:
        items.append("停机是否计划性/管理性：需施工日志确认")
    if ledger.ser_event_count > 0 and ledger.ser_causality_status != "proven":
        items.append("SER 高发是否对应地层变化：需地质记录确认")
    claims.unresolved_items = items


def _build_next_checks(ledger: EvidenceLedger, claims: CompiledClaims) -> None:
    checks = []
    if not ledger.external_log_available and ledger.total_stoppage_cases > 0:
        checks.append("核查施工日志")
    if ledger.undrilled_stoppage_cases > 0:
        checks.append(f"核查未覆盖停机案例：{', '.join(ledger.undrilled_case_ids)}")
    if ledger.ser_event_count > 0:
        checks.append("核查 SER 高发时段对应地层/操作记录")
    claims.next_manual_checks = checks
