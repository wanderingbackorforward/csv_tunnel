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


def render_project_intro_tab() -> None:
    st.subheader("演示路线")
    st.markdown(
        "1. 单文件诊断：先看一个文件有没有异常\n"
        "2. 批量扫描：再从大量文件中筛出高风险文件\n"
        "3. 智能复核：对重点文件调用大模型进行总结\n"
        "4. 停机追查：把大量碎片事件合并成少数停机案例"
    )

    st.subheader("处理链路")
    st.markdown(
        "CSV/XLS 文件\n"
        "→ 单文件诊断\n"
        "→ 批量扫描\n"
        "→ 智能复核\n"
        "→ ReAct 停机追查\n"
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
    st.subheader("停机追查")
    st.markdown("这一部分用于进一步追查高风险文件。系统会把碎片化停机事件合并成停机案例，并检查停机前后是否存在掘进阻力、液压波动或重载推进等异常迹象。")

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
    max_iterations = st.number_input("输入最大轮数", min_value=1, max_value=50, value=12, step=1)

    if st.button("运行停机追查", type="primary", use_container_width=True):
        input_path = normalize_path(selected_file or input_path_text)
        output_dir = normalize_path(output_dir_text)
        if not input_path or not input_path.exists():
            st.error("请输入有效的本地文件路径。")
            return
        if not output_dir:
            st.error("请输入有效的输出目录。")
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        result = run_cli(
            [
                "investigate",
                "--input",
                str(input_path),
                "--output-dir",
                str(output_dir),
                "--max-iterations",
                str(int(max_iterations)),
            ],
            "正在运行停机追查，请稍候",
        )
        render_cli_output(result)

        if result["returncode"] != 0:
            st.error("运行状态：失败。请展开查看命令行输出。")
            return

        st.session_state["latest_investigation_dir"] = str(output_dir)
        st.success(f"运行状态：成功。已生成停机追查结果：{output_dir}")

    investigation_dir = normalize_path(st.session_state.get("latest_investigation_dir")) or INVESTIGATION_DEMO_DIR
    report_path = investigation_dir / "investigation_report.md"
    case_memory_path = investigation_dir / "case_memory.json"

    if report_path.exists():
        st.markdown("**停机追查报告预览**")
        st.markdown(read_markdown_text(report_path))
        render_download(report_path, "下载停机追查 Markdown 报告", "text/markdown")
    else:
        st.info("当前还没有可预览的停机追查报告。")

    if not case_memory_path.exists():
        st.info("未发现明显停机追查目标。")
        return

    try:
        cases = read_json(case_memory_path)
    except Exception as exc:
        st.error(f"读取 case_memory.json 失败：{exc}")
        return

    if not cases:
        st.info("未发现明显停机追查目标。")
        return

    st.markdown("**停机案例摘要**")
    st.dataframe(build_case_display_table(cases), use_container_width=True, hide_index=True)
    render_download(case_memory_path, "下载停机案例 JSON", "application/json")


def main() -> None:
    ensure_demo_directories()
    st.set_page_config(page_title="盾构/TBM CSV 智能诊断 Agent 演示系统", page_icon="盾", layout="wide")
    st.title("盾构/TBM CSV 智能诊断 Agent 演示系统")
    st.markdown("本系统面向现场系统只能导出 CSV/XLS 文件的情况，通过规则诊断、批量扫描、AI 复核和 ReAct 停机追查，把大量原始数据转换为可人工核查的工程事件和停机案例。")

    tabs = st.tabs(["项目说明", "单文件诊断", "批量扫描", "智能复核", "停机追查"])
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
