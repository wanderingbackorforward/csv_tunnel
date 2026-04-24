"""planner.py — LLM planner + rule-based fallback

LLM planner 使用 OpenAI-compatible API。
无 API key 时自动降级为 rule-based fallback。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from tbm_diag.investigation.state import InvestigationState, FileOverview

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
    "analyze_stoppage_cases",
    "analyze_resistance_pattern",
    "analyze_hydraulic_pattern",
    "analyze_event_fragmentation",
    "drilldown_time_window",
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

def _fallback_plan(state: InvestigationState, audit: bool = False) -> dict[str, Any]:
    """无 LLM 时的动态规则决策。根据观察结果选择不同调查路径。"""
    fp = state.current_file
    candidates = []  # (action, reason, selected)
    rejected = []    # (action, reason)

    def _select(action: str, reason: str, arguments: dict) -> dict[str, Any]:
        candidates.append((action, reason))
        result = {
            "rationale": reason,
            "action": action,
            "arguments": arguments,
        }
        if audit:
            result["_audit"] = {
                "candidates": [(a, r) for a, r in candidates],
                "rejected": rejected[:],
            }
        return result

    def _reject(action: str, reason: str) -> None:
        rejected.append((action, reason))

    # Step 1: 先获取文件概览
    if fp and fp not in state.file_overviews:
        return _select("inspect_file_overview", "尚未检查当前文件概览", {"file_path": fp})

    # Step 2: 加载事件摘要
    if fp and fp not in state.event_summaries:
        return _select("load_event_summary", "尚未加载事件摘要", {"file_path": fp})

    # Step 3: 根据观察结果动态选择路径
    overview = state.file_overviews.get(fp)
    event_summary = state.event_summaries.get(fp)
    sem_dist = overview.semantic_event_distribution if overview else {}
    state_dist_map = overview.state_distribution if overview else {}

    stoppage_count = sem_dist.get("stoppage_segment", 0)
    ser_count = (sem_dist.get("suspected_excavation_resistance", 0)
                 + sem_dist.get("excavation_resistance_under_load", 0))
    hyd_count = sem_dist.get("hydraulic_instability", 0)
    total_events = overview.event_count if overview else 0
    stopped_pct = state_dist_map.get("stopped", 0)

    # 记录已对当前文件执行过的分析工具和 drilldown 目标
    file_analyses_done = set()
    drilldown_targets_done = set()
    for a in state.actions_taken:
        args = a.arguments or {}
        afp = args.get("file_path", "")
        if afp == fp or (not afp and a.action in (
            "analyze_stoppage_cases", "analyze_resistance_pattern",
            "analyze_hydraulic_pattern", "analyze_event_fragmentation",
        )):
            file_analyses_done.add(a.action)
        if a.action == "drilldown_time_window" and afp == fp:
            tid = args.get("target_id", "")
            if tid:
                drilldown_targets_done.add(tid)

    # 路径 A: 停机主导
    if stoppage_count >= 3 or stopped_pct >= 30:
        if "analyze_stoppage_cases" not in file_analyses_done:
            candidates.append(("analyze_stoppage_cases", f"stoppage={stoppage_count}, stopped={stopped_pct:.0f}%"))
        else:
            _reject("analyze_stoppage_cases", "已执行")
    else:
        _reject("analyze_stoppage_cases", f"stoppage={stoppage_count}<3, stopped={stopped_pct:.0f}%<30")

    if candidates and candidates[-1][0] == "analyze_stoppage_cases":
        return _select("analyze_stoppage_cases",
                       f"stoppage_segment={stoppage_count}, stopped={stopped_pct:.0f}%，优先停机追查",
                       {"file_path": fp})

    # 停机 drilldown
    if "analyze_stoppage_cases" in file_analyses_done:
        cases = state.stoppage_cases.get(fp, [])
        for c in cases[:3]:
            if c.case_id not in drilldown_targets_done:
                return _select("drilldown_time_window",
                               f"对停机案例 {c.case_id} ({c.duration_seconds/60:.0f}min) 做窗口钻取",
                               {"file_path": fp, "target_id": c.case_id})
        if cases:
            _reject("drilldown_time_window(stoppage)", f"top {min(3,len(cases))} cases 已钻取")

    # 路径 B: 掘进阻力主导
    if ser_count >= 3:
        if "analyze_resistance_pattern" not in file_analyses_done:
            return _select("analyze_resistance_pattern",
                           f"SER 事件 {ser_count} 个，进入掘进阻力模式分析",
                           {"file_path": fp})
        else:
            _reject("analyze_resistance_pattern", "已执行")
    else:
        _reject("analyze_resistance_pattern", f"SER={ser_count}<3")

    # SER drilldown
    if "analyze_resistance_pattern" in file_analyses_done and ser_count >= 2:
        top_events = event_summary.top_events if event_summary else []
        ser_types = {"suspected_excavation_resistance", "excavation_resistance_under_load"}
        ser_targets = [
            e for e in top_events
            if e.get("event_type") in ser_types or
            any(st in (e.get("semantic_type", "") or e.get("event_type", "")) for st in ser_types)
        ]
        if not ser_targets:
            ser_targets = [e for e in top_events if "resistance" in (e.get("event_type", "") or "").lower()]
        for e in ser_targets[:2]:
            eid = e.get("event_id", "")
            if eid and eid not in drilldown_targets_done:
                return _select("drilldown_time_window",
                               f"对 SER 事件 {eid} 做窗口钻取，判断是否发生在推进中",
                               {"file_path": fp, "target_id": eid})
        if ser_targets:
            _reject("drilldown_time_window(SER)", "top SER 已钻取")

    # 路径 C: 液压问题
    if hyd_count >= 3:
        if "analyze_hydraulic_pattern" not in file_analyses_done:
            return _select("analyze_hydraulic_pattern",
                           f"HYD 事件 {hyd_count} 个，分析液压异常模式",
                           {"file_path": fp})
        else:
            _reject("analyze_hydraulic_pattern", "已执行")
    else:
        _reject("analyze_hydraulic_pattern", f"HYD={hyd_count}<3")

    # HYD drilldown
    if "analyze_hydraulic_pattern" in file_analyses_done and hyd_count >= 2:
        top_events = event_summary.top_events if event_summary else []
        hyd_targets = [e for e in top_events if e.get("event_type") == "hydraulic_instability"]
        for e in hyd_targets[:2]:
            eid = e.get("event_id", "")
            if eid and eid not in drilldown_targets_done:
                return _select("drilldown_time_window",
                               f"对 HYD 事件 {eid} 做窗口钻取，判断是否在停机边界",
                               {"file_path": fp, "target_id": eid})
        if hyd_targets:
            _reject("drilldown_time_window(HYD)", "top HYD 已钻取")

    # 路径 D: 碎片化
    if total_events >= 8:
        top_events = event_summary.top_events if event_summary else []
        avg_dur = 0
        if top_events:
            durs = [e.get("duration_s", 0) for e in top_events]
            avg_dur = sum(durs) / len(durs) if durs else 0
        if avg_dur < 120 or total_events >= 15:
            if "analyze_event_fragmentation" not in file_analyses_done:
                return _select("analyze_event_fragmentation",
                               f"事件 {total_events} 个，平均时长 {avg_dur:.0f}s，检查碎片化",
                               {"file_path": fp})
            else:
                _reject("analyze_event_fragmentation", "已执行")
        else:
            _reject("analyze_event_fragmentation", f"events={total_events}, avg_dur={avg_dur:.0f}s 不满足碎片化条件")
    else:
        _reject("analyze_event_fragmentation", f"events={total_events}<8")

    # 补充分析
    last_obs = state.observations[-1] if state.observations else None
    if (last_obs and last_obs.action == "analyze_stoppage_cases"
            and ser_count >= 2 and "analyze_resistance_pattern" not in file_analyses_done):
        return _select("analyze_resistance_pattern",
                        "停机分析完成，SER 事件存在，补充阻力分析",
                        {"file_path": fp})

    # 多文件处理
    if len(state.input_files) > 1:
        not_overviewed = [f for f in state.input_files if f not in state.file_overviews]
        if not_overviewed:
            state.current_file = not_overviewed[0]
            return _select("inspect_file_overview", "切换到下一个文件",
                           {"file_path": not_overviewed[0]})

        not_evented = [f for f in state.input_files if f not in state.event_summaries]
        if not_evented:
            return _select("load_event_summary", "加载事件摘要",
                           {"file_path": not_evented[0]})

        if not state.cross_file_patterns:
            processed = [f for f in state.input_files if f in state.stoppage_cases]
            if len(processed) > 1:
                return _select("compare_cases_across_files", "所有文件已处理，进行跨文件比较",
                               {"files": processed})

    return _select("generate_investigation_report", "证据收集完成，生成报告", {})


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
    audit: bool = False,
) -> dict[str, Any]:
    """决定下一步 action。use_llm=True 时优先尝试 LLM，失败则 fallback。"""
    if use_llm:
        result = _llm_plan(state)
        if result:
            if audit:
                result["_audit"] = {"candidates": [], "rejected": [], "is_llm": True}
            return result
        logger.info("LLM planner unavailable, using fallback")

    return _fallback_plan(state, audit=audit)

