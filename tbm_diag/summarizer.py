"""
summarizer.py — LLM 跨事件总结层

职责：
- 输入：已有结构化结果（Explanation 列表 + 状态分布）
- 输出：LLMSummaryResult（overall_summary / top_risks / suggested_actions）

设计原则：
- LLM 不参与核心检测，只做跨事件自然语言归纳
- LLM 只能看到精简的结构化摘要，不接触原始 DataFrame
- 任何失败（无 key、超时、API 错误、JSON 解析失败）均返回 None，不向上抛异常
- 作为可选功能，anthropic SDK 未安装时静默跳过
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── 输入 dataclass ─────────────────────────────────────────────────────────────

@dataclass
class EventSummaryItem:
    """单个事件的精简摘要，供 LLM 消费。"""
    event_id: str
    event_type_zh: str          # 中文类型名，如"疑似掘进阻力异常"
    severity_label: str         # 高风险 / 中风险 / 低风险 / 观察
    severity_score: float
    start_time: str
    end_time: str
    duration_seconds: Optional[float]
    dominant_state_zh: str      # 主导工况中文名，如"重载推进"
    one_line_summary: str       # Explanation.summary（模板生成的一句话）
    top_evidence: list[str]     # evidence_bullets 前两条


@dataclass
class DiagSummaryInput:
    """传给 LLM 的完整上下文，不含原始 DataFrame。"""
    input_file: str
    total_rows: int
    time_range_start: str
    time_range_end: str
    state_distribution: dict[str, str]   # {"正常推进": "28.3%", ...}
    events: list[EventSummaryItem]
    semantic_stats: dict = field(default_factory=dict)
    """各 semantic_event_type 的统计：{sem_type: {"count": N, "total_seconds": X}}"""


# ── 输出 dataclass ─────────────────────────────────────────────────────────────

@dataclass
class LLMSummaryResult:
    """LLM 返回的跨事件总结。"""
    overall_summary: str
    top_risks: list[str]
    suggested_actions: list[str]
    model_used: str
    generated_at: str


# ── 构造输入 ───────────────────────────────────────────────────────────────────

def build_summary_input(
    input_file: str,
    total_rows: int,
    explanations: list,          # list[Explanation]
    evidences: list,             # list[EventEvidence]
    events: list,                # list[Event]
    event_states: Optional[dict] = None,
    enriched_df=None,            # 可选，用于提取状态分布
    semantic_stats: Optional[dict] = None,  # {sem_type: {"count": N, "total_seconds": X}}
) -> Optional["DiagSummaryInput"]:
    """
    从现有结构化结果构造 DiagSummaryInput。
    """
    if not events or not explanations:
        return None

    from tbm_diag.state_engine import STATE_LABELS

    time_start = ""
    time_end = ""
    if explanations[0].start_time is not None:
        time_start = str(explanations[0].start_time)[:19]
    if explanations[-1].end_time is not None:
        time_end = str(explanations[-1].end_time)[:19]

    state_dist: dict[str, str] = {}
    if enriched_df is not None and "machine_state" in enriched_df.columns:
        counts = enriched_df["machine_state"].value_counts()
        n_total = len(enriched_df)
        for key in ["stopped", "low_load_operation", "normal_excavation", "heavy_load_excavation"]:
            n = counts.get(key, 0)
            pct = n / n_total * 100 if n_total > 0 else 0.0
            label_zh = STATE_LABELS.get(key, key)
            state_dist[label_zh] = f"{pct:.1f}%"

    ev_map = {ev.event_id: ev for ev in evidences}

    event_items: list[EventSummaryItem] = []
    for exp in explanations:
        ev = ev_map.get(exp.event_id)
        dominant_state_zh = ""
        if exp.state_context:
            import re
            m = re.search(r'"(.+?)"', exp.state_context)
            dominant_state_zh = m.group(1) if m else exp.state_context
        elif event_states and exp.event_id in event_states:
            ds_key = event_states[exp.event_id].dominant_state
            dominant_state_zh = STATE_LABELS.get(ds_key, ds_key)

        top_evidence = exp.evidence_bullets[:2] if exp.evidence_bullets else []

        dur = None
        for e in events:
            if e.event_id == exp.event_id:
                dur = e.duration_seconds
                break

        event_items.append(EventSummaryItem(
            event_id=exp.event_id,
            event_type_zh=exp.title,
            severity_label=exp.severity_label,
            severity_score=exp.severity_score,
            start_time=str(exp.start_time)[:19] if exp.start_time is not None else "",
            end_time=str(exp.end_time)[:19] if exp.end_time is not None else "",
            duration_seconds=dur,
            dominant_state_zh=dominant_state_zh,
            one_line_summary=exp.summary,
            top_evidence=top_evidence,
        ))

    return DiagSummaryInput(
        input_file=input_file,
        total_rows=total_rows,
        time_range_start=time_start,
        time_range_end=time_end,
        state_distribution=state_dist,
        events=event_items,
        semantic_stats=semantic_stats or {},
    )


# ── Prompt 构造 ────────────────────────────────────────────────────────────────

_SEM_LABELS_ZH = {
    "stoppage_segment":                 "停机片段（停机/静止工况，非推进效率问题）",
    "low_efficiency_excavation":        "推进中低效掘进",
    "excavation_resistance_under_load": "重载推进下的掘进阻力异常",
    "suspected_excavation_resistance":  "疑似掘进阻力异常",
    "attitude_or_bias_risk":            "姿态偏斜风险",
    "hydraulic_instability":            "液压系统不稳定",
}

_MAX_EVENTS_IN_PROMPT = 20


def _build_prompt(summary_input: DiagSummaryInput) -> str:
    si = summary_input

    events_for_prompt = sorted(si.events, key=lambda e: e.severity_score, reverse=True)
    truncated = len(events_for_prompt) > _MAX_EVENTS_IN_PROMPT
    events_for_prompt = events_for_prompt[:_MAX_EVENTS_IN_PROMPT]

    lines = [
        "你是一名盾构/TBM 施工数据分析助手。",
        "以下是本次诊断的结构化结果，请基于这些信息做跨事件归纳总结。",
        "",
        f"【数据概况】",
        f"- 文件：{si.input_file}",
        f"- 数据行数：{si.total_rows:,}",
        f"- 时间范围：{si.time_range_start} ~ {si.time_range_end}",
    ]

    if si.state_distribution:
        lines.append("- 工况分布：" + "，".join(f"{k} {v}" for k, v in si.state_distribution.items()))

    # ── 语义事件分类统计（关键：帮助 LLM 区分停机 vs 推进效率）────────────────
    if si.semantic_stats:
        lines += ["", "【语义事件分类统计】（重要：请在总结中明确区分以下类别，不要混淆）"]
        for sem, stats in sorted(si.semantic_stats.items(), key=lambda x: -x[1].get("count", 0)):
            label = _SEM_LABELS_ZH.get(sem, sem)
            dur_s = stats.get("total_seconds", 0)
            dur_str = f"，总时长 {dur_s/3600:.1f}h" if dur_s >= 3600 else (f"，总时长 {dur_s/60:.0f}min" if dur_s > 0 else "")
            lines.append(f"- {label}：{stats['count']} 个{dur_str}")
        stoppage = si.semantic_stats.get("stoppage_segment", {})
        if stoppage.get("count", 0) > 0:
            lines.append("⚠ 注意：停机片段属于停机/静止工况，不是推进参数问题，请在总结中单独说明停机情况，不要归入低效掘进。")

    total_note = f"（共 {len(si.events)} 个，以下展示风险最高的 {len(events_for_prompt)} 个）" if truncated else f"（共 {len(si.events)} 个）"
    lines += [
        "",
        f"【异常事件列表】{total_note}",
    ]

    for i, ev in enumerate(events_for_prompt, 1):
        dur_str = f"，持续 {ev.duration_seconds:.0f}s" if ev.duration_seconds else ""
        lines.append(f"{i}. [{ev.severity_label}] {ev.event_id} — {ev.event_type_zh}")
        lines.append(f"   时间：{ev.start_time} ~ {ev.end_time}{dur_str}")
        if ev.dominant_state_zh:
            lines.append(f"   主导工况：{ev.dominant_state_zh}")
        lines.append(f"   摘要：{ev.one_line_summary}")
        for bullet in ev.top_evidence:
            lines.append(f"   • {bullet}")

    lines += [
        "",
        "【输出要求】",
        "请严格输出以下 JSON 格式，不要输出任何其他内容：",
        "{",
        '  "overall_summary": "2~3句整体评估，明确区分停机问题与推进效率问题，说明本次掘进的整体状态和主要问题",',
        '  "top_risks": ["风险1", "风险2", "风险3"],  // 3~5条，跨事件归纳，停机问题和推进效率问题分开列',
        '  "suggested_actions": ["建议1", "建议2", "建议3"]  // 3~5条，可操作的具体建议',
        "}",
        "",
        "注意：",
        "- 只基于上方提供的数据，不要编造原始数据中不存在的指标",
        "- 停机片段（停机/静止工况）不是推进效率问题，请单独描述，不要与低效掘进混淆",
        "- top_risks 要做跨事件归纳（如多个事件集中在某时段、某工况），不要逐条重复事件摘要",
        "- 语言面向现场工程师，简洁务实",
        "- 输出必须是合法 JSON，不要加 markdown 代码块",
        "- 不要输出任何思考过程或分析步骤，直接输出 JSON",
    ]

    return "\n".join(lines)


# ── 主函数 ─────────────────────────────────────────────────────────────────────

def summarize(
    summary_input: DiagSummaryInput,
    cfg: "LLMConfig",  # type: ignore[name-defined]
) -> Optional[LLMSummaryResult]:
    """
    调用 OpenAI-compatible LLM（默认 MiniMax）生成跨事件总结。

    任何失败均返回 None，不向上抛异常。
    """
    if not summary_input or not summary_input.events:
        logger.debug("summarizer: no events, skipping LLM call")
        return None

    # 检查 openai SDK
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("summarizer: openai SDK 未安装，跳过 LLM 总结（pip install openai）")
        return None

    # 读取 API key
    api_key = os.environ.get(cfg.api_key_env, "").strip()
    if not api_key:
        logger.warning("summarizer: 未找到环境变量 %s，跳过 LLM 总结", cfg.api_key_env)
        return None

    base_url = os.environ.get(cfg.base_url_env, "").strip() or None
    client = OpenAI(api_key=api_key, base_url=base_url)

    prompt = _build_prompt(summary_input)

    try:
        response = client.chat.completions.create(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            timeout=cfg.timeout_seconds,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("summarizer: LLM 调用失败（%s: %s），跳过总结", type(exc).__name__, exc)
        return None

    parsed = _parse_llm_response(raw_text)
    if parsed is None:
        return None

    from datetime import datetime
    return LLMSummaryResult(
        overall_summary=parsed.get("overall_summary", ""),
        top_risks=parsed.get("top_risks", []),
        suggested_actions=parsed.get("suggested_actions", []),
        model_used=cfg.model,
        generated_at=datetime.now().isoformat(),
    )


def _parse_llm_response(raw_text: str) -> Optional[dict]:
    """
    解析 LLM 返回的 JSON 文本。

    先剥离 <think>...</think> 推理块（部分模型如 MiniMax-M2.7 会输出 CoT）；
    再尝试直接解析；若失败则尝试提取 {...} 块；仍失败则返回 None。
    """
    import re

    # 剥离 <think>...</think> 块（含跨行）；也处理未闭合的 <think> 块
    text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text, flags=re.IGNORECASE).strip()
    m_open = re.search(r"<think>", text, flags=re.IGNORECASE)
    if m_open:
        text = text[:m_open.start()].strip()

    # 直接解析
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 尝试提取第一个 {...} 块
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    logger.warning("summarizer: 无法解析 LLM 返回的 JSON，跳过总结\n原始响应：%s", raw_text[:300])
    return None
