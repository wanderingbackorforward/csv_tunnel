"""test_evidence_claims.py — Evidence Ledger + Claim Compiler synthetic golden tests."""
import pytest
from tbm_diag.investigation.evidence_ledger import (
    EvidenceLedger, validate_evidence_ledger,
)
from tbm_diag.investigation.claim_compiler import compile_claims_from_ledger
from tbm_diag.investigation.report_checker import validate_rendered_report


def _make_ledger(**overrides) -> EvidenceLedger:
    defaults = dict(
        total_stoppage_cases=10, drilled_stoppage_cases=10, undrilled_stoppage_cases=0,
        drilled_case_ids=[f"SC_{i:03d}" for i in range(1, 11)],
        undrilled_case_ids=[],
        drilled_cases_no_pre_ser_hyd=10, drilled_cases_with_pre_ser_or_hyd=0,
        drilled_cases_inconclusive=0, drilled_cases_recovered_after=10,
        confirmed_planned_by_external_log=0, confirmed_abnormal_by_external_log=0,
        nature_unknown_count=10, external_log_available=False,
        ser_event_count=39, ser_duration_hours=18.5,
        ser_drilldown_completed=True, ser_causality_status="not_proven",
        hyd_event_count=3, hyd_duration_hours=0.0, hyd_status="metric_warning",
    )
    defaults.update(overrides)
    return EvidenceLedger(**defaults)


# ── 1. no_external_log_partial_coverage ──
def test_no_external_log_partial_coverage():
    ledger = _make_ledger(
        total_stoppage_cases=10, drilled_stoppage_cases=4, undrilled_stoppage_cases=6,
        drilled_case_ids=["SC_001", "SC_002", "SC_003", "SC_004"],
        undrilled_case_ids=[f"SC_{i:03d}" for i in range(5, 11)],
        drilled_cases_no_pre_ser_hyd=4, drilled_cases_recovered_after=4,
        nature_unknown_count=10,
    )
    errors = validate_evidence_ledger(ledger)
    assert not errors, f"Ledger errors: {errors}"

    claims = compile_claims_from_ledger(ledger)
    assert "计划停机" not in claims.one_sentence_conclusion
    assert "主要原因为计划" not in claims.one_sentence_conclusion

    for blocked in claims.blocked_claims:
        assert blocked not in claims.one_sentence_conclusion
        for finding in claims.key_findings:
            assert blocked not in finding

    # Must NOT generalize to all cases
    for finding in claims.key_findings:
        assert "本日停机均" not in finding
        assert "整体停机性质" not in finding


# ── 2. full_coverage_no_pre_abnormal ──
def test_full_coverage_no_pre_abnormal():
    ledger = _make_ledger(
        total_stoppage_cases=10, drilled_stoppage_cases=10, undrilled_stoppage_cases=0,
        drilled_case_ids=[f"SC_{i:03d}" for i in range(1, 11)],
        undrilled_case_ids=[],
        drilled_cases_no_pre_ser_hyd=10, drilled_cases_recovered_after=10,
        nature_unknown_count=10,
    )
    errors = validate_evidence_ledger(ledger)
    assert not errors

    claims = compile_claims_from_ledger(ledger)
    # Can say "all drilled cases no pre-abnormal"
    assert any("10 个停机前未见明显" in f for f in claims.key_findings)
    # Still cannot confirm planned stoppage
    assert "确认计划停机" not in claims.one_sentence_conclusion
    assert "需施工日志确认" in claims.one_sentence_conclusion


# ── 3. ser_partial_only ──
def test_ser_partial_only():
    ledger = _make_ledger(
        total_stoppage_cases=5, drilled_stoppage_cases=2, undrilled_stoppage_cases=3,
        drilled_case_ids=["SC_001", "SC_002"],
        undrilled_case_ids=["SC_003", "SC_004", "SC_005"],
        drilled_cases_no_pre_ser_hyd=2, drilled_cases_recovered_after=2,
        ser_event_count=50, ser_duration_hours=20.0,
        ser_drilldown_completed=False, ser_causality_status="insufficient_evidence",
        nature_unknown_count=5, hyd_event_count=0, hyd_duration_hours=0.0,
        hyd_status="insufficient_evidence",
    )
    errors = validate_evidence_ledger(ledger)
    assert not errors

    claims = compile_claims_from_ledger(ledger)
    assert "SER" in claims.one_sentence_conclusion or "SER" in str(claims.key_findings)
    # Cannot say SER proven
    for finding in claims.key_findings:
        assert "SER 导致停机" not in finding
        assert "SER 已排除" not in finding


# ── 4. hyd_zero_duration ──
def test_hyd_zero_duration():
    ledger = _make_ledger(
        hyd_event_count=3, hyd_duration_hours=0.0, hyd_status="metric_warning",
    )
    errors = validate_evidence_ledger(ledger)
    assert not errors

    claims = compile_claims_from_ledger(ledger)
    hyd_claims = [f for f in claims.key_findings if "HYD" in f]
    assert any("口径" in c or "warning" in c for c in hyd_claims)
    for blocked in claims.blocked_claims:
        if "HYD" in blocked:
            for finding in claims.key_findings:
                assert blocked not in finding


# ── 5. external_log_planned_available ──
def test_external_log_planned_available():
    ledger = _make_ledger(
        external_log_available=True,
        confirmed_planned_by_external_log=3,
        confirmed_abnormal_by_external_log=0,
        nature_unknown_count=7,
    )
    errors = validate_evidence_ledger(ledger)
    assert not errors

    # This is the ONLY scenario where "confirmed planned" is allowed
    assert ledger.confirmed_planned_by_external_log == 3


# ── Ledger validation edge cases ──
def test_ledger_total_mismatch():
    ledger = _make_ledger(total_stoppage_cases=10, drilled_stoppage_cases=3, undrilled_stoppage_cases=5)
    errors = validate_evidence_ledger(ledger)
    assert any("total" in e for e in errors)


def test_ledger_confirmed_without_log():
    ledger = _make_ledger(external_log_available=False, confirmed_planned_by_external_log=1)
    errors = validate_evidence_ledger(ledger)
    assert any("confirmed_planned" in e for e in errors)


def test_ledger_hyd_status_wrong():
    ledger = _make_ledger(hyd_event_count=3, hyd_duration_hours=0.0, hyd_status="valid_signal")
    errors = validate_evidence_ledger(ledger)
    assert any("metric_warning" in e for e in errors)


# ── Report checker: forbidden phrases ──
def test_report_checker_catches_forbidden():
    ledger = _make_ledger()
    validate_evidence_ledger(ledger)
    bad_report = "主要原因为计划停机，已排除 SER。"
    result = validate_rendered_report(bad_report, ledger)
    assert not result.passed
    assert any("主要原因为计划" in p for p in result.forbidden_found)


def test_report_checker_passes_clean():
    ledger = _make_ledger()
    validate_evidence_ledger(ledger)
    clean_report = (
        "停机案例总数：10\n"
        "已 drilldown：10\n"
        "当前 CSV 证据不支持 SER/HYD 直接触发停机，停机性质仍需施工日志确认。\n"
    )
    result = validate_rendered_report(clean_report, ledger)
    assert result.passed
