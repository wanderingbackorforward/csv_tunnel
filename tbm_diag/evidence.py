"""
evidence.py — 事件证据提取

职责：
- 输入：enriched DataFrame（含原始列 + 特征列）+ Event 列表
- 输出：EventEvidence 列表，每个事件附带 3~5 条 SignalEvidence

设计原则：
- 只在事件时间窗口内统计（按 iloc 定位）
- 自动跳过缺列，不报错
- 不做任何异常判断，只做数据摘要
- 生成的 evidence_text 为简洁机器文本，供 explainer.py 渲染
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from tbm_diag.segmenter import Event

logger = logging.getLogger(__name__)


# ── 数据类 ─────────────────────────────────────────────────────────────────────

@dataclass
class ValueSummary:
    mean: float
    min: float
    max: float
    start: float
    end: float
    change_pct: Optional[float]   # (end - start) / |start| * 100，start=0 时为 None


@dataclass
class SignalEvidence:
    signal_name: str          # canonical 列名
    display_name: str         # 中文显示名
    direction: str            # up / down / unstable / imbalanced / normal
    magnitude_text: str       # 量级描述，如 "均值 3 412 kNm，峰值 4 500 kNm"
    evidence_text: str        # 一句话证据，如 "事件窗口内刀盘转矩持续偏高"
    value_summary: ValueSummary


@dataclass
class EventEvidence:
    event_id: str
    event_type: str
    start_time: Optional[pd.Timestamp]
    end_time: Optional[pd.Timestamp]
    severity_score: float     # 第一版直接取 peak_score
    top_signals: list[SignalEvidence] = field(default_factory=list)
    dominant_state: Optional[str] = None
    """事件窗口内主导工况状态（英文 key），由 state_engine 填充。"""
    state_distribution: Optional[dict] = None
    """各状态占比 dict，由 state_engine 填充。"""
    semantic_event_type: Optional[str] = None
    """语义事件类型，由 semantic_layer.apply_to_evidences() 填充。"""


# ── 候选信号配置 ───────────────────────────────────────────────────────────────
# 每种异常类型的候选信号：(canonical列名, 中文显示名, 单位, 期望方向)
# 期望方向：'hi'=偏高触发, 'lo'=偏低触发, 'diff'=差值偏大, 'std'=波动偏大

_SIGNAL_SPECS: dict[str, list[tuple[str, str, str, str]]] = {
    "suspected_excavation_resistance": [
        ("cutter_torque_kNm",              "刀盘转矩",       "kNm",      "hi"),
        ("advance_speed_mm_per_min",       "推进速度",       "mm/min",   "lo"),
        ("penetration_rate_mm_per_rev",    "贯入度",         "mm/rev",   "lo"),
        ("total_thrust_kN",                "总推进力",       "kN",       "hi"),
        ("torque_to_speed_ratio",          "转矩/速度比",    "kNm·min/mm","hi"),
    ],
    "low_efficiency_excavation": [
        ("advance_speed_mm_per_min",       "推进速度",       "mm/min",   "lo"),
        ("penetration_rate_mm_per_rev",    "贯入度",         "mm/rev",   "lo"),
        ("thrust_to_speed_ratio",          "推力/速度比",    "kN·min/mm","hi"),
        ("cutter_speed_rpm",               "刀盘转速",       "rpm",      "lo"),
        ("cutter_torque_kNm",              "刀盘转矩",       "kNm",      "lo"),
    ],
    "attitude_or_bias_risk": [
        ("stabilizer_stroke_diff_mm",      "稳定器行程差",   "mm",       "diff"),
        ("stabilizer_pressure_diff_bar",   "稳定器压力差",   "bar",      "diff"),
        ("front_shield_inclination_pct",   "前盾倾角",       "%",        "std"),
        ("gripper_shield_inclination_pct", "撑紧盾倾角",     "%",        "std"),
        ("thrust_pressure_range_bar",      "推进压力极差",   "bar",      "hi"),
    ],
    "hydraulic_instability": [
        ("main_pump_pressure_bar",         "主推进泵压力",   "bar",      "std"),
        ("main_push_ctrl_pressure_bar",    "控制油压力",     "bar",      "std"),
        ("thrust_pressure_std_bar",        "推进压力组标准差","bar",     "hi"),
        ("thrust_pressure_range_bar",      "推进压力极差",   "bar",      "hi"),
    ],
}


# ── 内部辅助 ───────────────────────────────────────────────────────────────────

def _value_summary(s: pd.Series) -> Optional[ValueSummary]:
    """计算窗口内统计摘要，若全为 NaN 返回 None。"""
    valid = s.dropna()
    if valid.empty:
        return None
    start_v = float(s.iloc[0]) if pd.notna(s.iloc[0]) else float(valid.iloc[0])
    end_v   = float(s.iloc[-1]) if pd.notna(s.iloc[-1]) else float(valid.iloc[-1])
    change_pct: Optional[float] = None
    if abs(start_v) > 1e-9:
        change_pct = round((end_v - start_v) / abs(start_v) * 100, 1)
    return ValueSummary(
        mean=round(float(valid.mean()), 2),
        min=round(float(valid.min()), 2),
        max=round(float(valid.max()), 2),
        start=round(start_v, 2),
        end=round(end_v, 2),
        change_pct=change_pct,
    )


def _direction(vs: ValueSummary, expected: str) -> str:
    """根据期望方向和实际统计推断 direction 标签。"""
    if expected == "hi":
        return "up"
    if expected == "lo":
        return "down"
    if expected in ("diff", "std"):
        # 用极差/标准差判断：max-min 相对均值超过 20% 视为 unstable/imbalanced
        spread = vs.max - vs.min
        if abs(vs.mean) > 1e-9 and spread / abs(vs.mean) > 0.2:
            return "imbalanced" if expected == "diff" else "unstable"
        return "normal"
    return "normal"


def _magnitude_text(vs: ValueSummary, unit: str, display: str) -> str:
    """生成量级描述文本。"""
    return f"均值 {vs.mean:,.1f} {unit}，峰值 {vs.max:,.1f} {unit}"


def _evidence_text(display: str, direction: str, vs: ValueSummary, unit: str) -> str:
    """生成一句话证据文本。"""
    if direction == "up":
        return f"事件窗口内{display}持续偏高，均值 {vs.mean:,.1f} {unit}，峰值达 {vs.max:,.1f} {unit}"
    if direction == "down":
        return f"事件窗口内{display}维持低位，均值 {vs.mean:,.1f} {unit}，最低 {vs.min:,.1f} {unit}"
    if direction == "unstable":
        spread = vs.max - vs.min
        return f"事件窗口内{display}波动明显，极差 {spread:,.1f} {unit}（{vs.min:,.1f}~{vs.max:,.1f}）"
    if direction == "imbalanced":
        spread = vs.max - vs.min
        return f"事件窗口内{display}持续偏大，均值 {vs.mean:,.1f} {unit}，最大 {vs.max:,.1f} {unit}"
    return f"事件窗口内{display}均值 {vs.mean:,.1f} {unit}（{vs.min:,.1f}~{vs.max:,.1f}）"


def _locate_event_window(
    df: pd.DataFrame,
    event: Event,
) -> tuple[int, int]:
    """
    定位事件在 df 中的 iloc 范围。

    优先用 timestamp 精确匹配；若无时间戳则回退到全表范围。
    返回 (iloc_start, iloc_end)（含端点）。
    """
    if event.start_time is not None and "timestamp" in df.columns:
        ts = df["timestamp"]
        mask = (ts >= event.start_time) & (ts <= event.end_time)
        idxs = np.where(mask.to_numpy())[0]
        if len(idxs) > 0:
            return int(idxs[0]), int(idxs[-1])
    return 0, len(df) - 1


# ── 公开接口 ───────────────────────────────────────────────────────────────────

def extract_evidence(
    df: pd.DataFrame,
    events: list[Event],
    max_signals: int = 5,
    event_states: Optional[dict] = None,
) -> list[EventEvidence]:
    """
    为每个 Event 提取关键证据信号。

    Args:
        df:           enriched DataFrame（含原始列 + 特征列）
        events:       segment_events() 的输出
        max_signals:  每个事件最多保留的证据条数（默认 5）
        event_states: dict[event_id → EventStateSummary]，由 state_engine 提供；
                      若传入则填充 EventEvidence.dominant_state / state_distribution

    Returns:
        EventEvidence 列表，顺序与 events 一致
    """
    results: list[EventEvidence] = []

    for event in events:
        iloc_start, iloc_end = _locate_event_window(df, event)
        window = df.iloc[iloc_start : iloc_end + 1]

        specs = _SIGNAL_SPECS.get(event.event_type, [])
        signals: list[SignalEvidence] = []

        for col, display, unit, expected in specs:
            if col not in window.columns:
                logger.debug("evidence: col '%s' missing for event %s", col, event.event_id)
                continue
            vs = _value_summary(window[col])
            if vs is None:
                continue
            direction = _direction(vs, expected)
            signals.append(SignalEvidence(
                signal_name=col,
                display_name=display,
                direction=direction,
                magnitude_text=_magnitude_text(vs, unit, display),
                evidence_text=_evidence_text(display, direction, vs, unit),
                value_summary=vs,
            ))
            if len(signals) >= max_signals:
                break

        results.append(EventEvidence(
            event_id=event.event_id,
            event_type=event.event_type,
            start_time=event.start_time,
            end_time=event.end_time,
            severity_score=event.peak_score,
            top_signals=signals,
            dominant_state=event_states[event.event_id].dominant_state if event_states and event.event_id in event_states else None,
            state_distribution=event_states[event.event_id].state_distribution if event_states and event.event_id in event_states else None,
        ))

        logger.debug(
            "evidence: event %s → %d signals extracted",
            event.event_id, len(signals),
        )

    return results
