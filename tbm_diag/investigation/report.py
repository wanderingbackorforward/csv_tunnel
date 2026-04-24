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


def build_report(state: InvestigationState) -> dict[str, Any]:
    """根据 InvestigationState 生成 Markdown 报告内容。"""
    lines: list[str] = []
    lines.append("# 停机案例追查报告\n")

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
    lines.append(f"- 原始停机事件数: {total_original}")
    lines.append(f"- 合并后停机案例数: {total_merged}")
    lines.append(f"- 异常停机（疑似）: {len(abnormal_cases)} 个")
    lines.append(f"- 计划停机（疑似）: {len(planned_cases)} 个")
    lines.append(f"- 待确认: {len(uncertain_cases)} 个")
    lines.append(f"- 调查轮次: {state.iteration_count}")
    lines.append(f"- 置信度: {state.confidence:.2f}")
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

