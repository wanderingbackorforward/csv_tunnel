"""Validation and reporting helpers for project-domain constraints."""

from __future__ import annotations

from dataclasses import dataclass

from tbm_diag.domain.models import ProjectProfile


@dataclass(frozen=True)
class ConstraintAudit:
    """Machine-checkable summary of a ProjectProfile."""

    profile_id: str
    parameter_band_count: int
    risk_family_count: int
    claim_level_count: int
    data_need_count: int
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_profile(profile: ProjectProfile) -> ConstraintAudit:
    """Validate the minimum invariants that make constraints usable."""

    errors: list[str] = []
    if not profile.profile_id:
        errors.append("profile_id is required")
    if not profile.display_name:
        errors.append("display_name is required")
    if not profile.machine_type:
        errors.append("machine_type is required")

    risk_ids = [r.risk_id for r in profile.risk_families]
    if len(risk_ids) != len(set(risk_ids)):
        errors.append("risk_families contain duplicate risk_id values")
    if not risk_ids:
        errors.append("at least one risk_family is required")
    if "stoppage" in set(risk_ids) and len(risk_ids) == 1:
        errors.append("stoppage cannot be the only risk family")

    for risk in profile.risk_families:
        if not risk.label:
            errors.append(f"risk_family {risk.risk_id}: label is required")
        if not risk.csv_observations:
            errors.append(f"risk_family {risk.risk_id}: csv_observations is required")
        if not risk.allowed_csv_claim:
            errors.append(f"risk_family {risk.risk_id}: allowed_csv_claim is required")

    policy = profile.claim_policy
    if not policy.allowed_qualifiers:
        errors.append("claim_policy.allowed_qualifiers is required")
    if not policy.forbidden_phrases:
        errors.append("claim_policy.forbidden_phrases is required")
    if not policy.claim_levels:
        errors.append("claim_policy.claim_levels is required")

    level_ids = [level.level_id for level in policy.claim_levels]
    if len(level_ids) != len(set(level_ids)):
        errors.append("claim_policy.claim_levels contain duplicate level_id values")
    for level in policy.claim_levels:
        if not level.required_evidence:
            errors.append(f"claim_level {level.level_id}: required_evidence is required")
        if not level.allowed_wording:
            errors.append(f"claim_level {level.level_id}: allowed_wording is required")

    return ConstraintAudit(
        profile_id=profile.profile_id,
        parameter_band_count=len(profile.parameter_bands),
        risk_family_count=len(profile.risk_families),
        claim_level_count=len(policy.claim_levels),
        data_need_count=len(profile.data_needs),
        errors=tuple(errors),
    )


def claim_levels_supported_by(
    profile: ProjectProfile,
    evidence_keys: set[str],
) -> list[str]:
    """Return claim level ids whose evidence requirements are satisfied."""

    supported: list[str] = []
    for level in profile.claim_policy.claim_levels:
        if set(level.required_evidence).issubset(evidence_keys):
            supported.append(level.level_id)
    return supported
