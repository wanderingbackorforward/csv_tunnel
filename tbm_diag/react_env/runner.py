"""Controller for the closed-loop ReAct environment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tbm_diag.config import DiagConfig
from tbm_diag.domain import load_project_profile, validate_profile
from tbm_diag.react_env.actions import ACTION_REGISTRY
from tbm_diag.react_env.policy import choose_rule_action
from tbm_diag.react_env.state import EnvironmentState, TraceRecord
from tbm_diag.react_env.verifier import verify_state


@dataclass
class ReactEnvResult:
    state: EnvironmentState
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = self.state.to_dict()
        if self.error:
            data["error"] = self.error
        return data


def run_react_environment(
    input_file: str | Path,
    cfg: DiagConfig,
    *,
    profile_path: str | Path | None = None,
    max_steps: int = 8,
    policy_type: str = "rule",
) -> ReactEnvResult:
    """Run the bounded environment until verifier-controlled termination."""

    profile = load_project_profile(profile_path)
    audit = validate_profile(profile)
    if not audit.ok:
        return ReactEnvResult(
            state=EnvironmentState(
                input_file=str(input_file),
                profile_id=profile.profile_id,
                policy_type=policy_type,
            ),
            error="; ".join(audit.errors),
        )

    state = EnvironmentState(
        input_file=str(input_file),
        profile_id=profile.profile_id,
        policy_type=policy_type,
        evidence_keys={"project_profile"},
    )

    if policy_type != "rule":
        return ReactEnvResult(state=state, error=f"unsupported policy_type: {policy_type}")

    for _ in range(max_steps):
        action, arguments = choose_rule_action(state)
        fn = ACTION_REGISTRY[action]
        state.round_num += 1
        observation = fn(state, profile, cfg, arguments)
        verification = verify_state(state, profile)

        state.trace.append(
            TraceRecord(
                round_num=state.round_num,
                action=action,
                arguments=arguments,
                observation_status=observation.status,
                observation_summary=observation.summary,
                evidence_keys_after=sorted(state.evidence_keys),
                max_claim_level_after=verification.max_level,
                stop_after=state.finalized,
            )
        )

        if observation.status != "ok":
            return ReactEnvResult(state=state, error=observation.summary)
        if state.finalized:
            return ReactEnvResult(state=state)

    return ReactEnvResult(state=state, error=f"max_steps exceeded: {max_steps}")


def save_react_env_result(result: ReactEnvResult, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
