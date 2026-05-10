"""Typed project-domain constraints.

The domain layer is deliberately data-only. It defines what can be observed,
what cannot be concluded from CSV alone, and which external records are needed
before a report may claim a root cause.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParameterBand:
    """A project-level operating range or design reference."""

    name: str
    field: str
    unit: str
    normal_min: float | None = None
    normal_max: float | None = None
    warning_min: float | None = None
    warning_max: float | None = None
    note: str = ""
    source_ref: str = ""


@dataclass(frozen=True)
class RiskFamily:
    """A bounded diagnosis family from the project ontology."""

    risk_id: str
    label: str
    description: str
    csv_observations: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    useful_external_records: tuple[str, ...] = ()
    allowed_csv_claim: str = ""
    forbidden_without_external: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimLevel:
    """A permitted conclusion level and its evidence requirements."""

    level_id: str
    label: str
    required_evidence: tuple[str, ...]
    allowed_wording: str
    forbidden_wording: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimPolicy:
    """Global wording constraints for generated reports."""

    allowed_qualifiers: tuple[str, ...] = ()
    forbidden_phrases: tuple[str, ...] = ()
    claim_levels: tuple[ClaimLevel, ...] = ()


@dataclass(frozen=True)
class DataNeed:
    """A staged field-data request constraint."""

    priority: str
    name: str
    acceptable_formats: tuple[str, ...]
    reason: str
    ask_in_first_meeting: bool


@dataclass(frozen=True)
class ProjectProfile:
    """Complete project-domain constraint package."""

    profile_id: str
    display_name: str
    machine_type: str
    scope_note: str
    geology_note: str = ""
    parameter_bands: tuple[ParameterBand, ...] = ()
    risk_families: tuple[RiskFamily, ...] = ()
    claim_policy: ClaimPolicy = field(default_factory=ClaimPolicy)
    data_needs: tuple[DataNeed, ...] = ()


def _tuple_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def profile_from_dict(raw: dict[str, Any]) -> ProjectProfile:
    """Build a ProjectProfile from JSON-compatible data."""

    bands = tuple(
        ParameterBand(
            name=str(item["name"]),
            field=str(item["field"]),
            unit=str(item["unit"]),
            normal_min=_float_or_none(item.get("normal_min")),
            normal_max=_float_or_none(item.get("normal_max")),
            warning_min=_float_or_none(item.get("warning_min")),
            warning_max=_float_or_none(item.get("warning_max")),
            note=str(item.get("note", "")),
            source_ref=str(item.get("source_ref", "")),
        )
        for item in raw.get("parameter_bands", [])
    )

    risks = tuple(
        RiskFamily(
            risk_id=str(item["risk_id"]),
            label=str(item["label"]),
            description=str(item.get("description", "")),
            csv_observations=_tuple_str(item.get("csv_observations")),
            required_fields=_tuple_str(item.get("required_fields")),
            useful_external_records=_tuple_str(item.get("useful_external_records")),
            allowed_csv_claim=str(item.get("allowed_csv_claim", "")),
            forbidden_without_external=_tuple_str(item.get("forbidden_without_external")),
        )
        for item in raw.get("risk_families", [])
    )

    levels = tuple(
        ClaimLevel(
            level_id=str(item["level_id"]),
            label=str(item["label"]),
            required_evidence=_tuple_str(item.get("required_evidence")),
            allowed_wording=str(item.get("allowed_wording", "")),
            forbidden_wording=_tuple_str(item.get("forbidden_wording")),
        )
        for item in raw.get("claim_policy", {}).get("claim_levels", [])
    )
    policy = ClaimPolicy(
        allowed_qualifiers=_tuple_str(raw.get("claim_policy", {}).get("allowed_qualifiers")),
        forbidden_phrases=_tuple_str(raw.get("claim_policy", {}).get("forbidden_phrases")),
        claim_levels=levels,
    )

    data_needs = tuple(
        DataNeed(
            priority=str(item["priority"]),
            name=str(item["name"]),
            acceptable_formats=_tuple_str(item.get("acceptable_formats")),
            reason=str(item.get("reason", "")),
            ask_in_first_meeting=bool(item.get("ask_in_first_meeting", False)),
        )
        for item in raw.get("data_needs", [])
    )

    return ProjectProfile(
        profile_id=str(raw["profile_id"]),
        display_name=str(raw["display_name"]),
        machine_type=str(raw["machine_type"]),
        scope_note=str(raw.get("scope_note", "")),
        geology_note=str(raw.get("geology_note", "")),
        parameter_bands=bands,
        risk_families=risks,
        claim_policy=policy,
        data_needs=data_needs,
    )
