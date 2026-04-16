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
) -> Optional["DiagSummaryInput"]:
    """
    从现有结构化结果构造 DiagSummaryInput。

    Args:
        input_file:   输入文件路径字符串
        total_rows:   清洗后总行数
        explanations: TemplateExplainer.explain_all() 的输出
        evidences:    extract_evidence() 的输出
        events:       segment_events() 的输出
        event_states: dict[event_id → EventStateSummary]，可选
        enriched_df:  enrich_features 后的 DataFrame，用于提取状态分布

    Returns:
        DiagSummaryInput，若无事件则返回 None
    """
    if not events or not explanations:
        return None

    # 时间范围
    from tbm_diag.state_engine import STATE_LABELS

    time_start = ""
    time_end = ""
    if explanations[0].start_time is not None:
        time_start = str(explanations[0].start_time)[:19]
    if explanations[-1].end_time is not None:
        time_end = str(explanations[-1].end_time)[:19]

    # 状态分布
    state_dist: dict[str, str] = {}
    if enriched_df is not None and "machine_state" in enriched_df.columns:
        counts = enriched_df["machine_state"].value_counts()
        n_total = len(enriched_df)
        for key in ["stopped", "low_load_operation", "normal_excavation", "heavy_load_excavation"]:
            n = counts.get(key, 0)
            pct = n / n_total * 100 if n_total > 0 else 0.0
            label_zh = STATE_LABELS.get(key, key)
            state_dist[label_zh] = f"{pct:.1f}%"

    # 建立 evidence 查找表
    ev_map = {ev.event_id: ev for ev in evidences}

    # 构造每个事件的精简摘要
    event_items: list[EventSummaryItem] = []
    for exp in explanations:
        ev = ev_map.get(exp.event_id)
        dominant_state_zh = ""
        if exp.state_context:
            # state_context 形如 '该事件主要发生在"重载推进"状态下'
            # 直接用 state_context 里的中文名
            import re
            m = re.search(r'"(.+?)"', exp.state_context)
            dominant_state_zh = m.group(1) if m else exp.state_context
        elif event_states and exp.event_id in event_states:
            ds_key = event_states[exp.event_id].dominant_state
            dominant_state_zh = STATE_LABELS.get(ds_key, ds_key)

        top_evidence = exp.evidence_bullets[:2] if exp.evidence_bullets else []

        # 找对应 event 的 duration_seconds
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
    )


# ── Prompt 构造 ────────────────────────────────────────────────────────────────

def _build_prompt(summary_input: DiagSummaryInput) -> str:
    """将 DiagSummaryInput 序列化为 LLM prompt。"""
    si = summary_input

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

    lines += [
        "",
        f"【异常事件列表】（共 {len(si.events)} 个）",
    ]

    for i, ev in enumerate(si.events, 1):
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
        '  "overall_summary": "2~3句整体评估，说明本次掘进的整体状态和主要问题",',
        '  "top_risks": ["风险1", "风险2", "风险3"],  // 3~5条，跨事件归纳，不要重复单个事件的模板描述',
        '  "suggested_actions": ["建议1", "建议2", "建议3"]  // 3~5条，可操作的具体建议',
        "}",
        "",
        "注意：",
        "- 只基于上方提供的数据，不要编造原始数据中不存在的指标",
        "- top_risks 要做跨事件归纳（如多个事件集中在某时段、某工况），不要逐条重复事件摘要",
        "- 语言面向现场工程师，简洁务实",
        "- 输出必须是合法 JSON，不要加 markdown 代码块",
    ]

    return "\n".join(lines)


# ── 主函数 ─────────────────────────────────────────────────────────────────────

def summarize(
    summary_input: DiagSummaryInput,
    cfg: "LLMConfig",  # type: ignore[name-defined]
) -> Optional[LLMSummaryResult]:
    """
    调用 LLM 生成跨事件总结。

    任何失败均返回 None，不向上抛异常。

    Args:
        summary_input: build_summary_input() 的输出
        cfg:           LLMConfig（来自 DiagConfig.llm）

    Returns:
        LLMSummaryResult，或 None（失败时）
    """
    if not summary_input or not summary_input.events:
        logger.debug("summarizer: no events, skipping LLM call")
        return None

    # 检查 anthropic SDK
    try:
        import anthropic
    except ImportError:
        logger.warning("summarizer: anthropic SDK 未安装，跳过 LLM 总结（pip install anthropic）")
        return None

    # 读取 API key
    api_key = os.environ.get(cfg.api_key_env, "").strip()
    if not api_key:
        logger.warning(
            "summarizer: 未找到环境变量 %s，跳过 LLM 总结", cfg.api_key_env
        )
        return None

    prompt = _build_prompt(summary_input)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            timeout=cfg.timeout_seconds,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = message.content[0].text.strip()
    except Exception as exc:
        logger.warning("summarizer: LLM 调用失败（%s: %s），跳过总结", type(exc).__name__, exc)
        return None

    # 解析 JSON
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

    先尝试直接解析；若失败则尝试提取 {...} 块；仍失败则返回 None。
    """
    # 直接解析
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 尝试提取第一个 {...} 块
    import re
    m = re.search(r"\{[\s\S]*\}", raw_text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    logger.warning("summarizer: 无法解析 LLM 返回的 JSON，跳过总结\n原始响应：%s", raw_text[:300])
    return None
