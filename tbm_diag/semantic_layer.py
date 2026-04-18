"""
semantic_layer.py — 语义事件再分类

基于 (event_type, dominant_state) 映射到 semantic_event_type。
不修改检测器输出，保留原始 event_type 供溯源。

调用方式：
    from tbm_diag.semantic_layer import apply_to_evidences, SEMANTIC_LABELS
    apply_to_evidences(evidences)   # 在 extract_evidence() 之后、explain_all() 之前
"""

from __future__ import annotations

from typing import Optional

# ── 规则表 ────────────────────────────────────────────────────────────────────
# key: (event_type, dominant_state)  →  semantic_event_type
# 未命中规则时回退到原始 event_type（规则 4：all others → keep original）

_RULES: dict[tuple[str, str], str] = {
    # 低效掘进 + 停机 → 停机片段
    ("low_efficiency_excavation",       "stopped"):               "stoppage_segment",
    # 低效掘进 + 推进中 → 保持低效掘进
    ("low_efficiency_excavation",       "normal_excavation"):     "low_efficiency_excavation",
    ("low_efficiency_excavation",       "heavy_load_excavation"): "low_efficiency_excavation",
    # 掘进阻力异常 + 重载推进 → 重载推进下的掘进阻力异常
    ("suspected_excavation_resistance", "heavy_load_excavation"): "excavation_resistance_under_load",
}

# ── 语义类型中文名 ─────────────────────────────────────────────────────────────

SEMANTIC_LABELS: dict[str, str] = {
    "stoppage_segment":                 "停机片段",
    "excavation_resistance_under_load": "重载推进下的掘进阻力异常",
    "low_efficiency_excavation":        "低效掘进",
    "suspected_excavation_resistance":  "疑似掘进阻力异常",
    "attitude_or_bias_risk":            "姿态偏斜风险",
    "hydraulic_instability":            "液压系统不稳定",
}


# ── 公开接口 ───────────────────────────────────────────────────────────────────

def classify(event_type: str, dominant_state: Optional[str]) -> str:
    """
    返回语义事件类型。

    dominant_state 为 None 时回退到原始 event_type（无状态信息，无法重分类）。
    规则未命中时同样回退到原始 event_type。
    """
    if dominant_state is None:
        return event_type
    return _RULES.get((event_type, dominant_state), event_type)


def apply_to_evidences(evidences: list) -> None:
    """
    原地为每个 EventEvidence 填充 semantic_event_type。

    在 extract_evidence() 之后、explain_all() 之前调用。
    依赖 ev.event_type 和 ev.dominant_state（均已由上游填充）。
    """
    for ev in evidences:
        ev.semantic_event_type = classify(ev.event_type, ev.dominant_state)
