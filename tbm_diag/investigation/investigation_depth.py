"""investigation_depth.py — 调查充分性目标配置。

max_iterations 是预算，depth coverage target 才是调查目标。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class CoverageTarget:
    depth: str
    total_cases: int
    target_count: int
    cap: int
    target_ratio: float
    description_zh: str


_DEPTH_LABELS = {
    "quick": "快速初筛",
    "standard": "标准调查",
    "deep": "深度复核",
    "exhaustive": "穷尽调查",
}

_DEPTH_DESCRIPTIONS = {
    "quick": "查 Top 3 停机案例，适合快速预览",
    "standard": "查约 60% 停机案例，最多 10 个",
    "deep": "查全部停机案例，最多 30 个",
    "exhaustive": "查全部停机案例 + 关键 SER 窗口，最多 100 个",
}

_DEPTH_DEFAULT_ITERATIONS = {
    "quick": 12,
    "standard": 30,
    "deep": 80,
    "exhaustive": 120,
}

_DEPTH_BATCH_SIZE = 5


def compute_stoppage_coverage_target(
    total_cases: int,
    depth: str = "standard",
) -> CoverageTarget:
    """根据停机案例总数和调查深度，计算 coverage target。"""
    depth = depth or "standard"

    if total_cases <= 0:
        return CoverageTarget(
            depth=depth,
            total_cases=0,
            target_count=0,
            cap=0,
            target_ratio=0.0,
            description_zh="无停机案例，不适用",
        )

    if depth == "quick":
        target_count = min(3, total_cases)
        cap = 3
    elif depth == "standard":
        target_count = min(total_cases, max(5, math.ceil(total_cases * 0.6)), 10)
        cap = 10
    elif depth == "deep":
        target_count = min(total_cases, 30)
        cap = 30
    elif depth == "exhaustive":
        target_count = total_cases
        cap = 100
    else:
        target_count = min(3, total_cases)
        cap = 3

    target_ratio = target_count / total_cases if total_cases > 0 else 0.0
    label = _DEPTH_LABELS.get(depth, depth)
    description = f"{label}：目标 {target_count}/{total_cases}"

    return CoverageTarget(
        depth=depth,
        total_cases=total_cases,
        target_count=target_count,
        cap=cap,
        target_ratio=target_ratio,
        description_zh=description,
    )


def get_depth_default_iterations(depth: str) -> int:
    return _DEPTH_DEFAULT_ITERATIONS.get(depth, 30)


def get_depth_label(depth: str) -> str:
    return _DEPTH_LABELS.get(depth, depth)


def get_depth_batch_size() -> int:
    return _DEPTH_BATCH_SIZE


def compute_completeness_status(
    actual_count: int,
    target: CoverageTarget,
    remaining_rounds: int = 0,
) -> tuple[str, str]:
    """返回 (status, message_zh)。

    status:
      - complete_for_depth
      - incomplete_due_to_budget
      - incomplete_due_to_cap
      - not_applicable_no_stoppage
    """
    if target.total_cases <= 0:
        return "not_applicable_no_stoppage", "无停机案例，调查充分性不适用"

    if actual_count >= target.target_count:
        return (
            "complete_for_depth",
            f"已达到{get_depth_label(target.depth)}目标 "
            f"({actual_count}/{target.target_count})",
        )

    if remaining_rounds <= 0:
        return (
            "incomplete_due_to_budget",
            f"因预算不足未完成，实际 {actual_count}/{target.target_count}，"
            f"未覆盖 {target.target_count - actual_count} 个",
        )

    if actual_count >= target.cap:
        return (
            "incomplete_due_to_cap",
            f"已达到上限 {target.cap}，但目标为 {target.target_count}",
        )

    return (
        "incomplete_due_to_budget",
        f"调查未充分，实际 {actual_count}/{target.target_count}，"
        f"还需 {target.target_count - actual_count} 个",
    )


def compute_p1_status(
    drilled_count: int,
    target: CoverageTarget,
    remaining_rounds: int,
    has_analyze: bool = False,
) -> tuple[str, str]:
    """返回 (status_zh_key, display_text)。

    status_zh_key:
      - not_applicable
      - not_started
      - partially_completed
      - minimum_completed
      - target_completed
      - blocked_by_budget
    """
    if target.total_cases <= 0:
        return "not_applicable", "无停机案例，不适用"

    if not has_analyze:
        return "not_started", "尚未开始停机分析"

    if drilled_count >= target.target_count:
        return (
            "target_completed",
            f"已达到当前深度目标 ({drilled_count}/{target.target_count})",
        )

    quick_min = min(3, target.total_cases)
    if drilled_count >= quick_min and target.depth == "quick":
        return (
            "target_completed",
            f"已达到快速初筛目标 ({drilled_count}/{target.target_count})",
        )

    if drilled_count >= quick_min and drilled_count < target.target_count:
        if remaining_rounds <= 0:
            return (
                "blocked_by_budget",
                f"因预算不足未完成（已查 {drilled_count}/{target.target_count}）",
            )
        return (
            "minimum_completed",
            f"已达到快速初筛最低覆盖 ({drilled_count}/{target.target_count})，"
            f"未达到{get_depth_label(target.depth)}目标",
        )

    if drilled_count > 0:
        return (
            "partially_completed",
            f"部分完成 ({drilled_count}/{target.target_count})",
        )

    return "not_started", "尚未开始 drilldown"


def select_stoppage_drilldown_batch(
    drilled_case_ids: set[str],
    all_cases: list,
    target: CoverageTarget,
    batch_size: int = 0,
) -> list[str]:
    """选择下一批待 drilldown 的停机案例 ID。

    优先级：未验证异常 > 长停机 > 其他未覆盖。
    不包含已 drilldown 的 case。
    """
    if not batch_size:
        batch_size = get_depth_batch_size()

    remaining_needed = target.target_count - len(drilled_case_ids)
    if remaining_needed <= 0:
        return []

    undrilled = [c for c in all_cases if c.case_id not in drilled_case_ids]
    undrilled.sort(key=lambda c: -c.duration_seconds)

    selected = []
    for c in undrilled:
        if len(selected) >= min(batch_size, remaining_needed):
            break
        selected.append(c.case_id)

    return selected
