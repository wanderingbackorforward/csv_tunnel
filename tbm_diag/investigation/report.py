"""report.py — 生成 investigation_report.md

报告结构（工程人可读）：
1. 一句话结论 — 业务语言
2. 这一天发生了什么 — 停机概览
3. 最值得人工核查的停机段 — Top 案例前置
4. 我们已经查清了什么 — 停机/SER/HYD
5. 还不能下结论的地方 — 明确缺口
6. 下一步怎么查 — 行动清单
7. 技术附录 — ReAct 轨迹、LLM 明细等

所有用户可见文本必须从 ReportViewModel 读取，禁止直接读取 raw source：
- state.final_conclusion.*
- state.executive_summary.recommendation_for_user
- state.actions_taken.rationale
- state.llm_calls.thought_summary
- state.investigation_questions.findings
- state.case_classifications.reasons
"""

from __future__ import annotations

from typing import Any

from tbm_diag.investigation.state import InvestigationState, compute_drilldown_coverage
from tbm_diag.investigation.report_view_model import (
    ReportViewModel, build_report_view_model,
)


# ── Section 1: 一句话结论 ──

def _build_section_1(lines: list[str], state: InvestigationState, vm: ReportViewModel, d: dict) -> None:
    lines.append("## 1. 一句话结论\n")
    if vm.conclusion_text:
        lines.append(vm.conclusion_text)
    else:
        total_sc = d["cov"]["total_count"]
        if total_sc > 0:
            total_h = sum(c.duration_seconds for c, _ in d["all_cases"]) / 3600
            drilled = d["cov"]["covered_count"]
            lines.append(
                f"这一天共识别出 {total_sc} 段停机（合计 {total_h:.1f}h），"
                f"已逐案检查 {drilled} 段。"
            )
        else:
            lines.append("这一天未检测到停机事件。")
    lines.append("")

    if vm.key_findings:
        lines.append("**关键发现：**")
        for f in vm.key_findings:
            lines.append(f"- {f}")
        lines.append("")

    if state.report_quality_status == "failed":
        lines.append("> **调查质量提示：** 本次自动调查遇到问题，部分结论可能不完整。建议结合施工日志综合判断。")
        lines.append("")
    if state.planner_runtime_status == "llm_unavailable":
        lines.append("> **提示：** 本次未能使用 AI 分析，所有判断由固定规则生成，结论覆盖面有限。")
        lines.append("")


# ── Section 2: 这一天发生了什么 ──
# Safe: reads structured data from state.file_overviews and coverage only.

def _build_section_2(lines: list[str], state: InvestigationState, d: dict) -> None:
    lines.append("## 2. 这一天发生了什么\n")
    file_name = state.current_file or ""
    overview = state.file_overviews.get(file_name) if file_name else None
    if overview:
        lines.append(f"- 时间范围：{overview.time_start} ~ {overview.time_end}")
    total_sc = d["cov"]["total_count"]
    if total_sc > 0:
        total_h = sum(c.duration_seconds for c, _ in d["all_cases"]) / 3600
        drilled = d["cov"]["covered_count"]
        lines.append(f"- 共识别出 **{total_sc} 段停机**，合计 **{total_h:.1f}h**")
        lines.append(f"- 已逐案检查 {drilled}/{total_sc} 段")
        if d["all_cases"]:
            top = d["all_cases"][0]
            lines.append(f"- 最长一段停了 {top[0].duration_seconds/60:.0f} 分钟（{top[0].start_time} ~ {top[0].end_time}）")
    else:
        lines.append("- 未检测到停机。")
    if overview and overview.event_count > 0:
        sem = overview.semantic_event_distribution or {}
        parts = [f"当天共识别异常事件 {overview.event_count} 个"]
        detail_parts = []
        if sem.get("stoppage_segment", 0) > 0:
            detail_parts.append(f"停机相关 {sem['stoppage_segment']} 段")
        if sem.get("suspected_excavation_resistance", 0) > 0:
            detail_parts.append(f"SER {sem['suspected_excavation_resistance']} 个")
        if sem.get("hydraulic_instability", 0) > 0:
            detail_parts.append(f"HYD {sem['hydraulic_instability']} 个")
        if detail_parts:
            parts.append("（" + "、".join(detail_parts) + "）")
        lines.append("- " + "".join(parts))
    lines.append("")


# ── Section 3: 最值得人工核查的停机段 ──

def _build_section_3(lines: list[str], vm: ReportViewModel) -> None:
    if not vm.top_cases:
        return
    lines.append("## 3. 最值得人工核查的停机段\n")
    lines.append("以下停机段按时长从长到短排列，建议优先核查排在前面的案例。\n")
    lines.append("| 优先级 | 案例 | 时间段 | 时长 | CSV 观察结论 | 建议核查原因 |")
    lines.append("|--------|------|--------|------|-------------|-------------|")
    for i, tc in enumerate(vm.top_cases, 1):
        lines.append(
            f"| {i} | {tc.case_id} | {tc.start_time} ~ {tc.end_time} "
            f"| {tc.duration_min:.0f}min | {tc.csv_observation} | {tc.nature_status} |"
        )
    lines.append("")


# ── Section 4: 我们已经查清了什么 ──

def _build_section_4(lines: list[str], state: InvestigationState, d: dict, vm: ReportViewModel) -> None:
    ledger = state.evidence_ledger
    cov = d["cov"]
    lines.append("## 4. 我们已经查清了什么\n")

    # 4.1 停机
    lines.append("### 4.1 停机\n")
    if d["total_merged"] > 0:
        lines.append(f"- 停机案例总数：{d['total_merged']}")
        drilled_count = ledger.drilled_stoppage_cases if ledger else cov["covered_count"]
        lines.append(f"- 已逐案检查：{drilled_count}")
        if ledger and ledger.drilled_stoppage_cases > 0:
            lines.append(f"- 检查结果：**{ledger.drilled_cases_no_pre_ser_hyd} 段**停机前后未见明显异常")
            if ledger.drilled_cases_with_pre_ser_or_hyd > 0:
                lines.append(f"- {ledger.drilled_cases_with_pre_ser_or_hyd} 段停机前存在异常前兆")
            if ledger.drilled_cases_inconclusive > 0:
                lines.append(f"- {ledger.drilled_cases_inconclusive} 段需人工进一步确认")
            if not ledger.external_log_available:
                lines.append("- 未接入施工日志，停机性质（计划/异常）暂无法判定")
        undrilled = ledger.undrilled_stoppage_cases if ledger else len(cov["uncovered_case_ids"])
        if undrilled > 0:
            undrilled_ids = ledger.undrilled_case_ids if ledger else cov["uncovered_case_ids"]
            lines.append(f"- 未逐案检查：{undrilled} 段（{', '.join(undrilled_ids)}）")
    else:
        lines.append("未检测到停机案例。")
    lines.append("")

    # 4.2 SER
    lines.append("### 4.2 掘进阻力异常（SER）\n")
    lines.append("> SER = 疑似掘进阻力异常，即推进过程中遇到的地层阻力突然升高。\n")
    if vm.ser_text_lines:
        for l in vm.ser_text_lines:
            lines.append(l)
    else:
        lines.append("未执行掘进阻力分析。")
    lines.append("")

    # 4.3 HYD
    lines.append("### 4.3 液压异常（HYD）\n")
    lines.append(vm.hyd_text)
    lines.append("")

    # 4.4 碎片化
    lines.append("### 4.4 碎片化\n")
    if vm.frag_text_lines:
        for l in vm.frag_text_lines:
            lines.append(l)
    else:
        lines.append("未执行碎片化分析。")
    lines.append("")


# ── Section 5: 还不能下结论的地方 ──

def _build_section_5(lines: list[str], vm: ReportViewModel) -> None:
    lines.append("## 5. 还不能下结论的地方\n")
    if vm.unresolved_items:
        for item in vm.unresolved_items:
            lines.append(f"- {item}")
    else:
        lines.append("当前调查未发现明显缺口。")
    lines.append("")
    lines.append("> 以上不确定项是因为当前 CSV 数据不足以给出确定结论，需要结合施工日志或其他外部证据进一步判断。")
    lines.append("")


# ── Section 6: 下一步怎么查 ──

def _build_section_6(lines: list[str], vm: ReportViewModel) -> None:
    lines.append("## 6. 下一步怎么查\n")
    if vm.next_steps:
        for i, s in enumerate(vm.next_steps, 1):
            lines.append(f"{i}. {s}")
    else:
        lines.append("当前调查已覆盖所有停机段，如需进一步确认请结合施工日志综合判断。")
    lines.append("")


# ── Drilldown detail rendering (reads from DrilldownView, no raw data) ──

def _render_drilldown_view_detail(lines: list[str], dv) -> None:
    """Render a DrilldownView's structured detail — all text pre-sanitized."""
    from tbm_diag.investigation.report_view_model import DrilldownView
    tei = dv.target_event_info
    if tei.get("source") == "event":
        lines.append(f"- 目标事件类型：{tei.get('semantic_event_type', '')}")
        lines.append(f"- 主导工况：{tei.get('dominant_state', '')}")
        lines.append(f"- 持续时长：{tei.get('duration_seconds', 0)}s")
    sem_ol = dv.semantic_overlap
    during_ol = sem_ol.get("during", {})
    if during_ol.get("total", 0) > 0:
        lines.append(f"- 事件期间重叠事件数：{during_ol['total']}")
        if during_ol.get("ser", 0) > 0:
            lines.append(f"- 重叠 SER：{during_ol['ser']}")
        if during_ol.get("hyd", 0) > 0:
            lines.append(f"- 重叠 HYD：{during_ol['hyd']}")
        if during_ol.get("stoppage", 0) > 0:
            lines.append(f"- 重叠停机：{during_ol['stoppage']}")
    lines.append("")
    lines.append("**行级规则命中：**")
    for label, s in [("前窗口", dv.pre_summary), ("事件期间", dv.during_summary), ("后窗口", dv.post_summary)]:
        if isinstance(s, dict) and not s.get("empty", True):
            lines.append(
                f"- {label}：{s.get('rows', 0)}行，"
                f"SER={s.get('ser_hits', 0)}/{s.get('ser_ratio', 0):.1%}，"
                f"HYD={s.get('hyd_hits', 0)}/{s.get('hyd_ratio', 0):.1%}，"
                f"LEE={s.get('lee_hits', 0)}/{s.get('lee_ratio', 0):.1%}"
            )
    lines.append("")
    lines.append("**工况统计：**")
    for label, s in [("前窗口", dv.pre_summary), ("事件期间", dv.during_summary), ("后窗口", dv.post_summary)]:
        if isinstance(s, dict) and not s.get("empty", True):
            sd = s.get("state_distribution", {})
            sp = [f"{k}={v:.0f}%" for k, v in sorted(sd.items(), key=lambda x: -x[1]) if v > 0]
            lines.append(
                f"- {label}：速度={s.get('avg_advance_speed', 0)}，"
                f"转矩={s.get('avg_cutter_torque', 0)}，{'，'.join(sp)}"
            )
    if dv.safe_divergence_notes:
        lines.append("")
        lines.append("**证据口径一致性提示：**")
        for note in dv.safe_divergence_notes:
            lines.append(f"- {note}")
    if dv.safe_hint:
        lines.append(f"\n- 初步解释: {dv.safe_hint}")
    if dv.safe_transition_findings:
        lines.append(f"- 转变发现: {'，'.join(dv.safe_transition_findings)}")
    lines.append("")


# ── Section 7: 技术附录 ──

def _build_section_7(lines: list[str], state: InvestigationState, d: dict, vm: ReportViewModel) -> None:
    lines.append("## 7. 技术附录\n")
    lines.append("> 以下为技术审计信息，供系统开发者或审计人员参考。\n")

    # 7.1 ReAct trace
    lines.append("## ReAct 调查轨迹\n")
    has_overrides = any(r.evidence_gate != "—" for r in vm.trace_rows)
    if has_overrides:
        lines.append("| 轮次 | Planner | LLM | 决策理由 | 调用工具 | 观察结果 | Evidence Gate |")
        lines.append("|------|---------|-----|----------|----------|----------|--------------|")
    else:
        lines.append("| 轮次 | Planner | LLM | 决策理由 | 调用工具 | 观察结果 |")
        lines.append("|------|---------|-----|----------|----------|----------|")
    for r in vm.trace_rows:
        if has_overrides:
            lines.append(
                f"| {r.round_num} | {r.planner_label} | {r.llm_status} "
                f"| {r.sanitized_reason} | {r.action} | {r.sanitized_observation} | {r.evidence_gate} |"
            )
        else:
            lines.append(
                f"| {r.round_num} | {r.planner_label} | {r.llm_status} "
                f"| {r.sanitized_reason} | {r.action} | {r.sanitized_observation} |"
            )
    lines.append("")

    # 7.2 Planner audit
    lines.append("## Planner 与大模型调用审计\n")
    lines.append(f"- Planner 类型：{vm.planner_type_label}")
    lines.append(f"- LLM 调用次数：{vm.llm_call_count}")
    lines.append(f"- LLM 成功次数：{vm.llm_success_count}")
    lines.append(f"- fallback 次数：{vm.llm_fallback_count}")
    if vm.llm_model:
        lines.append(f"- 模型：{vm.llm_model}")
    lines.append("")
    if vm.planner_description:
        lines.append(vm.planner_description)
    lines.append("")

    # LLM call details
    if vm.llm_call_rows:
        lines.append("### LLM 调用明细\n")
        lines.append("> 以下为 LLM planner 决策摘要，仅用于审计；最终业务结论以 validator 校验后的调查结论为准。\n")
        lines.append("| 轮次 | 状态 | 选择 | 耗时 | 摘要 |")
        lines.append("|------|------|------|------|------|")
        for c in vm.llm_call_rows:
            lines.append(f"| {c.round_num} | {c.status} | {c.selected_action} | {c.latency_s:.1f}s | {c.sanitized_thought} |")
        lines.append("")

    # 7.3 Evidence Gate audit (safe: structured data)
    cov = d["cov"]
    eg_overrides = state.evidence_gate_overrides
    if eg_overrides or cov["total_count"] > 0:
        lines.append("### Evidence Gate 审计\n")
        lines.append(f"- Evidence Gate 触发次数：{len(eg_overrides)}")
        lines.append(f"- 停机案例 drilldown 覆盖率：{cov['covered_count']}/{cov['total_count']}")
        if cov["single_drilldown_case_ids"]:
            lines.append(f"- 单次 drilldown 覆盖：{', '.join(cov['single_drilldown_case_ids'])}")
        if cov["batch_drilldown_case_ids"]:
            lines.append(f"- batch drilldown 覆盖：{', '.join(cov['batch_drilldown_case_ids'])}")
        if cov["uncovered_case_ids"]:
            lines.append(f"- 未覆盖：{', '.join(cov['uncovered_case_ids'])}")
        lines.append("")
        for eg in eg_overrides:
            lines.append(
                f"- 第 {eg.round_num} 轮：LLM 选择 `{eg.llm_selected_action}`，"
                f"但{eg.override_reason}，因此改为 `{eg.final_selected_action}({eg.target_id})`"
            )
        if eg_overrides:
            lines.append("")

    # 7.4 drilldown detail (from DrilldownView — all text sanitized)
    if vm.drilldown_views:
        lines.append("### drilldown 明细\n")
        lines.append("| 目标 | 前窗口观察 | 事件期间观察 | 后窗口观察 | 初步解释 |")
        lines.append("|------|-----------|-------------|-----------|----------|")
        for dv in vm.drilldown_views:
            lines.append(
                f"| {dv.target_id} | {dv.compact_pre} | {dv.compact_during} "
                f"| {dv.compact_post} | {dv.safe_hint} |"
            )
        lines.append("")
        for dv in vm.drilldown_views:
            lines.append(f"#### 钻取详情：{dv.target_id}\n")
            _render_drilldown_view_detail(lines, dv)

    # 7.5 Top cases audit table
    if vm.audit_top_cases:
        lines.append("### Top 停机案例\n")
        lines.append("| 案例ID | 开始时间 | 结束时间 | 时长(min) | 合并事件数 | 分类 | 置信度 |")
        lines.append("|--------|----------|----------|-----------|-----------|------|--------|")
        for acd in vm.audit_top_cases:
            lines.append(
                f"| {acd.case_id} | "
                f"{next((c.start_time for cases in state.stoppage_cases.values() for c in cases if c.case_id == acd.case_id), '')} | "
                f"{next((c.end_time for cases in state.stoppage_cases.values() for c in cases if c.case_id == acd.case_id), '')} "
                f"| {next((c.duration_seconds/60 for cases in state.stoppage_cases.values() for c in cases if c.case_id == acd.case_id), 0):.0f} | "
                f"{next((c.merged_event_count for cases in state.stoppage_cases.values() for c in cases if c.case_id == acd.case_id), 0)} "
                f"| {acd.case_type_label} | {acd.confidence:.0%} |"
            )
        lines.append("")

    # 7.6 Abnormal case details
    abnormal_details = [a for a in vm.audit_top_cases if "异常" in a.case_type_label]
    if abnormal_details:
        lines.append("### 异常停机疑似案例详情\n")
        for acd in abnormal_details:
            lines.append(f"**{acd.case_id}**")
            lines.append(f"- 置信度: {acd.confidence:.0%}")
            lines.append("- 判定依据:")
            for r in acd.safe_reasons:
                lines.append(f"  - {r}")
            if acd.pre_event_count > 0 or acd.post_event_count > 0:
                lines.append(f"- 停机前异常事件: {acd.pre_event_count} 个")
                lines.append(f"- 恢复后异常事件: {acd.post_event_count} 个")
            lines.append("")

    # 7.7 Consistency items
    if vm.consistency_items:
        lines.append("### 证据一致性检查\n")
        corrections = [i for i in vm.consistency_items if i.category == "correction"]
        warnings = [i for i in vm.consistency_items if i.category == "warning"]
        drilled_uv = [i for i in vm.consistency_items if i.category == "drilled_former_unverified"]
        not_drilled_uv = [i for i in vm.consistency_items if i.category == "not_drilled_unverified"]

        if corrections:
            lines.append("**分类修正：**")
            for c in corrections:
                lines.append(f"- {c.safe_text}")
            lines.append("")
        if warnings:
            lines.append("**需人工确认：**")
            for w in warnings:
                lines.append(f"- {w.safe_text}")
            lines.append("")
        if drilled_uv:
            lines.append("**已验证案例：**")
            for i in drilled_uv:
                lines.append(f"- {i.safe_text}")
            lines.append("")
        if not_drilled_uv:
            lines.append("**证据等级提示：**")
            for i in not_drilled_uv:
                lines.append(f"- {i.safe_text}")
            lines.append("")

    # 7.8 Investigation questions
    if vm.question_views:
        lines.append("### 调查问题完成情况\n")
        lines.append("| 问题 | 状态 | 已调用工具 | 关键发现 | 人工核查 |")
        lines.append("|------|------|-----------|----------|---------|")
        for q in vm.question_views:
            lines.append(f"| {q.qid}: {q.text[:20]} | {q.status_label} | {q.tools_called} | {q.safe_findings} | {'是' if q.needs_manual_check else '否'} |")
        lines.append("")

    # 7.9 Cross-file patterns
    if vm.cross_file_patterns_safe:
        lines.append("### 跨文件模式\n")
        for p in vm.cross_file_patterns_safe:
            lines.append(f"- {p}")
        lines.append("")


# ── Data collection (minimal, for sections that still read from state) ──

def _collect_report_data(state: InvestigationState) -> dict[str, Any]:
    """Collect structured data still needed for Section 2, 4.1, drilldown detail, EG audit."""
    cov = compute_drilldown_coverage(state)
    all_cases = []
    for fp, cases in state.stoppage_cases.items():
        for c in cases:
            all_cases.append((c, state.case_classifications.get(c.case_id)))
    all_cases.sort(key=lambda x: -x[0].duration_seconds)
    total_original = sum(c.merged_event_count for c, _ in all_cases)
    total_merged = len(all_cases)
    return {
        "cov": cov, "all_cases": all_cases,
        "total_original": total_original, "total_merged": total_merged,
    }


# ── Main entry ──

def build_report(state: InvestigationState) -> dict[str, Any]:
    """根据 InvestigationState 生成工程人可读的 Markdown 报告。"""
    d = _collect_report_data(state)
    vm = build_report_view_model(state)
    lines: list[str] = ["# TBM 停机调查报告\n"]

    # No-event early exit
    has_any = (d["total_original"] > 0
               or any(o.action == "analyze_resistance_pattern" for o in state.observations)
               or any(o.action == "analyze_hydraulic_pattern" for o in state.observations)
               or any(o.action == "analyze_event_fragmentation" for o in state.observations))
    if not has_any:
        has_events = any(s.event_count > 0 for s in state.event_summaries.values())
        if has_events:
            lines.append("该文件存在异常事件，但未检测到需要深入追查的模式。\n")
        else:
            lines.append("该文件未检测到异常事件，数据整体正常，无需追查。\n")
        lines.append(f"- 调查轮次: {state.iteration_count}\n")
        return {"status": "ok", "report_text": "\n".join(lines),
                "total_original_events": 0, "total_merged_cases": 0,
                "abnormal_count": 0, "planned_count": 0, "uncertain_count": 0}

    _build_section_1(lines, state, vm, d)
    _build_section_2(lines, state, d)
    _build_section_3(lines, vm)
    _build_section_4(lines, state, d, vm)
    _build_section_5(lines, vm)
    _build_section_6(lines, vm)
    _build_section_7(lines, state, d, vm)

    abnormal = sum(1 for a in vm.audit_top_cases if "异常" in a.case_type_label)
    planned = sum(1 for a in vm.audit_top_cases if "施工日志确认" in a.case_type_label)
    uncertain = sum(1 for a in vm.audit_top_cases if "待" in a.case_type_label and "异常" not in a.case_type_label)

    return {"status": "ok", "report_text": "\n".join(lines),
            "total_original_events": d["total_original"],
            "total_merged_cases": d["total_merged"],
            "abnormal_count": abnormal, "planned_count": planned,
            "uncertain_count": uncertain}
