"""
feature_engine.py — 衍生特征计算

基于清洗后的标准化 DataFrame 计算检测所需的时序特征。
所有原始字段保留，新增特征列以后缀追加。

设计原则：
- 若原始字段缺失则自动跳过对应特征，不报错
- 特征命名统一：{原始列名}_{特征后缀}
- 不做异常检测，只做特征工程
- 除零保护：比值型特征中分母为 0 时结果为 NaN

输出特征列表：
  ┌─────────────────────────────────────────────────────────────────┐
  │ 逐列滚动特征（对 ROLLING_FEATURE_COLS 中每一列生成）            │
  │  1. {col}_rolling_mean_{w}     滚动均值                        │
  │  2. {col}_rolling_std_{w}      滚动标准差                      │
  │  3. {col}_slope_{w}            窗口内线性回归斜率               │
  │  4. {col}_pct_change           单步百分比变化                   │
  ├─────────────────────────────────────────────────────────────────┤
  │ 跨列特征                                                       │
  │  5. thrust_pressure_range_bar  A~F 组推进压力极差               │
  │  6. thrust_pressure_std_bar    A~F 组推进压力标准差             │
  │  7. thrust_stroke_range_mm     A~F 组推进行程极差               │
  │  8. stabilizer_stroke_diff_mm  左右稳定器行程差（绝对值）       │
  │  9. stabilizer_pressure_diff_bar 左右稳定器压力差（绝对值）     │
  │ 10. torque_to_speed_ratio      刀盘转矩 / 推进速度             │
  │ 11. thrust_to_speed_ratio      总推进力 / 推进速度             │
  └─────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── 列名常量 ───────────────────────────────────────────────────────────────────
# 使用 schema.py 中定义的 canonical 名称，与上游模块完全一致。

# 需要生成逐列滚动特征的核心字段
ROLLING_FEATURE_COLS: list[str] = [
    # 刀盘
    "cutter_speed_rpm",
    "cutter_torque_kNm",
    # 推进
    "total_thrust_kN",
    "penetration_rate_mm_per_rev",
    "advance_speed_mm_per_min",
    # 盾体姿态
    "front_shield_inclination_pct",
    "gripper_shield_inclination_pct",
    # 液压压力
    "main_pump_pressure_bar",
    "main_push_ctrl_pressure_bar",
    # 稳定器压力
    "top_left_stab_rodless_pressure_bar",
    "top_right_stab_rodless_pressure_bar",
]

# A~F 组推进油缸压力（跨列统计用）
THRUST_PRESSURE_COLS: list[str] = [
    f"thrust_cyl_{g}_pressure_bar" for g in "ABCDEF"
]

# A~F 组推进油缸行程（跨列统计用）
THRUST_STROKE_COLS: list[str] = [
    f"thrust_cyl_{g}_stroke_mm" for g in "ABCDEF"
]


# ── 内部辅助 ───────────────────────────────────────────────────────────────────

def _safe_cols(df: pd.DataFrame, candidates: list[str]) -> list[str]:
    """返回 candidates 中 df 实际包含的列名子集（保持顺序）。"""
    return [c for c in candidates if c in df.columns]


# 预计算斜率回归系数（窗口固定时只算一次）
_SLOPE_CACHE: dict[int, np.ndarray] = {}


def _get_slope_weights(window: int) -> np.ndarray:
    """
    返回等间距简单线性回归的 x 系数向量（缓存）。

    对等间距 x=[0,1,...,n-1]，斜率 = sum(x_centered * y) / sum(x_centered^2)。
    预计算 x_centered / sum(x_centered^2) 作为权重向量，
    斜率 = dot(weights, y - y.mean()) = dot(weights, y) - mean(y) * sum(weights)。
    由于 x_centered 求和为 0，简化为 slope = dot(weights, y)。
    """
    if window not in _SLOPE_CACHE:
        x = np.arange(window, dtype=np.float64)
        x_centered = x - x.mean()
        denom = (x_centered ** 2).sum()
        # denom > 0 因为 window >= 2
        _SLOPE_CACHE[window] = x_centered / denom
    return _SLOPE_CACHE[window]


def _add_rolling_stats(
    df: pd.DataFrame,
    col: str,
    window: int,
) -> None:
    """
    为单列就地添加 4 类滚动特征。

    产出列：
        {col}_rolling_mean_{window}
        {col}_rolling_std_{window}
        {col}_slope_{window}
        {col}_pct_change
    """
    s = df[col]

    # 1) 滚动均值（min_periods=1：首几行也有结果）
    df[f"{col}_rolling_mean_{window}"] = (
        s.rolling(window, min_periods=1).mean()
    )

    # 2) 滚动标准差（至少 2 点才有意义）
    df[f"{col}_rolling_std_{window}"] = (
        s.rolling(window, min_periods=2).std()
    )

    # 3) 窗口内线性回归斜率
    #    slope = dot(weights, y_values)，其中 weights 对称于窗口中心
    weights = _get_slope_weights(window)

    def _slope_fn(y: np.ndarray) -> float:
        return float(np.dot(weights, y))

    df[f"{col}_slope_{window}"] = (
        s.rolling(window, min_periods=window).apply(_slope_fn, raw=True)
    )

    # 4) 单步百分比变化（fill_method=None 避免 pandas 2.x FutureWarning）
    df[f"{col}_pct_change_1"] = s.pct_change(periods=1, fill_method=None)


def _add_cross_column_features(df: pd.DataFrame) -> None:
    """计算跨列衍生特征（极差、差值、比值）。所有操作就地修改 df。"""

    # ── 推进压力组特征 (A~F) ────────────────────────────────────────────────────
    pcols = _safe_cols(df, THRUST_PRESSURE_COLS)
    if len(pcols) >= 2:
        pdf = df[pcols]
        df["thrust_pressure_range_bar"] = pdf.max(axis=1) - pdf.min(axis=1)
        df["thrust_pressure_std_bar"] = pdf.std(axis=1)
        logger.debug(
            "thrust_pressure_range_bar / _std_bar computed from %d pressure cols",
            len(pcols),
        )

    # ── 推进行程组特征 (A~F) ────────────────────────────────────────────────────
    scols = _safe_cols(df, THRUST_STROKE_COLS)
    if len(scols) >= 2:
        sdf = df[scols]
        df["thrust_stroke_range_mm"] = sdf.max(axis=1) - sdf.min(axis=1)
        logger.debug(
            "thrust_stroke_range_mm computed from %d stroke cols", len(scols)
        )

    # ── 左右稳定器行程差（有符号：左 - 右，正值表示左侧伸出更多）────────────
    left_s, right_s = "left_stabilizer_stroke_mm", "right_stabilizer_stroke_mm"
    if left_s in df.columns and right_s in df.columns:
        df["stabilizer_stroke_diff_mm"] = df[left_s] - df[right_s]
        logger.debug("stabilizer_stroke_diff_mm computed")

    # ── 左右稳定器压力差（有符号：左 - 右）──────────────────────────────────
    left_p = "top_left_stab_rodless_pressure_bar"
    right_p = "top_right_stab_rodless_pressure_bar"
    if left_p in df.columns and right_p in df.columns:
        df["stabilizer_pressure_diff_bar"] = df[left_p] - df[right_p]
        logger.debug("stabilizer_pressure_diff_bar computed")

    # ── 转矩 / 推进速度 比值 ──────────────────────────────────────────────────
    torque_col = "cutter_torque_kNm"
    speed_col = "advance_speed_mm_per_min"
    if torque_col in df.columns and speed_col in df.columns:
        # 分母为 0 → NaN（避免 inf）
        safe_speed = df[speed_col].replace(0, np.nan)
        df["torque_to_speed_ratio"] = df[torque_col] / safe_speed
        logger.debug("torque_to_speed_ratio computed")

    # ── 总推进力 / 推进速度 比值 ──────────────────────────────────────────────
    thrust_col = "total_thrust_kN"
    if thrust_col in df.columns and speed_col in df.columns:
        safe_speed = df[speed_col].replace(0, np.nan)
        df["thrust_to_speed_ratio"] = df[thrust_col] / safe_speed
        logger.debug("thrust_to_speed_ratio computed")


# ── 公开接口 ───────────────────────────────────────────────────────────────────

def enrich_features(
    df: pd.DataFrame,
    window: int = 5,
) -> pd.DataFrame:
    """
    基于清洗后的标准化 DataFrame 计算衍生特征。

    所有原始列保留不变，新增特征列追加在右侧。

    Args:
        df:     清洗后的 DataFrame（来自 cleaning.clean()）
        window: 滚动统计窗口大小（默认 5 点）

    Returns:
        enriched_df: 新 DataFrame = 原始列 + 新增特征列
    """
    df = df.copy()
    n_before = len(df.columns)

    # ── 逐列滚动特征 ──────────────────────────────────────────────────────────
    present = _safe_cols(df, ROLLING_FEATURE_COLS)
    skipped = sorted(set(ROLLING_FEATURE_COLS) - set(present))

    for col in present:
        _add_rolling_stats(df, col, window=window)

    if present:
        logger.info(
            "Rolling features (window=%d) computed for %d columns: %s",
            window, len(present), present,
        )
    if skipped:
        logger.info(
            "Rolling features skipped for %d missing columns: %s",
            len(skipped), skipped,
        )

    # ── 跨列特征 ──────────────────────────────────────────────────────────────
    _add_cross_column_features(df)

    n_after = len(df.columns)
    logger.info(
        "Feature enrichment complete: %d -> %d columns (+%d features)",
        n_before, n_after, n_after - n_before,
    )

    return df
