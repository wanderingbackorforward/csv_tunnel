"""report.py — 生成 investigation_report.md"""

from __future__ import annotations

from typing import Any

from tbm_diag.investigation.state import InvestigationState


_CASE_TYPE_LABELS = {
    "abnormal_like_stoppage": "异常停机（疑似）",
    "planned_like_stoppage": "计划停机（疑似）",
    "uncertain_stoppage": "待确认停机",
    "short_operational_pause": "短暂运行暂停",
}


def _build_react_trace_table(state: InvestigationState) -> list[str]:
    """构建 ReAct 调查轨迹表。"""
    lines = ["## ReAct 调查轨迹", ""]
    lines.append("| 轮次 | 决策理由 | 调用工具 | 观察结果 | 触发字段 |")
    lines.append("|------|----------|----------|----------|----------|")

    audit_map = {a.round_num: a for a in state.audit_log} if state.audit_log else {}

    for action_rec in state.actions_taken:
        obs = None
        for o in state.observations:
            if o.round_num == action_rec.round_num:
                obs = o
                break
        obs_text = (obs.result_summary[:80] if obs else "无").replace("|", "/")
        rationale = (action_rec.rationale or "").replace("|", "/")[:60]
        ar = audit_map.get(action_rec.round_num)
        trigger = (ar.triggered_by_field if ar and ar.triggered_by_field else "—").replace("|", "/")
        lines.append(
            f"| {action_rec.round_num} | {rationale} "
            f"| {action_rec.action} | {obs_text} | {trigger} |"
        )
    lines.append("")
    return lines


def build_report(state: InvestigationState) -> dict[str, Any]:
    """根据 InvestigationState 生成 Markdown 报告内容。"""
    lines: list[str] = []
    lines.append("# 调查报告\n")

    # ── ReAct 调查轨迹（始终输出）──
    lines.extend(_build_react_trace_table(state))

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
    lines.append(f"- 置信度: {state.confidence:.2f}")

    if total_merged > 0:
        lines.append(f"- 原始停机事件数: {total_original}")
        lines.append(f"- 合并后停机案例数: {total_merged}")
        lines.append(f"- 异常停机（疑似）: {len(abnormal_cases)} 个")
        lines.append(f"- 计划停机（疑似）: {len(planned_cases)} 个")
        lines.append(f"- 待确认: {len(uncertain_cases)} 个")
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
            hint = data.get("interpretation_hint", "")
            lines.append(f"- 初步解释: {hint}")
            tf = data.get("transition_findings", [])
            if tf:
                lines.append(f"- 转变发现: {'，'.join(tf)}")
            for label, key in [("前窗口", "pre_summary"), ("事件期间", "during_summary"), ("后窗口", "post_summary")]:
                s = data.get(key, {})
                if isinstance(s, dict) and not s.get("empty", True):
                    lines.append(f"- {label}: {s.get('rows', 0)}行，"
                                 f"速度={s.get('avg_advance_speed', 0)}，"
                                 f"转矩={s.get('avg_cutter_torque', 0)}，"
                                 f"SER={s.get('ser_hits', 0)}/{s.get('ser_ratio', 0):.1%}，"
                                 f"HYD={s.get('hyd_hits', 0)}")
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

    # ── 异常停机疑似案例 ──
    if abnormal_cases:
        lines.append("## 异常停机疑似案例\n")
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

