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

def _get_last_obs_data(state: InvestigationState, action_name: str) -> dict:
    """获取最近一次指定 action 的 observation data。"""
    for obs in reversed(state.observations):
        if obs.action == action_name:
            return obs.data or {}
    return {}


def _fallback_plan(state: InvestigationState, audit: bool = False) -> dict[str, Any]:
    """动态规则决策。根据 focus + observation 选择路径。"""
    fp = state.current_file
    candidates = []
    rejected = []
    triggered_by = ""
    obs_used = ""

    def _select(action: str, reason: str, arguments: dict,
                trigger: str = "", obs_ref: str = "") -> dict[str, Any]:
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
                "triggered_by": trigger,
                "observation_used": obs_ref,
            }
        return result

    def _reject(action: str, reason: str) -> None:
        rejected.append((action, reason))

    # Step 1/2: overview + events (mandatory)
    if fp and fp not in state.file_overviews:
        return _select("inspect_file_overview", "尚未检查当前文件概览", {"file_path": fp})
    if fp and fp not in state.event_summaries:
        return _select("load_event_summary", "尚未加载事件摘要", {"file_path": fp})

    # ── 读取文件特征 ──
    focus = state.focus or "auto"
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

    run_stoppage = focus in ("auto", "stoppage")
    run_resistance = focus in ("auto", "resistance")
    run_hydraulic = focus in ("auto", "hydraulic")
    run_fragmentation = focus in ("auto", "fragmentation")

    # ── 读取已有 observation 数据 ──
    res_obs = _get_last_obs_data(state, "analyze_resistance_pattern")
    hyd_obs = _get_last_obs_data(state, "analyze_hydraulic_pattern")
    frag_obs = _get_last_obs_data(state, "analyze_event_fragmentation")
    stoppage_obs = _get_last_obs_data(state, "analyze_stoppage_cases")

    # 收集所有 drilldown observations 的 interpretation_hint
    drilldown_hints = []
    for obs in state.observations:
        if obs.action == "drilldown_time_window":
            d = obs.data or {}
            drilldown_hints.append({
                "target": d.get("target_id", ""),
                "hint": d.get("interpretation_hint", ""),
                "pre_ser": (d.get("pre_summary") or {}).get("ser_ratio", 0),
                "pre_hyd": (d.get("pre_summary") or {}).get("hyd_ratio", 0),
            })

    # ════════════════════════════════════════════════════════════════════
    # 路径 A: 停机
    # ════════════════════════════════════════════════════════════════════
    if run_stoppage and (stoppage_count >= 3 or stopped_pct >= 30 or focus == "stoppage"):
        if "analyze_stoppage_cases" not in file_analyses_done:
            return _select("analyze_stoppage_cases",
                           f"stoppage_segment={stoppage_count}, stopped={stopped_pct:.0f}%，优先停机追查",
                           {"file_path": fp})
        else:
            _reject("analyze_stoppage_cases", "已执行")
    else:
        _reject("analyze_stoppage_cases",
                f"focus={focus}" if not run_stoppage else f"stoppage={stoppage_count}<3, stopped={stopped_pct:.0f}%<30")

    # 停机 drilldown
    if run_stoppage and "analyze_stoppage_cases" in file_analyses_done:
        cases = state.stoppage_cases.get(fp, [])
        for c in cases[:3]:
            if c.case_id not in drilldown_targets_done:
                return _select("drilldown_time_window",
                               f"对停机案例 {c.case_id} ({c.duration_seconds/60:.0f}min) 做窗口钻取",
                               {"file_path": fp, "target_id": c.case_id})
        if cases:
            _reject("drilldown_time_window(stoppage)", f"top {min(3,len(cases))} cases 已钻取")

    # ★ 停机 observation-reactive: drilldown 发现停机前有 SER/HYD → 追加分析
    if (run_stoppage and "analyze_stoppage_cases" in file_analyses_done
            and drilldown_hints):
        pre_ser_any = any(h["pre_ser"] > 0.05 for h in drilldown_hints)
        pre_hyd_any = any(h["pre_hyd"] > 0.05 for h in drilldown_hints)
        hint_anomaly = any("异常迹象" in h["hint"] for h in drilldown_hints)

        if (pre_ser_any or hint_anomaly) and "analyze_resistance_pattern" not in file_analyses_done:
            return _select("analyze_resistance_pattern",
                           "drilldown 发现停机前存在 SER 异常迹象，追加阻力分析",
                           {"file_path": fp},
                           trigger="drilldown.pre_ser_ratio>0.05",
                           obs_ref="drilldown_time_window.interpretation_hint")
        if pre_hyd_any and "analyze_hydraulic_pattern" not in file_analyses_done:
            return _select("analyze_hydraulic_pattern",
                           "drilldown 发现停机前存在 HYD 异常迹象，追加液压分析",
                           {"file_path": fp},
                           trigger="drilldown.pre_hyd_ratio>0.05",
                           obs_ref="drilldown_time_window.pre_summary.hyd_ratio")

    # ════════════════════════════════════════════════════════════════════
    # 路径 B: 掘进阻力
    # ════════════════════════════════════════════════════════════════════
    if run_resistance and (ser_count >= 3 or focus == "resistance"):
        if "analyze_resistance_pattern" not in file_analyses_done:
            return _select("analyze_resistance_pattern",
                           f"SER 事件 {ser_count} 个，进入掘进阻力模式分析",
                           {"file_path": fp})
        else:
            _reject("analyze_resistance_pattern", "已执行")
    else:
        _reject("analyze_resistance_pattern",
                f"focus={focus}" if not run_resistance else f"SER={ser_count}<3")

    # SER drilldown — 使用 analyze_resistance_pattern 返回的 top_ser_event_ids
    if run_resistance and "analyze_resistance_pattern" in file_analyses_done:
        ser_targets = res_obs.get("top_ser_event_ids", [])
        for eid in ser_targets[:2]:
            if eid and eid not in drilldown_targets_done:
                return _select("drilldown_time_window",
                               f"对 SER 事件 {eid} 做窗口钻取（来自 resistance 分析 top 目标）",
                               {"file_path": fp, "target_id": eid},
                               trigger="resistance.top_ser_event_ids",
                               obs_ref="analyze_resistance_pattern.top_ser_event_ids")
        if ser_targets:
            _reject("drilldown_time_window(SER)", "top SER 已钻取")

    # ★ resistance observation-reactive
    if run_resistance and "analyze_resistance_pattern" in file_analyses_done and res_obs:
        if res_obs.get("near_stoppage") and "analyze_stoppage_cases" not in file_analyses_done:
            return _select("analyze_stoppage_cases",
                           "SER 靠近停机，追加停机分析以判断是否为停机前兆",
                           {"file_path": fp},
                           trigger="resistance.near_stoppage=True",
                           obs_ref="analyze_resistance_pattern.near_stoppage")

    # ════════════════════════════════════════════════════════════════════
    # 路径 C: 液压
    # ════════════════════════════════════════════════════════════════════
    if run_hydraulic and (hyd_count >= 3 or focus == "hydraulic"):
        if "analyze_hydraulic_pattern" not in file_analyses_done:
            return _select("analyze_hydraulic_pattern",
                           f"HYD 事件 {hyd_count} 个，分析液压异常模式",
                           {"file_path": fp})
        else:
            _reject("analyze_hydraulic_pattern", "已执行")
    else:
        _reject("analyze_hydraulic_pattern",
                f"focus={focus}" if not run_hydraulic else f"HYD={hyd_count}<3")

    # HYD drilldown — 使用 analyze_hydraulic_pattern 返回的 top_hyd_event_ids
    if run_hydraulic and "analyze_hydraulic_pattern" in file_analyses_done:
        if hyd_obs.get("isolated_short_fluctuation") and hyd_obs.get("hyd_total_duration_h", 0) < 0.5:
            _reject("drilldown_time_window(HYD)",
                    "HYD 为孤立短时波动且总时长<0.5h，跳过钻取")
        else:
            hyd_targets = hyd_obs.get("top_hyd_event_ids", [])
            for eid in hyd_targets[:2]:
                if eid and eid not in drilldown_targets_done:
                    return _select("drilldown_time_window",
                                   f"对 HYD 事件 {eid} 做窗口钻取（来自 hydraulic 分析 top 目标）",
                                   {"file_path": fp, "target_id": eid},
                                   trigger="hydraulic.top_hyd_event_ids",
                                   obs_ref="analyze_hydraulic_pattern.top_hyd_event_ids")
            if hyd_targets:
                _reject("drilldown_time_window(HYD)", "top HYD 已钻取")

    # ★ hydraulic observation-reactive
    if run_hydraulic and "analyze_hydraulic_pattern" in file_analyses_done and hyd_obs:
        if hyd_obs.get("near_stoppage_boundary") and "analyze_stoppage_cases" not in file_analyses_done:
            return _select("analyze_stoppage_cases",
                           "HYD 靠近停机边界，追加停机分析以判断是否为启停波动",
                           {"file_path": fp},
                           trigger="hydraulic.near_stoppage_boundary=True",
                           obs_ref="analyze_hydraulic_pattern.near_stoppage_boundary")
        if hyd_obs.get("sync_with_ser") and "analyze_resistance_pattern" not in file_analyses_done:
            return _select("analyze_resistance_pattern",
                           "HYD 与 SER 同步，追加阻力分析以判断是否为伴随现象",
                           {"file_path": fp},
                           trigger="hydraulic.sync_with_ser=True",
                           obs_ref="analyze_hydraulic_pattern.sync_with_ser")

    # ════════════════════════════════════════════════════════════════════
    # 路径 D: 碎片化
    # ════════════════════════════════════════════════════════════════════
    if run_fragmentation and (total_events >= 8 or focus == "fragmentation"):
        top_events = event_summary.top_events if event_summary else []
        avg_dur = 0
        if top_events:
            durs = [e.get("duration_s", 0) for e in top_events]
            avg_dur = sum(durs) / len(durs) if durs else 0
        if avg_dur < 120 or total_events >= 15 or focus == "fragmentation":
            if "analyze_event_fragmentation" not in file_analyses_done:
                return _select("analyze_event_fragmentation",
                               f"事件 {total_events} 个，平均时长 {avg_dur:.0f}s，检查碎片化",
                               {"file_path": fp})
            else:
                _reject("analyze_event_fragmentation", "已执行")
        else:
            _reject("analyze_event_fragmentation",
                    f"events={total_events}, avg_dur={avg_dur:.0f}s 不满足碎片化条件")
    else:
        _reject("analyze_event_fragmentation",
                f"focus={focus}" if not run_fragmentation else f"events={total_events}<8")

    # ★ fragmentation observation-reactive
    if run_fragmentation and "analyze_event_fragmentation" in file_analyses_done and frag_obs:
        if not frag_obs.get("fragmentation_risk") and ser_count >= 3 and "analyze_resistance_pattern" not in file_analyses_done:
            return _select("analyze_resistance_pattern",
                           "碎片化风险低但 SER 明显，追加阻力分析",
                           {"file_path": fp},
                           trigger="fragmentation.risk=False+SER>=3",
                           obs_ref="analyze_event_fragmentation.fragmentation_risk")

    # ════════════════════════════════════════════════════════════════════
    # 多文件 / 收尾
    # ════════════════════════════════════════════════════════════════════
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

