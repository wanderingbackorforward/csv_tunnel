"""planner.py — investigation planner: rule / llm / hybrid

planner_mode:
- rule: 纯规则决策，不调用 LLM
- llm: 每轮调用 LLM 选择 action
- hybrid: 前 2 轮规则（overview/events），后续关键分支由 LLM 决策
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

from tbm_diag.investigation.state import (
    InvestigationState, FileOverview, LlmCallRecord, PlannerParseResult,
)

logger = logging.getLogger(__name__)

LLM_TOOL_WHITELIST = [
    "inspect_file_overview",
    "load_event_summary",
    "analyze_stoppage_cases",
    "drilldown_time_window",
    "drilldown_time_windows_batch",
    "analyze_resistance_pattern",
    "analyze_hydraulic_pattern",
    "analyze_event_fragmentation",
    "generate_investigation_report",
]

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


def _strip_think_tags(text: str) -> str:
    """去除 <think ...>...</think 和未闭合 <think ...> 标签。"""
    text = re.sub(r"<think[^>]*>.*?</think\s*>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think[^>]*/>", "", text)
    text = re.sub(r"<think[^>]*>", "", text)
    return text.strip()


def _strip_code_fence(text: str) -> str:
    """去除 ```json ... ``` 或 ``` ... ``` 包裹。"""
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _extract_first_json(text: str) -> Optional[dict[str, Any]]:
    """用括号平衡扫描从文本中提取第一个完整 JSON object。"""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # 继续往后找下一个 {
                    next_start = text.find("{", i + 1)
                    if next_start < 0:
                        return None
                    return _extract_first_json(text[next_start:])
    return None


def parse_planner_response(
    response_message: Any,
    whitelist: list[str] | None = None,
) -> PlannerParseResult:
    """鲁棒解析 LLM planner 响应。

    支持：tool_calls、thinking 标签、code fence、括号平衡 JSON 提取。
    """
    if whitelist is None:
        whitelist = LLM_TOOL_WHITELIST

    raw_content = ""
    tool_calls = None

    if response_message is not None:
        raw_content = getattr(response_message, "content", None) or ""
        if not isinstance(raw_content, str):
            raw_content = str(raw_content)
        tool_calls = getattr(response_message, "tool_calls", None)

    # 策略 1: tool_calls
    if tool_calls:
        for tc in tool_calls:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            fn_name = getattr(fn, "name", "") or ""
            fn_args_str = getattr(fn, "arguments", "") or "{}"
            if fn_name == "planner_decision" or fn_name in whitelist:
                try:
                    args = json.loads(fn_args_str) if isinstance(fn_args_str, str) else fn_args_str
                    action = args.get("selected_action", fn_name)
                    if action in whitelist:
                        result = PlannerParseResult(
                            status="success",
                            parsed={
                                "thought_summary": args.get("thought_summary", ""),
                                "selected_action": action,
                                "arguments": args.get("arguments", {}),
                                "selected_reason": args.get("selected_reason", ""),
                                "rejected_actions": args.get("rejected_actions", []),
                                "stop": args.get("stop", False),
                            },
                            raw_content=raw_content[:1500],
                            cleaned_content=f"tool_call:{fn_name}",
                            raw_preview=raw_content[:1500],
                            parse_strategy="tool_call",
                        )
                        return result
                except json.JSONDecodeError:
                    pass
        # tool_calls 存在但没有找到有效的 planner decision
        return PlannerParseResult(
            status="tool_call_found",
            raw_content=raw_content[:1500],
            raw_preview=raw_content[:1500],
            error_message="tool_calls 存在但未找到有效的 planner decision",
            parse_strategy="tool_call",
        )

    # 策略 2: content 为空
    if not raw_content.strip():
        return PlannerParseResult(
            status="empty_content",
            raw_content="",
            error_message="response.content 为空且无 tool_calls",
            parse_strategy="none",
        )

    # 策略 3: 清洗 content 并提取 JSON
    cleaned = _strip_think_tags(raw_content)
    cleaned = _strip_code_fence(cleaned)
    cleaned = cleaned.strip()

    # 尝试直接解析
    parsed = None
    parse_strategy = ""

    try:
        parsed = json.loads(cleaned)
        parse_strategy = "direct_json"
    except json.JSONDecodeError:
        pass

    # 直接失败则用括号平衡扫描
    if parsed is None:
        parsed = _extract_first_json(cleaned)
        if parsed is not None:
            parse_strategy = "balanced_scan"

    if parsed is None:
        # 最后尝试从原始未清洗文本提取
        parsed = _extract_first_json(raw_content)
        if parsed is not None:
            parse_strategy = "balanced_scan_raw"

    if parsed is None:
        return PlannerParseResult(
            status="json_not_found",
            raw_content=raw_content[:1500],
            cleaned_content=cleaned[:1500],
            raw_preview=raw_content[:1500],
            error_message="清洗后和原始文本中均未找到合法 JSON",
            parse_strategy="none",
        )

    # schema 校验
    if not isinstance(parsed, dict):
        return PlannerParseResult(
            status="json_invalid",
            raw_content=raw_content[:1500],
            cleaned_content=cleaned[:1500],
            raw_preview=raw_content[:1500],
            error_message=f"解析到非 object 类型: {type(parsed).__name__}",
            parse_strategy=parse_strategy,
        )

    action = parsed.get("selected_action", "")
    if not isinstance(action, str) or action not in whitelist:
        return PlannerParseResult(
            status="schema_invalid",
            parsed=parsed,
            raw_content=raw_content[:1500],
            cleaned_content=cleaned[:1500],
            raw_preview=raw_content[:1500],
            error_message=f"selected_action='{action}' 不在白名单中",
            parse_strategy=parse_strategy,
        )

    # 补全缺失字段
    parsed.setdefault("arguments", {})
    parsed.setdefault("selected_reason", "")
    parsed.setdefault("stop", False)
    parsed.setdefault("thought_summary", "")
    parsed.setdefault("rejected_actions", [])

    return PlannerParseResult(
        status="success",
        parsed=parsed,
        raw_content=raw_content[:1500],
        cleaned_content=cleaned[:1500],
        raw_preview=raw_content[:1500],
        parse_strategy=parse_strategy,
    )


def _compress_state(state: InvestigationState) -> dict[str, Any]:
    """压缩 state 为 LLM 可消费的摘要。"""
    overview = state.file_overviews.get(state.current_file)
    sem_dist = overview.semantic_event_distribution if overview else {}
    state_dist = overview.state_distribution if overview else {}

    actions_done = [a.action for a in state.actions_taken]

    stoppage_case_count = sum(len(v) for v in state.stoppage_cases.values())
    drilldown_sc_count = sum(
        1 for a in state.actions_taken
        if a.action == "drilldown_time_window"
        and (a.arguments or {}).get("target_id", "").startswith("SC_")
    )
    unverified_cases = [
        cid for cid, cls in state.case_classifications.items()
        if cls.case_type == "event_level_abnormal_unverified"
    ]
    drilldown_done_ids = {
        (a.arguments or {}).get("target_id", "")
        for a in state.actions_taken
        if a.action == "drilldown_time_window"
    }
    unverified_not_drilled = [cid for cid in unverified_cases if cid not in drilldown_done_ids]

    return {
        "mode": state.mode,
        "focus": state.focus,
        "current_file": state.current_file,
        "round": state.iteration_count,
        "max_iterations": 15,
        "actions_done": actions_done,
        "last_observation": (
            state.observations[-1].result_summary if state.observations else ""
        ),
        "indicators": {
            "event_count": overview.event_count if overview else 0,
            "stoppage_segment_count": sem_dist.get("stoppage_segment", 0),
            "stopped_ratio_pct": state_dist.get("stopped", 0),
            "ser_count": (sem_dist.get("suspected_excavation_resistance", 0)
                         + sem_dist.get("excavation_resistance_under_load", 0)),
            "hyd_count": sem_dist.get("hydraulic_instability", 0),
        },
        "evidence_status": {
            "stoppage_case_count": stoppage_case_count,
            "drilldown_sc_count": drilldown_sc_count,
            "unverified_not_drilled": unverified_not_drilled,
        },
        "open_questions": [
            {"qid": q.qid, "text": q.text, "priority": q.priority, "status": q.status}
            for q in state.investigation_questions
            if q.status != "answered"
        ],
        "available_tools": [t for t in LLM_TOOL_WHITELIST if t not in actions_done],
        "completed_tools": [t for t in LLM_TOOL_WHITELIST if t in actions_done],
    }


def build_planner_decision_context(state: InvestigationState) -> dict[str, Any]:
    """构建极简 planner decision context，限制 token 量。

    与 _compress_state 不同，这个函数只返回决策必需的字段，
    并包含 rule_recommended_action 供 LLM 参考。
    """
    overview = state.file_overviews.get(state.current_file)
    sem_dist = overview.semantic_event_distribution if overview else {}
    state_dist = overview.state_distribution if overview else {}

    actions_done = [a.action for a in state.actions_taken]
    recent_actions = actions_done[-5:]

    stoppage_case_count = sum(len(v) for v in state.stoppage_cases.values())
    drilldown_sc_count = sum(
        1 for a in state.actions_taken
        if a.action == "drilldown_time_window"
        and (a.arguments or {}).get("target_id", "").startswith("SC_")
    )
    ser_count = (sem_dist.get("suspected_excavation_resistance", 0)
                 + sem_dist.get("excavation_resistance_under_load", 0))
    hyd_count = sem_dist.get("hydraulic_instability", 0)
    stopped_pct = state_dist.get("stopped", 0)
    event_count = overview.event_count if overview else 0

    unverified_cases = [
        cid for cid, cls in state.case_classifications.items()
        if cls.case_type == "event_level_abnormal_unverified"
    ]
    drilldown_done_ids = {
        (a.arguments or {}).get("target_id", "")
        for a in state.actions_taken
        if a.action == "drilldown_time_window"
    }
    unverified_not_drilled = [cid for cid in unverified_cases if cid not in drilldown_done_ids]

    available_tools = [t for t in LLM_TOOL_WHITELIST if t not in actions_done]

    last_obs = ""
    if state.observations:
        last_obs = (state.observations[-1].result_summary or "")[:200]

    # plan status summary
    plan_summary = {}
    if state.investigation_plan:
        for item in state.investigation_plan.plan_items:
            plan_summary[item.plan_id] = item.status

    # open questions summary
    question_summary = []
    for q in state.investigation_questions:
        if q.status != "answered":
            question_summary.append(f"{q.qid}:{q.status}")

    # rule recommendation
    rule_rec = _fallback_plan(state)
    rule_recommended = rule_rec.get("action", "")
    rule_reason = rule_rec.get("rationale", "")[:100]

    return {
        "round": state.iteration_count,
        "recent_actions": recent_actions,
        "last_obs": last_obs,
        "stoppage_cases": stoppage_case_count,
        "drilldown_done": drilldown_sc_count,
        "ser_count": ser_count,
        "hyd_count": hyd_count,
        "stopped_pct": round(stopped_pct),
        "event_count": event_count,
        "unverified_count": len(unverified_not_drilled),
        "plan_status": plan_summary,
        "questions": question_summary,
        "allowed_actions": available_tools,
        "rule_recommended": rule_recommended,
        "rule_reason": rule_reason,
    }


_LLM_SYSTEM_PROMPT_MINIMAL = """你是 TBM 调查决策器。从 allowed_actions 中选一个动作。
rule_recommended 是规则系统推荐的动作，没有充分理由请选择它。

只输出 JSON: {"selected_action": "动作名", "selected_reason": "理由", "stop": false}

禁止输出 <think ...> 标签。禁止输出 markdown。只输出 JSON。
SER 是掘进阻力异常，不是电阻。"""


def _llm_plan(state: InvestigationState, audit: bool = False) -> tuple[Optional[dict[str, Any]], LlmCallRecord]:
    """调用 OpenAI-compatible API 进行决策。返回 (decision, call_record)。"""
    record = LlmCallRecord(round_num=state.iteration_count)

    try:
        from openai import OpenAI
    except ImportError:
        record.status = "no_sdk"
        record.error_message = "openai SDK 未安装"
        return None, record

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None
    if not api_key:
        record.status = "no_key"
        record.error_message = "OPENAI_API_KEY 未设置"
        return None, record

    model = os.environ.get("LLM_MODEL", "").strip()
    if not model:
        from tbm_diag.config import DiagConfig
        cfg = DiagConfig()
        model = cfg.llm.model or "gpt-4o-mini"
    record.model = model
    record.base_url_host = urlparse(base_url).hostname if base_url else "api.openai.com"

    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    # 使用极简 context + rule recommendation
    ctx = build_planner_decision_context(state)

    client = OpenAI(**client_kwargs)
    t0 = time.time()

    # MiniMax reasoning_split 支持
    use_reasoning_split = os.environ.get("LLM_REASONING_SPLIT", "").strip().lower() in ("true", "1", "yes")

    try:
        create_kwargs: dict[str, Any] = dict(
            model=model,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT_MINIMAL},
                {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)},
            ],
            max_tokens=1024,
            temperature=0.1,
            timeout=30,
        )
        if use_reasoning_split:
            create_kwargs["extra_body"] = {"reasoning_split": True}

        try:
            resp = client.chat.completions.create(**create_kwargs)
        except Exception as exc:
            if use_reasoning_split and any(k in str(exc).lower() for k in (
                "extra_body", "reasoning_split", "unknown", "invalid", "unexpected", "parameter",
            )):
                logger.warning("_llm_plan: reasoning_split not supported, retrying without")
                create_kwargs.pop("extra_body", None)
                resp = client.chat.completions.create(**create_kwargs)
            else:
                raise

        record.latency_seconds = round(time.time() - t0, 2)

        msg = resp.choices[0].message
        pr = parse_planner_response(msg, whitelist=LLM_TOOL_WHITELIST)

        record.raw_preview = pr.raw_preview[:1500]
        record.cleaned_preview = pr.cleaned_content[:1500]
        record.parse_strategy = pr.parse_strategy

        if pr.status != "success":
            record.status = "parse_error"
            record.error_message = pr.error_message
            return None, record

        parsed = pr.parsed
        action = parsed["selected_action"]

        record.status = "success"
        record.selected_action = action
        record.selected_reason = parsed.get("selected_reason", "")
        record.thought_summary = parsed.get("thought_summary", "")

        arguments = parsed.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        arguments.pop("current_file", None)
        if "file_path" not in arguments and action != "generate_investigation_report":
            arguments["file_path"] = state.current_file

        result = {
            "rationale": parsed.get("selected_reason", parsed.get("thought_summary", "")),
            "action": action,
            "arguments": arguments,
        }
        if audit:
            rejected = parsed.get("rejected_actions", [])
            result["_audit"] = {
                "candidates": [(action, record.selected_reason)],
                "rejected": [(r.get("action", ""), r.get("reason", "")) for r in rejected] if isinstance(rejected, list) else [],
                "is_llm": True,
                "triggered_by": "",
                "observation_used": "",
            }

        if parsed.get("stop"):
            result["action"] = "generate_investigation_report"
            result["arguments"] = {}

        return result, record

    except Exception as exc:
        record.latency_seconds = round(time.time() - t0, 2)
        exc_name = type(exc).__name__
        if "timeout" in exc_name.lower() or "timed out" in str(exc).lower():
            record.status = "timeout"
        else:
            record.status = "api_error"
        record.error_message = f"{exc_name}: {str(exc)[:200]}"
        return None, record

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

    # 停机 drilldown — depth-aware target selection
    if run_stoppage and "analyze_stoppage_cases" in file_analyses_done:
        from tbm_diag.investigation.investigation_depth import (
            compute_stoppage_coverage_target,
            select_stoppage_drilldown_batch,
        )
        cases = state.stoppage_cases.get(fp, [])
        depth = getattr(state, "investigation_depth", "standard") or "standard"
        cov_target = compute_stoppage_coverage_target(len(cases), depth)
        drilled_sc = {tid for tid in drilldown_targets_done if tid.startswith("SC_")}
        batch_ids = select_stoppage_drilldown_batch(drilled_sc, cases, cov_target)
        if batch_ids:
            target_id = batch_ids[0]
            dur = next((c.duration_seconds / 60 for c in cases if c.case_id == target_id), 0)
            return _select("drilldown_time_window",
                           f"对停机案例 {target_id} ({dur:.0f}min) 做窗口钻取",
                           {"file_path": fp, "target_id": target_id})
        if cases:
            _reject("drilldown_time_window(stoppage)",
                    f"stoppage coverage target met ({len(drilled_sc)}/{cov_target.target_count})")

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
            if durs:
                avg_dur = sum(durs) / len(durs)
        dur_note = f"（Top {len(top_events)} 事件均值）" if top_events and len(top_events) < total_events else ""
        if avg_dur < 120 or total_events >= 15 or focus == "fragmentation":
            if "analyze_event_fragmentation" not in file_analyses_done:
                return _select("analyze_event_fragmentation",
                               f"事件 {total_events} 个，Top 事件平均时长 {avg_dur:.0f}s{dur_note}，检查碎片化",
                               {"file_path": fp})
            else:
                _reject("analyze_event_fragmentation", "已执行")
        else:
            _reject("analyze_event_fragmentation",
                    f"events={total_events}, top_avg_dur={avg_dur:.0f}s 不满足碎片化条件")
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


# ── 公开接口 ──────────────────────────────────────────────────────────────────

def plan_next_action(
    state: InvestigationState,
    use_llm: bool = False,
    audit: bool = False,
    planner_mode: str = "rule",
) -> dict[str, Any]:
    """决定下一步 action。

    planner_mode:
    - rule: 纯规则
    - llm: 每轮调 LLM，失败 fallback
    - hybrid: 前 2 轮规则，后续调 LLM
    """
    # 兼容旧 use_llm 参数
    if use_llm and planner_mode == "rule":
        planner_mode = "llm"

    use_llm_this_round = False
    if planner_mode == "llm":
        use_llm_this_round = True
    elif planner_mode == "hybrid":
        use_llm_this_round = state.iteration_count > 2

    if use_llm_this_round:
        result, call_record = _llm_plan(state, audit=audit)
        state.llm_calls.append(call_record)
        state.llm_call_count += 1
        if call_record.model and not state.llm_model:
            state.llm_model = call_record.model

        if result:
            state.llm_success_count += 1
            result["_planner_type"] = "llm" if planner_mode == "llm" else "hybrid_llm"
            result["_llm_status"] = "success"
            return result
        else:
            state.llm_fallback_count += 1
            logger.info("LLM planner %s (round %d), fallback to rule",
                        call_record.status, state.iteration_count)
            fb = _fallback_plan(state, audit=audit)
            fb["_planner_type"] = "llm" if planner_mode == "llm" else "hybrid_llm"
            fb["_llm_status"] = call_record.status
            fb["_fallback_used"] = True
            return fb

    # rule planner (or hybrid early rounds)
    skipped_record = LlmCallRecord(
        round_num=state.iteration_count,
        status="skipped",
    )
    state.llm_calls.append(skipped_record)

    fb = _fallback_plan(state, audit=audit)
    fb["_planner_type"] = "rule" if planner_mode == "rule" else "hybrid_rule"
    fb["_llm_status"] = "skipped"
    return fb

