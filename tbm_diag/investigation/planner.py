"""planner.py — LLM planner + rule-based fallback

LLM planner 使用 OpenAI-compatible API。
无 API key 时自动降级为 rule-based fallback。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from tbm_diag.investigation.state import InvestigationState

logger = logging.getLogger(__name__)

AVAILABLE_ACTIONS = [
    "inspect_file_overview",
    "load_event_summary",
    "merge_stoppage_cases",
    "inspect_transition_window",
    "classify_stoppage_case",
    "compare_cases_across_files",
    "retrieve_operation_context",
    "generate_investigation_report",
]


def _compress_state(state: InvestigationState) -> dict[str, Any]:
    """压缩 state 为 LLM 可消费的摘要。"""
    return {
        "mode": state.mode,
        "current_file": state.current_file,
        "files": state.input_files,
        "iteration": state.iteration_count,
        "confidence": state.confidence,
        "has_overview": bool(state.file_overviews),
        "has_events": bool(state.event_summaries),
        "stoppage_cases_count": sum(len(v) for v in state.stoppage_cases.values()),
        "transitions_done": list(state.transition_analyses.keys()),
        "classifications_done": list(state.case_classifications.keys()),
        "has_cross_file": bool(state.cross_file_patterns),
        "open_questions": state.open_questions[:3],
        "last_observation": (
            state.observations[-1].result_summary if state.observations else ""
        ),
    }


# ── Rule-based fallback planner ───────────────────────────────────────────────

def _fallback_plan(state: InvestigationState) -> dict[str, Any]:
    """无 LLM 时的规则决策。"""
    fp = state.current_file

    if fp and fp not in state.file_overviews:
        return {
            "rationale": "尚未检查当前文件概览",
            "action": "inspect_file_overview",
            "arguments": {"file_path": fp},
        }

    if fp and fp not in state.event_summaries:
        return {
            "rationale": "尚未加载事件摘要",
            "action": "load_event_summary",
            "arguments": {"file_path": fp},
        }

    overview = state.file_overviews.get(fp)
    sem_dist = overview.semantic_event_distribution if overview else {}
    has_stoppage = sem_dist.get("stoppage_segment", 0) > 0

    if fp and has_stoppage and fp not in state.stoppage_cases:
        return {
            "rationale": f"stoppage_segment 事件 {sem_dist.get('stoppage_segment', 0)} 个，需合并",
            "action": "merge_stoppage_cases",
            "arguments": {"file_path": fp},
        }

    cases = state.stoppage_cases.get(fp, [])
    top_cases = cases[:3]
    uninspected = [
        c for c in top_cases if c.case_id not in state.transition_analyses
    ]
    if uninspected:
        c = uninspected[0]
        return {
            "rationale": f"检查 {c.case_id} 前后窗口",
            "action": "inspect_transition_window",
            "arguments": {"file_path": fp, "case_id": c.case_id},
        }

    unclassified = [
        c for c in top_cases
        if c.case_id in state.transition_analyses
        and c.case_id not in state.case_classifications
    ]
    if unclassified:
        c = unclassified[0]
        return {
            "rationale": f"分类 {c.case_id}",
            "action": "classify_stoppage_case",
            "arguments": {"case_id": c.case_id},
        }

    if len(state.input_files) > 1 and not state.cross_file_patterns:
        processed = [
            f for f in state.input_files if f in state.stoppage_cases
        ]
        unprocessed = [
            f for f in state.input_files if f not in state.file_overviews
        ]
        if unprocessed:
            next_file = unprocessed[0]
            return {
                "rationale": f"切换到下一个文件 {next_file}",
                "action": "inspect_file_overview",
                "arguments": {"file_path": next_file},
            }
        if len(processed) > 1:
            return {
                "rationale": "所有文件已处理，进行跨文件比较",
                "action": "compare_cases_across_files",
                "arguments": {"files": processed},
            }

    return {
        "rationale": "证据收集完成，生成报告",
        "action": "generate_investigation_report",
        "arguments": {},
    }


# ── LLM planner ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是一个 TBM 停机案例追查 agent 的决策器。
根据当前调查状态，选择下一步 action。

可用 actions: {actions}

输出严格 JSON：
{{"rationale": "简短理由", "action": "action_name", "arguments": {{...}}}}

不要输出长思维链。action 必须在白名单内。"""


def _llm_plan(state: InvestigationState) -> Optional[dict[str, Any]]:
    """调用 OpenAI-compatible API 进行决策。"""
    try:
        from openai import OpenAI
    except ImportError:
        logger.info("openai SDK not installed, falling back to rule-based planner")
        return None

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    if not api_key:
        logger.info("OPENAI_API_KEY not set, falling back to rule-based planner")
        return None

    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    client = OpenAI(**client_kwargs)
    compressed = _compress_state(state)

    model = os.environ.get("INVESTIGATION_MODEL", "MiniMax-M2.7")

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": _SYSTEM_PROMPT.format(actions=", ".join(AVAILABLE_ACTIONS)),
                },
                {
                    "role": "user",
                    "content": json.dumps(compressed, ensure_ascii=False),
                },
            ],
            max_tokens=256,
            temperature=0.2,
        )
        text = resp.choices[0].message.content.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
            if result.get("action") in AVAILABLE_ACTIONS:
                return result
            logger.warning("LLM returned invalid action: %s", result.get("action"))
    except Exception as exc:
        logger.warning("LLM planner failed: %s", exc)

    return None


# ── 公开接口 ──────────────────────────────────────────────────────────────────

def plan_next_action(
    state: InvestigationState,
    use_llm: bool = False,
) -> dict[str, Any]:
    """决定下一步 action。use_llm=True 时优先尝试 LLM，失败则 fallback。"""
    if use_llm:
        result = _llm_plan(state)
        if result:
            return result
        logger.info("LLM planner unavailable, using fallback")

    return _fallback_plan(state)

