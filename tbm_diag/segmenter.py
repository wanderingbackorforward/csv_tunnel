"""
segmenter.py — 异常事件分段

职责：
- 输入：detect() 输出的 DataFrame（含 is_xxx / score_xxx 列）
- 输出：segment_events(df) -> list[Event]

算法：
1. 对每种异常类型扫描 is_xxx 列的连续 True 区间
2. 允许短间隙合并（默认 gap_tolerance_points=2）
3. 过滤太短的事件（默认 min_event_points=5）
4. 计算每个事件的时间范围、持续时长、峰值/均值分数

滚动窗口扩散说明：
  detector.py 的 score 基于 5 点滚动均值，因此一段真实异常（如 20 行）
  会在前后各扩散约 4 行（窗口半径），形成约 28 行的连续命中区间。
  gap_tolerance_points=2 进一步把相邻小间隙合并，最终多个扩散区间
  通常收敛为 1~2 个事件段，而非数十个碎片。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

ANOMALY_TYPES: list[str] = [
    "suspected_excavation_resistance",
    "low_efficiency_excavation",
    "attitude_or_bias_risk",
    "hydraulic_instability",
]

_TYPE_PREFIX: dict[str, str] = {
    "suspected_excavation_resistance": "SER",
    "low_efficiency_excavation":       "LEE",
    "attitude_or_bias_risk":           "ABR",
    "hydraulic_instability":           "HYD",
}


@dataclass
class SegmenterConfig:
    gap_tolerance_points: int = 2
    """允许合并的最大间隙点数（连续 False 点数 <= 此值时合并两侧事件）。"""
    min_event_points: int = 5
    """事件最小持续点数，低于此值的事件被过滤。"""


@dataclass
class Event:
    event_id: str
    event_type: str
    start_time: Optional[pd.Timestamp]
    end_time: Optional[pd.Timestamp]
    duration_points: int
    duration_seconds: Optional[float]
    peak_score: float
    mean_score: float


# ── 内部辅助 ───────────────────────────────────────────────────────────────────

def _find_runs(mask: pd.Series) -> list[tuple[int, int]]:
    """返回 mask 中连续 True 区间的 (iloc_start, iloc_end) 列表（含端点）。"""
    runs: list[tuple[int, int]] = []
    arr = mask.to_numpy()
    n = len(arr)
    i = 0
    while i < n:
        if arr[i]:
            j = i
            while j < n and arr[j]:
                j += 1
            runs.append((i, j - 1))
            i = j
        else:
            i += 1
    return runs


def _merge_runs(
    runs: list[tuple[int, int]],
    gap: int,
) -> list[tuple[int, int]]:
    """将间隙 <= gap 点的相邻区间合并。"""
    if not runs:
        return []
    merged = [runs[0]]
    for start, end in runs[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end - 1 <= gap:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


# ── 公开接口 ───────────────────────────────────────────────────────────────────

def segment_events(
    df: pd.DataFrame,
    config: Optional[SegmenterConfig] = None,
) -> list[Event]:
    """
    将 detect() 输出的逐点异常标记合并为事件段列表。

    Args:
        df:     DetectionResult.df（含 is_xxx / score_xxx 列，可含 timestamp 列）
        config: 分段配置，None 时使用默认值

    Returns:
        按 (peak_score 降序, duration_points 降序, start_time 升序) 排序的 Event 列表
    """
    cfg = config or SegmenterConfig()
    events: list[Event] = []
    has_ts = "timestamp" in df.columns

    for atype in ANOMALY_TYPES:
        is_col = f"is_{atype}"
        score_col = f"score_{atype}"

        if is_col not in df.columns:
            logger.debug("segmenter: column '%s' not found, skipping", is_col)
            continue

        mask = df[is_col].fillna(False).astype(bool)
        runs = _find_runs(mask)
        runs = _merge_runs(runs, gap=cfg.gap_tolerance_points)

        prefix = _TYPE_PREFIX.get(atype, atype[:3].upper())
        counter = 0

        for iloc_start, iloc_end in runs:
            n_points = iloc_end - iloc_start + 1
            if n_points < cfg.min_event_points:
                continue

            counter += 1
            event_id = f"{prefix}_{counter:03d}"

            start_time: Optional[pd.Timestamp] = None
            end_time: Optional[pd.Timestamp] = None
            duration_seconds: Optional[float] = None

            if has_ts:
                ts_slice = df["timestamp"].iloc[iloc_start : iloc_end + 1]
                start_time = ts_slice.iloc[0]
                end_time = ts_slice.iloc[-1]
                try:
                    duration_seconds = (end_time - start_time).total_seconds()
                except Exception:
                    pass

            if score_col in df.columns:
                score_slice = df[score_col].iloc[iloc_start : iloc_end + 1]
                peak_score = float(score_slice.max())
                mean_score = float(score_slice.mean())
            else:
                peak_score = 1.0
                mean_score = 1.0

            events.append(Event(
                event_id=event_id,
                event_type=atype,
                start_time=start_time,
                end_time=end_time,
                duration_points=n_points,
                duration_seconds=duration_seconds,
                peak_score=round(peak_score, 4),
                mean_score=round(mean_score, 4),
            ))

            logger.debug(
                "segmenter: event %s [%s] iloc=%d~%d points=%d peak=%.3f",
                event_id, atype, iloc_start, iloc_end, n_points, peak_score,
            )

    # 排序：peak_score 降序 → duration_points 降序 → start_time 升序
    events.sort(
        key=lambda e: (
            -e.peak_score,
            -e.duration_points,
            e.start_time if e.start_time is not None else pd.Timestamp.min,
        )
    )

    logger.info(
        "Segmentation complete: %d events from %d anomaly types",
        len(events),
        sum(1 for t in ANOMALY_TYPES if f"is_{t}" in df.columns),
    )

    return events
