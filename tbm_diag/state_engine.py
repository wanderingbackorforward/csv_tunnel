"""
state_engine.py — 工况状态识别层 v1

职责：
- 输入：enrich_features() 输出的 DataFrame（含 rolling mean 列）
- 输出：
    classify_states()       → 原 df + machine_state 列
    summarize_event_state() → EventStateSummary（事件窗口内主导状态）

识别的 4 类状态（优先级从高到低）：
  1. stopped              停机/静止
  2. heavy_load_excavation 重载推进
  3. low_load_operation   低负载运行
  4. normal_excavation    正常推进

设计原则：
- 优先复用 feature_engine 已计算的 rolling mean 列，不重复计算
- 缺字段自动降级，不报错
- 规则保守、可解释，v1 不追求精确，先做可运行版本
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from tbm_diag.segmenter import Event

logger = logging.getLogger(__name__)


# ── 状态枚举与中文名 ───────────────────────────────────────────────────────────

STATE_STOPPED = "stopped"
STATE_HEAVY   = "heavy_load_excavation"
STATE_LOW     = "low_load_operation"
STATE_NORMAL  = "normal_excavation"

ALL_STATES: list[str] = [STATE_STOPPED, STATE_HEAVY, STATE_LOW, STATE_NORMAL]

STATE_LABELS: dict[str, str] = {
    STATE_STOPPED: "停机/静止",
    STATE_HEAVY:   "重载推进",
    STATE_LOW:     "低负载运行",
    STATE_NORMAL:  "正常推进",
}


# ── 配置 ───────────────────────────────────────────────────────────────────────

@dataclass
class StateConfig:
    # ── stopped 判定阈值 ──────────────────────────────────────────────────────
    stopped_speed_threshold: float = 1.0
    """推进速度 <= 此值（mm/min）时视为停机候选。"""
    stopped_rpm_threshold: float = 0.1
    """刀盘转速 <= 此值（rpm）时视为停机候选。"""
    stopped_thrust_threshold: float = 200.0
    """总推进力 <= 此值（kN）时视为停机候选。"""

    # ── heavy_load 判定阈值 ───────────────────────────────────────────────────
    heavy_load_torque_threshold: float = 2000.0
    """刀盘转矩滚动均值 > 此值（kNm）时触发重载候选。"""
    heavy_load_thrust_threshold: float = 4000.0
    """总推进力滚动均值 > 此值（kN）时触发重载候选。"""
    heavy_load_penetration_threshold: float = 1.0
    """贯入度滚动均值 < 此值（mm/rev）时配合高转矩/高推力判为重载。"""

    # ── low_load 判定阈值 ─────────────────────────────────────────────────────
    low_load_speed_threshold: float = 5.0
    """推进速度 <= 此值（mm/min）但未达停机条件时视为低负载。"""

    rolling_window: int = 5
    """滚动窗口大小（与 feature_engine 保持一致，用于构造列名）。"""


# ── 内部辅助 ───────────────────────────────────────────────────────────────────

def _col(df: pd.DataFrame, name: str) -> Optional[pd.Series]:
    """安全取列；不存在或全 NaN 时返回 None。"""
    if name not in df.columns:
        return None
    s = df[name]
    if s.isna().all():
        return None
    return s


def _rolling_col(df: pd.DataFrame, base: str, window: int) -> Optional[pd.Series]:
    """取 feature_engine 生成的 rolling mean 列；不存在时回退到原始列。"""
    rm_name = f"{base}_rolling_mean_{window}"
    s = _col(df, rm_name)
    if s is not None:
        return s
    return _col(df, base)


# ── 公开接口 ───────────────────────────────────────────────────────────────────

def classify_states(
    df: pd.DataFrame,
    config: Optional[StateConfig] = None,
) -> pd.DataFrame:
    """
    对 DataFrame 每行打上工况状态标签。

    Args:
        df:     enrich_features() 输出的 DataFrame
        config: 状态识别配置，None 时使用默认值

    Returns:
        原 df 的副本，新增 'machine_state' 列（str）。
    """
    cfg = config or StateConfig()
    w = cfg.rolling_window
    df = df.copy()
    n = len(df)

    # ── 取关键列（优先 rolling mean，缺则原始列，再缺则 None）────────────────
    speed   = _col(df, "advance_speed_mm_per_min")
    rpm     = _col(df, "cutter_speed_rpm")
    thrust  = _col(df, "total_thrust_kN")
    torque_rm  = _rolling_col(df, "cutter_torque_kNm", w)
    thrust_rm  = _rolling_col(df, "total_thrust_kN", w)
    pen_rm     = _rolling_col(df, "penetration_rate_mm_per_rev", w)

    # ── 逐条件构建布尔 mask ───────────────────────────────────────────────────

    # stopped：speed 低 AND (rpm 低 OR rpm 缺) AND (thrust 低 OR thrust 缺)
    if speed is not None:
        m_speed_low = speed <= cfg.stopped_speed_threshold
    else:
        m_speed_low = pd.Series(False, index=df.index)

    if rpm is not None:
        m_rpm_low = rpm <= cfg.stopped_rpm_threshold
    else:
        m_rpm_low = pd.Series(True, index=df.index)   # 缺字段不阻止 stopped 判定

    if thrust is not None:
        m_thrust_low = thrust <= cfg.stopped_thrust_threshold
    else:
        m_thrust_low = pd.Series(True, index=df.index)

    mask_stopped = m_speed_low & m_rpm_low & m_thrust_low

    # heavy_load：(高转矩 OR 高推力) AND 低贯入度
    if torque_rm is not None:
        m_torque_hi = torque_rm > cfg.heavy_load_torque_threshold
    else:
        m_torque_hi = pd.Series(False, index=df.index)

    if thrust_rm is not None:
        m_thrust_hi = thrust_rm > cfg.heavy_load_thrust_threshold
    else:
        m_thrust_hi = pd.Series(False, index=df.index)

    if pen_rm is not None:
        m_pen_lo = pen_rm < cfg.heavy_load_penetration_threshold
    else:
        m_pen_lo = pd.Series(True, index=df.index)   # 缺贯入度时不阻止 heavy 判定

    mask_heavy = (m_torque_hi | m_thrust_hi) & m_pen_lo & ~mask_stopped

    # low_load：速度低但非停机
    if speed is not None:
        mask_low = (speed <= cfg.low_load_speed_threshold) & ~mask_stopped & ~mask_heavy
    else:
        mask_low = pd.Series(False, index=df.index)

    # normal：其余
    mask_normal = ~mask_stopped & ~mask_heavy & ~mask_low

    # ── 赋值（优先级：stopped > heavy > low > normal）────────────────────────
    state = pd.Series(STATE_NORMAL, index=df.index, dtype=object)
    state[mask_low]     = STATE_LOW
    state[mask_heavy]   = STATE_HEAVY
    state[mask_stopped] = STATE_STOPPED

    df["machine_state"] = state

    # 日志摘要
    counts = state.value_counts()
    total = len(state)
    logger.info(
        "State classification: stopped=%.1f%% heavy=%.1f%% low=%.1f%% normal=%.1f%%",
        counts.get(STATE_STOPPED, 0) / total * 100,
        counts.get(STATE_HEAVY,   0) / total * 100,
        counts.get(STATE_LOW,     0) / total * 100,
        counts.get(STATE_NORMAL,  0) / total * 100,
    )

    return df


# ── 事件级状态汇总 ─────────────────────────────────────────────────────────────

@dataclass
class EventStateSummary:
    event_id: str
    dominant_state: str
    """事件窗口内占比最高的状态（英文 key）。"""
    state_distribution: dict[str, float]
    """各状态占比，如 {"heavy_load_excavation": 0.82, "normal_excavation": 0.18}。"""
    state_note: str
    """简短中文说明，如"该事件主要发生在重载推进状态下"。"""


def summarize_event_state(
    df: pd.DataFrame,
    event: Event,
) -> EventStateSummary:
    """
    统计事件时间窗口内的工况状态分布，返回 EventStateSummary。

    df 必须已经过 classify_states()，含 'machine_state' 列。
    若 machine_state 列不存在，返回 dominant_state='unknown'。
    """
    if "machine_state" not in df.columns:
        return EventStateSummary(
            event_id=event.event_id,
            dominant_state="unknown",
            state_distribution={},
            state_note="（工况状态列不可用）",
        )

    # 定位事件 iloc 范围（与 evidence.py 逻辑一致）
    if event.start_time is not None and "timestamp" in df.columns:
        ts = df["timestamp"]
        mask = (ts >= event.start_time) & (ts <= event.end_time)
        idxs = np.where(mask.to_numpy())[0]
        if len(idxs) > 0:
            iloc_start, iloc_end = int(idxs[0]), int(idxs[-1])
        else:
            iloc_start, iloc_end = 0, len(df) - 1
    else:
        iloc_start, iloc_end = 0, len(df) - 1

    window_states = df["machine_state"].iloc[iloc_start : iloc_end + 1]
    total = len(window_states)
    if total == 0:
        dominant = STATE_NORMAL
        dist: dict[str, float] = {}
    else:
        counts = window_states.value_counts()
        dominant = str(counts.index[0])
        dist = {
            k: round(int(v) / total, 3)
            for k, v in counts.items()
            if round(int(v) / total, 3) > 0
        }

    label = STATE_LABELS.get(dominant, dominant)
    note = f"该事件主要发生在\"{label}\"状态下"

    logger.debug(
        "state summary: event %s → dominant=%s dist=%s",
        event.event_id, dominant, dist,
    )

    return EventStateSummary(
        event_id=event.event_id,
        dominant_state=dominant,
        state_distribution=dist,
        state_note=note,
    )
