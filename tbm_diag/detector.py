"""
detector.py — 第一版异常点检测器

职责：
- 输入：enrich_features() 输出的 DataFrame（含原始列 + 衍生特征列）
- 输出：detect(df) -> DetectionResult，包含带 is_xxx / score_xxx 列的 DataFrame

四类异常：
  A. suspected_excavation_resistance  — 疑似掘进阻力异常
  B. low_efficiency_excavation        — 低效掘进
  C. attitude_or_bias_risk            — 姿态偏斜风险
  D. hydraulic_instability            — 液压系统不稳定

设计原则：
- 所有阈值集中在 DetectorConfig 中，不散落在规则逻辑里
- 缺少依赖列时自动跳过对应规则，不报错
- 每类异常输出 is_xxx（bool）和 score_xxx（0~1 float）两列
- score 由命中子规则数 / 总子规则数线性归一化
- 不依赖 LLM，不含任何文本解释（解释在 explainer.py）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── 阈值配置 ───────────────────────────────────────────────────────────────────

@dataclass
class DetectorConfig:
    """
    所有检测阈值的集中配置。

    命名约定：
      {异常类型}_{字段语义}_{hi|lo}
      hi = 超过此值触发，lo = 低于此值触发
    """

    # ── A. suspected_excavation_resistance ────────────────────────────────────
    # 刀盘转矩滚动均值偏高（kNm）
    resist_torque_rolling_hi: float = 3000.0
    # 推进速度滚动均值偏低（mm/min）
    resist_speed_rolling_lo: float = 20.0
    # 贯入度滚动均值偏低（mm/rev）
    resist_penetration_rolling_lo: float = 5.0
    # 转矩/速度比值偏高（kNm·min/mm）
    resist_torque_speed_ratio_hi: float = 200.0

    # ── B. low_efficiency_excavation ──────────────────────────────────────────
    # 推进速度长期偏低（mm/min）
    loweff_speed_rolling_lo: float = 15.0
    # 贯入度偏低（mm/rev）
    loweff_penetration_rolling_lo: float = 3.0
    # 转矩不高（区分于 A 类）：转矩滚动均值低于此值时才判为低效（非阻力）
    loweff_torque_rolling_hi: float = 2500.0

    # ── C. attitude_or_bias_risk ──────────────────────────────────────────────
    # 稳定器行程差偏大（mm）
    attitude_stab_stroke_diff_hi: float = 30.0
    # 稳定器压力差偏大（bar）
    attitude_stab_pressure_diff_hi: float = 50.0
    # 前盾/撑紧盾倾角滚动标准差偏大（%）
    attitude_pitch_std_hi: float = 0.5
    # 推进压力极差偏大（bar）
    attitude_thrust_pressure_range_hi: float = 80.0

    # ── D. hydraulic_instability ──────────────────────────────────────────────
    # 主泵压力滚动标准差偏大（bar）
    hydro_main_pump_std_hi: float = 30.0
    # 控制油压力滚动标准差偏大（bar）
    hydro_ctrl_pressure_std_hi: float = 20.0
    # 推进压力组标准差偏大（bar）
    hydro_thrust_pressure_std_hi: float = 40.0
    # 主泵压力单步变化率偏大（绝对值，bar/step）
    hydro_main_pump_pct_change_hi: float = 0.15


# ── 结果数据类 ─────────────────────────────────────────────────────────────────

@dataclass
class DetectionResult:
    """detect() 的输出。"""

    df: pd.DataFrame
    """原始 + 特征 + 检测列（is_xxx / score_xxx）的完整 DataFrame。"""

    hit_counts: dict[str, int]
    """各异常类型命中点数，key = 异常类型名。"""

    skipped_rules: dict[str, list[str]]
    """各异常类型中因缺列而跳过的子规则列表。"""

    total_rows: int
    """检测的总行数。"""


# ── 内部工具 ───────────────────────────────────────────────────────────────────

def _col(df: pd.DataFrame, name: str) -> Optional[pd.Series]:
    """安全取列：存在且非全 NaN 则返回 Series，否则返回 None。"""
    if name in df.columns and df[name].notna().any():
        return df[name]
    return None


def _flag_and_score(
    df: pd.DataFrame,
    anomaly_name: str,
    conditions: list[tuple[str, pd.Series]],
    skipped: list[str],
) -> None:
    """
    将多个子条件合并为 is_{name} 和 score_{name} 列，就地写入 df。

    Args:
        anomaly_name: 异常类型名（不含 is_ 前缀）
        conditions:   [(rule_name, bool_series), ...]，每个 Series 为该子规则命中情况
        skipped:      因缺列跳过的子规则名列表（用于分母修正）
    """
    if not conditions:
        # 所有子规则都跳过，不写列
        logger.debug("detector: all rules skipped for '%s'", anomaly_name)
        return

    n_rules = len(conditions)
    hit_sum = pd.Series(np.zeros(len(df), dtype=np.float32), index=df.index)

    for rule_name, mask in conditions:
        hit_sum += mask.fillna(False).astype(np.float32)
        logger.debug(
            "detector: rule '%s.%s' hit %d/%d rows",
            anomaly_name, rule_name, int(mask.sum()), len(df),
        )

    score = hit_sum / n_rules
    df[f"is_{anomaly_name}"] = score >= 0.5   # 超过半数子规则命中即触发
    df[f"score_{anomaly_name}"] = score.round(4)


# ── 四类检测函数 ───────────────────────────────────────────────────────────────

def _detect_excavation_resistance(
    df: pd.DataFrame,
    cfg: DetectorConfig,
) -> tuple[list[tuple[str, pd.Series]], list[str]]:
    """A. 疑似掘进阻力异常"""
    conditions: list[tuple[str, pd.Series]] = []
    skipped: list[str] = []

    # 子规则 1：刀盘转矩滚动均值偏高
    torque_rm = _col(df, "cutter_torque_kNm_rolling_mean_5")
    if torque_rm is not None:
        conditions.append(("torque_rolling_hi", torque_rm > cfg.resist_torque_rolling_hi))
    else:
        skipped.append("torque_rolling_hi")

    # 子规则 2：推进速度滚动均值偏低
    speed_rm = _col(df, "advance_speed_mm_per_min_rolling_mean_5")
    if speed_rm is not None:
        conditions.append(("speed_rolling_lo", speed_rm < cfg.resist_speed_rolling_lo))
    else:
        skipped.append("speed_rolling_lo")

    # 子规则 3：贯入度滚动均值偏低
    pen_rm = _col(df, "penetration_rate_mm_per_rev_rolling_mean_5")
    if pen_rm is not None:
        conditions.append(("penetration_rolling_lo", pen_rm < cfg.resist_penetration_rolling_lo))
    else:
        skipped.append("penetration_rolling_lo")

    # 子规则 4：转矩/速度比值偏高
    ratio = _col(df, "torque_to_speed_ratio")
    if ratio is not None:
        conditions.append(("torque_speed_ratio_hi", ratio > cfg.resist_torque_speed_ratio_hi))
    else:
        skipped.append("torque_speed_ratio_hi")

    return conditions, skipped


def _detect_low_efficiency(
    df: pd.DataFrame,
    cfg: DetectorConfig,
) -> tuple[list[tuple[str, pd.Series]], list[str]]:
    """B. 低效掘进"""
    conditions: list[tuple[str, pd.Series]] = []
    skipped: list[str] = []

    # 子规则 1：推进速度长期偏低
    speed_rm = _col(df, "advance_speed_mm_per_min_rolling_mean_5")
    if speed_rm is not None:
        conditions.append(("speed_rolling_lo", speed_rm < cfg.loweff_speed_rolling_lo))
    else:
        skipped.append("speed_rolling_lo")

    # 子规则 2：贯入度偏低
    pen_rm = _col(df, "penetration_rate_mm_per_rev_rolling_mean_5")
    if pen_rm is not None:
        conditions.append(("penetration_rolling_lo", pen_rm < cfg.loweff_penetration_rolling_lo))
    else:
        skipped.append("penetration_rolling_lo")

    # 子规则 3：转矩不高（区分于 A 类阻力异常）
    torque_rm = _col(df, "cutter_torque_kNm_rolling_mean_5")
    if torque_rm is not None:
        # 转矩低于阻力阈值 → 低效而非阻力
        conditions.append(("torque_not_extreme", torque_rm < cfg.loweff_torque_rolling_hi))
    else:
        skipped.append("torque_not_extreme")

    return conditions, skipped


def _detect_attitude_bias(
    df: pd.DataFrame,
    cfg: DetectorConfig,
) -> tuple[list[tuple[str, pd.Series]], list[str]]:
    """C. 姿态偏斜风险"""
    conditions: list[tuple[str, pd.Series]] = []
    skipped: list[str] = []

    # 子规则 1：稳定器行程差偏大
    stab_diff = _col(df, "stabilizer_stroke_diff_mm")
    if stab_diff is not None:
        conditions.append(("stab_stroke_diff_hi", stab_diff.abs() > cfg.attitude_stab_stroke_diff_hi))
    else:
        skipped.append("stab_stroke_diff_hi")

    # 子规则 2：稳定器压力差偏大
    p_diff = _col(df, "stabilizer_pressure_diff_bar")
    if p_diff is not None:
        conditions.append(("stab_pressure_diff_hi", p_diff.abs() > cfg.attitude_stab_pressure_diff_hi))
    else:
        skipped.append("stab_pressure_diff_hi")

    # 子规则 3：前盾倾角滚动标准差偏大
    front_std = _col(df, "front_shield_inclination_pct_rolling_std_5")
    if front_std is not None:
        conditions.append(("front_pitch_std_hi", front_std > cfg.attitude_pitch_std_hi))
    else:
        skipped.append("front_pitch_std_hi")

    # 子规则 4：撑紧盾倾角滚动标准差偏大
    gripper_std = _col(df, "gripper_shield_inclination_pct_rolling_std_5")
    if gripper_std is not None:
        conditions.append(("gripper_pitch_std_hi", gripper_std > cfg.attitude_pitch_std_hi))
    else:
        skipped.append("gripper_pitch_std_hi")

    # 子规则 5：推进压力极差偏大
    p_range = _col(df, "thrust_pressure_range_bar")
    if p_range is not None:
        conditions.append(("thrust_pressure_range_hi", p_range > cfg.attitude_thrust_pressure_range_hi))
    else:
        skipped.append("thrust_pressure_range_hi")

    return conditions, skipped


def _detect_hydraulic_instability(
    df: pd.DataFrame,
    cfg: DetectorConfig,
) -> tuple[list[tuple[str, pd.Series]], list[str]]:
    """D. 液压系统不稳定"""
    conditions: list[tuple[str, pd.Series]] = []
    skipped: list[str] = []

    # 子规则 1：主泵压力滚动标准差偏大
    pump_std = _col(df, "main_pump_pressure_bar_rolling_std_5")
    if pump_std is not None:
        conditions.append(("main_pump_std_hi", pump_std > cfg.hydro_main_pump_std_hi))
    else:
        skipped.append("main_pump_std_hi")

    # 子规则 2：控制油压力滚动标准差偏大
    ctrl_std = _col(df, "main_push_ctrl_pressure_bar_rolling_std_5")
    if ctrl_std is not None:
        conditions.append(("ctrl_pressure_std_hi", ctrl_std > cfg.hydro_ctrl_pressure_std_hi))
    else:
        skipped.append("ctrl_pressure_std_hi")

    # 子规则 3：推进压力组标准差偏大（跨 A~F 组）
    thrust_std = _col(df, "thrust_pressure_std_bar")
    if thrust_std is not None:
        conditions.append(("thrust_pressure_std_hi", thrust_std > cfg.hydro_thrust_pressure_std_hi))
    else:
        skipped.append("thrust_pressure_std_hi")

    # 子规则 4：主泵压力单步变化率偏大（短时抖动）
    pump_pct = _col(df, "main_pump_pressure_bar_pct_change_1")
    if pump_pct is not None:
        conditions.append(("main_pump_pct_change_hi", pump_pct.abs() > cfg.hydro_main_pump_pct_change_hi))
    else:
        skipped.append("main_pump_pct_change_hi")

    return conditions, skipped


# ── 公开接口 ───────────────────────────────────────────────────────────────────

def detect(
    df: pd.DataFrame,
    config: Optional[DetectorConfig] = None,
) -> DetectionResult:
    """
    对特征增强后的 DataFrame 执行四类异常点检测。

    Args:
        df:     enrich_features() 的输出（含原始列 + 衍生特征列）
        config: 阈值配置，None 时使用默认值

    Returns:
        DetectionResult，其中 .df 包含所有原始列 + 特征列 + 检测列
    """
    cfg = config or DetectorConfig()
    df = df.copy()

    all_skipped: dict[str, list[str]] = {}

    # ── A. 疑似掘进阻力异常 ───────────────────────────────────────────────────
    conds_a, skip_a = _detect_excavation_resistance(df, cfg)
    _flag_and_score(df, "suspected_excavation_resistance", conds_a, skip_a)
    all_skipped["suspected_excavation_resistance"] = skip_a

    # ── B. 低效掘进 ───────────────────────────────────────────────────────────
    conds_b, skip_b = _detect_low_efficiency(df, cfg)
    _flag_and_score(df, "low_efficiency_excavation", conds_b, skip_b)
    all_skipped["low_efficiency_excavation"] = skip_b

    # ── C. 姿态偏斜风险 ───────────────────────────────────────────────────────
    conds_c, skip_c = _detect_attitude_bias(df, cfg)
    _flag_and_score(df, "attitude_or_bias_risk", conds_c, skip_c)
    all_skipped["attitude_or_bias_risk"] = skip_c

    # ── D. 液压系统不稳定 ─────────────────────────────────────────────────────
    conds_d, skip_d = _detect_hydraulic_instability(df, cfg)
    _flag_and_score(df, "hydraulic_instability", conds_d, skip_d)
    all_skipped["hydraulic_instability"] = skip_d

    # ── 统计命中点数 ──────────────────────────────────────────────────────────
    anomaly_names = [
        "suspected_excavation_resistance",
        "low_efficiency_excavation",
        "attitude_or_bias_risk",
        "hydraulic_instability",
    ]
    hit_counts: dict[str, int] = {}
    for name in anomaly_names:
        col = f"is_{name}"
        hit_counts[name] = int(df[col].sum()) if col in df.columns else 0

    logger.info(
        "Detection complete: %d rows, hits=%s",
        len(df),
        {k: v for k, v in hit_counts.items() if v > 0},
    )

    return DetectionResult(
        df=df,
        hit_counts=hit_counts,
        skipped_rules=all_skipped,
        total_rows=len(df),
    )
