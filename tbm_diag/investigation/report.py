"""report.py — 生成 investigation_report.md

报告结构（产品化）：
1. 调查结论总览 — 非技术人员可读
2. 本次查清了什么 — 按业务维度
3. 本次没有查清什么 — 明确缺口
4. 调查计划执行情况 — P1~P4 中文表格
5. 技术审计附录 — ReAct 轨迹、LLM 明细、drilldown 详情等
"""

from __future__ import annotations

from typing import Any

from tbm_diag.investigation.state import InvestigationState, compute_drilldown_coverage


_CASE_TYPE_LABELS = {
    "abnormal_like_stoppage": "异常停机（疑似，已验证）",
    "event_level_abnormal_unverified": "事件级异常线索，待验证",
    "planned_like_stoppage": "计划停机（疑似）",
    "uncertain_stoppage": "待确认停机",
    "short_operational_pause": "短暂运行暂停",
}

_PLAN_ID_ZH = {
    "P1": "P1 停机验证",
    "P2": "P2 掘进阻力验证",
    "P3": "P3 液压验证",
    "P4": "P4 碎片化验证",
}

_PLAN_STATUS_ZH = {
    "pending": "待执行",
    "in_progress": "进行中",
    "completed": "已完成",
    "partially_completed": "部分完成",
    "skipped_due_to_budget": "因轮数不足跳过",
}


def _build_react_trace_table(state: InvestigationState) -> list[str]:
    """构建 ReAct 调查轨迹表。"""
    has_overrides = any(a.evidence_gate_override for a in state.actions_taken)

    lines = ["## ReAct 调查轨迹", ""]
    if has_overrides:
        lines.append("| 轮次 | Planner | LLM | 决策理由 | 调用工具 | 观察结果 | Evidence Gate |")
        lines.append("|------|---------|-----|----------|----------|----------|--------------|")
    else:
        lines.append("| 轮次 | Planner | LLM | 决策理由 | 调用工具 | 观察结果 | 触发字段 | fallback |")
        lines.append("|------|---------|-----|----------|----------|----------|----------|----------|")

    audit_map = {a.round_num: a for a in state.audit_log} if state.audit_log else {}

    _PT = {"rule": "规则", "llm": "LLM", "hybrid_rule": "混合/规则", "hybrid_llm": "混合/LLM"}

    for action_rec in state.actions_taken:
        obs = None
        for o in state.observations:
            if o.round_num == action_rec.round_num:
                obs = o
                break
        obs_text = (obs.result_summary[:60] if obs else "无").replace("|", "/")
        rationale = (action_rec.rationale or "").replace("|", "/")[:50]
        ar = audit_map.get(action_rec.round_num)
        trigger = (ar.triggered_by_field if ar and ar.triggered_by_field else "—").replace("|", "/")
        pt = _PT.get(action_rec.planner_type, action_rec.planner_type)
        llm_col = action_rec.llm_status if action_rec.llm_called else "—"
        fb = "是" if action_rec.fallback_used else "—"
        if has_overrides:
            if action_rec.evidence_gate_override:
                eg_col = f"override: {action_rec.evidence_gate_original_action}→{action_rec.action}"
            else:
                eg_col = "—"
            lines.append(
                f"| {action_rec.round_num} | {pt} | {llm_col} "
                f"| {rationale} | {action_rec.action} | {obs_text} | {eg_col} |"
            )
        else:
            lines.append(
                f"| {action_rec.round_num} | {pt} | {llm_col} "
                f"| {rationale} | {action_rec.action} | {obs_text} | {trigger} | {fb} |"
            )
    lines.append("")
    return lines


def _build_planner_audit_section(state: InvestigationState) -> list[str]:
    """构建 Planner 与大模型调用审计 section。"""
    lines = ["## Planner 与大模型调用审计", ""]

    _PT_LABELS = {
        "rule": "规则 planner（未调用 LLM API）",
        "llm": "LLM planner（每轮调用 LLM API）",
        "hybrid": "混合 planner（关键分支调用 LLM）",
    }
    lines.append(f"- Planner 类型：{_PT_LABELS.get(state.planner_type, state.planner_type)}")

    llm_attempted = sum(1 for c in state.llm_calls if c.status != "skipped")
    lines.append(f"- LLM 调用次数：{llm_attempted}")
    lines.append(f"- LLM 成功次数：{state.llm_success_count}")
    lines.append(f"- fallback 次数：{state.llm_fallback_count}")
    if state.llm_model:
        lines.append(f"- 模型：{state.llm_model}")

    lines.append("")
    if state.planner_type == "rule":
        lines.append("本次使用规则 planner，未调用 LLM API。")
        lines.append("属于规则驱动的 ReAct-style 调查流程，每轮工具选择由确定性规则决定。")
        lines.append("如需真正 LLM 驱动调查，请使用 `--planner llm`。")
    elif llm_attempted > 0 and state.llm_success_count == llm_attempted:
        lines.append(f"本次使用 {state.planner_type} planner，"
                     f"共 {llm_attempted} 次 LLM planner 调用，全部成功。")
    elif llm_attempted > 0:
        lines.append(f"本次使用 {state.planner_type} planner，"
                     f"共 {llm_attempted} 次 LLM 调用，"
                     f"{state.llm_success_count} 次成功，"
                     f"{state.llm_fallback_count} 次 fallback 到规则。")
    elif state.planner_type in ("llm", "hybrid"):
        no_key = any(c.status == "no_key" for c in state.llm_calls)
        if no_key:
            lines.append("未检测到 API Key，所有轮次 fallback 到规则 planner。")
        else:
            lines.append("LLM 调用全部跳过或失败，已 fallback 到规则 planner。")
    lines.append("")

    # LLM 调用明细
    actual_calls = [c for c in state.llm_calls if c.status != "skipped"]
    if actual_calls:
        lines.append("### LLM 调用明细")
        lines.append("")
        lines.append("> 以下为 LLM planner 原始决策摘要，仅用于审计；最终业务结论以 validator 校验后的最终调查结论为准。")
        lines.append("")
        lines.append("| 轮次 | 状态 | 选择 | 耗时 | 摘要 |")
        lines.append("|------|------|------|------|------|")
        for c in actual_calls:
            thought = (c.thought_summary or c.error_message or "").replace("|", "/")[:40]
            lines.append(
                f"| {c.round_num} | {c.status} | {c.selected_action or '—'} "
                f"| {c.latency_seconds:.1f}s | {thought} |"
            )
        lines.append("")

    return lines


def _run_consistency_check(state: InvestigationState) -> tuple[list[str], list[str]]:
    """检查 drilldown 证据与分类结论的一致性，返回 (corrections, warnings)。"""
    corrections: list[str] = []
    warnings: list[str] = []

    drilldown_map: dict[str, dict] = {}
    for obs in state.observations:
        if obs.action == "drilldown_time_window":
            tid = obs.data.get("target_id", "")
            if tid:
                drilldown_map[tid] = obs.data

    for case_id, cls in list(state.case_classifications.items()):
        dd = drilldown_map.get(case_id)
        if dd is None:
            continue

        pre = dd.get("pre_summary", {})
        post = dd.get("post_summary", {})
        hint = dd.get("interpretation_hint", "")

        pre_ser_ratio = pre.get("ser_ratio", 0) if isinstance(pre, dict) else 0
        pre_hyd_count = pre.get("hyd_hits", 0) if isinstance(pre, dict) else 0
        post_empty = post.get("empty", True) if isinstance(post, dict) else True
        post_ser_ratio = post.get("ser_ratio", 0) if isinstance(post, dict) else 0
        post_hyd_count = post.get("hyd_hits", 0) if isinstance(post, dict) else 0

        drilldown_clean_pre = pre_ser_ratio <= 0.05 and pre_hyd_count == 0
        drilldown_clean_post = post_empty or (post_ser_ratio <= 0.05 and post_hyd_count == 0)

        filtered_reasons = []
        for r in cls.reasons:
            if "停机前存在" in r and "SER" in r and drilldown_clean_pre:
                corrections.append(
                    f"{case_id}: 分类依据「{r}」已按 drilldown 修正——"
                    f"停机前 SER 未被窗口证据支持（pre SER ratio={pre_ser_ratio:.3f}）"
                )
                continue
            if "停机前存在" in r and "HYD" in r and drilldown_clean_pre:
                corrections.append(
                    f"{case_id}: 分类依据「{r}」已按 drilldown 修正——"
                    f"停机前 HYD 未被窗口证据支持（pre HYD hits={pre_hyd_count}）"
                )
                continue
            if "恢复后仍有异常" in r and drilldown_clean_post:
                corrections.append(
                    f"{case_id}: 分类依据「{r}」已按 drilldown 修正——"
                    f"恢复后窗口未检测到异常"
                )
                continue
            filtered_reasons.append(r)

        if cls.case_type in ("abnormal_like_stoppage", "event_level_abnormal_unverified") and drilldown_clean_pre and drilldown_clean_post:
            if "停机前未见明显异常" in hint:
                old_type = cls.case_type
                cls.case_type = "planned_like_stoppage"
                cls.confidence = min(cls.confidence, 0.55)
                corrections.append(
                    f"{case_id}: 分类从 {old_type} 降级为 {cls.case_type}——"
                    f"drilldown 显示「{hint}」，与异常线索矛盾"
                )
                filtered_reasons = [
                    r for r in filtered_reasons
                    if r != "（疑似，需结合施工日志确认）"
                    and "未经 drilldown" not in r
                    and "未经drilldown" not in r
                ]
                filtered_reasons.append("经 drilldown 验证：停机前后窗口未见明显 SER/HYD 行级异常，疑似计划性/管理性停机，需施工日志确认")

        cls.reasons = filtered_reasons
        state.case_classifications[case_id] = cls

    # 检查 SER 目标有效性
    for obs in state.observations:
        if obs.action == "analyze_resistance_pattern":
            if obs.data.get("all_stopped_overlap"):
                warnings.append(
                    "当前 SER 事件多与停机片段重叠，暂不能证明推进中的掘进阻力异常，"
                    "需要重新区分停机期伪异常与推进期 SER"
                )

    for obs in state.observations:
        if obs.action == "drilldown_time_window":
            tid = obs.data.get("target_id", "")
            if tid.startswith("SER_"):
                during = obs.data.get("during_summary", {})
                if isinstance(during, dict):
                    stopped_pct = during.get("state_distribution", {}).get("stopped", 0)
                    avg_speed = during.get("avg_advance_speed", 0)
                    if stopped_pct > 80 and avg_speed < 1:
                        warnings.append(
                            f"{tid}: 事件期间 stopped={stopped_pct:.0f}%、"
                            f"速度={avg_speed}，实为停机窗口，不代表推进中 SER"
                        )

    return corrections, warnings


def _collect_report_data(state: InvestigationState) -> dict[str, Any]:
    """收集报告所需的公共数据，避免各 section 重复计算。"""
    cov = compute_drilldown_coverage(state)
    all_cases = []
    for fp, cases in state.stoppage_cases.items():
        for c in cases:
            cls = state.case_classifications.get(c.case_id)
            all_cases.append((c, cls))
    all_cases.sort(key=lambda x: -x[0].duration_seconds)
    total_original = sum(c.merged_event_count for c, _ in all_cases)
    total_merged = len(all_cases)
    abnormal = [(cid, cl) for cid, cl in state.case_classifications.items() if cl.case_type == "abnormal_like_stoppage"]
    unverified = [(cid, cl) for cid, cl in state.case_classifications.items() if cl.case_type == "event_level_abnormal_unverified"]
    planned = [(cid, cl) for cid, cl in state.case_classifications.items() if cl.case_type == "planned_like_stoppage"]
    uncertain = [(cid, cl) for cid, cl in state.case_classifications.items() if cl.case_type == "uncertain_stoppage"]
    resistance_obs = [o for o in state.observations if o.action == "analyze_resistance_pattern"]
    hydraulic_obs = [o for o in state.observations if o.action == "analyze_hydraulic_pattern"]
    fragmentation_obs = [o for o in state.observations if o.action == "analyze_event_fragmentation"]
    drilldown_obs = [o for o in state.observations if o.action == "drilldown_time_window"]
    return {
        "cov": cov, "all_cases": all_cases,
        "total_original": total_original, "total_merged": total_merged,
        "abnormal": abnormal, "unverified": unverified,
        "planned": planned, "uncertain": uncertain,
        "resistance_obs": resistance_obs, "hydraulic_obs": hydraulic_obs,
        "fragmentation_obs": fragmentation_obs, "drilldown_obs": drilldown_obs,
    }


def _build_section_1_executive(lines: list[str], state: InvestigationState) -> None:
    """第 1 节：调查结论总览 — 业务优先，技术指标后移。"""
    es = state.executive_summary
    fc = state.final_conclusion
    if not es and not fc:
        return
    lines.append("## 1. 结论摘要\n")

    # ── 调查对象（第一屏第一块）──
    from tbm_diag.investigation.investigation_depth import (
        get_depth_label, compute_stoppage_coverage_target,
    )
    cov = compute_drilldown_coverage(state)
    total_sc = cov["total_count"]
    actual_sc = cov["covered_count"]
    depth = state.investigation_depth or "standard"
    cov_target = compute_stoppage_coverage_target(total_sc, depth)

    lines.append("### 调查对象\n")
    file_name = state.current_file or ""
    lines.append(f"- 文件：{file_name}")
    overview = state.file_overviews.get(file_name) if file_name else None
    if overview:
        lines.append(f"- 时间范围：{overview.time_start} ~ {overview.time_end}")
    lines.append(f"- 调查深度：{get_depth_label(depth)}")
    if total_sc > 0:
        total_duration = 0.0
        for cases in state.stoppage_cases.values():
            for c in cases:
                total_duration += c.duration_seconds
        lines.append(f"- 停机案例：{total_sc} 个，总时长 {total_duration/3600:.1f}h")
        lines.append(f"- 逐案钻取（drilldown）：{actual_sc}/{total_sc}")
    lines.append("")

    # ── 一句话结论（第一屏第二块）──
    claims = state.compiled_claims
    one_sentence = ""
    if claims and claims.one_sentence_conclusion:
        one_sentence = claims.one_sentence_conclusion
    elif es and es.one_sentence_conclusion:
        one_sentence = es.one_sentence_conclusion
    elif fc and fc.primary_conclusion_zh:
        one_sentence = fc.primary_conclusion_zh

    if one_sentence:
        lines.append(f"**结论：** {one_sentence}")
        lines.append("")

    # ── 关键发现（第一屏第三块）──
    key_findings = []
    if claims and claims.key_findings:
        key_findings = claims.key_findings
    elif es and es.key_findings:
        key_findings = es.key_findings

    if key_findings:
        lines.append("**关键发现：**")
        for f in key_findings:
            lines.append(f"- {f}")
        lines.append("")

    # ── 仍不确定（第一屏第四块）──
    unresolved = []
    if claims and claims.unresolved_items:
        unresolved = claims.unresolved_items
    elif es and es.unresolved_items:
        unresolved = es.unresolved_items

    if unresolved:
        lines.append("**仍不确定：**")
        for u in unresolved:
            lines.append(f"- {u}")
        lines.append("")

    # ── 下一步人工核查（第一屏第五块）──
    next_checks = []
    if claims and claims.next_manual_checks:
        next_checks = claims.next_manual_checks
    elif es and es.next_manual_checks:
        next_checks = es.next_manual_checks

    if next_checks:
        lines.append("**下一步人工核查：**")
        for c in next_checks:
            lines.append(f"- {c}")
        lines.append("")

    # ── 建议（基于 completeness_status）──
    recommendation = ""
    if es and es.recommendation_for_user:
        recommendation = es.recommendation_for_user
    if recommendation:
        lines.append(f"**建议：** {recommendation}")
        lines.append("")

    # ── 质量门禁失败时的业务提示 ──
    if state.report_quality_status == "failed":
        lines.append("> **质量门禁未通过。** 建议运行 `python -m tbm_diag.cli llm-planner-check` "
                     "检查 LLM planner 可用性，或切换标准调查 `--planner hybrid`。")
        for issue in state.report_quality_issues:
            if issue.severity == "critical":
                lines.append(f"> - {issue.message}")
        lines.append("")

    # ── LLM 不可用/不稳定的业务提示 ──
    if state.planner_runtime_status == "llm_unavailable":
        lines.append("> **警告：本次 LLM planner 0 次成功，所有决策均由规则 fallback 完成。"
                     "本报告不能视为 LLM ReAct 结果。**")
        lines.append("")
    elif state.planner_runtime_status == "llm_unstable":
        lines.append("> **注意：LLM planner 不稳定，部分决策由规则 fallback 接管。**")
        lines.append("")

    # ── 调查充分性 ──
    comp_status = state.investigation_completeness_status or ""
    lines.append("### 调查充分性\n")
    lines.append(f"- 调查深度：{get_depth_label(depth)}")
    lines.append(f"- 停机案例总数：{total_sc}")
    lines.append(f"- 当前深度目标：{cov_target.target_count}/{total_sc}")
    lines.append(f"- 实际逐案钻取覆盖：{actual_sc}/{total_sc}")
    if comp_status == "complete_for_depth":
        lines.append("- 调查充分性：**已达到当前深度目标**")
    elif comp_status == "not_applicable_no_stoppage":
        lines.append("- 调查充分性：无停机案例，不适用")
    elif comp_status == "incomplete_due_to_budget":
        lines.append("- 调查充分性：**因预算不足未完成**")
        lines.append("> 本次报告为部分调查结果，不代表全部停机案例均已完成逐案钻取。")
    elif comp_status == "incomplete_due_to_cap":
        lines.append("- 调查充分性：**已达到上限，但未覆盖全部**")
    else:
        lines.append(f"- 调查充分性：{comp_status or '未知'}")
    lines.append("")

    # ── 技术状态摘要（开发者参考，后移）──
    _RUN_ZH = {"success": "成功", "partial": "部分成功", "failed_degraded": "失败/降级"}
    _Q_ZH = {"passed": "通过", "warning": "有警告", "failed": "未通过"}
    run_label = _RUN_ZH.get(es.run_status, es.run_status) if es else "未知"
    q_label = _Q_ZH.get(es.report_quality_status, es.report_quality_status) if es else "未知"
    lines.append("### 技术状态摘要（开发者参考）\n")
    lines.append(f"- 调查运行状态：**{run_label}**")
    if es:
        lines.append(f"- 实际 planner：{es.actual_planner_label}")
        lines.append(f"- LLM 成功率：{es.llm_success_ratio_text}")
    lines.append(f"- 报告质量门禁：**{q_label}**")
    lines.append("")

def _build_section_2_clarified(lines: list[str], state: InvestigationState, d: dict) -> None:
    """第 2 节：本次查清了什么（按业务维度）。"""
    ledger = state.evidence_ledger
    cov = d["cov"]
    lines.append("## 2. 本次查清了什么\n")
    # ── 停机问题 ──
    lines.append("### 停机问题\n")
    if d["total_merged"] > 0:
        lines.append(f"- 停机案例总数：{d['total_merged']}")
        lines.append(f"- 已逐案钻取：{ledger.drilled_stoppage_cases if ledger else cov['covered_count']}")
        lines.append(f"- 未逐案钻取：{ledger.undrilled_stoppage_cases if ledger else len(cov['uncovered_case_ids'])}")
        lines.append("")
        # 已逐案钻取案例分类（从 ledger）
        if ledger and ledger.drilled_stoppage_cases > 0:
            lines.append("**已逐案钻取案例中：**")
            lines.append(f"- 停机前后未见明显行级异常：{ledger.drilled_cases_no_pre_ser_hyd}")
            if ledger.drilled_cases_with_pre_ser_or_hyd > 0:
                lines.append(f"- 停机前存在异常前兆：{ledger.drilled_cases_with_pre_ser_or_hyd}")
            if ledger.drilled_cases_inconclusive > 0:
                lines.append(f"- 仍需人工确认：{ledger.drilled_cases_inconclusive}")
            lines.append("")
            lines.append("**停机性质：**")
            lines.append(f"- 已由外部日志确认计划停机：{ledger.confirmed_planned_by_external_log}")
            lines.append(f"- 已由外部日志确认异常停机：{ledger.confirmed_abnormal_by_external_log}")
            if not ledger.external_log_available:
                lines.append("- 未接入外部日志，全部停机性质仍需确认")
        # 未 drilldown 案例
        if ledger and ledger.undrilled_stoppage_cases > 0:
            lines.append("")
            lines.append(f"**未逐案钻取案例（{ledger.undrilled_stoppage_cases} 个）：**")
            lines.append(f"- {', '.join(ledger.undrilled_case_ids)}")
    else:
        lines.append("未检测到停机案例。")
    lines.append("")
    # ── 掘进阻力异常 SER ──
    lines.append("### 掘进阻力异常 SER\n")
    if d["resistance_obs"]:
        for obs in d["resistance_obs"]:
            data = obs.data or {}
            lines.append(f"- SER 事件数：{data.get('ser_count', 0)}")
            lines.append(f"- SER 总时长：{data.get('ser_total_duration_h', 0)}h")
            in_adv = data.get("in_advancing_ratio", 0)
            lines.append(f"- 是否主要发生在推进中：{'是' if in_adv > 0.5 else '否'}（占比 {in_adv:.0%}）")
            near = data.get("near_stoppage", False)
            lines.append(f"- 是否靠近停机：{'是' if near else '否'}")
            if data.get("all_stopped_overlap"):
                lines.append("- 当前结论：未支持（SER 事件多与停机重叠）")
            elif in_adv > 0.5 and near:
                lines.append("- 当前结论：部分支持（推进中存在 SER 且靠近停机）")
            elif in_adv > 0.5:
                lines.append("- 当前结论：线索（推进中存在 SER，与停机关联不明确）")
            else:
                lines.append("- 当前结论：未支持")
    else:
        lines.append("未执行掘进阻力分析。")
    lines.append("")
    # ── 液压异常 HYD ──
    lines.append("### 液压异常 HYD\n")
    if d["hydraulic_obs"]:
        for obs in d["hydraulic_obs"]:
            data = obs.data or {}
            hyd_dur = data.get("hyd_total_duration_h", 0)
            lines.append(f"- HYD 事件数：{data.get('hyd_count', 0)}")
            lines.append(f"- HYD 总时长：{hyd_dur}h")
            if hyd_dur == 0.0 and data.get("hyd_count", 0) > 0:
                lines.append("- HYD 事件时长统计为 0.0h，疑似显示精度或聚合口径问题，需先核查指标口径")
            else:
                near_b = data.get("near_stoppage_boundary", False)
                lines.append(f"- 是否靠近停机边界：{'是' if near_b else '否'}")
                isolated = data.get("isolated_short_fluctuation", False)
                if isolated:
                    lines.append("- 是否构成主因：否（孤立短时波动）")
                elif near_b:
                    lines.append("- 是否构成主因：待确认（靠近停机边界）")
                else:
                    lines.append("- 是否构成主因：未支持")
    else:
        lines.append("未执行液压分析。")
    lines.append("")
    # ── 碎片化 ──
    lines.append("### 碎片化\n")
    if d["fragmentation_obs"]:
        for obs in d["fragmentation_obs"]:
            data = obs.data or {}
            short_r = data.get("short_event_ratio", 0)
            lines.append(f"- 短事件占比：{short_r:.0%}")
            frag = data.get("fragmentation_risk", False)
            lines.append(f"- 是否影响结论：{'是，碎片化风险较高' if frag else '否'}")
    else:
        lines.append("未执行碎片化分析。")
    lines.append("")


def _is_stale_finalizer_claim(text: str, ledger: Any) -> bool:
    """判断 LLM finalizer 的一条结论是否与 evidence_ledger 冲突。"""
    if not ledger or ledger.total_stoppage_cases <= 0:
        return False
    import re
    full_coverage = ledger.actual_stoppage_coverage_count >= ledger.total_stoppage_cases
    complete = ledger.completeness_status == "complete_for_depth"
    if full_coverage and complete:
        stale_patterns = [
            r"样本量仅\s*\d+/\d+",
            r"仅\s*\d+/\d+",
            r"\d+个[^\s]*案例能否代表全部\d+个",
            r"已钻取\s*\d+/\d+",
            r"已[^\s]*钻取.*?(\d+)/(\d+)",
            r"覆盖\s*\d+/\d+",
            r"未覆盖案例",
            r"未\s*drilldown\s*案例",
            r"增加调查轮数",
            r"针对未覆盖案例",
            r"样本量不足",
            r"未钻取验证",
        ]
        for pat in stale_patterns:
            if re.search(pat, text):
                return True
    ratio_match = re.search(r"(\d+)/(\d+)", text)
    if ratio_match and ledger.total_stoppage_cases > 0:
        reported_actual = int(ratio_match.group(1))
        reported_total = int(ratio_match.group(2))
        if reported_total == ledger.total_stoppage_cases:
            if reported_actual != ledger.actual_stoppage_coverage_count:
                return True
    return False


def _build_section_3_unclarified(
    lines: list[str], state: InvestigationState, d: dict,
    corrections: list[str], consistency_warnings: list[str],
) -> None:
    """第 3 节：本次没有查清什么。优先使用 compiled_claims，fc 仅作 fallback 并校验。"""
    lines.append("## 3. 本次没有查清什么\n")
    items: list[str] = []
    ledger = state.evidence_ledger
    claims = state.compiled_claims

    # 主来源：compiled_claims.unresolved_items（从 evidence_ledger 生成）
    if claims and claims.unresolved_items:
        items.extend(claims.unresolved_items)
    else:
        # Fallback：从 coverage 直接生成（仅在 compiled_claims 缺失时）
        cov = d["cov"]
        if cov["uncovered_case_ids"]:
            items.append(f"未逐案钻取的停机案例：{', '.join(cov['uncovered_case_ids'])}")

    # 补充：未验证的事件级异常线索
    if d["unverified"]:
        items.append(f"事件级异常线索待验证：{', '.join(cid for cid, _ in d['unverified'])}")

    # LLM finalizer 的 unresolved_questions_zh：仅当 compiled_claims 缺失时作为 fallback，
    # 且每条必须通过 ledger 校验
    fc = state.final_conclusion
    if fc and fc.unresolved_questions_zh and not (claims and claims.unresolved_items):
        for q in fc.unresolved_questions_zh:
            if _is_stale_finalizer_claim(q, ledger):
                continue
            if q not in items:
                items.append(q)

    # consistency_warnings 和 corrections
    if consistency_warnings:
        for w in consistency_warnings:
            items.append(w)
    if corrections:
        items.append(f"事件级标签与行级规则口径差异：已修正 {len(corrections)} 项（详见技术审计附录）")

    # 需要施工日志确认的案例时间（从 uncertain/abnormal 分类）
    for cid, _ in list(d["abnormal"]) + list(d["uncertain"]):
        for cases in state.stoppage_cases.values():
            for c in cases:
                if c.case_id == cid:
                    items.append(f"需要施工日志确认：{c.start_time} ~ {c.end_time}（案例 {cid}）")

    if items:
        for item in items:
            lines.append(f"- {item}")
    else:
        lines.append("当前调查未发现明显缺口。")
    lines.append("")
    lines.append("> 不确定不是失败，而是当前证据不足，系统没有强行下结论。")
    lines.append("")


def _build_section_4_plan(lines: list[str], state: InvestigationState) -> None:
    """第 4 节：调查计划执行情况。"""
    plan = state.investigation_plan
    if not plan or not plan.plan_items:
        return
    lines.append("## 4. 调查计划执行情况\n")
    lines.append("| 计划 | 要回答的问题 | 状态 | 已用工具 | 关键发现 |")
    lines.append("|------|-------------|------|----------|----------|")
    cov = compute_drilldown_coverage(state)
    for item in plan.plan_items:
        label = _PLAN_ID_ZH.get(item.plan_id, item.plan_id)
        q = item.question[:30].replace("|", "/")
        status = _PLAN_STATUS_ZH.get(item.status, item.status)
        # P1 drilldown 覆盖不足时不能显示"已完成"
        if item.plan_id == "P1" and item.status == "completed":
            dd_ratio = cov["coverage_ratio"]
            if dd_ratio < 1.0:
                status = f"部分完成（已 drilldown {cov['covered_count']}/{cov['total_count']}，"
                status += f"未覆盖 {len(cov['uncovered_case_ids'])} 个）"
        tools = ", ".join(item.required_tools)
        finding = ""
        for tn in item.required_tools:
            for obs in state.observations:
                if obs.action == tn:
                    finding = (obs.result_summary or "")[:40]
                    break
            if finding:
                break
        finding = finding.replace("|", "/")
        lines.append(f"| {label} | {q} | {status} | {tools} | {finding} |")
    lines.append("")
    if plan.budget_warning:
        lines.append(f"> {plan.budget_warning}")
        lines.append("")


def _build_drilldown_detail(lines: list[str], obs, state: InvestigationState) -> None:
    """单个 drilldown 目标的详细审计信息。"""
    data = obs.data or {}
    tid = data.get("target_id", "?")
    lines.append(f"#### 钻取详情：{tid}\n")
    tei = data.get("target_event_info", {})
    if tei.get("source") == "event":
        lines.append(f"- 目标事件类型：{tei.get('semantic_event_type', '')}")
        lines.append(f"- 主导工况：{tei.get('dominant_state', '')}")
        lines.append(f"- 持续时长：{tei.get('duration_seconds', 0)}s")
    sem_ol = data.get("semantic_overlap", {})
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
    for label, key in [("前窗口", "pre_summary"), ("事件期间", "during_summary"), ("后窗口", "post_summary")]:
        s = data.get(key, {})
        if isinstance(s, dict) and not s.get("empty", True):
            lines.append(
                f"- {label}：{s.get('rows', 0)}行，"
                f"SER={s.get('ser_hits', 0)}/{s.get('ser_ratio', 0):.1%}，"
                f"HYD={s.get('hyd_hits', 0)}/{s.get('hyd_ratio', 0):.1%}，"
                f"LEE={s.get('lee_hits', 0)}/{s.get('lee_ratio', 0):.1%}"
            )
    lines.append("")
    lines.append("**工况统计：**")
    for label, key in [("前窗口", "pre_summary"), ("事件期间", "during_summary"), ("后窗口", "post_summary")]:
        s = data.get(key, {})
        if isinstance(s, dict) and not s.get("empty", True):
            sd = s.get("state_distribution", {})
            sp = [f"{k}={v:.0f}%" for k, v in sorted(sd.items(), key=lambda x: -x[1]) if v > 0]
            lines.append(
                f"- {label}：速度={s.get('avg_advance_speed', 0)}，"
                f"转矩={s.get('avg_cutter_torque', 0)}，{'，'.join(sp)}"
            )
    div_notes = data.get("divergence_notes", [])
    if div_notes:
        lines.append("")
        lines.append("**证据口径一致性提示：**")
        for note in div_notes:
            lines.append(f"- {note}")
    hint = data.get("interpretation_hint", "")
    if hint:
        lines.append(f"\n- 初步解释: {hint}")
    tf = data.get("transition_findings", [])
    if tf:
        lines.append(f"- 转变发现: {'，'.join(tf)}")
    lines.append("")


def _build_section_5_audit(
    lines: list[str], state: InvestigationState, d: dict,
    corrections: list[str], consistency_warnings: list[str],
) -> None:
    """第 5 节：技术审计附录。"""
    lines.append("## 5. 技术审计附录\n")
    # 5.1 ReAct 调查轨迹
    lines.extend(_build_react_trace_table(state))
    # 5.2 Planner 与大模型调用审计
    lines.extend(_build_planner_audit_section(state))
    # 5.3 Evidence Gate 审计
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
        uv_eg = [cid for cid, cl in state.case_classifications.items() if cl.case_type == "event_level_abnormal_unverified"]
        if uv_eg:
            lines.append(f"- 仍有未验证事件级异常线索：{', '.join(uv_eg)}")
        if "max_iterations" in state.stop_reason and cov["covered_count"] < cov["total_count"]:
            lines.append("- 因最大轮数限制，未完成最低 drilldown 覆盖。")
        lines.append("")
        for eg in eg_overrides:
            lines.append(
                f"- 第 {eg.round_num} 轮：LLM 选择 `{eg.llm_selected_action}`，"
                f"但{eg.override_reason}，因此改为 `{eg.final_selected_action}({eg.target_id})`"
            )
        if eg_overrides:
            lines.append("")
    # 5.4 drilldown 明细
    dd_obs = d["drilldown_obs"]
    if dd_obs:
        lines.append("### drilldown 明细\n")
        lines.append("| 目标 | 前窗口观察 | 事件期间观察 | 后窗口观察 | 初步解释 |")
        lines.append("|------|-----------|-------------|-----------|----------|")
        for obs in dd_obs:
            data = obs.data or {}
            tid = data.get("target_id", "?")
            cpre = (data.get("compact_pre", "") or "").replace("|", "/")[:40]
            cdur = (data.get("compact_during", "") or "").replace("|", "/")[:40]
            cpost = (data.get("compact_post", "") or "").replace("|", "/")[:40]
            hint = (data.get("interpretation_hint", "") or "").replace("|", "/")[:40]
            lines.append(f"| {tid} | {cpre} | {cdur} | {cpost} | {hint} |")
        lines.append("")
        for obs in dd_obs:
            _build_drilldown_detail(lines, obs, state)
    # 5.5 Top 停机案例
    if d["all_cases"]:
        lines.append("### Top 停机案例\n")
        lines.append("| 案例ID | 开始时间 | 结束时间 | 时长(min) | 合并事件数 | 分类 | 置信度 |")
        lines.append("|--------|----------|----------|-----------|-----------|------|--------|")
        for c, cls in d["all_cases"][:10]:
            ct = _CASE_TYPE_LABELS.get(cls.case_type, cls.case_type) if cls else "未分类"
            conf = f"{cls.confidence:.0%}" if cls else "-"
            lines.append(
                f"| {c.case_id} | {c.start_time} | {c.end_time} "
                f"| {c.duration_seconds/60:.0f} | {c.merged_event_count} "
                f"| {ct} | {conf} |"
            )
        lines.append("")
    # 5.6 异常停机疑似案例详情
    if d["abnormal"]:
        lines.append("### 异常停机疑似案例详情\n")
        for cid, cls in d["abnormal"]:
            lines.append(f"**{cid}**")
            lines.append(f"- 置信度: {cls.confidence:.0%}")
            lines.append("- 判定依据:")
            for r in cls.reasons:
                lines.append(f"  - {r}")
            ta = state.transition_analyses.get(cid)
            if ta:
                lines.append(f"- 停机前异常事件: {len(ta.pre_events)} 个")
                lines.append(f"- 恢复后异常事件: {len(ta.post_events)} 个")
            lines.append("")
    # 5.7 证据一致性检查
    if corrections or consistency_warnings or d["unverified"]:
        lines.append("### 证据一致性检查\n")
        if corrections:
            lines.append("**分类修正：**")
            for c in corrections:
                lines.append(f"- {c}")
            lines.append("")
        if consistency_warnings:
            lines.append("**需人工确认：**")
            for w in consistency_warnings:
                lines.append(f"- {w}")
            lines.append("")
        if d["unverified"]:
            lines.append("**证据等级提示：**")
            for cid, _ in d["unverified"]:
                lines.append(f"- {cid}：事件级证据显示异常迹象，但未运行 drilldown 验证")
            lines.append("")
    # 5.8 调查问题完成情况
    if state.investigation_questions:
        _QS = {"unanswered": "未回答", "partially_answered": "部分回答",
               "answered": "已回答", "blocked_by_missing_data": "缺少数据"}
        lines.append("### 调查问题完成情况\n")
        lines.append("| 问题 | 状态 | 已调用工具 | 关键发现 | 人工核查 |")
        lines.append("|------|------|-----------|----------|---------|")
        for q in state.investigation_questions:
            sz = _QS.get(q.status, q.status)
            ts = ", ".join(q.tools_called) if q.tools_called else "—"
            fs = (q.findings[-1][:40] if q.findings else
                  (q.reason_if_unanswered[:40] if q.reason_if_unanswered else "—"))
            fs = fs.replace("|", "/")
            m = "是" if q.needs_manual_check else "否"
            lines.append(f"| {q.qid}: {q.text[:20]} | {sz} | {ts} | {fs} | {m} |")
        lines.append("")
    # 5.9 跨文件模式
    if state.cross_file_patterns:
        lines.append("### 跨文件模式\n")
        for p in state.cross_file_patterns:
            lines.append(f"- {p}")
        lines.append("")


def build_report(state: InvestigationState) -> dict[str, Any]:
    """根据 InvestigationState 生成产品化 Markdown 报告。

    结构：1.结论总览 → 2.查清了什么 → 3.没查清什么 → 4.计划执行 → 5.技术审计
    """
    corrections, consistency_warnings = _run_consistency_check(state)
    d = _collect_report_data(state)
    lines: list[str] = ["# TBM 调查报告\n"]

    # 无事件早退
    has_any = (d["total_original"] > 0 or d["resistance_obs"]
               or d["hydraulic_obs"] or d["fragmentation_obs"])
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

    _build_section_1_executive(lines, state)
    _build_section_2_clarified(lines, state, d)
    _build_section_3_unclarified(lines, state, d, corrections, consistency_warnings)
    _build_section_4_plan(lines, state)
    _build_section_5_audit(lines, state, d, corrections, consistency_warnings)

    return {"status": "ok", "report_text": "\n".join(lines),
            "total_original_events": d["total_original"],
            "total_merged_cases": d["total_merged"],
            "abnormal_count": len(d["abnormal"]),
            "planned_count": len(d["planned"]),
            "uncertain_count": len(d["uncertain"])}

