"""
config.py — 配置文件加载与合并

支持 YAML（推荐）和 JSON 两种格式。
缺失字段自动回退到各 dataclass 的默认值。
解析错误给出友好提示，不抛裸异常。

用法：
    cfg = load_config("sample_config.yaml")   # 从文件加载
    cfg = load_config(None)                   # 全部使用默认值

DiagConfig 包含五个子配置，与现有 dataclass 一一对应：
    cleaning   → CleaningConfig（传给 cleaning.clean()）
    feature    → FeatureConfig（传给 feature_engine.enrich_features()）
    detector   → DetectorConfig（传给 detector.detect()）
    segmenter  → SegmenterConfig（传给 segmenter.segment_events()）
    cli        → CliConfig（控制 CLI 输出行为）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Any, Optional

from tbm_diag.detector import DetectorConfig
from tbm_diag.segmenter import SegmenterConfig

logger = logging.getLogger(__name__)


# ── 子配置 dataclass ───────────────────────────────────────────────────────────

@dataclass
class CleaningConfig:
    resample: Optional[str] = "1s"
    """重采样频率，pandas offset alias；'none' 或 null 跳过。"""
    fill: str = "ffill"
    """缺失值填充方式：ffill | linear"""
    max_gap: int = 5
    """最大连续填充步数。"""
    spike_k: float = 5.0
    """IQR 尖峰检测宽松倍数。"""


@dataclass
class FeatureConfig:
    rolling_window: int = 5
    """滚动统计窗口大小（点数）。"""


@dataclass
class CliConfig:
    top_k_explanations: int = 3
    """默认输出的 Top-K 事件解释数量。"""
    watch_interval: float = 3.0
    """watch 模式轮询间隔（秒）。"""


@dataclass
class DiagConfig:
    """全局诊断配置，由 load_config() 返回。"""
    cleaning:  CleaningConfig  = field(default_factory=CleaningConfig)
    feature:   FeatureConfig   = field(default_factory=FeatureConfig)
    detector:  DetectorConfig  = field(default_factory=DetectorConfig)
    segmenter: SegmenterConfig = field(default_factory=SegmenterConfig)
    cli:       CliConfig       = field(default_factory=CliConfig)


# ── 内部辅助 ───────────────────────────────────────────────────────────────────

def _try_import_yaml() -> Any:
    """尝试导入 PyYAML；未安装时返回 None。"""
    try:
        import yaml
        return yaml
    except ImportError:
        return None


def _merge_dataclass(dc_instance: Any, raw: dict) -> None:
    """
    将 raw dict 中存在的键就地写入 dc_instance 对应字段。
    未知键忽略，类型错误给出警告但不中断。
    """
    valid_fields = {f.name: f for f in fields(dc_instance)}
    for key, value in raw.items():
        if key not in valid_fields:
            logger.warning("config: unknown key '%s' in section '%s', ignored",
                           key, type(dc_instance).__name__)
            continue
        try:
            # 简单类型强制转换（int/float/str/bool）
            expected = valid_fields[key].type
            if expected in ("int", int) and not isinstance(value, bool):
                value = int(value)
            elif expected in ("float", float):
                value = float(value)
            elif expected in ("bool", bool):
                value = bool(value)
            setattr(dc_instance, key, value)
        except (TypeError, ValueError) as exc:
            logger.warning("config: cannot set '%s'=%r — %s, using default", key, value, exc)


def _load_raw(path: Path) -> dict:
    """读取 YAML 或 JSON 文件，返回原始 dict。"""
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")

    if suffix in (".yaml", ".yml"):
        yaml = _try_import_yaml()
        if yaml is None:
            raise ImportError(
                "PyYAML 未安装，无法解析 .yaml 配置文件。\n"
                "请运行：pip install pyyaml\n"
                "或改用 .json 格式的配置文件。"
            )
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        raise ValueError(
            f"不支持的配置文件格式：{suffix}（仅支持 .yaml / .yml / .json）"
        )

    if not isinstance(data, dict):
        raise ValueError(f"配置文件顶层必须是 key-value 映射，实际得到：{type(data).__name__}")

    return data


# ── 公开接口 ───────────────────────────────────────────────────────────────────

def load_config(path: Optional[str | Path]) -> DiagConfig:
    """
    从文件加载配置并与默认值合并，返回 DiagConfig。

    Args:
        path: 配置文件路径（.yaml / .yml / .json）；None 时返回全默认配置。

    Returns:
        DiagConfig，所有未指定字段保持默认值。

    Raises:
        SystemExit: 文件不存在或格式错误时打印友好提示并退出。
    """
    cfg = DiagConfig()

    if path is None:
        logger.debug("config: no config file specified, using all defaults")
        return cfg

    p = Path(path)
    if not p.exists():
        import sys
        print(f"✗ 配置文件不存在: {p}", file=sys.stderr)
        sys.exit(2)

    try:
        raw = _load_raw(p)
    except (ImportError, ValueError) as exc:
        import sys
        print(f"✗ 配置文件解析失败: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        import sys
        print(f"✗ 读取配置文件时出错: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── 逐节合并 ──────────────────────────────────────────────────────────────
    section_map = {
        "cleaning":  cfg.cleaning,
        "feature":   cfg.feature,
        "detector":  cfg.detector,
        "segmenter": cfg.segmenter,
        "cli":       cfg.cli,
    }
    for section_name, dc_instance in section_map.items():
        section_raw = raw.get(section_name)
        if section_raw is None:
            continue
        if not isinstance(section_raw, dict):
            logger.warning("config: section '%s' is not a mapping, skipped", section_name)
            continue
        _merge_dataclass(dc_instance, section_raw)

    # 未知顶层键提示
    for key in raw:
        if key not in section_map:
            logger.warning("config: unknown top-level section '%s', ignored", key)

    logger.info(
        "Config loaded from %s: cleaning=%s feature=%s detector=... segmenter=%s cli=%s",
        p,
        asdict(cfg.cleaning),
        asdict(cfg.feature),
        asdict(cfg.segmenter),
        asdict(cfg.cli),
    )

    return cfg
