"""
ingestion.py — CSV 加载、编码/分隔符自动检测、时间解析、数值转换

职责（仅此模块）：
- 检测文件编码：utf-8-sig → utf-8 → gbk → gb18030 → latin-1 回退
- 检测分隔符：逗号、分号、制表符、竖线
- 调用 schema.resolve_columns 建立字段映射
- 将时间戳列解析为 pandas datetime（coerce 模式）
- 将数值列转换为 float64（coerce 模式，无法解析置 NaN）
- 返回 IngestionResult（已重命名 + 已转换，不做清洗）
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import chardet
import pandas as pd

from tbm_diag.schema import (
    FIELD_CATALOG,
    SUSPICIOUS_UNIT_FIELDS,
    TIMESTAMP_CANONICAL,
    TIMESTAMP_RAW,
    resolve_columns,
)

logger = logging.getLogger(__name__)

# 编码候选列表（按优先级）
_CANDIDATE_ENCODINGS = [
    "utf-8-sig",   # UTF-8 with BOM（Excel 导出常见）
    "utf-8",
    "gbk",         # 简体中文最常用
    "gb18030",     # GBK 超集
    "gb2312",
    "latin-1",     # 终极回退，不抛异常
]

# 时间格式（按优先级尝试，精确匹配比 auto-infer 快）
_TIMESTAMP_FORMATS = [
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M",
    "%Y%m%d%H%M%S",
    "%d/%m/%Y %H:%M:%S",
]


# ── 结果数据类 ─────────────────────────────────────────────────────────────────

@dataclass
class IngestionResult:
    """ingestion.load_csv() 的输出契约。下游模块只依赖此类型。"""

    df: pd.DataFrame
    """已重命名（原始列名 → 标准列名）、时间解析、数值转换后的 DataFrame。
    未识别列名保持原始中文列名不变，仍包含在 df 中。
    时间戳列名为 'timestamp'（TIMESTAMP_CANONICAL）。"""

    recognized: dict[str, str]
    """原始列名 → 标准列名，已在 FIELD_CATALOG 中定义的列。"""

    unrecognized: list[str]
    """未在 FIELD_CATALOG 中定义的列名（原始）。"""

    encoding_used: str
    """实际成功解码文件使用的编码名称。"""

    delimiter_used: str
    """实际使用的 CSV 分隔符。"""

    suspicious_unit_fields: list[str]
    """当前文件中出现的单位可疑标准列名（raw_ 前缀）。"""


# ── 内部辅助函数 ───────────────────────────────────────────────────────────────

def _detect_encoding(raw_bytes: bytes) -> str:
    """
    先用 chardet 取建议编码，再逐一验证候选列表，返回第一个可成功解码的编码。

    chardet 对中文 GBK/GB2312 有时置信度低或误判为 windows-1252，
    因此以候选列表验证为主，chardet 仅做参考日志。
    """
    sample = raw_bytes[:65536]
    guess = chardet.detect(sample)
    logger.debug(
        "chardet guess: encoding=%s confidence=%.2f",
        guess.get("encoding"),
        guess.get("confidence", 0.0),
    )

    for enc in _CANDIDATE_ENCODINGS:
        try:
            raw_bytes.decode(enc)
            logger.debug("Encoding confirmed: %s", enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue

    logger.warning("All encodings failed, forcing latin-1")
    return "latin-1"


def _detect_delimiter(text_sample: str) -> str:
    """
    统计文件前 10 行中各候选分隔符的平均出现次数，选频次最高者。
    遇到平局时优先选择逗号。
    """
    candidates = [",", ";", "\t", "|"]
    lines = [ln for ln in text_sample.split("\n")[:10] if ln.strip()]
    if not lines:
        return ","

    scores = {
        sep: sum(line.count(sep) for line in lines) / len(lines)
        for sep in candidates
    }
    # 平局时 max() 返回第一个，candidates 列表以逗号开头
    best = max(scores, key=scores.get)
    logger.debug("Delimiter scores: %s → selected %r", scores, best)
    return best


def _parse_timestamp(series: pd.Series) -> pd.Series:
    """
    依次尝试 _TIMESTAMP_FORMATS 中的格式精确解析。
    全部失败则回退到 pandas 自动推断（errors='coerce'）。
    返回 datetime64[ns] Series，无法解析的行为 NaT。
    """
    for fmt in _TIMESTAMP_FORMATS:
        try:
            parsed = pd.to_datetime(series, format=fmt, errors="raise")
            logger.debug("Timestamp parsed with format: %s", fmt)
            return parsed
        except (ValueError, TypeError):
            continue

    logger.warning(
        "No timestamp format matched exactly; falling back to pandas auto-infer"
    )
    return pd.to_datetime(series, errors="coerce")


# ── 公开接口 ───────────────────────────────────────────────────────────────────

def load_csv(path: str | Path) -> IngestionResult:
    """
    加载 TBM CSV 文件并执行字段映射、时间解析、数值转换。

    不做任何清洗（无 IQR、无插值、无重采样）——清洗由 cleaning.py 负责。

    Args:
        path: CSV 文件路径（str 或 Path）

    Returns:
        IngestionResult

    Raises:
        FileNotFoundError: 文件不存在
        ValueError:        文件为空或 CSV 解析失败
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到文件: {path}")

    # ── 步骤 1：读取原始字节 ───────────────────────────────────────────────────
    raw_bytes = path.read_bytes()
    if not raw_bytes.strip():
        raise ValueError(f"文件为空: {path}")

    # ── 步骤 2：检测编码 ───────────────────────────────────────────────────────
    encoding = _detect_encoding(raw_bytes)
    text = raw_bytes.decode(encoding, errors="replace")

    # ── 步骤 3：检测分隔符 ─────────────────────────────────────────────────────
    delimiter = _detect_delimiter(text)

    # ── 步骤 4：pandas 读取（全列 str，避免类型推断干扰后续转换）────────────────
    try:
        raw_df = pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            dtype=str,              # 所有列先读为字符串
            keep_default_na=False,  # 不自动将 '' 转为 NaN，交由后续统一处理
            skipinitialspace=True,
            engine="python",        # python engine 对奇异分隔符更健壮
        )
    except Exception as exc:
        raise ValueError(f"CSV 解析失败: {exc}") from exc

    if raw_df.empty:
        raise ValueError(f"CSV 无数据行（仅有表头或完全空白）: {path}")

    # 去除列名首尾空白（Excel/系统导出常有隐藏空格）
    raw_df.columns = [c.strip() for c in raw_df.columns]

    logger.info(
        "Loaded %d rows × %d cols from '%s' [enc=%s, sep=%r]",
        len(raw_df), len(raw_df.columns), path.name, encoding, delimiter,
    )

    # ── 步骤 5：字段映射 ───────────────────────────────────────────────────────
    recognized, unrecognized = resolve_columns(list(raw_df.columns))

    if unrecognized:
        logger.warning(
            "%d unrecognized column(s) will be kept as-is: %s",
            len(unrecognized), unrecognized,
        )

    # ── 步骤 6：重命名已识别列（原始列名 → 标准列名）─────────────────────────
    df = raw_df.rename(columns=recognized)

    # ── 步骤 7：解析时间戳列 ───────────────────────────────────────────────────
    if TIMESTAMP_CANONICAL in df.columns:
        df[TIMESTAMP_CANONICAL] = _parse_timestamp(df[TIMESTAMP_CANONICAL])
        nat_count = int(df[TIMESTAMP_CANONICAL].isna().sum())
        if nat_count:
            logger.warning(
                "%d row(s) have unparseable timestamps → set to NaT", nat_count
            )
    else:
        logger.warning(
            "Expected timestamp column '%s' not found in CSV; "
            "time-based features will be unavailable",
            TIMESTAMP_RAW,
        )

    # ── 步骤 8：数值列类型转换（coerce：无法解析 → NaN）──────────────────────
    # 已识别的非时间戳列全部转为 float64
    numeric_candidates = [
        canonical
        for raw_col, canonical in recognized.items()
        if not FIELD_CATALOG[raw_col].is_timestamp
    ]
    conversion_errors: dict[str, int] = {}
    for col in numeric_candidates:
        if col not in df.columns:
            continue
        before_nan = int(df[col].isna().sum())  # '' 已被 keep_default_na=False 保留为字符串
        df[col] = pd.to_numeric(df[col], errors="coerce")
        after_nan = int(df[col].isna().sum())
        coerced = after_nan - before_nan
        if coerced:
            conversion_errors[col] = coerced
            logger.debug("Coerced %d non-numeric value(s) to NaN in column '%s'", coerced, col)

    if conversion_errors:
        logger.info(
            "Non-numeric → NaN in %d column(s): %s",
            len(conversion_errors),
            {k: v for k, v in list(conversion_errors.items())[:5]},
        )

    # ── 步骤 9：标记当前文件中出现的单位可疑字段 ─────────────────────────────
    suspicious_present = [
        col for col in df.columns if col in SUSPICIOUS_UNIT_FIELDS
    ]
    if suspicious_present:
        logger.warning(
            "Fields with suspicious units (kept as raw, do not use for physics): %s",
            suspicious_present,
        )

    return IngestionResult(
        df=df,
        recognized=recognized,
        unrecognized=unrecognized,
        encoding_used=encoding,
        delimiter_used=delimiter,
        suspicious_unit_fields=suspicious_present,
    )
