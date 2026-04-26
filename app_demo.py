from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


ROOT = Path(__file__).resolve().parent
PYTHON_BIN = sys.executable
TMP_UPLOAD_DIR = ROOT / "tmp_demo_uploads"
TMP_OUTPUT_DIR = ROOT / "tmp_demo_outputs"
SCAN_DEMO_DIR = ROOT / "scan_demo_out"
REVIEW_DEMO_DIR = ROOT / "review_demo_out"
INVESTIGATION_DEMO_DIR = ROOT / "investigation_demo_out"
SUPPORTED_EXTENSIONS = {".csv", ".xls", ".xlsx"}

if load_dotenv is not None:
    load_dotenv(ROOT / ".env", override=False)


def ensure_demo_directories() -> None:
    for path in [
        TMP_UPLOAD_DIR,
        TMP_OUTPUT_DIR,
        SCAN_DEMO_DIR,
        REVIEW_DEMO_DIR,
        INVESTIGATION_DEMO_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def normalize_path(raw: str | Path | None) -> Path | None:
    if raw is None:
        return None
    text = str(raw).strip().strip('"').strip("'")
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def save_uploaded_file(uploaded_file) -> Path:
    suffix = Path(uploaded_file.name).suffix.lower()
    target = TMP_UPLOAD_DIR / f"{Path(uploaded_file.name).stem}_{uuid.uuid4().hex[:8]}{suffix}"
    target.write_bytes(uploaded_file.getbuffer())
    return target


def quote_command(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def run_cli(parts: list[str], waiting_text: str) -> dict[str, Any]:
    command = [PYTHON_BIN, "-m", "tbm_diag.cli", *parts]
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    with st.spinner(waiting_text):
        proc = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def render_cli_output(result: dict[str, Any]) -> None:
    with st.expander("查看命令行输出", expanded=False):
        st.code(quote_command(result["command"]), language="bash")
        st.caption("标准输出")
        st.code(result.get("stdout") or "（无输出）", language="text")
        st.caption("错误输出")
        st.code(result.get("stderr") or "（无输出）", language="text")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_markdown_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig", errors="replace")


def read_csv_table(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="utf-8", engine="python")


def render_download(path: Path, label: str, mime: str) -> None:
    if not path.exists():
        st.caption(f"{label}未生成")
        return
    st.download_button(
        label=label,
        data=path.read_bytes(),
        file_name=path.name,
        mime=mime,
        use_container_width=True,
    )


def has_openai_compatible_config() -> bool:
    return bool(os.getenv("OPENAI_API_KEY")) and bool(os.getenv("OPENAI_BASE_URL"))


def choose_scan_index(preferred: str = "") -> Path | None:
    for candidate in [
        normalize_path(preferred),
        normalize_path(st.session_state.get("latest_scan_index")),
        ROOT / "scan_real_out" / "scan_index.csv",
        SCAN_DEMO_DIR / "scan_index.csv",
    ]:
        if candidate and candidate.exists():
            return candidate
    return None


def summarize_scan(df: pd.DataFrame) -> dict[str, int]:
    status = df.get("status", pd.Series(dtype="object")).fillna("")
    if "is_high_priority" in df.columns:
        high_risk_count = int(pd.Series(df["is_high_priority"]).fillna(False).astype(bool).sum())
    else:
        high_risk_count = int((df.get("max_severity_label", pd.Series(dtype="object")) == "高风险").sum())
    return {
        "file_total": int(len(df)),
        "ok_total": int((status == "ok").sum()),
        "skipped_total": int((status == "skipped").sum()),
        "failed_total": int((status == "error").sum()),
        "high_risk_total": high_risk_count,
    }


def build_detect_event_rows(result_doc: dict[str, Any]) -> list[dict[str, str]]:
    explanations = result_doc.get("explanations", [])
    if explanations:
        rows = []
        for item in explanations[:3]:
            rows.append(
                {
                    "事件标题": item.get("title") or item.get("event_type") or item.get("event_id") or "未命名事件",
                    "风险等级": item.get("severity_label") or "未标注",
                    "摘要": item.get("summary") or "暂无摘要",
                }
            )
        return rows

    rows = []
    for item in result_doc.get("events", [])[:3]:
        rows.append(
            {
                "事件标题": item.get("event_id") or "未命名事件",
                "风险等级": "未标注",
                "摘要": item.get("event_type") or "暂无摘要",
            }
        )
    return rows


def build_scan_display_table(df: pd.DataFrame) -> pd.DataFrame:
    renamed = pd.DataFrame(
        {
            "文件名": df.get("file_name", pd.Series(dtype="object")),
            "事件数": df.get("event_count", pd.Series(dtype="object")),
            "最高风险": df.get("max_severity_label", pd.Series(dtype="object")),
            "风险分数": df.get("risk_rank_score", pd.Series(dtype="object")),
            "主要事件类型": df.get("top_event_type", pd.Series(dtype="object")),
            "事件摘要": df.get("top_event_summary", pd.Series(dtype="object")),
            "报告路径": df.get("md_path", pd.Series(dtype="object")),
        }
    )
    return renamed.head(10)


def build_review_display_table(file_results: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    _SRC = {"llm": "LLM 成功", "fallback": "规则降级", "none": "未生成"}
    for item in file_results:
        src = _SRC.get(item.get("summary_source", ""), item.get("summary_source", ""))
        rows.append(
            {
                "文件名": item.get("file_name", ""),
                "运行状态": item.get("status", ""),
                "风险分数": item.get("risk_rank_score", ""),
                "事件数": item.get("event_count", ""),
                "最高风险": item.get("max_severity_label", ""),
                "总结来源": src,
                "LLM状态": item.get("llm_status", ""),
                "模型": item.get("llm_model", ""),
                "复核结论": item.get("ai_summary", ""),
            }
        )
    return pd.DataFrame(rows)


def build_case_display_table(cases: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for item in cases:
        reasons = item.get("reasons", [])
        if isinstance(reasons, list):
            reason_text = "；".join(str(reason) for reason in reasons[:3])
        else:
            reason_text = str(reasons)
        rows.append(
            {
                "案例编号": item.get("case_id", ""),
                "开始时间": item.get("start_time", ""),
                "结束时间": item.get("end_time", ""),
                "持续时长": item.get("duration_seconds", ""),
                "案例类型": item.get("case_type", ""),
                "置信度": item.get("confidence", ""),
                "判断依据": reason_text,
            }
        )
    return pd.DataFrame(rows)


def _parse_mode_from_command(command: str) -> str:
    """从 investigate 命令中解析 --mode 值。"""
    parts = command.split()
    for i, part in enumerate(parts):
        if part == "--mode" and i + 1 < len(parts):
            return parts[i + 1]
    return "auto"


def _parse_input_from_command(command: str) -> str:
    """从 investigate 命令中解析 --input 值。"""
    parts = command.split()
    for i, part in enumerate(parts):
        if part in ("--input", "-i") and i + 1 < len(parts):
            return parts[i + 1]
    return ""


_MODE_LABELS = {
    "stoppage": "停机追查",
    "resistance": "掘进阻力追查",
    "hydraulic": "液压异常追查",
    "fragmentation": "碎片化检查",
    "auto": "自动",
}


def _render_technical_audit(state_doc: dict) -> None:
    """技术审计折叠区内容：ReAct 轨迹、LLM 统计、Evidence Gate。"""
    _PT = {"rule": "规则", "llm": "LLM", "hybrid": "混合"}
    planner_type = state_doc.get("planner_type", "rule")
    rounds = state_doc.get("iteration_count", 0)
    action_names = [a.get("action", "") for a in state_doc.get("actions_taken", [])]
    action_seq = " → ".join(action_names) if action_names else "未记录"

    col1, col2, col3 = st.columns(3)
    col1.metric("Planner", _PT.get(planner_type, planner_type))
    col2.metric("轮次", rounds)
    col3.metric("工具调用数", len(action_names))

    llm_success = state_doc.get("llm_success_count", 0)
    llm_fallback = state_doc.get("llm_fallback_count", 0)
    llm_attempted = sum(1 for c in state_doc.get("llm_calls", []) if c.get("status") != "skipped")
    if llm_attempted > 0 or planner_type in ("llm", "hybrid"):
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("LLM 调用", llm_attempted)
        col_b.metric("LLM 成功", llm_success)
        col_c.metric("fallback", llm_fallback)
        col_d.metric("模型", state_doc.get("llm_model", "—") or "—")

    st.caption(f"action_sequence: {action_seq}")

    eg_overrides = state_doc.get("evidence_gate_overrides", [])
    stoppage_cases_all = state_doc.get("stoppage_cases", {})
    total_sc = sum(len(v) for v in stoppage_cases_all.values()) if isinstance(stoppage_cases_all, dict) else 0
    sc_drilled: set[str] = set()
    for o in state_doc.get("observations", []):
        if not isinstance(o, dict):
            continue
        data = o.get("data", {})
        if o.get("action") == "drilldown_time_window":
            tid = data.get("target_id", "")
            if tid.startswith("SC_") and data.get("status") != "error":
                sc_drilled.add(tid)
        elif o.get("action") == "drilldown_time_windows_batch" and data.get("status") != "error":
            for pt in data.get("per_target", []):
                tid = pt.get("target_id", "")
                if tid.startswith("SC_") and pt.get("status") != "error":
                    sc_drilled.add(tid)
    if eg_overrides or total_sc > 0:
        st.markdown("**Evidence Gate**")
        col_eg1, col_eg2 = st.columns(2)
        col_eg1.metric("Gate 触发", len(eg_overrides))
        col_eg2.metric("drilldown 覆盖", f"{len(sc_drilled)}/{total_sc}")
        if eg_overrides:
            for eg in eg_overrides:
                st.markdown(
                    f"- 第 {eg.get('round_num')} 轮：`{eg.get('llm_selected_action')}`"
                    f" → `{eg.get('final_selected_action')}({eg.get('target_id', '')})`"
                )

    actions = state_doc.get("actions_taken", [])
    audit_map = {a.get("round_num"): a for a in state_doc.get("audit_log", [])}
    if actions:
        st.markdown("**ReAct 调查轨迹**")
        _PT_L = {"rule": "规则", "llm": "LLM", "hybrid_rule": "混合/规则", "hybrid_llm": "混合/LLM"}
        rows = []
        for a in actions:
            rn = a.get("round_num", "")
            au = audit_map.get(rn, {})
            rows.append({
                "轮次": rn,
                "Planner": _PT_L.get(a.get("planner_type", "rule"), a.get("planner_type", "")),
                "LLM": a.get("llm_status", "") if a.get("llm_called") else "—",
                "决策理由": (au.get("selected_reason", "") or a.get("rationale", "") or "")[:50],
                "工具": a.get("action", ""),
                "观察": (a.get("observation_summary", "") or "")[:60],
                "fallback": "是" if a.get("fallback_used") else "—",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    inv_qs = state_doc.get("investigation_questions", [])
    if inv_qs:
        _QS = {"unanswered": "未回答", "partially_answered": "部分回答",
               "answered": "已回答", "blocked_by_missing_data": "缺少数据"}
        st.markdown("**调查问题完成情况**")
        q_rows = []
        for q in inv_qs:
            findings = q.get("findings", [])
            q_rows.append({
                "问题": f"{q.get('qid', '')}: {q.get('text', '')[:20]}",
                "状态": _QS.get(q.get("status", ""), q.get("status", "")),
                "关键发现": (findings[-1][:40] if findings else (q.get("reason_if_unanswered", "") or "—")[:40]),
                "人工核查": "是" if q.get("needs_manual_check") else "否",
            })
        st.dataframe(pd.DataFrame(q_rows), use_container_width=True, hide_index=True)


def render_investigation_audit(output_dir: Path) -> None:
    """读取 investigation 输出，按产品化顺序展示结果。"""
    state_path = output_dir / "investigation_state.json"
    report_path = output_dir / "investigation_report.md"
    case_memory_path = output_dir / "case_memory.json"

    if not state_path.exists():
        st.info("该目录下暂无调查结果。")
        return

    try:
        state_doc = read_json(state_path)
    except Exception as exc:
        st.error(f"读取 investigation_state.json 失败：{exc}")
        return

    # ── 1. 最终调查结论卡片（executive_summary 优先）──
    es = state_doc.get("executive_summary")
    fc = state_doc.get("final_conclusion")
    if es and isinstance(es, dict) and es.get("one_sentence_conclusion"):
        st.markdown("#### 调查结论")
        col1, col2, col3 = st.columns(3)
        col1.metric("调查状态", es.get("status_label_zh", "—"))
        col2.metric("置信度", es.get("confidence_label_zh", "—"))
        col3.metric("主要问题", es.get("main_problem_type", "—"))
        st.info(es.get("one_sentence_conclusion", ""))
        if es.get("key_findings"):
            st.markdown("**关键发现：**")
            for f in es["key_findings"]:
                st.markdown(f"- {f}")
        if es.get("unresolved_items"):
            st.markdown("**仍不确定：**")
            for u in es["unresolved_items"]:
                st.markdown(f"- {u}")
        if es.get("next_manual_checks"):
            with st.expander("下一步人工核查建议"):
                for c in es["next_manual_checks"]:
                    st.markdown(f"- {c}")
        if es.get("coverage_summary"):
            st.caption(f"覆盖情况：{es['coverage_summary']}")
        if es.get("recommendation_for_user"):
            st.caption(f"建议：{es['recommendation_for_user']}")
    elif fc and isinstance(fc, dict):
        _CONV = {"converged": "已收敛", "partially_converged": "部分收敛", "not_converged": "未收敛"}
        st.markdown("#### 调查结论")
        col1, col2 = st.columns(2)
        col1.metric("收敛状态", _CONV.get(fc.get("convergence_status", ""), "—"))
        col2.metric("置信度", fc.get("confidence_label", "—"))
        st.info(fc.get("primary_conclusion_zh", ""))

    # ── 2. 调查计划执行情况 ──
    inv_plan = state_doc.get("investigation_plan")
    if inv_plan and isinstance(inv_plan, dict):
        plan_items = inv_plan.get("plan_items", [])
        if plan_items:
            _PLAN_ZH = {"P1": "P1 停机验证", "P2": "P2 掘进阻力验证", "P3": "P3 液压验证", "P4": "P4 碎片化验证"}
            _PS_ZH = {"pending": "待执行", "in_progress": "进行中",
                      "completed": "已完成", "skipped_due_to_budget": "轮数不足跳过"}
            st.markdown("#### 调查计划执行情况")
            plan_rows = []
            for item in plan_items:
                pid = item.get("plan_id", "")
                plan_rows.append({
                    "计划": _PLAN_ZH.get(pid, pid),
                    "要回答的问题": item.get("question", "")[:30],
                    "状态": _PS_ZH.get(item.get("status", ""), item.get("status", "")),
                    "已用工具": ", ".join(item.get("required_tools", [])),
                })
            st.dataframe(pd.DataFrame(plan_rows), use_container_width=True, hide_index=True)
            budget_warning = inv_plan.get("budget_warning", "")
            if budget_warning:
                st.warning(budget_warning)

    # ── 3. 技术审计（默认折叠）──
    with st.expander("技术审计（ReAct 轨迹、LLM 明细、Evidence Gate）"):
        _render_technical_audit(state_doc)

    # 报告预览
    if report_path.exists():
        st.markdown("#### 报告预览")
        with st.expander("展开查看调查报告"):
            st.markdown(read_markdown_text(report_path))
        render_download(report_path, "下载调查报告", "text/markdown")

    # 案例记忆
    if case_memory_path.exists():
        try:
            cases = read_json(case_memory_path)
            if cases:
                st.markdown("#### 停机案例摘要")
                st.dataframe(build_case_display_table(cases), use_container_width=True, hide_index=True)
        except Exception:
            pass

    st.caption(f"输出目录：`{output_dir}`")


def render_project_intro_tab() -> None:
    st.subheader("演示路线")
    st.markdown(
        "1. 单文件诊断：先看一个文件有没有异常\n"
        "2. 批量扫描：再从大量文件中筛出高风险文件\n"
        "3. 智能复核：对重点文件进行分诊和证据摘要\n"
        "4. ReAct 调查：对高风险文件进行真正的动态工具调用调查"
    )

    st.subheader("处理链路")
    st.markdown(
        "CSV/XLS 文件\n"
        "→ 单文件诊断\n"
        "→ 批量扫描\n"
        "→ 智能复核（分诊）\n"
        "→ ReAct 调查（动态工具调用）\n"
        "→ 工程师可读报告"
    )

    st.info("该页面是本地演示入口，用于现场演示已有命令行能力，不是生产平台。")


def render_detect_tab() -> None:
    st.subheader("单文件诊断")
    st.markdown("这一部分用于分析单个 CSV/XLS 文件，快速判断文件中是否存在异常事件，并生成报告。")

    uploaded_file = st.file_uploader("上传 CSV / XLS / XLSX 文件", type=["csv", "xls", "xlsx"])
    default_path = ROOT / "incoming" / "anomaly_segment.csv"
    path_text = st.text_input(
        "或输入本地文件路径",
        value=str(default_path if default_path.exists() else ""),
    )

    selected_path = normalize_path(path_text)
    if uploaded_file is not None:
        selected_path = save_uploaded_file(uploaded_file)
        st.success(f"已保存上传文件：{selected_path}")

    if selected_path:
        st.caption(f"当前文件：`{selected_path}`")

    if st.button("运行单文件诊断", type="primary", use_container_width=True):
        if not selected_path or not selected_path.exists():
            st.error("请输入有效的文件路径，或先上传文件。")
            return
        if selected_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            st.error("仅支持 CSV、XLS 和 XLSX 文件。")
            return

        output_dir = TMP_OUTPUT_DIR / f"detect_{uuid.uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=True)
        result_json = output_dir / "result.json"
        report_md = output_dir / "report.md"
        events_csv = output_dir / "events.csv"

        result = run_cli(
            [
                "detect",
                "--input",
                str(selected_path),
                "--save-json",
                str(result_json),
                "--save-report",
                str(report_md),
                "--save-events-csv",
                str(events_csv),
            ],
            "正在运行单文件诊断，请稍候",
        )
        render_cli_output(result)

        if result["returncode"] != 0:
            st.error("运行状态：失败。请展开查看命令行输出。")
            return
        if not result_json.exists():
            st.error("运行状态：失败。命令执行完成，但没有找到结果文件。")
            return

        result_doc = read_json(result_json)
        explanations = result_doc.get("explanations", [])
        event_total = len(result_doc.get("events", []))
        highest_risk = explanations[0]["severity_label"] if explanations else "未发现明显异常"

        st.success("运行状态：成功")
        col1, col2 = st.columns(2)
        col1.metric("异常事件数", event_total)
        col2.metric("最高风险等级", highest_risk)

        st.markdown("**前 3 个事件**")
        event_rows = build_detect_event_rows(result_doc)
        if event_rows:
            st.dataframe(pd.DataFrame(event_rows), use_container_width=True, hide_index=True)
        else:
            st.info("当前文件未发现明显异常事件。")

        if report_md.exists():
            st.markdown("**报告预览**")
            st.markdown(read_markdown_text(report_md))

        cols = st.columns(3)
        with cols[0]:
            render_download(result_json, "下载 JSON 结果", "application/json")
        with cols[1]:
            render_download(report_md, "下载 Markdown 报告", "text/markdown")
        with cols[2]:
            render_download(events_csv, "下载事件表 CSV", "text/csv")


def render_scan_tab() -> None:
    st.subheader("批量扫描")
    st.markdown("这一部分用于处理一个目录下的大量文件，先用规则诊断快速筛选出最值得关注的高风险文件。")

    default_input_dir = ROOT / "incoming"
    input_dir_text = st.text_input(
        "输入目录路径",
        value=str(default_input_dir if default_input_dir.exists() else ROOT),
    )
    output_dir_text = st.text_input("输入输出目录路径", value=str(SCAN_DEMO_DIR))
    file_size_limit = st.number_input("输入单文件大小上限（MB）", min_value=1, max_value=500, value=20, step=1)
    scan_index_text = st.text_input(
        "或填写已有 scan_index.csv 路径",
        value=str((ROOT / "scan_real_out" / "scan_index.csv") if (ROOT / "scan_real_out" / "scan_index.csv").exists() else ""),
    )

    if st.button("运行批量扫描", type="primary", use_container_width=True):
        input_dir = normalize_path(input_dir_text)
        output_dir = normalize_path(output_dir_text)
        if not input_dir or not input_dir.exists() or not input_dir.is_dir():
            st.error("请输入有效的输入目录路径。")
            return
        if not output_dir:
            st.error("请输入有效的输出目录路径。")
            return
        output_dir.mkdir(parents=True, exist_ok=True)

        result = run_cli(
            [
                "scan",
                "--input-dir",
                str(input_dir),
                "--output-dir",
                str(output_dir),
                "--max-file-size-mb",
                str(int(file_size_limit)),
            ],
            "正在运行批量扫描，请稍候",
        )
        render_cli_output(result)

        if result["returncode"] != 0:
            st.error("运行状态：失败。请展开查看命令行输出。")
            return

        index_path = output_dir / "scan_index.csv"
        if not index_path.exists():
            st.error("运行状态：失败。命令执行完成，但没有找到 scan_index.csv。")
            return

        st.session_state["latest_scan_index"] = str(index_path)
        st.success(f"运行状态：成功。已生成扫描索引：{index_path}")

    index_path = choose_scan_index(scan_index_text)
    if not index_path:
        st.info("请先运行批量扫描，或填写已有的 scan_index.csv 路径。")
        return

    st.caption(f"当前扫描索引：`{index_path}`")
    try:
        df = read_csv_table(index_path)
    except Exception as exc:
        st.error(f"读取 scan_index.csv 失败：{exc}")
        return

    ranked_df = df.sort_values(by=["risk_rank_score", "event_count"], ascending=[False, False], kind="stable")
    st.session_state["latest_scan_index"] = str(index_path)
    st.session_state["latest_scan_df"] = ranked_df

    summary = summarize_scan(ranked_df)
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("文件总数", summary["file_total"])
    col2.metric("成功数量", summary["ok_total"])
    col3.metric("跳过数量", summary["skipped_total"])
    col4.metric("失败数量", summary["failed_total"])
    col5.metric("高风险文件数量", summary["high_risk_total"])

    st.markdown("**高风险文件前 10 名**")
    st.dataframe(build_scan_display_table(ranked_df), use_container_width=True, hide_index=True)

    report_options = [
        str(item)
        for item in ranked_df.get("md_path", pd.Series(dtype="object")).dropna().tolist()
        if str(item).strip()
    ]
    if report_options:
        selected_report = st.selectbox("选择报告路径进行预览", report_options)
        report_path = normalize_path(selected_report)
        if report_path and report_path.exists():
            st.markdown("**报告预览**")
            st.markdown(read_markdown_text(report_path))


def render_review_tab() -> None:
    st.subheader("智能复核")
    st.markdown("这一部分不会对所有文件都调用大模型，而是只对批量扫描筛出的重点文件进行 AI 复核，降低成本并提高可读性。")

    default_scan_index = choose_scan_index()
    scan_index_text = st.text_input(
        "输入 scan_index.csv 路径",
        value=str(default_scan_index) if default_scan_index else "",
    )
    output_dir_text = st.text_input("输入输出目录", value=str(REVIEW_DEMO_DIR))
    top_n = st.number_input("输入复核文件数量", min_value=1, max_value=20, value=3, step=1)

    if not has_openai_compatible_config():
        st.warning("未检测到大模型 API Key，无法运行智能复核。请检查 .env 中的 OPENAI_API_KEY 和 OPENAI_BASE_URL。")

    if st.button("运行智能复核", type="primary", use_container_width=True):
        scan_index = normalize_path(scan_index_text)
        output_dir = normalize_path(output_dir_text)
        if not scan_index or not scan_index.exists():
            st.error("请输入有效的 scan_index.csv 路径。")
            return
        if not output_dir:
            st.error("请输入有效的输出目录。")
            return
        if not has_openai_compatible_config():
            st.error("未检测到大模型 API Key，无法运行智能复核。请检查 .env 中的 OPENAI_API_KEY 和 OPENAI_BASE_URL。")
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        result = run_cli(
            [
                "review",
                "--scan-index",
                str(scan_index),
                "--output-dir",
                str(output_dir),
                "--top-n",
                str(int(top_n)),
                "--overwrite",
            ],
            "正在运行智能复核，请稍候",
        )
        render_cli_output(result)

        if result["returncode"] != 0:
            st.error("运行状态：失败。请展开查看命令行输出。")
            return

        st.session_state["latest_review_dir"] = str(output_dir)
        st.success(f"运行状态：成功。已生成复核结果：{output_dir}")

    review_dir = normalize_path(st.session_state.get("latest_review_dir")) or REVIEW_DEMO_DIR
    summary_md = review_dir / "review_summary.md"
    summary_json = review_dir / "review_summary.json"

    if not summary_json.exists():
        if summary_md.exists():
            st.markdown("**复核报告预览**")
            st.markdown(read_markdown_text(summary_md))
        else:
            st.info("当前还没有可预览的智能复核报告。")
        return

    try:
        summary_doc = read_json(summary_json)
    except Exception as exc:
        st.error(f"读取 review_summary.json 失败：{exc}")
        return

    file_results = summary_doc.get("file_results", [])
    if not file_results:
        st.info("当前还没有可预览的智能复核报告。")
        return

    # LLM 状态汇总
    llm_count = sum(1 for f in file_results if f.get("summary_source") == "llm")
    fb_count = sum(1 for f in file_results if f.get("summary_source") == "fallback")
    col1, col2, col3 = st.columns(3)
    col1.metric("LLM 成功", f"{llm_count} 个")
    col2.metric("规则降级", f"{fb_count} 个")
    col3.metric("文件总数", f"{len(file_results)} 个")

    # 工具调用摘要
    tool_names_used = set()
    for fr in file_results:
        for tt in fr.get("tool_traces", []):
            tool_names_used.add(tt.get("tool_name", ""))
    if tool_names_used:
        _TOOL_ZH = {
            "scan_index_reader": "扫描索引读取",
            "semantic_event_summary": "语义事件统计",
            "state_distribution": "工况分布统计",
            "top_events_summary": "Top 事件提取",
            "stoppage_time_pattern": "停机时间模式分析",
            "llm_summary": "AI 总结生成",
        }
        tool_labels = [_TOOL_ZH.get(t, t) for t in sorted(tool_names_used) if t]
        st.caption(f"本次复核调用工具：{'、'.join(tool_labels)}")

    # 每个文件的详细结果
    st.markdown("**重点文件复核结论**")
    st.dataframe(build_review_display_table(file_results), use_container_width=True, hide_index=True)

    for fr in file_results:
        fname = fr.get("file_name", "")
        with st.expander(f"{fname} — 工具证据链与详情"):
            _SRC = {"llm": "LLM 成功", "fallback": "规则降级", "none": "未生成"}
            src = _SRC.get(fr.get("summary_source", ""), fr.get("summary_source", ""))
            st.markdown(f"- 规则复核流程：{'成功' if fr.get('status') == 'ok' else '失败'}")
            st.markdown(f"- LLM 总结状态：{src}")
            st.markdown(f"- 工具证据链：见下方")

            traces = fr.get("tool_traces", [])
            if traces:
                trace_rows = []
                for tt in traces:
                    trace_rows.append({
                        "工具": tt.get("tool_name", ""),
                        "作用": tt.get("purpose_zh", ""),
                        "关键输出": (tt.get("output_summary", "") or "")[:60],
                        "证据编号": ", ".join(tt.get("evidence_ids", [])),
                    })
                st.dataframe(pd.DataFrame(trace_rows), use_container_width=True, hide_index=True)

            evidence = fr.get("evidence_items", [])
            if evidence:
                ev_rows = []
                for ei in evidence:
                    ev_rows.append({
                        "编号": ei.get("evidence_id", ""),
                        "标题": ei.get("title", ""),
                        "解读": (ei.get("interpretation", "") or "")[:80],
                        "可靠性": ei.get("reliability", ""),
                    })
                st.dataframe(pd.DataFrame(ev_rows), use_container_width=True, hide_index=True)

            # 建议进一步调查
            suggestions = fr.get("investigation_suggestions", [])
            if suggestions:
                st.markdown("**建议进一步调查的问题**")
                for s in suggestions:
                    st.markdown(f"- {s.get('text', '')}")
                    st.code(s.get("command", ""), language="bash")

                st.markdown("**一键运行 ReAct 调查**")
                btn_cols = st.columns(len(suggestions))
                for idx_s, s in enumerate(suggestions):
                    mode = _parse_mode_from_command(s.get("command", ""))
                    input_file = _parse_input_from_command(s.get("command", ""))
                    if not input_file or mode == "auto":
                        continue
                    btn_label = f"运行{_MODE_LABELS.get(mode, mode)}"
                    safe_stem = Path(input_file).stem.replace(" ", "_")
                    inv_out = INVESTIGATION_DEMO_DIR / f"{safe_stem}_{mode}"
                    btn_key = f"inv_{fname}_{mode}"
                    with btn_cols[idx_s]:
                        if st.button(btn_label, key=btn_key, use_container_width=True):
                            inv_out.mkdir(parents=True, exist_ok=True)
                            inv_result = run_cli(
                                [
                                    "investigate",
                                    "--input", input_file,
                                    "--mode", mode,
                                    "--output-dir", str(inv_out),
                                    "--max-iterations", "12",
                                    "--planner-audit",
                                ],
                                f"正在运行{_MODE_LABELS.get(mode, mode)}，请稍候",
                            )
                            render_cli_output(inv_result)
                            if inv_result["returncode"] == 0:
                                st.success(f"{_MODE_LABELS.get(mode, mode)}完成")
                                render_investigation_audit(inv_out)
                            else:
                                st.error("调查运行失败，请展开查看命令行输出。")

    st.caption("以上是分诊推荐。点击上方对应按钮或手动运行命令后，才能看到真正 ReAct 调查轨迹。")

    # 跨文件分析
    cross = summary_doc.get("cross_file_analysis", {})
    if cross.get("composite_judgment"):
        st.markdown("**跨文件综合判断**")
        st.info(cross["composite_judgment"])

    if summary_md.exists():
        st.markdown("**完整复核报告预览**")
        with st.expander("展开查看 Markdown 报告"):
            st.markdown(read_markdown_text(summary_md))
        render_download(summary_md, "下载复核 Markdown 报告", "text/markdown")


def render_investigation_tab() -> None:
    st.subheader("ReAct 调查")
    st.markdown("选择调查档位后点击运行，系统会自动选择调查路径并生成结论报告。")

    latest_scan_df = st.session_state.get("latest_scan_df")
    select_options: list[str] = []
    if isinstance(latest_scan_df, pd.DataFrame) and "file_path" in latest_scan_df.columns:
        select_options = [str(item) for item in latest_scan_df["file_path"].dropna().head(10).tolist()]

    selected_file = st.selectbox("可直接从高风险文件中选择", [""] + select_options)
    default_path = ROOT / "sample2.xls"
    input_path_text = st.text_input(
        "输入本地文件路径",
        value=selected_file or str(default_path if default_path.exists() else ""),
    )
    output_dir_text = st.text_input("输入输出目录", value=str(INVESTIGATION_DEMO_DIR))

    # ── 三档主入口 ──
    _PRESETS = {
        "快速初筛": {"mode": "auto", "planner": "rule", "max_iterations": 12,
                     "desc": "稳定、便宜、适合快速看一眼"},
        "标准调查（推荐）": {"mode": "auto", "planner": "hybrid", "max_iterations": 20,
                           "desc": "推荐默认，兼顾稳定和智能"},
        "深度复核": {"mode": "auto", "planner": "llm", "max_iterations": 40,
                     "desc": "调用更多 LLM，速度较慢，适合深入调查"},
    }
    preset_label = st.radio("调查档位", list(_PRESETS.keys()), index=1, horizontal=True,
                            help="选择调查深度，高级设置可覆盖")
    preset = _PRESETS[preset_label]
    st.caption(preset["desc"])

    focus_mode = preset["mode"]
    planner_mode = preset["planner"]
    max_iterations = preset["max_iterations"]
    planner_audit = True

    # ── 高级设置（默认折叠）──
    with st.expander("高级设置（开发者/调试用）"):
        adv_mode = st.selectbox("调查聚焦模式", ["auto", "stoppage", "resistance", "hydraulic", "fragmentation"],
                                help="auto=自动选择 | 其他=专项调查")
        adv_planner = st.selectbox("Planner 模式", ["rule", "llm", "hybrid"],
                                   help="rule=纯规则 | llm=每轮调LLM | hybrid=混合")
        adv_iter = st.number_input("自定义轮数", min_value=1, max_value=50,
                                   value=preset["max_iterations"], step=1)
        adv_audit = st.checkbox("启用 planner 审计日志", value=True)
        if adv_mode != "auto" or adv_planner != preset["planner"] or adv_iter != preset["max_iterations"] or not adv_audit:
            focus_mode = adv_mode
            planner_mode = adv_planner
            max_iterations = adv_iter
            planner_audit = adv_audit
            st.info(f"高级设置已覆盖：mode={focus_mode}, planner={planner_mode}, iterations={max_iterations}")

    if planner_mode in ("llm", "hybrid") and not has_openai_compatible_config():
        st.warning("未检测到 API Key，LLM planner 无法运行，将 fallback 到 rule。请检查 .env。")

    if st.button("运行 ReAct 调查", type="primary", use_container_width=True):
        input_path = normalize_path(selected_file or input_path_text)
        output_dir = normalize_path(output_dir_text)
        if not input_path or not input_path.exists():
            st.error("请输入有效的本地文件路径。")
            return
        if not output_dir:
            st.error("请输入有效的输出目录。")
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        cli_parts = [
            "investigate",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--mode",
            focus_mode,
            "--planner",
            planner_mode,
            "--max-iterations",
            str(int(max_iterations)),
        ]
        if planner_audit:
            cli_parts.append("--planner-audit")
        result = run_cli(cli_parts, "正在运行 ReAct 调查，请稍候")
        render_cli_output(result)

        if result["returncode"] != 0:
            st.error("运行状态：失败。请展开查看命令行输出。")
            return

        st.session_state["latest_investigation_dir"] = str(output_dir)
        st.success(f"运行状态：成功。已生成调查结果：{output_dir}")

    investigation_dir = normalize_path(st.session_state.get("latest_investigation_dir")) or INVESTIGATION_DEMO_DIR

    if (investigation_dir / "investigation_state.json").exists():
        render_investigation_audit(investigation_dir)
    elif (investigation_dir / "investigation_report.md").exists():
        st.markdown("**调查报告预览**")
        st.markdown(read_markdown_text(investigation_dir / "investigation_report.md"))
        render_download(investigation_dir / "investigation_report.md", "下载调查 Markdown 报告", "text/markdown")
    else:
        st.info("当前还没有可预览的调查报告。")


def main() -> None:
    ensure_demo_directories()
    st.set_page_config(page_title="盾构/TBM CSV 智能诊断 Agent 演示系统", page_icon="盾", layout="wide")
    st.title("盾构/TBM CSV 智能诊断 Agent 演示系统")
    st.markdown("本系统面向现场系统只能导出 CSV/XLS 文件的情况，通过规则诊断、批量扫描、AI 复核和 ReAct 停机追查，把大量原始数据转换为可人工核查的工程事件和停机案例。")

    tabs = st.tabs(["项目说明", "单文件诊断", "批量扫描", "智能复核", "ReAct 调查"])
    with tabs[0]:
        render_project_intro_tab()
    with tabs[1]:
        render_detect_tab()
    with tabs[2]:
        render_scan_tab()
    with tabs[3]:
        render_review_tab()
    with tabs[4]:
        render_investigation_tab()


if __name__ == "__main__":
    main()
