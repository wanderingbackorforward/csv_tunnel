"""report.py — 生成 investigation_report.md"""

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


def build_report(state: InvestigationState) -> dict[str, Any]:
    """根据 InvestigationState 生成 Markdown 报告内容。"""
    lines: list[str] = []
    lines.append("# 调查报告\n")

    # ── 证据一致性检查（在生成报告内容前修正分类）──
    corrections, consistency_warnings = _run_consistency_check(state)

    # ── ReAct 调查轨迹（始终输出）──
    lines.extend(_build_react_trace_table(state))

    # ── 最终调查结论（优先展示）──
    fc = state.final_conclusion
    if fc:
        _CONV = {"converged": "已收敛", "partially_converged": "部分收敛", "not_converged": "未收敛"}
        _FT = {"rule": "规则 finalizer", "llm": "LLM finalizer", "fallback": "LLM 失败后 fallback 到规则"}
        lines.append("## 最终调查结论\n")
        lines.append(f"- 收敛状态：{_CONV.get(fc.convergence_status, fc.convergence_status)}")
        lines.append(f"- 停止原因：{fc.stop_reason}")
        lines.append(f"- 结论置信度：{fc.confidence_label}（{fc.confidence_reason_zh}）")
        ft_label = _FT.get(fc.finalizer_type, fc.finalizer_type)
        if fc.validator_applied:
            ft_label += " + rule validator"
        lines.append(f"- Finalizer：{ft_label}")
        if fc.finalizer_model:
            lines.append(f"- 模型：{fc.finalizer_model}")
        if fc.validator_applied and fc.downgraded_fields:
            lines.append(f"- Validator：已修正（{len(fc.downgraded_fields)} 项降级）")
        elif fc.validator_applied and fc.validation_warnings:
            lines.append(f"- Validator：有警告（{len(fc.validation_warnings)} 项）")
        elif fc.validator_applied:
            lines.append("- Validator：通过")
        lines.append("")

        if fc.downgraded_fields:
            lines.append("**降级原因：**")
            for d in fc.downgraded_fields:
                lines.append(f"- {d}")
            lines.append("")

        if fc.validation_warnings:
            lines.append("**Validator 警告：**")
            for w in fc.validation_warnings:
                lines.append(f"- {w}")
            lines.append("")

        # 补充 validator 区域的综合限制因素（未被 warnings 覆盖的）
        if fc.validator_applied:
            supplementary: list[str] = []
            cov_v = compute_drilldown_coverage(state)
            total_cases_v = cov_v["total_count"]
            dd_count = cov_v["covered_count"]
            unclassified_v = total_cases_v - len(state.case_classifications)
            fallback_count = state.llm_fallback_count

            if total_cases_v > 0 and dd_count < total_cases_v:
                txt = f"drilldown 覆盖不足：{dd_count}/{total_cases_v}"
                if not any(txt[:20] in w for w in fc.validation_warnings):
                    supplementary.append(txt)
            if unclassified_v > 0:
                supplementary.append(f"未分类停机案例较多：{unclassified_v} 个")
            if fallback_count > 0:
                supplementary.append(f"LLM planner 存在 fallback：{fallback_count} 次")

            if supplementary:
                lines.append("**其他限制因素：**")
                for s in supplementary:
                    lines.append(f"- {s}")
                lines.append("")

        lines.append("**主要判断：**")
        lines.append(f"{fc.primary_conclusion_zh}")
        lines.append("")
        if fc.ruled_out_zh:
            lines.append("**当前未支持/已排除：**")
            for r in fc.ruled_out_zh:
                lines.append(f"- {r}")
            lines.append("")
        if fc.unresolved_questions_zh:
            lines.append("**仍不确定：**")
            for q in fc.unresolved_questions_zh:
                lines.append(f"- {q}")
            lines.append("")
        if fc.next_manual_checks:
            lines.append("**下一步人工核查：**")
            for c in fc.next_manual_checks:
                lines.append(f"- {c}")
            lines.append("")

    # ── 核心结论 ──
    total_original = 0
    total_merged = 0
    for fp, cases in state.stoppage_cases.items():
        for c in cases:
            total_merged += 1
            total_original += c.merged_event_count

    abnormal_cases = [
        (cid, cls) for cid, cls in state.case_classifications.items()
        if cls.case_type == "abnormal_like_stoppage"
    ]
    unverified_cases = [
        (cid, cls) for cid, cls in state.case_classifications.items()
        if cls.case_type == "event_level_abnormal_unverified"
    ]
    planned_cases = [
        (cid, cls) for cid, cls in state.case_classifications.items()
        if cls.case_type == "planned_like_stoppage"
    ]
    uncertain_cases = [
        (cid, cls) for cid, cls in state.case_classifications.items()
        if cls.case_type == "uncertain_stoppage"
    ]

    lines.append("## 核心结论\n")

    # 收集非停机分析结果
    resistance_obs = [o for o in state.observations if o.action == "analyze_resistance_pattern"]
    hydraulic_obs = [o for o in state.observations if o.action == "analyze_hydraulic_pattern"]
    fragmentation_obs = [o for o in state.observations if o.action == "analyze_event_fragmentation"]

    if total_original == 0 and not resistance_obs and not hydraulic_obs and not fragmentation_obs:
        has_events = any(s.event_count > 0 for s in state.event_summaries.values())
        if has_events:
            lines.append("该文件存在异常事件，但未检测到需要深入追查的模式，")
            lines.append("可能偏向推进过程中的轻微异常。\n")
        else:
            lines.append("该文件未检测到异常事件，数据整体正常，无需追查。\n")
        lines.append(f"- 调查轮次: {state.iteration_count}")
        lines.append("")
        report_text = "\n".join(lines)
        return {
            "status": "ok",
            "report_text": report_text,
            "total_original_events": 0,
            "total_merged_cases": 0,
            "abnormal_count": 0,
            "planned_count": 0,
            "uncertain_count": 0,
        }

    lines.append(f"- 调查轮次: {state.iteration_count}")

    # 置信度：以 final_conclusion.confidence_label（经 validator 校验）为准
    if fc:
        _CL = {"high": "高", "medium": "中", "low": "低"}
        cl_zh = _CL.get(fc.confidence_label, fc.confidence_label)
        lines.append(f"- 整体结论置信度：{cl_zh}（{fc.confidence_reason_zh}）")
    elif corrections:
        lines.append("- 整体结论置信度：低（存在证据口径冲突已修正）")
    elif consistency_warnings:
        lines.append("- 整体结论置信度：低（存在需人工确认的问题）")
    elif total_merged > 0 or resistance_obs or hydraulic_obs:
        lines.append("- 整体结论置信度：中（疑似，需施工日志确认）")
    else:
        lines.append("- 整体结论置信度：未计算")

    if total_merged > 0:
        unclassified = total_merged - len(state.case_classifications)
        lines.append(f"- 原始停机事件数: {total_original}")
        lines.append(f"- 合并后停机案例数: {total_merged}")
        lines.append(f"- 已验证异常停机（疑似）: {len(abnormal_cases)} 个")
        lines.append(f"- 事件级异常线索，待验证: {len(unverified_cases)} 个")
        lines.append(f"- 计划停机（疑似）: {len(planned_cases)} 个")
        lines.append(f"- 待确认: {len(uncertain_cases)} 个")
        if unclassified > 0:
            lines.append(f"- 未分类: {unclassified} 个")
    lines.append("")

    # ── 掘进阻力分析结果 ──
    if resistance_obs:
        lines.append("## 掘进阻力异常分析\n")
        for obs in resistance_obs:
            data = obs.data or {}
            lines.append(f"- SER 事件数: {data.get('ser_count', 0)}")
            lines.append(f"- SER 总时长: {data.get('ser_total_duration_h', 0)}h")
            lines.append(f"- 推进中占比: {data.get('in_advancing_ratio', 0):.0%}")
            lines.append(f"- 时间集中: {'是' if data.get('concentrated_in_time') else '否'}")
            lines.append(f"- 靠近停机: {'是' if data.get('near_stoppage') else '否'}")
            if data.get("invalid_ser_count", 0) > 0:
                lines.append(f"- 停机期 SER 事件（已排除）: {data.get('invalid_ser_count', 0)} 个")
            if data.get("all_stopped_overlap"):
                lines.append("- **注意**: 当前 SER 事件多与停机片段重叠，暂不能证明推进中的掘进阻力异常，"
                             "需要重新区分停机期伪异常与推进期 SER")
            lines.append(f"- 摘要: {data.get('summary', '')}")
            lines.append("")

    # ── 液压分析结果 ──
    if hydraulic_obs:
        lines.append("## 液压不稳定分析\n")
        for obs in hydraulic_obs:
            data = obs.data or {}
            lines.append(f"- HYD 事件数: {data.get('hyd_count', 0)}")
            lines.append(f"- HYD 总时长: {data.get('hyd_total_duration_h', 0)}h")
            lines.append(f"- 与 SER 同步: {'是' if data.get('sync_with_ser') else '否'}")
            lines.append(f"- 靠近停机边界: {'是' if data.get('near_stoppage_boundary') else '否'}")
            lines.append(f"- 孤立短时波动: {'是' if data.get('isolated_short_fluctuation') else '否'}")
            lines.append(f"- 摘要: {data.get('summary', '')}")
            lines.append("")

    # ── 碎片化分析结果 ──
    if fragmentation_obs:
        lines.append("## 事件碎片化分析\n")
        for obs in fragmentation_obs:
            data = obs.data or {}
            lines.append(f"- 事件总数: {data.get('event_count', 0)}")
            lines.append(f"- 平均时长: {data.get('avg_duration_s', 0)}s")
            lines.append(f"- 短事件占比: {data.get('short_event_ratio', 0):.0%}")
            lines.append(f"- 碎片化风险: {'是' if data.get('fragmentation_risk') else '否'}")
            lines.append(f"- 摘要: {data.get('summary', '')}")
            lines.append("")

    # ── 时间窗口钻取结果 ──
    drilldown_obs = [o for o in state.observations if o.action == "drilldown_time_window"]
    if drilldown_obs:
        lines.append("## 时间窗口钻取结果\n")
        lines.append("| 目标 | 前窗口观察 | 事件期间观察 | 后窗口观察 | 初步解释 |")
        lines.append("|------|-----------|-------------|-----------|----------|")
        for obs in drilldown_obs:
            data = obs.data or {}
            tid = data.get("target_id", "?")
            cpre = (data.get("compact_pre", "") or "").replace("|", "/")[:40]
            cdur = (data.get("compact_during", "") or "").replace("|", "/")[:40]
            cpost = (data.get("compact_post", "") or "").replace("|", "/")[:40]
            hint = (data.get("interpretation_hint", "") or "").replace("|", "/")[:40]
            lines.append(f"| {tid} | {cpre} | {cdur} | {cpost} | {hint} |")
        lines.append("")

        for obs in drilldown_obs:
            data = obs.data or {}
            tid = data.get("target_id", "?")
            lines.append(f"### 钻取详情：{tid}\n")

            # target_event_info
            tei = data.get("target_event_info", {})
            if tei.get("source") == "event":
                lines.append(f"**事件级证据：**")
                sem = tei.get("semantic_event_type", "")
                lines.append(f"- 目标事件类型：{sem}")
                lines.append(f"- 主导工况：{tei.get('dominant_state', '')}")
                lines.append(f"- 持续时长：{tei.get('duration_seconds', 0)}s")

            # semantic_overlap_summary
            sem_overlap = data.get("semantic_overlap", {})
            during_ol = sem_overlap.get("during", {})
            if during_ol.get("total", 0) > 0:
                lines.append(f"- 事件期间重叠事件数：{during_ol['total']}")
                if during_ol.get("ser", 0) > 0:
                    lines.append(f"- 重叠 SER 事件数：{during_ol['ser']}")
                if during_ol.get("hyd", 0) > 0:
                    lines.append(f"- 重叠 HYD 事件数：{during_ol['hyd']}")
                if during_ol.get("stoppage", 0) > 0:
                    lines.append(f"- 重叠停机事件数：{during_ol['stoppage']}")

            # row-level summary
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

            # state summary
            lines.append("")
            lines.append("**工况统计：**")
            for label, key in [("前窗口", "pre_summary"), ("事件期间", "during_summary"), ("后窗口", "post_summary")]:
                s = data.get(key, {})
                if isinstance(s, dict) and not s.get("empty", True):
                    sd = s.get("state_distribution", {})
                    state_parts = [f"{k}={v:.0f}%" for k, v in sorted(sd.items(), key=lambda x: -x[1]) if v > 0]
                    lines.append(
                        f"- {label}：速度={s.get('avg_advance_speed', 0)}，"
                        f"转矩={s.get('avg_cutter_torque', 0)}，"
                        f"{'，'.join(state_parts)}"
                    )

            # divergence notes
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

    # ── Top 停机案例 ──
    all_cases = []
    for fp, cases in state.stoppage_cases.items():
        for c in cases:
            cls = state.case_classifications.get(c.case_id)
            all_cases.append((c, cls))

    all_cases.sort(key=lambda x: -x[0].duration_seconds)

    if all_cases:
        lines.append("## Top 停机案例\n")
        lines.append("| 案例ID | 开始时间 | 结束时间 | 时长(min) | 合并事件数 | 分类 | 置信度 |")
        lines.append("|--------|----------|----------|-----------|-----------|------|--------|")
        for c, cls in all_cases[:10]:
            ct = _CASE_TYPE_LABELS.get(cls.case_type, cls.case_type) if cls else "未分类"
            conf = f"{cls.confidence:.0%}" if cls else "-"
            lines.append(
                f"| {c.case_id} | {c.start_time} | {c.end_time} "
                f"| {c.duration_seconds/60:.0f} | {c.merged_event_count} "
                f"| {ct} | {conf} |"
            )
        lines.append("")

    # ── 异常停机疑似案例（已验证）──
    if abnormal_cases:
        lines.append("## 异常停机疑似案例（drilldown 已验证）\n")
        for cid, cls in abnormal_cases:
            lines.append(f"### {cid}\n")
            lines.append(f"- 置信度: {cls.confidence:.0%}")
            lines.append("- 判定依据:")
            for r in cls.reasons:
                lines.append(f"  - {r}")
            ta = state.transition_analyses.get(cid)
            if ta:
                lines.append(f"- 停机前异常事件: {len(ta.pre_events)} 个")
                lines.append(f"- 恢复后异常事件: {len(ta.post_events)} 个")
            lines.append("")

    # ── 事件级异常线索，待验证 ──
    if unverified_cases:
        lines.append("## 事件级异常线索，待验证\n")
        lines.append("以下案例在事件摘要层面存在异常线索，但尚未经过 drilldown 窗口验证，不能直接判定为异常停机。\n")
        for cid, cls in unverified_cases:
            lines.append(f"### {cid}\n")
            lines.append(f"- 证据来源：事件级摘要")
            lines.append(f"- 验证状态：未 drilldown")
            lines.append(f"- 置信度: {cls.confidence:.0%}")
            lines.append("- 事件级线索:")
            for r in cls.reasons:
                if "事件级证据" in r or "drilldown" not in r:
                    lines.append(f"  - {r}")
            lines.append(f"- 建议：优先对该案例运行 `drilldown_time_window --target_id {cid}`")
            lines.append("")

    # ── 计划停机疑似案例 ──
    if planned_cases:
        lines.append("## 计划停机疑似案例\n")
        for cid, cls in planned_cases:
            lines.append(f"- {cid}: {', '.join(cls.reasons)}")
        lines.append("")

    # ── 待人工确认 ──
    if uncertain_cases or state.open_questions:
        lines.append("## 待人工确认\n")
        if uncertain_cases:
            lines.append("以下案例无法自动判定，建议人工核查:\n")
            for cid, cls in uncertain_cases:
                target = None
                for cases in state.stoppage_cases.values():
                    for c in cases:
                        if c.case_id == cid:
                            target = c
                            break
                if target:
                    lines.append(f"- {cid}: {target.start_time} ~ {target.end_time} ({target.duration_seconds/60:.0f}min)")
        if state.open_questions:
            lines.append("\n未解决问题:\n")
            for q in state.open_questions:
                lines.append(f"- {q}")
        lines.append("")

    # ── 建议核查的施工日志时间段 ──
    check_periods = []
    for cid, cls in abnormal_cases:
        for cases in state.stoppage_cases.values():
            for c in cases:
                if c.case_id == cid:
                    check_periods.append((c.start_time, c.end_time, cid))
    for cid, cls in uncertain_cases:
        for cases in state.stoppage_cases.values():
            for c in cases:
                if c.case_id == cid:
                    check_periods.append((c.start_time, c.end_time, cid))

    if check_periods:
        lines.append("## 建议核查的施工日志时间段\n")
        for start, end, cid in check_periods:
            lines.append(f"- {start} ~ {end} (案例 {cid})")
        lines.append("")

    # ── Planner 与大模型调用审计 ──
    lines.extend(_build_planner_audit_section(state))

    # ── Evidence Gate 审计 ──
    eg_overrides = state.evidence_gate_overrides
    cov = compute_drilldown_coverage(state)
    total_cases_eg = cov["total_count"]
    dd_sc_eg = cov["covered_count"]
    if eg_overrides or total_cases_eg > 0:
        lines.append("## Evidence Gate 审计\n")
        lines.append(f"- Evidence Gate 触发次数：{len(eg_overrides)}")
        lines.append(f"- 停机案例 drilldown 覆盖率：{dd_sc_eg}/{total_cases_eg}")
        if cov["single_drilldown_case_ids"]:
            lines.append(f"- 单次 drilldown 覆盖：{', '.join(cov['single_drilldown_case_ids'])}")
        if cov["batch_drilldown_case_ids"]:
            lines.append(f"- batch drilldown 覆盖：{', '.join(cov['batch_drilldown_case_ids'])}")
        if cov["uncovered_case_ids"]:
            lines.append(f"- 未覆盖：{', '.join(cov['uncovered_case_ids'])}")
        unverified_eg = [
            cid for cid, cls in state.case_classifications.items()
            if cls.case_type == "event_level_abnormal_unverified"
        ]
        if unverified_eg:
            lines.append(f"- 仍有未验证事件级异常线索：{', '.join(unverified_eg)}")
        if "max_iterations" in state.stop_reason and dd_sc_eg < total_cases_eg:
            lines.append(f"- 因最大轮数限制，未完成最低 drilldown 覆盖。")
        lines.append("")
        if eg_overrides:
            for eg in eg_overrides:
                lines.append(
                    f"- 第 {eg.round_num} 轮：LLM 选择 `{eg.llm_selected_action}`，"
                    f"但{eg.override_reason}，因此改为 `{eg.final_selected_action}({eg.target_id})`"
                )
            lines.append("")

    # ── 调查计划执行情况 ──
    plan = state.investigation_plan
    if plan and plan.plan_items:
        _PS = {
            "pending": "待执行",
            "in_progress": "进行中",
            "completed": "已完成",
            "skipped_due_to_budget": "因轮数不足跳过",
        }
        lines.append("## 调查计划执行情况\n")
        lines.append(f"- 预估所需轮数：{plan.estimated_required_rounds}")
        lines.append(f"- 推荐 max_iterations：{plan.recommended_max_iterations}")
        lines.append(f"- 实际 max_iterations：{state.iteration_count}"
                     f"（停止原因：{state.stop_reason}）")
        if plan.budget_warning:
            lines.append(f"- **预算警告**：{plan.budget_warning}")
        lines.append("")

        lines.append("| 计划项 | 优先级 | 目标 | 所需工具 | 状态 |")
        lines.append("|--------|--------|------|----------|------|")
        for item in plan.plan_items:
            targets = ", ".join(item.target_ids[:3]) if item.target_ids else "—"
            tools = ", ".join(item.required_tools)
            status_zh = _PS.get(item.status, item.status)
            lines.append(
                f"| {item.plan_id}: {item.question[:20]} | {item.priority} "
                f"| {targets} | {tools} | {status_zh} |"
            )
        lines.append("")

        skipped = [i for i in plan.plan_items if i.status == "skipped_due_to_budget"]
        if skipped:
            lines.append("当前轮数不足以完成完整调查，结果仅供初筛。\n")

    # ── 调查问题完成情况 ──
    if state.investigation_questions:
        _QS = {
            "unanswered": "未回答",
            "partially_answered": "部分回答",
            "answered": "已回答",
            "blocked_by_missing_data": "缺少数据",
        }
        lines.append("## 调查问题完成情况\n")
        lines.append("| 问题 | 状态 | 已调用工具 | 关键发现 | 是否还需人工核查 |")
        lines.append("|------|------|-----------|----------|----------------|")
        for q in state.investigation_questions:
            status_zh = _QS.get(q.status, q.status)
            tools_str = ", ".join(q.tools_called) if q.tools_called else "—"
            finding_str = (q.findings[-1][:40] if q.findings else
                           (q.reason_if_unanswered[:40] if q.reason_if_unanswered else "—"))
            finding_str = finding_str.replace("|", "/")
            manual = "是" if q.needs_manual_check else "否"
            lines.append(
                f"| {q.qid}: {q.text[:20]} | {status_zh} "
                f"| {tools_str} | {finding_str} | {manual} |"
            )
        lines.append("")

        # 未回答的问题详情
        unanswered_qs = [q for q in state.investigation_questions
                         if q.status in ("unanswered", "blocked_by_missing_data")]
        if unanswered_qs:
            lines.append("### 未回答的问题\n")
            for q in unanswered_qs:
                lines.append(f"- **{q.qid}**: {q.text}")
                if q.reason_if_unanswered:
                    lines.append(f"  - 原因：{q.reason_if_unanswered}")
            lines.append("")

    # ── 证据一致性检查 ──
    if corrections or consistency_warnings or unverified_cases:
        lines.append("## 证据一致性检查\n")
        if corrections:
            lines.append("### 分类修正\n")
            lines.append("以下分类依据经 drilldown 窗口证据核实后被修正：\n")
            for c in corrections:
                lines.append(f"- {c}")
            lines.append("")
        if consistency_warnings:
            lines.append("### 需人工确认\n")
            for w in consistency_warnings:
                lines.append(f"- {w}")
            lines.append("")
        if unverified_cases:
            lines.append("### 证据等级提示\n")
            lines.append('以下案例仅有事件级异常线索，尚无窗口级验证，已从异常停机降级为待验证线索：\n')
            for cid, cls in unverified_cases:
                lines.append(f"- {cid}：事件级证据显示异常迹象，但未运行 drilldown 验证")
            lines.append("")
    else:
        lines.append("## 证据一致性检查\n")
        lines.append("未发现 drilldown 窗口证据与分类结论之间的冲突。\n")

    # ── 跨文件模式 ──
    if state.cross_file_patterns:
        lines.append("## 跨文件模式\n")
        for p in state.cross_file_patterns:
            lines.append(f"- {p}")
        lines.append("")

    report_text = "\n".join(lines)

    return {
        "status": "ok",
        "report_text": report_text,
        "total_original_events": total_original,
        "total_merged_cases": total_merged,
        "abnormal_count": len(abnormal_cases),
        "planned_count": len(planned_cases),
        "uncertain_count": len(uncertain_cases),
    }

