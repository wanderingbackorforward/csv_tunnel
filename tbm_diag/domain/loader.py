"""Load built-in or local project constraint profiles."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from tbm_diag.domain.models import ProjectProfile, profile_from_dict

BUILTIN_PROFILE_ID = "urban_rail_epb_soft_ground"


def _load_builtin(profile_id: str) -> dict:
    package = "tbm_diag.domain.profiles"
    file_name = f"{profile_id}.json"
    try:
        text = resources.files(package).joinpath(file_name).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"内置约束 profile 不存在: {profile_id}") from exc
    return json.loads(text)


def _load_json_file(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"约束 profile 不存在: {path}")
    if path.suffix.lower() != ".json":
        raise ValueError("约束 profile 目前仅支持 .json，避免新增 YAML 运行依赖")
    return json.loads(path.read_text(encoding="utf-8"))


def load_project_profile(
    path: str | Path | None = None,
    *,
    profile_id: str = BUILTIN_PROFILE_ID,
) -> ProjectProfile:
    """Load a project profile.

    Args:
        path: Optional local JSON path. Use this for site-specific profiles that
            should remain outside version control.
        profile_id: Built-in profile id when path is not provided.
    """

    raw = _load_json_file(Path(path)) if path else _load_builtin(profile_id)
    return profile_from_dict(raw)
