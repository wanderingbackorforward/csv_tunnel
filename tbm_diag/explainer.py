"""
explainer.py — 模板解释生成器

职责：
- 输入：EventEvidence
- 输出：Explanation dataclass（title / summary / evidence_bullets /
        possible_causes / suggested_actions / severity_label）

设计原则：
- 不使用 LLM，纯模板 + 数据驱动
- 先讲证据，再讲推测
- 推测使用"可能""疑似""需关注"等限定词
- 每种 event_type 有独立模板
- severity_label 由 severity_score 映射：
    >= 0.75 → 高风险
    >= 0.50 → 中风险
    >= 0.25 → 低风险
    <  0.25 → 观察
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from tbm_diag.evidence import EventEvidence, SignalEvidence

logger = logging.getLogger(__name__)


# ── 数据类 ─────────────────────────────────────────────────────────────────────

@dataclass
class Explanation:
    event_id: str
    event_type: str
    severity_label: str           # 高风险 / 中风险 / 低风险 / 观察
    severity_score: float
    start_time: Optional[object]
    end_time: Optional[object]
    title: str                    # 一行标题
    summary: str                  # 一句话总结
    evidence_bullets: list[str]   # 证据列表（来自 SignalEvidence.evidence_text）
    possible_causes: list[str]    # 可能原因（模板生成）
    suggested_actions: list[str]  # 建议关注项（模板生成）
    state_context: str = ""       # 工况状态上下文，如"该事件主要发生在重载推进状态下"


# ── 严重度映射 ─────────────────────────────────────────────────────────────────

def _severity_label(score: float) -> str:
    if score >= 0.75:
        return "高风险"
    if score >= 0.50:
        return "中风险"
    if score >= 0.25:
        return "低风险"
    return "观察"


# ── 每类异常的模板库 ───────────────────────────────────────────────────────────

_TITLES: dict[str, str] = {
    "suspected_excavation_resistance": "疑似掘进阻力异常",
    "low_efficiency_excavation":       "低效掘进",
    "attitude_or_bias_risk":           "姿态偏斜风险",
    "hydraulic_instability":           "液压系统不稳定",
}

_SUMMARIES: dict[str, str] = {
    "suspected_excavation_resistance":
        "该时段刀盘转矩偏高、推进速度偏低，疑似地层阻力增大或刀盘负载异常。",
    "low_efficiency_excavation":
        "该时段推进速度与贯入度持续偏低，掘进效率明显不足，需关注工况设置与地层条件。",
    "attitude_or_bias_risk":
        "该时段稳定器或推进压力分布出现不均衡，可能存在盾体姿态偏斜风险。",
    "hydraulic_instability":
        "该时段液压压力出现明显波动，主推进系统稳定性需关注。",
}

_POSSIBLE_CAUSES: dict[str, list[str]] = {
    "suspected_excavation_resistance": [
        "可能遭遇地层变化（硬岩夹层、孤石或断层破碎带）",
        "疑似刀盘磨损加剧，切削效率下降",
        "可能存在刀盘结泥饼或渣土堆积，导致负载升高",
        "需关注推进参数设置是否与当前地层匹配",
    ],
    "low_efficiency_excavation": [
        "可能推进速度设定偏保守，未充分利用地层可掘性",
        "疑似刀盘转速或推进力参数配置不当",
        "可能存在设备限速或操作干预导致速度受限",
        "需关注是否处于换刀、停机或特殊工况阶段",
    ],
    "attitude_or_bias_risk": [
        "可能左右推进油缸出力不均，导致盾体偏转",
        "疑似地层软硬不均，单侧阻力差异较大",
        "可能稳定器调整不及时，未能有效纠偏",
        "需关注是否存在超挖或欠挖导致的姿态漂移",
    ],
    "hydraulic_instability": [
        "可能液压系统存在内泄或密封老化",
        "疑似泵组切换或溢流阀动作引起压力波动",
        "可能管路存在气穴或油温异常",
        "需关注是否与推进速度突变同步发生",
    ],
}

_SUGGESTED_ACTIONS: dict[str, list[str]] = {
    "suspected_excavation_resistance": [
        "复核该时间段推进工况记录，确认是否有地层变化或异常事件",
        "检查刀盘负载与推进协调性，评估是否需要调整推进参数",
        "结合现场地质记录确认是否存在硬岩或孤石",
        "关注后续时段转矩趋势，判断是否持续恶化",
    ],
    "low_efficiency_excavation": [
        "复核该时段操作记录，确认是否为主动降速或特殊工况",
        "对比相邻正常掘进段参数，评估效率损失幅度",
        "检查刀盘转速与推进力配合是否合理",
        "若非主动干预，建议检查设备状态与刀具磨损情况",
    ],
    "attitude_or_bias_risk": [
        "关注压力分布是否持续失衡，及时调整各组油缸出力",
        "复核稳定器行程与压力记录，确认纠偏操作是否到位",
        "结合测量数据确认盾体实际姿态偏差量",
        "若偏差持续，建议暂停推进并进行姿态调整",
    ],
    "hydraulic_instability": [
        "检查主推进泵及控制油路工作状态",
        "关注压力波动是否与特定操作动作相关",
        "排查液压油温度、油位及过滤器状态",
        "若波动持续，建议安排液压系统专项检查",
    ],
}


# ── 公开接口 ───────────────────────────────────────────────────────────────────

class TemplateExplainer:
    """基于模板的事件解释生成器，不依赖 LLM。"""

    def explain(
        self,
        ev: EventEvidence,
        priority_score: Optional[float] = None,
        dominant_state: Optional[str] = None,
    ) -> Explanation:
        """
        为单个 EventEvidence 生成解释。

        Args:
            ev:             extract_evidence() 的输出
            priority_score: 可选优先级分数，None 时使用 ev.severity_score
            dominant_state: 可选工况状态（英文 key），用于生成 state_context

        Returns:
            Explanation dataclass
        """
        score = priority_score if priority_score is not None else ev.severity_score
        label = _severity_label(score)
        etype = ev.event_type

        title   = _TITLES.get(etype, etype)
        summary = _SUMMARIES.get(etype, "该时段检测到异常，请结合现场记录核实。")

        # 证据列表：直接取 SignalEvidence.evidence_text
        bullets = [sig.evidence_text for sig in ev.top_signals] if ev.top_signals else [
            "（当前数据字段不足，无法提取详细证据）"
        ]

        causes  = _POSSIBLE_CAUSES.get(etype, ["需结合现场记录进一步分析。"])
        actions = _SUGGESTED_ACTIONS.get(etype, ["复核该时间段工况记录。"])

        # 工况状态上下文
        state_ctx = ""
        _ds = dominant_state or (ev.dominant_state if hasattr(ev, "dominant_state") else None)
        if _ds:
            from tbm_diag.state_engine import STATE_LABELS
            label_zh = STATE_LABELS.get(_ds, _ds)
            state_ctx = f"该事件主要发生在\"{label_zh}\"状态下"

        logger.debug(
            "explainer: event %s → label=%s score=%.3f bullets=%d",
            ev.event_id, label, score, len(bullets),
        )

        return Explanation(
            event_id=ev.event_id,
            event_type=etype,
            severity_label=label,
            severity_score=round(score, 4),
            start_time=ev.start_time,
            end_time=ev.end_time,
            title=title,
            summary=summary,
            evidence_bullets=bullets,
            possible_causes=causes,
            suggested_actions=actions,
            state_context=state_ctx,
        )

    def explain_all(
        self,
        evidences: list[EventEvidence],
        event_states: Optional[dict] = None,
    ) -> list[Explanation]:
        """批量生成解释，顺序与 evidences 一致。

        Args:
            evidences:    extract_evidence() 的输出
            event_states: dict[event_id → EventStateSummary]，可选
        """
        results = []
        for ev in evidences:
            ds = None
            if event_states and ev.event_id in event_states:
                ds = event_states[ev.event_id].dominant_state
            results.append(self.explain(ev, dominant_state=ds))
        return results
