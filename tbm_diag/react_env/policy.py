"""Policies that choose the next action.

The first implementation is deterministic. A future LLM policy should return
one of the same action names and arguments, then still pass through verifier.
"""

from __future__ import annotations

from tbm_diag.react_env.state import EnvironmentState


def choose_rule_action(state: EnvironmentState) -> tuple[str, dict]:
    if not state.schema_inspected:
        return "inspect_schema", {}
    if not state.detection_done:
        return "run_detection", {}
    if not state.risk_mapped:
        return "map_risk_families", {}
    if not state.claim_checked:
        return "check_claim_level", {}
    if not state.gaps_identified:
        return "identify_evidence_gaps", {}
    return "finalize", {}
