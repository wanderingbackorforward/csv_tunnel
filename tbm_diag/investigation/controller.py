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

    try:
        return fn(**arguments)
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
) -> InvestigationResult:
    """运行停机案例追查 ReAct 循环。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    state = InvestigationState(
        task_id=str(uuid.uuid4())[:8],
        mode=mode,
        input_files=input_files,
        current_file=input_files[0] if input_files else "",
        focus=focus,
    )

    start_time = time.time()
    tool_call_count = 0
    report_text = ""

    print(f"[investigate] task={state.task_id} mode={mode} focus={focus} files={len(input_files)}")
    print(f"[investigate] planner={'LLM' if use_llm else 'rule-based'}")

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

        decision = plan_next_action(state, use_llm=use_llm, audit=planner_audit)
        action = decision.get("action", "")
        arguments = decision.get("arguments", {})
        rationale = decision.get("rationale", "")
        audit_data = decision.pop("_audit", None)

        print(f"[investigate] round {iteration} reason: {rationale}")
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

        state.actions_taken.append(ActionRecord(
            round_num=iteration,
            action=action,
            arguments={k: v for k, v in arguments.items() if k != "state"},
            rationale=rationale,
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

        if action == "inspect_file_overview" and state.mode == "single_file":
            pass

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

    if not report_text:
        from tbm_diag.investigation.report import build_report
        report_result = build_report(state)
        report_text = report_result.get("report_text", "")

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


