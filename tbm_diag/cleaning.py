"""
cleaning.py — 缺失值处理、尖峰去除、均匀时间网格重采样

职责：
- 输入：IngestionResult.df（已重命名 + 已转换数值，未清洗）
- 输出：(cleaned_df, CleaningReport)
- 不涉及任何异常检测逻辑，不修改 schema 定义
- 单位可疑字段（raw_ 前缀）跳过 IQR 尖峰检测，原样保留

清洗流程：
  1. 去除时间戳为 NaT 的行
  2. 时间戳去重（保留最后一条）
  3. 按时间戳升序排列，设为索引
  4. IQR 尖峰去除（宽松 k=5，单位可疑列跳过）
  5. 重采样到均匀时间网格（默认 1s，可关闭）
  6. 缺失值填充（默认前向填充，最多连续填充 5 步）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from tbm_diag.schema import SUSPICIOUS_UNIT_FIELDS, TIMESTAMP_CANONICAL

logger = logging.getLogger(__name__)


# ── 报告数据类 ─────────────────────────────────────────────────────────────────

@dataclass
class CleaningReport:
    """clean() 的清洗统计摘要，供 CLI 打印和后续模块审计。"""

    rows_input: int
    """进入清洗前的总行数。"""

    rows_after_ts_drop: int
    """去除 NaT 时间戳行后的行数。"""

    rows_after_dedup: int
    """时间戳去重后的行数。"""

    rows_output: int
    """清洗 + 重采样后最终输出行数。"""

    null_counts_before: dict[str, int]
    """各数值列清洗前（尖峰去除前）的 NaN 数量。"""

    null_counts_after: dict[str, int]
    """各数值列填充后的残余 NaN 数量。"""

    spike_removed: dict[str, int]
    """各列通过 IQR 被置为 NaN 的点数（0 = 未检测或无尖峰）。"""

    resample_freq: Optional[str]
    """实际使用的重采样频率（None = 未重采样）。"""

    warnings: list[str] = field(default_factory=list)
    """清洗过程中产生的警告信息列表。"""


# ── 内部辅助 ───────────────────────────────────────────────────────────────────

def _remove_spikes_iqr(
    series: pd.Series,
    k: float = 5.0,
) -> tuple[pd.Series, int]:
    """
    IQR 法尖峰检测：将 [Q1 - k*IQR, Q3 + k*IQR] 范围外的值置 NaN。

    选择 k=5（宽松）原因：
    - TBM 数据中压力/行程在特殊工况下本身有大幅跃变（非异常）
    - 过严（k=1.5）会误杀正常工程极值
    - 后续 detector.py 用专用阈值做异常判断，这里只清除采集故障

    若列全为 NaN 或 IQR=0（常数列），跳过检测返回原列。

    Returns:
        (cleaned_series, n_removed)
    """
    valid = series.dropna()
    if valid.empty:
        return series, 0

    q1 = valid.quantile(0.25)
    q3 = valid.quantile(0.75)
    iqr = q3 - q1

    if iqr == 0:
        # 常数列（如停机时压力固定），不做尖峰检测
        return series, 0

    lo = q1 - k * iqr
    hi = q3 + k * iqr
    spike_mask = (series < lo) | (series > hi)
    n_removed = int(spike_mask.sum())

    if n_removed == 0:
        return series, 0

    cleaned = series.copy()
    cleaned[spike_mask] = np.nan
    logger.debug(
        "IQR spike: col='%s' k=%.1f bounds=[%.3f, %.3f] removed=%d",
        series.name, k, lo, hi, n_removed,
    )
    return cleaned, n_removed


# ── 公开接口 ───────────────────────────────────────────────────────────────────

def clean(
    df: pd.DataFrame,
    resample_freq: Optional[str] = "1s",
    spike_k: float = 5.0,
    fill_method: str = "ffill",
    max_gap_fill: int = 5,
    skip_spike_cols: Optional[set[str]] = None,
) -> tuple[pd.DataFrame, CleaningReport]:
    """
    对 ingestion 输出的 DataFrame 执行基础清洗。

    Args:
        df:              IngestionResult.df（timestamp 为普通列，非索引）
        resample_freq:   重采样目标频率，pandas offset alias（如 '1s' '5s' '1min'）；
                         None = 跳过重采样，保留原始时间间隔。
        spike_k:         IQR 倍数阈值（默认 5.0，越大越宽松）。
        fill_method:     缺失值填充方式：
                         'ffill'  — 前向填充（适合步进信号如行程）
                         'linear' — 线性插值（适合连续变化信号如速度）
        max_gap_fill:    前向填充/插值的最大连续步数，超出部分保留 NaN。
        skip_spike_cols: 额外跳过 IQR 检测的标准列名集合
                         （单位可疑字段自动跳过，无需在此传入）。

    Returns:
        (cleaned_df, CleaningReport)
        cleaned_df 的 timestamp 列重置为普通列（非索引）。
    """
    df = df.copy()
    warnings: list[str] = []
    rows_input = len(df)

    # ── 检查时间戳列是否存在 ───────────────────────────────────────────────────
    has_ts = TIMESTAMP_CANONICAL in df.columns
    if not has_ts:
        warnings.append(
            f"缺少时间戳列 '{TIMESTAMP_CANONICAL}'，跳过时间相关步骤（去重、重采样）"
        )
        logger.warning("No timestamp column — time-based steps will be skipped")

    # ── 步骤 1：去除时间戳 NaT 行 ─────────────────────────────────────────────
    if has_ts:
        n_before = len(df)
        df = df.dropna(subset=[TIMESTAMP_CANONICAL])
        n_dropped = n_before - len(df)
        if n_dropped:
            warnings.append(f"去除 NaT 时间戳行: {n_dropped} 行")
            logger.info("Dropped %d NaT-timestamp rows", n_dropped)
    rows_after_ts_drop = len(df)

    # ── 步骤 2：时间戳去重（保留最后一条，兼容重复采集） ──────────────────────
    if has_ts:
        n_before = len(df)
        df = (
            df.sort_values(TIMESTAMP_CANONICAL)
              .drop_duplicates(subset=[TIMESTAMP_CANONICAL], keep="last")
        )
        n_dedup = n_before - len(df)
        if n_dedup:
            warnings.append(f"去除重复时间戳行: {n_dedup} 行（保留最后一条）")
            logger.info("Dropped %d duplicate-timestamp rows", n_dedup)
    rows_after_dedup = len(df)

    # ── 步骤 3：设置时间戳为索引（后续重采样需要） ────────────────────────────
    if has_ts:
        df = df.set_index(TIMESTAMP_CANONICAL)

    # ── 步骤 4：识别数值列，确定跳过集合 ──────────────────────────────────────
    numeric_cols: list[str] = df.select_dtypes(include="number").columns.tolist()

    # 自动跳过：单位可疑字段 + 调用方传入的列
    _skip = SUSPICIOUS_UNIT_FIELDS | (skip_spike_cols or set())

    # ── 步骤 5：记录清洗前 NaN 基线 ────────────────────────────────────────────
    null_before: dict[str, int] = {
        col: int(df[col].isna().sum()) for col in numeric_cols
    }

    # ── 步骤 6：IQR 尖峰去除 ───────────────────────────────────────────────────
    spike_removed: dict[str, int] = {}
    for col in numeric_cols:
        if col in _skip:
            spike_removed[col] = 0
            continue
        df[col], n = _remove_spikes_iqr(df[col], k=spike_k)
        spike_removed[col] = n

    total_spikes = sum(spike_removed.values())
    if total_spikes:
        logger.info("Total spike points removed: %d", total_spikes)

    # ── 步骤 7：重采样到均匀时间网格 ──────────────────────────────────────────
    actual_resample_freq: Optional[str] = None
    if has_ts and resample_freq:
        try:
            # 数值列取均值（重采样窗口内平均），保留时序语义
            # 非数值列（字符串等）取最后值
            obj_cols = [c for c in df.columns if c not in numeric_cols]
            agg_dict: dict[str, str] = {col: "mean" for col in numeric_cols}
            agg_dict.update({col: "last" for col in obj_cols})

            df = df.resample(resample_freq).agg(agg_dict)
            actual_resample_freq = resample_freq
            logger.info(
                "Resampled to freq='%s' → %d rows", resample_freq, len(df)
            )
        except Exception as exc:
            msg = f"重采样失败（freq='{resample_freq}'）: {exc}，已跳过"
            warnings.append(msg)
            logger.warning(msg)

    # ── 步骤 8：缺失值填充 ─────────────────────────────────────────────────────
    for col in numeric_cols:
        if df[col].isna().any():
            if fill_method == "linear" and has_ts:
                # time 插值需要 DatetimeIndex
                df[col] = df[col].interpolate(
                    method="time", limit=max_gap_fill, limit_direction="forward"
                )
            else:
                df[col] = df[col].ffill(limit=max_gap_fill)

    # ── 步骤 9：记录填充后残余 NaN ────────────────────────────────────────────
    null_after: dict[str, int] = {
        col: int(df[col].isna().sum()) for col in numeric_cols
    }
    residual_nan_cols = [col for col, n in null_after.items() if n > 0]
    if residual_nan_cols:
        logger.info(
            "%d column(s) still have NaN after filling (max_gap_fill=%d): %s",
            len(residual_nan_cols), max_gap_fill,
            residual_nan_cols[:5],
        )

    # ── 步骤 10：将时间戳索引重置为普通列 ─────────────────────────────────────
    if has_ts:
        df = df.reset_index()

    report = CleaningReport(
        rows_input=rows_input,
        rows_after_ts_drop=rows_after_ts_drop,
        rows_after_dedup=rows_after_dedup,
        rows_output=len(df),
        null_counts_before=null_before,
        null_counts_after=null_after,
        spike_removed=spike_removed,
        resample_freq=actual_resample_freq,
        warnings=warnings,
    )
    return df, report
