"""Finite actions for the closed-loop diagnosis environment."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from tbm_diag.cleaning import clean
from tbm_diag.config import DiagConfig
from tbm_diag.detector import detect
from tbm_diag.domain.models import ProjectProfile, RiskFamily
from tbm_diag.evidence import extract_evidence
from tbm_diag.feature_engine import enrich_features
from tbm_diag.ingestion import load_csv
from tbm_diag.react_env.state import EnvironmentState, Observation
from tbm_diag.react_env.verifier import verify_state
from tbm_diag.segmenter import segment_events
from tbm_diag.semantic_layer import apply_to_evidences
from tbm_diag.state_engine import classify_states, summarize_event_state


EVENT_RISK_HINTS: dict[str, tuple[str, ...]] = {
    "suspected_excavation_resistance": ("excavation_resistance_tooling", "face_stability"),
    "excavation_resistance_under_load": ("excavation_resistance_tooling", "face_stability"),
    "low_efficiency_excavation": ("operational_pause", "excavation_resistance_tooling"),
    "stoppage_segment": ("operational_pause",),
    "attitude_or_bias_risk": ("attitude_deviation",),
    "hydraulic_instability": ("hydraulic_system",),
}


def inspect_schema(
    state: EnvironmentState,
    profile: ProjectProfile,
    cfg: DiagConfig,
    arguments: dict[str, Any],
) -> Observation:
    ingestion = load_csv(state.input_file)
    state.fields_present = set(ingestion.recognized.values())
    state.unrecognized_fields = list(ingestion.unrecognized)
    state.suspicious_unit_fields = list(ingestion.suspicious_unit_fields)
    state.row_count = int(len(ingestion.df))
    state.schema_inspected = True
    if "timestamp" in ingestion.df.columns:
        state.evidence_keys.add("csv_time_series")

    summary = (
        f"recognized={len(state.fields_present)}, unrecognized={len(state.unrecognized_fields)}, "
        f"rows={state.row_count}"
    )
    return Observation(
        status="ok",
        summary=summary,
        payload={
            "recognized_fields": sorted(state.fields_present),
            "unrecognized_fields": state.unrecognized_fields,
            "suspicious_unit_fields": state.suspicious_unit_fields,
        },
    )


def run_detection(
    state: EnvironmentState,
    profile: ProjectProfile,
    cfg: DiagConfig,
    arguments: dict[str, Any],
) -> Observation:
    cc = cfg.cleaning
    resample_freq = None if (cc.resample or "").strip().lower() == "none" else cc.resample

    ingestion = load_csv(state.input_file)
    df, _cleaning = clean(
        ingestion.df,
        resample_freq=resample_freq,
        spike_k=cc.spike_k,
        fill_method=cc.fill,
        max_gap_fill=cc.max_gap,
        skip_spike_cols=set(cc.iqr_exempt_fields) if cc.iqr_exempt_fields else None,
    )
    enriched = enrich_features(df, window=cfg.feature.rolling_window)
    detection = detect(enriched, config=cfg.detector)
    events = segment_events(detection.df, config=cfg.segmenter)

    event_states = {}
    if events:
        state_df = classify_states(enriched, config=cfg.state)
        event_states = {event.event_id: summarize_event_state(state_df, event) for event in events}
    else:
        state_df = enriched

    evidences = extract_evidence(state_df, events, event_states=event_states)
    apply_to_evidences(evidences)

    state.detection_done = True
    state.row_count = int(len(enriched))
    state.event_count = len(events)
    state.skipped_rules = detection.skipped_rules
    state.event_type_counts = dict(Counter(event.event_type for event in events))
    state.semantic_type_counts = dict(Counter(ev.semantic_event_type or ev.event_type for ev in evidences))
    state.top_events = [
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "semantic_event_type": evidence.semantic_event_type or evidence.event_type,
            "start_time": str(event.start_time) if event.start_time is not None else "",
            "end_time": str(event.end_time) if event.end_time is not None else "",
            "duration_seconds": event.duration_seconds,
            "peak_score": event.peak_score,
            "signals": [sig.signal_name for sig in evidence.top_signals],
        }
        for event, evidence in zip(events[:5], evidences[:5])
    ]
    state.evidence_keys.add("csv_time_series")

    summary = f"events={state.event_count}, types={state.event_type_counts}"
    return Observation(
        status="ok",
        summary=summary,
        payload={
            "event_count": state.event_count,
            "event_type_counts": state.event_type_counts,
            "semantic_type_counts": state.semantic_type_counts,
            "top_events": state.top_events,
            "skipped_rules": state.skipped_rules,
        },
    )


def _risk_score_from_events(risk: RiskFamily, state: EnvironmentState) -> int:
    event_score = 0
    event_types = set(state.event_type_counts) | set(state.semantic_type_counts)
    for event_type in event_types:
        if risk.risk_id in EVENT_RISK_HINTS.get(event_type, ()):
            event_score += 3
    if risk.risk_id == "data_quality" and (state.unrecognized_fields or state.suspicious_unit_fields):
        return 2
    if event_score <= 0:
        return 0

    score = event_score
    if risk.required_fields:
        present = set(risk.required_fields).intersection(state.fields_present)
        if present:
            score += len(present)
    return score


def map_risk_families(
    state: EnvironmentState,
    profile: ProjectProfile,
    cfg: DiagConfig,
    arguments: dict[str, Any],
) -> Observation:
    candidates: list[dict[str, Any]] = []
    for risk in profile.risk_families:
        score = _risk_score_from_events(risk, state)
        if score <= 0:
            continue
        required = set(risk.required_fields)
        missing = sorted(required - state.fields_present)
        candidates.append(
            {
                "risk_id": risk.risk_id,
                "label": risk.label,
                "score": score,
                "required_fields_present": not missing,
                "missing_required_fields": missing,
                "allowed_csv_claim": risk.allowed_csv_claim,
                "useful_external_records": list(risk.useful_external_records),
            }
        )

    candidates.sort(key=lambda item: (-int(item["score"]), item["risk_id"]))
    state.risk_candidates = candidates
    state.risk_mapped = True

    summary = (
        "candidates="
        + ", ".join(item["risk_id"] for item in candidates[:5])
        if candidates
        else "no risk family candidate"
    )
    return Observation(status="ok", summary=summary, payload={"risk_candidates": candidates})


def check_claim_level(
    state: EnvironmentState,
    profile: ProjectProfile,
    cfg: DiagConfig,
    arguments: dict[str, Any],
) -> Observation:
    result = verify_state(state, profile)
    state.supported_claim_levels = result.supported_levels
    state.max_claim_level = result.max_level
    state.verifier_blockers = result.blockers
    state.stop_reason = result.stop_reason
    state.claim_checked = True

    summary = f"max_claim_level={state.max_claim_level or 'none'}, blockers={len(state.verifier_blockers)}"
    return Observation(
        status="ok",
        summary=summary,
        payload={
            "supported_claim_levels": state.supported_claim_levels,
            "max_claim_level": state.max_claim_level,
            "blockers": state.verifier_blockers,
            "stop_reason": state.stop_reason,
        },
    )


def identify_evidence_gaps(
    state: EnvironmentState,
    profile: ProjectProfile,
    cfg: DiagConfig,
    arguments: dict[str, Any],
) -> Observation:
    gaps_by_name: dict[str, dict[str, Any]] = {}
    for candidate in state.risk_candidates[:5]:
        for name in candidate.get("useful_external_records", []):
            gaps_by_name.setdefault(
                name,
                {
                    "record_name": name,
                    "why_needed": [],
                    "related_risk_ids": [],
                },
            )
            gaps_by_name[name]["related_risk_ids"].append(candidate["risk_id"])
            gaps_by_name[name]["why_needed"].append(candidate["allowed_csv_claim"])

    for need in profile.data_needs:
        if need.ask_in_first_meeting:
            gaps_by_name.setdefault(
                need.name,
                {
                    "record_name": need.name,
                    "why_needed": [need.reason],
                    "related_risk_ids": [],
                    "priority": need.priority,
                    "acceptable_formats": list(need.acceptable_formats),
                },
            )
        elif any(name in need.name for name in ("日志", "维修", "停机", "换刀")) and state.risk_candidates:
            gaps_by_name.setdefault(
                need.name,
                {
                    "record_name": need.name,
                    "why_needed": [need.reason],
                    "related_risk_ids": [item["risk_id"] for item in state.risk_candidates[:3]],
                    "priority": need.priority,
                    "acceptable_formats": list(need.acceptable_formats),
                },
            )

    state.evidence_gaps = list(gaps_by_name.values())
    state.gaps_identified = True
    result = verify_state(state, profile)
    state.supported_claim_levels = result.supported_levels
    state.max_claim_level = result.max_level
    state.verifier_blockers = result.blockers
    state.stop_reason = result.stop_reason

    summary = f"gaps={len(state.evidence_gaps)}, stop_reason={state.stop_reason or 'not ready'}"
    return Observation(status="ok", summary=summary, payload={"evidence_gaps": state.evidence_gaps})


def finalize(
    state: EnvironmentState,
    profile: ProjectProfile,
    cfg: DiagConfig,
    arguments: dict[str, Any],
) -> Observation:
    result = verify_state(state, profile)
    state.supported_claim_levels = result.supported_levels
    state.max_claim_level = result.max_level
    state.verifier_blockers = result.blockers
    state.stop_reason = result.stop_reason or "环境达到终止条件。"
    state.finalized = True

    if state.risk_candidates:
        top_risk = state.risk_candidates[0]
        state.final_summary = (
            f"当前最高允许结论等级为 {state.max_claim_level or 'none'}。"
            f"CSV 可将主要线索映射到「{top_risk['label']}」，但不能越过现场记录确认。"
        )
    elif state.event_count == 0:
        state.final_summary = (
            f"当前最高允许结论等级为 {state.max_claim_level or 'none'}。"
            "CSV 未形成可分段异常事件，建议先核查字段完整性和数据时段。"
        )
    else:
        state.final_summary = f"当前最高允许结论等级为 {state.max_claim_level or 'none'}。"

    return Observation(
        status="ok",
        summary=state.final_summary,
        payload={
            "final_summary": state.final_summary,
            "max_claim_level": state.max_claim_level,
            "stop_reason": state.stop_reason,
            "blockers": state.verifier_blockers,
        },
    )


ACTION_REGISTRY = {
    "inspect_schema": inspect_schema,
    "run_detection": run_detection,
    "map_risk_families": map_risk_families,
    "check_claim_level": check_claim_level,
    "identify_evidence_gaps": identify_evidence_gaps,
    "finalize": finalize,
}
