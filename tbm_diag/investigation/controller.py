"""controller.py — ReAct 循环控制器

Reason-Act-Observe 循环：
1. 读取当前 InvestigationState
2. planner 决定下一步 action
3. 调用对应工具
4. 将 observation 写回 state
5. 判断是否终止
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from tbm_diag.investigation.state import (
    InvestigationState,
    ActionRecord,
    Observation,
    EvidenceGateOverride,
    OpenQuestion,
)
from tbm_diag.investigation.tools import TOOL_REGISTRY
from tbm_diag.investigation.planner import plan_next_action
from tbm_diag.investigation.memory import save_case_memory

logger = logging.getLogger(__name__)


@dataclass
class InvestigationResult:
    state: InvestigationState
    report_text: str = ""
    report_path: Optional[str] = None
    state_path: Optional[str] = None
    memory_path: Optional[str] = None
    error: Optional[str] = None


def _execute_action(
    action: str,
    arguments: dict[str, Any],
    state: InvestigationState,
) -> dict[str, Any]:
    """执行一个工具调用，返回结构化结果。"""
    tool_info = TOOL_REGISTRY.get(action)
    if not tool_info:
        return {"status": "error", "error": f"unknown action: {action}"}

    fn = tool_info["fn"]
    allowed_params = set(tool_info.get("params", []))

    if action == "inspect_transition_window":
        arguments["state"] = state
    elif action == "classify_stoppage_case":
        arguments["state"] = state
    elif action == "compare_cases_across_files":
        arguments["state"] = state
    elif action == "generate_investigation_report":
        arguments["state"] = state
    elif action == "analyze_stoppage_cases":
        arguments["state"] = state
    elif action == "drilldown_time_window":
        arguments["state"] = state

    allowed_params.add("state")
    clean_args = {k: v for k, v in arguments.items() if k in allowed_params}

    try:
        return fn(**clean_args)
    except Exception as exc:
        logger.error("tool %s failed: %s", action, exc)
        return {"status": "error", "error": str(exc)}


def _update_state(
    state: InvestigationState,
    action: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """根据工具返回更新 state。"""
    fp = arguments.get("file_path", state.current_file)

    if action == "inspect_file_overview" and result.get("status") == "ok":
        state.current_file = fp
        from tbm_diag.investigation.state import FileOverview
        state.file_overviews[fp] = FileOverview(
            file_path=fp,
            total_rows=result.get("total_rows", 0),
            time_start=result.get("time_start", ""),
            time_end=result.get("time_end", ""),
            state_distribution=result.get("state_distribution", {}),
            event_count=result.get("event_count", 0),
            semantic_event_distribution=result.get("semantic_event_distribution", {}),
        )

    elif action == "load_event_summary" and result.get("status") == "ok":
        from tbm_diag.investigation.state import EventSummary
        state.event_summaries[fp] = EventSummary(
            file_path=fp,
            event_count=result.get("event_count", 0),
            event_type_distribution=result.get("event_type_distribution", {}),
            semantic_event_distribution=result.get("semantic_event_distribution", {}),
            top_events=result.get("top_events", []),
        )

    elif action == "merge_stoppage_cases" and result.get("status") == "ok":
        case_objects = result.get("_case_objects", [])
        state.stoppage_cases[fp] = case_objects

    elif action == "inspect_transition_window" and result.get("status") == "ok":
        analysis = result.get("_analysis_object")
        if analysis:
            state.transition_analyses[analysis.case_id] = analysis

    elif action == "classify_stoppage_case" and result.get("status") == "ok":
        cls_obj = result.get("_classification_object")
        if cls_obj:
            state.case_classifications[cls_obj.case_id] = cls_obj
            state.confidence = _compute_confidence(state)

    elif action == "compare_cases_across_files" and result.get("status") == "ok":
        state.cross_file_patterns = result.get("patterns", [])


def _compute_confidence(state: InvestigationState) -> float:
    """根据已完成的分析步骤计算整体置信度。"""
    total_cases = sum(len(v) for v in state.stoppage_cases.values())
    if total_cases == 0:
        return 0.0

    classified = len(state.case_classifications)
    top_n = min(total_cases, 5)
    classified_top = min(classified, top_n)
    ratio = classified_top / top_n

    files_done = sum(1 for f in state.input_files if f in state.stoppage_cases)
    file_ratio = files_done / len(state.input_files) if state.input_files else 0

    return min(round(ratio * 0.5 + file_ratio * 0.3 + 0.05, 2), 0.85)


def _make_observation_summary(action: str, result: dict[str, Any]) -> str:
    """生成简短的 observation 摘要。"""
    if result.get("status") == "error":
        return f"error: {result.get('error', 'unknown')}"

    if action == "inspect_file_overview":
        return (
            f"rows={result.get('total_rows')}, events={result.get('event_count')}, "
            f"time={result.get('time_start')}~{result.get('time_end')}"
        )
    elif action == "load_event_summary":
        return f"events={result.get('event_count')}, sem_dist={result.get('semantic_event_distribution')}"
    elif action == "merge_stoppage_cases":
        return f"merged {result.get('original_stoppage_events')} events into {result.get('merged_cases')} cases"
    elif action == "inspect_transition_window":
        return (
            f"case={result.get('case_id')}, pre_ser={result.get('pre_has_ser')}, "
            f"pre_hyd={result.get('pre_has_hyd')}, post_anomaly={result.get('post_has_anomaly')}"
        )
    elif action == "classify_stoppage_case":
        return f"case={result.get('case_id')}, type={result.get('case_type')}, conf={result.get('confidence')}"
    elif action == "compare_cases_across_files":
        return f"files={result.get('files_compared')}, patterns={result.get('patterns')}"
    elif action == "generate_investigation_report":
        return f"report generated, {result.get('total_merged_cases')} cases"
    elif action == "analyze_stoppage_cases":
        return result.get("summary", f"cases={result.get('merged_cases')}")
    elif action == "analyze_resistance_pattern":
        return result.get("summary", f"ser={result.get('ser_count')}")
    elif action == "analyze_hydraulic_pattern":
        return result.get("summary", f"hyd={result.get('hyd_count')}")
    elif action == "analyze_event_fragmentation":
        return result.get("summary", f"events={result.get('event_count')}")
    elif action == "drilldown_time_window":
        return result.get("summary", f"target={result.get('target_id')}")
    return json.dumps({k: v for k, v in result.items() if not k.startswith("_")}, ensure_ascii=False)[:200]


def _generate_investigation_questions(state: InvestigationState) -> None:
    """根据文件特征生成调查问题。在 inspect_file_overview 完成后调用。"""
    if state.investigation_questions:
        return

    overview = state.file_overviews.get(state.current_file)
    if not overview:
        return

    sem = overview.semantic_event_distribution
    sd = overview.state_distribution
    stoppage_count = sem.get("stoppage_segment", 0)
    stopped_pct = sd.get("stopped", 0)
    ser_count = (sem.get("suspected_excavation_resistance", 0)
                 + sem.get("excavation_resistance_under_load", 0))
    hyd_count = sem.get("hydraulic_instability", 0)
    event_count = overview.event_count

    questions: list[OpenQuestion] = []

    # Q1: 停机
    if stoppage_count >= 3 or stopped_pct >= 30:
        questions.append(OpenQuestion(
            qid="Q1",
            text="是否存在长停机？停机是否有异常前兆？",
            priority="high",
            relevant_tools=["analyze_stoppage_cases", "drilldown_time_window"],
            needs_manual_check=True,
        ))
    else:
        questions.append(OpenQuestion(
            qid="Q1",
            text="是否存在长停机？停机是否有异常前兆？",
            priority="low",
            status="answered",
            relevant_tools=["analyze_stoppage_cases"],
            findings=[f"停机片段仅 {stoppage_count} 个，stopped={stopped_pct:.0f}%，不构成主要问题"],
        ))

    # Q2: SER
    if ser_count >= 3:
        questions.append(OpenQuestion(
            qid="Q2",
            text="SER 是否是推进中的真实阻力异常，还是停机/语义重叠？",
            priority="high",
            relevant_tools=["analyze_resistance_pattern", "drilldown_time_window"],
            needs_manual_check=True,
        ))
    else:
        questions.append(OpenQuestion(
            qid="Q2",
            text="SER 是否是推进中的真实阻力异常，还是停机/语义重叠？",
            priority="low",
            status="answered",
            relevant_tools=["analyze_resistance_pattern"],
            findings=[f"SER 事件仅 {ser_count} 个，不构成主要问题"],
        ))

    # Q3: HYD
    if hyd_count >= 3:
        questions.append(OpenQuestion(
            qid="Q3",
            text="HYD 是否是主因，还是启停边界伴随？",
            priority="medium",
            relevant_tools=["analyze_hydraulic_pattern"],
            needs_manual_check=True,
        ))
    else:
        questions.append(OpenQuestion(
            qid="Q3",
            text="HYD 是否是主因，还是启停边界伴随？",
            priority="low",
            status="answered",
            relevant_tools=["analyze_hydraulic_pattern"],
            findings=[f"HYD 事件仅 {hyd_count} 个，不构成主要问题"],
        ))

    # Q4: 碎片化
    if event_count >= 8:
        questions.append(OpenQuestion(
            qid="Q4",
            text="事件是否存在碎片化或规则放大？",
            priority="medium",
            relevant_tools=["analyze_event_fragmentation"],
        ))
    else:
        questions.append(OpenQuestion(
            qid="Q4",
            text="事件是否存在碎片化或规则放大？",
            priority="low",
            status="answered",
            relevant_tools=["analyze_event_fragmentation"],
            findings=[f"事件仅 {event_count} 个，不需要碎片化分析"],
        ))

    # Q5: 施工日志
    questions.append(OpenQuestion(
        qid="Q5",
        text="哪些结论需要施工日志确认？",
        priority="low",
        relevant_tools=[],
        needs_manual_check=True,
    ))

    state.investigation_questions = questions


def _update_question_status(
    state: InvestigationState,
    action: str,
    result: dict[str, Any],
) -> None:
    """根据工具调用结果更新调查问题状态。"""
    if not state.investigation_questions:
        return

    is_error = result.get("status") == "error"
    q_map = {q.qid: q for q in state.investigation_questions}

    if action == "analyze_stoppage_cases" and "Q1" in q_map:
        q = q_map["Q1"]
        if action not in q.tools_called:
            q.tools_called.append(action)
        if is_error:
            return
        cases = result.get("merged_cases", 0)
        total_h = result.get("total_duration_hours", 0)
        q.findings.append(f"{cases} 个停机案例，共 {total_h}h")
        if q.status == "unanswered":
            q.status = "partially_answered"

    elif action == "drilldown_time_window":
        tid = result.get("target_id", "")
        hint = result.get("interpretation_hint", "")
        finding = f"{tid}: {hint}" if hint else f"{tid}: drilldown 完成"

        if tid.startswith("SC_") and "Q1" in q_map:
            q = q_map["Q1"]
            if action not in q.tools_called:
                q.tools_called.append(action)
            if not is_error:
                q.findings.append(finding)
                if q.status in ("unanswered", "partially_answered"):
                    q.status = "partially_answered"

        elif tid.startswith("SER_") and "Q2" in q_map:
            q = q_map["Q2"]
            if action not in q.tools_called:
                q.tools_called.append(action)
            if not is_error:
                q.findings.append(finding)
                if q.status in ("unanswered", "partially_answered"):
                    q.status = "partially_answered"

    elif action == "analyze_resistance_pattern" and "Q2" in q_map:
        q = q_map["Q2"]
        if action not in q.tools_called:
            q.tools_called.append(action)
        if is_error:
            return
        summary = result.get("summary", "")
        all_overlap = result.get("all_stopped_overlap", False)
        if all_overlap:
            q.findings.append("SER 事件多与停机重叠，暂不能证明推进中阻力异常")
        else:
            adv = result.get("in_advancing_ratio", 0)
            q.findings.append(f"SER 推进中占比 {adv:.0%}")
        if q.status == "unanswered":
            q.status = "partially_answered"

    elif action == "analyze_hydraulic_pattern" and "Q3" in q_map:
        q = q_map["Q3"]
        if action not in q.tools_called:
            q.tools_called.append(action)
        if is_error:
            return
        isolated = result.get("isolated_short_fluctuation", False)
        near_stop = result.get("near_stoppage_boundary", False)
        if isolated:
            q.findings.append("HYD 多为孤立短时波动，不构成系统性异常")
        if near_stop:
            q.findings.append("HYD 靠近停机边界，可能为启停伴随")
        q.status = "answered"
        q.needs_manual_check = q.needs_manual_check and not isolated

    elif action == "analyze_event_fragmentation" and "Q4" in q_map:
        q = q_map["Q4"]
        if action not in q.tools_called:
            q.tools_called.append(action)
        if is_error:
            return
        risk = result.get("fragmentation_risk", False)
        short_ratio = result.get("short_event_ratio", 0)
        if risk:
            q.findings.append(f"存在碎片化风险，短事件占比 {short_ratio:.0%}")
        else:
            q.findings.append(f"碎片化风险低，短事件占比 {short_ratio:.0%}")
        q.status = "answered"


def _finalize_question_status(state: InvestigationState) -> None:
    """在调查结束时最终确认问题状态。"""
    for q in state.investigation_questions:
        # Q1: 停机类 — 需要 analyze + drilldown 才算 answered
        if q.qid == "Q1" and q.priority == "high":
            has_analyze = "analyze_stoppage_cases" in q.tools_called
            has_dd = "drilldown_time_window" in q.tools_called
            if has_analyze and has_dd:
                q.status = "answered"
            elif has_analyze and not has_dd:
                q.status = "partially_answered"
                q.reason_if_unanswered = "已分析停机案例但未做 drilldown 窗口验证"
            elif q.status == "unanswered":
                q.reason_if_unanswered = "未执行停机分析"

        # Q2: SER 类
        if q.qid == "Q2" and q.priority == "high":
            has_analyze = "analyze_resistance_pattern" in q.tools_called
            has_dd = "drilldown_time_window" in q.tools_called
            if has_analyze and has_dd:
                q.status = "answered"
            elif has_analyze:
                q.status = "partially_answered"
                q.reason_if_unanswered = "已分析 SER 模式但未做 drilldown 验证"
            elif q.status == "unanswered":
                q.reason_if_unanswered = "未执行 SER 分析"

        # Q5: 施工日志 — 有任何发现就 partially
        if q.qid == "Q5":
            answered_qs = [
                oq for oq in state.investigation_questions
                if oq.qid != "Q5" and oq.status in ("answered", "partially_answered")
            ]
            if answered_qs:
                q.status = "partially_answered"
                manual_items = []
                for oq in state.investigation_questions:
                    if oq.needs_manual_check and oq.findings:
                        manual_items.append(f"{oq.qid}: {oq.findings[-1]}")
                if manual_items:
                    q.findings = [f"需施工日志确认：{'; '.join(manual_items[:3])}"]
                else:
                    q.findings = ["所有疑似结论均需施工日志确认"]
            else:
                q.status = "unanswered"
                q.reason_if_unanswered = "调查未产生足够发现"

        # 任何 unanswered 且 high 的问题标注原因
        if q.status == "unanswered" and q.priority == "high" and not q.reason_if_unanswered:
            q.reason_if_unanswered = "因轮数限制或工具未执行"


def _select_drilldown_target(state: InvestigationState) -> tuple[str, str]:
    """选择 evidence gate 要求的 drilldown 目标。返回 (target_id, reason)。"""
    fp = state.current_file
    drilldown_done = set()
    for a in state.actions_taken:
        if a.action == "drilldown_time_window":
            tid = (a.arguments or {}).get("target_id", "")
            if tid:
                drilldown_done.add(tid)

    # 优先级 1: 事件级异常线索，待验证
    for cid, cls in state.case_classifications.items():
        if cls.case_type == "event_level_abnormal_unverified" and cid not in drilldown_done:
            return cid, f"存在未验证事件级异常线索 {cid}，必须先做 drilldown"

    # 优先级 2: 最长未 drilldown 的停机案例
    all_cases = []
    for cases in state.stoppage_cases.values():
        all_cases.extend(cases)
    all_cases.sort(key=lambda c: -c.duration_seconds)
    for c in all_cases:
        if c.case_id not in drilldown_done:
            return c.case_id, f"停机案例 {c.case_id} ({c.duration_seconds/60:.0f}min) 尚未 drilldown"

    return "", ""


def _check_evidence_gate(
    action: str,
    state: InvestigationState,
    max_iterations: int,
) -> tuple[bool, str, dict, str]:
    """检查是否满足最低证据门槛。

    返回 (should_override, new_action, new_arguments, reason)。
    """
    if action != "generate_investigation_report":
        return False, "", {}, ""

    remaining = max_iterations - state.iteration_count
    total_cases = sum(len(v) for v in state.stoppage_cases.values())
    drilldown_count = sum(
        1 for o in state.observations
        if o.action == "drilldown_time_window"
        and (o.data.get("target_id", "").startswith("SC_"))
    )

    # 如果 max_iterations 即将耗尽（只剩 1 轮），允许生成报告
    if remaining <= 1:
        return False, "", {}, ""

    # 规则 1: 存在停机案例但 drilldown_count == 0
    if total_cases > 0 and drilldown_count == 0:
        target_id, reason = _select_drilldown_target(state)
        if target_id:
            return True, "drilldown_time_window", {
                "file_path": state.current_file,
                "target_id": target_id,
            }, reason

    # 规则 2: 存在事件级异常线索但未 drilldown
    unverified = [
        cid for cid, cls in state.case_classifications.items()
        if cls.case_type == "event_level_abnormal_unverified"
    ]
    drilldown_done = set()
    for a in state.actions_taken:
        if a.action == "drilldown_time_window":
            tid = (a.arguments or {}).get("target_id", "")
            if tid:
                drilldown_done.add(tid)
    unverified_not_drilled = [cid for cid in unverified if cid not in drilldown_done]
    if unverified_not_drilled:
        target_id = unverified_not_drilled[0]
        return True, "drilldown_time_window", {
            "file_path": state.current_file,
            "target_id": target_id,
        }, f"存在未验证事件级异常线索 {target_id}，必须先做 drilldown"

    # 规则 3: 高优先级问题未被尝试调查
    actions_done = {a.action for a in state.actions_taken}
    for q in state.investigation_questions:
        if q.priority == "high" and q.status == "unanswered":
            for tool in q.relevant_tools:
                if tool not in actions_done and tool != "drilldown_time_window":
                    return True, tool, {
                        "file_path": state.current_file,
                    }, f"高优先级问题 {q.qid}（{q.text}）尚未被调查"

    return False, "", {}, ""


def run_investigation(
    input_files: list[str],
    mode: str = "single_file",
    output_dir: str | Path = "investigation_out",
    use_llm: bool = False,
    max_iterations: int = 15,
    max_tool_calls: int = 20,
    max_runtime_seconds: int = 300,
    planner_audit: bool = False,
    focus: str = "auto",
    planner_mode: str = "rule",
) -> InvestigationResult:
    """运行停机案例追查 ReAct 循环。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 兼容旧 use_llm 参数
    if use_llm and planner_mode == "rule":
        planner_mode = "llm"

    state = InvestigationState(
        task_id=str(uuid.uuid4())[:8],
        mode=mode,
        input_files=input_files,
        current_file=input_files[0] if input_files else "",
        focus=focus,
        planner_type=planner_mode,
    )

    start_time = time.time()
    tool_call_count = 0
    report_text = ""

    print(f"[investigate] task={state.task_id} mode={mode} focus={focus} files={len(input_files)}")
    print(f"[investigate] planner={planner_mode}")

    for iteration in range(1, max_iterations + 1):
        state.iteration_count = iteration

        elapsed = time.time() - start_time
        if elapsed > max_runtime_seconds:
            state.stop_reason = f"max_runtime ({max_runtime_seconds}s)"
            print(f"[investigate] STOP: {state.stop_reason}")
            break

        if tool_call_count >= max_tool_calls:
            state.stop_reason = f"max_tool_calls ({max_tool_calls})"
            print(f"[investigate] STOP: {state.stop_reason}")
            break

        decision = plan_next_action(state, use_llm=use_llm, audit=planner_audit,
                                    planner_mode=planner_mode)
        action = decision.get("action", "")
        arguments = decision.get("arguments", {})
        rationale = decision.get("rationale", "")
        audit_data = decision.pop("_audit", None)
        round_planner_type = decision.pop("_planner_type", planner_mode)
        round_llm_status = decision.pop("_llm_status", "skipped")
        round_fallback = decision.pop("_fallback_used", False)

        print(f"[investigate] round {iteration} planner={round_planner_type} reason: {rationale}")
        print(f"[investigate] action: {action}({json.dumps({k:v for k,v in arguments.items() if k != 'state'}, ensure_ascii=False)})")

        if planner_audit and audit_data:
            from tbm_diag.investigation.state import PlannerAuditRecord
            last_obs_summary = state.observations[-1].result_summary if state.observations else ""
            overview = state.file_overviews.get(state.current_file)
            snapshot = {}
            if overview:
                snapshot = {
                    "events": overview.event_count,
                    "stoppage_segment": overview.semantic_event_distribution.get("stoppage_segment", 0),
                    "SER": (overview.semantic_event_distribution.get("suspected_excavation_resistance", 0)
                            + overview.semantic_event_distribution.get("excavation_resistance_under_load", 0)),
                    "HYD": overview.semantic_event_distribution.get("hydraulic_instability", 0),
                    "stopped_pct": overview.state_distribution.get("stopped", 0),
                }
            audit_rec = PlannerAuditRecord(
                round_num=iteration,
                current_file=state.current_file,
                current_observation_summary=last_obs_summary,
                open_questions=state.open_questions[:3],
                candidate_actions=[a for a, _ in audit_data.get("candidates", [])],
                candidate_reasons=[r for _, r in audit_data.get("candidates", [])],
                rejected_actions=[a for a, _ in audit_data.get("rejected", [])],
                rejected_reasons=[r for _, r in audit_data.get("rejected", [])],
                selected_action=action,
                selected_reason=rationale,
                is_rule_based=not audit_data.get("is_llm", False),
                state_snapshot=snapshot,
                triggered_by_field=audit_data.get("triggered_by", ""),
                observation_used=audit_data.get("observation_used", ""),
            )
            state.audit_log.append(audit_rec)
            print(f"[audit] candidates: {audit_rec.candidate_actions}")
            print(f"[audit] rejected: {[f'{a}({r})' for a, r in zip(audit_rec.rejected_actions, audit_rec.rejected_reasons)]}")
            if audit_rec.triggered_by_field:
                print(f"[audit] ★ triggered_by: {audit_rec.triggered_by_field}  obs: {audit_rec.observation_used}")

        # ── Evidence Gate: 检查最低证据门槛 ──
        eg_override = False
        eg_original_action = ""
        eg_reason = ""
        should_override, new_action, new_args, override_reason = _check_evidence_gate(
            action, state, max_iterations,
        )
        if should_override:
            eg_override = True
            eg_original_action = action
            eg_reason = override_reason
            action = new_action
            arguments = new_args
            rationale = f"[Evidence Gate] {override_reason}"
            state.evidence_gate_overrides.append(EvidenceGateOverride(
                round_num=iteration,
                llm_selected_action=eg_original_action,
                final_selected_action=new_action,
                override_reason=override_reason,
                target_id=new_args.get("target_id", ""),
            ))
            print(f"[evidence_gate] OVERRIDE: {eg_original_action} → {action} (reason: {override_reason})")

        state.actions_taken.append(ActionRecord(
            round_num=iteration,
            action=action,
            arguments={k: v for k, v in arguments.items() if k != "state"},
            rationale=rationale,
            planner_type=round_planner_type,
            llm_called=round_llm_status != "skipped",
            llm_status=round_llm_status,
            fallback_used=round_fallback,
            evidence_gate_override=eg_override,
            evidence_gate_original_action=eg_original_action,
            evidence_gate_reason=eg_reason,
        ))

        result = _execute_action(action, arguments, state)
        tool_call_count += 1

        obs_summary = _make_observation_summary(action, result)
        print(f"[investigate] observe: {obs_summary}")

        state.observations.append(Observation(
            round_num=iteration,
            action=action,
            result_summary=obs_summary,
            data={k: v for k, v in result.items() if not k.startswith("_")},
        ))

        # 回填 observation_summary 到 action record
        state.actions_taken[-1].observation_summary = obs_summary

        _update_state(state, action, arguments, result)
        _update_question_status(state, action, result)

        if action == "inspect_file_overview" and state.mode == "single_file":
            _generate_investigation_questions(state)

        if action == "generate_investigation_report":
            report_text = result.get("report_text", "")
            state.stop_reason = "report_generated"
            print(f"[investigate] STOP: report generated")
            break

        if state.confidence >= 0.75 and len(state.case_classifications) > 0:
            all_top_classified = True
            for cases in state.stoppage_cases.values():
                for c in cases[:5]:
                    if c.case_id not in state.case_classifications:
                        all_top_classified = False
                        break
            if all_top_classified:
                pass

    if not state.stop_reason:
        state.stop_reason = f"max_iterations ({max_iterations})"

    # ── 问题状态最终确认 ──
    _finalize_question_status(state)

    # ── 最终结论（必须在报告生成之前调用）──
    from tbm_diag.investigation.tools import finalize_investigation
    finalize_investigation(state, planner_mode=planner_mode)
    if state.final_conclusion:
        fc = state.final_conclusion
        print(f"[investigate] conclusion: {fc.convergence_status} ({fc.finalizer_type})")

    # 始终重新生成报告以包含最终结论
    from tbm_diag.investigation.report import build_report
    report_result = build_report(state)
    report_text = report_result.get("report_text", "") or report_text

    report_path = output_dir / "investigation_report.md"
    report_path.write_text(report_text, encoding="utf-8")

    state_path = output_dir / "investigation_state.json"
    state_json = _serialize_state(state)
    state_path.write_text(
        json.dumps(state_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    memory_path = save_case_memory(state, output_dir)

    elapsed = time.time() - start_time
    print(f"[investigate] done in {elapsed:.1f}s, {tool_call_count} tool calls, {state.iteration_count} rounds")
    print(f"[investigate] output: {output_dir}")

    return InvestigationResult(
        state=state,
        report_text=report_text,
        report_path=str(report_path),
        state_path=str(state_path),
        memory_path=str(memory_path),
    )


def _serialize_state(state: InvestigationState) -> dict[str, Any]:
    """将 state 序列化为 JSON-safe dict。"""
    from dataclasses import asdict
    d = asdict(state)
    for key in ["file_overviews", "event_summaries", "stoppage_cases",
                "transition_analyses", "case_classifications"]:
        if key in d and isinstance(d[key], dict):
            for k, v in d[key].items():
                if isinstance(v, list):
                    d[key][k] = [
                        item if isinstance(item, dict) else asdict(item) if hasattr(item, '__dataclass_fields__') else item
                        for item in v
                    ]
    return d


