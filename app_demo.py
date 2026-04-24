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


ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
TMP_UPLOAD_DIR = ROOT / "tmp_demo_uploads"
TMP_OUTPUT_DIR = ROOT / "tmp_demo_outputs"
SCAN_DEMO_DIR = ROOT / "scan_demo_out"
REVIEW_DEMO_DIR = ROOT / "review_demo_out"
INVESTIGATION_DEMO_DIR = ROOT / "investigation_demo_out"
SUPPORTED_EXTS = {".csv", ".xls", ".xlsx"}


def ensure_demo_dirs() -> None:
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


def quote_cmd(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def run_cli(parts: list[str], label: str) -> dict[str, Any]:
    cmd = [PYTHON, "-m", "tbm_diag.cli", *parts]
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    with st.spinner(f"{label}..."):
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def render_cli_output(result: dict[str, Any], title: str = "CLI 输出") -> None:
    with st.expander(title, expanded=False):
        st.code(quote_cmd(result["cmd"]), language="bash")
        stdout = result.get("stdout") or "(stdout empty)"
        stderr = result.get("stderr") or "(stderr empty)"
        st.caption("stdout")
        st.code(stdout, language="text")
        st.caption("stderr")
        st.code(stderr, language="text")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def try_read_markdown(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig", errors="replace")


def safe_read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="utf-8", engine="python")


def detect_top_events(doc: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    explanations = doc.get("explanations", [])
    if explanations:
        return explanations[:limit]
    events = doc.get("events", [])
    return events[:limit]


def render_download(path: Path, label: str, mime: str) -> None:
    if not path.exists():
        st.caption(f"{label} 未生成")
        return
    st.download_button(
        label=label,
        data=path.read_bytes(),
        file_name=path.name,
        mime=mime,
        use_container_width=True,
    )


def build_scan_summary(df: pd.DataFrame) -> dict[str, int]:
    status = df.get("status", pd.Series(dtype="object")).fillna("")
    return {
        "total": int(len(df)),
        "ok": int((status == "ok").sum()),
        "skipped": int((status == "skipped").sum()),
        "failed": int((status == "error").sum()),
    }


def select_scan_table(df: pd.DataFrame) -> pd.DataFrame:
    wanted = [
        "file_name",
        "event_count",
        "max_severity_label",
        "risk_rank_score",
        "top_event_type",
        "top_event_summary",
        "md_path",
    ]
    cols = [col for col in wanted if col in df.columns]
    if not cols:
        return df
    ranked = df.sort_values(
        by=["risk_rank_score", "event_count"],
        ascending=[False, False],
        kind="stable",
    )
    return ranked[cols].head(10)


def resolve_demo_scan_index(preferred: str = "") -> Path | None:
    for candidate in [
        normalize_path(preferred),
        normalize_path(st.session_state.get("latest_scan_index")),
        ROOT / "scan_real_out" / "scan_index.csv",
        SCAN_DEMO_DIR / "scan_index.csv",
    ]:
        if candidate and candidate.exists():
            return candidate
    return None


def render_intro_tab() -> None:
    st.subheader("项目定位")
    st.markdown("**基于 CSV/XLS 输入的盾构/TBM 智能诊断 Agent 原型**")
    st.markdown(
        "现场系统只能导出 CSV/XLS，本工具作为外挂式分析层，自动完成诊断、筛选、AI 复核和停机追查。"
    )

    st.subheader("演示路线")
    st.markdown(
        "1. 单文件诊断：看一个文件是否异常\n"
        "2. 批量扫描：从大量文件中筛出高风险文件\n"
        "3. AI 复核：对重点文件做大模型总结\n"
        "4. 停机追查：把大量碎事件归并成少数停机案例"
    )

    st.subheader("简单架构")
    st.code("CSV/XLS  ->  detect  ->  scan  ->  review / agent  ->  investigate", language="text")

    st.info(
        "这个页面是本地演示入口，不重写诊断算法。所有关键动作都优先通过 CLI 执行，确保网页结果和命令行一致。"
    )


def render_detect_tab() -> None:
    st.subheader("单文件诊断")
    st.caption("这一层解决的是：一个文件里有没有明显异常，以及异常证据是什么。")

    uploaded = st.file_uploader(
        "上传 CSV / XLS / XLSX 文件",
        type=["csv", "xls", "xlsx"],
        key="detect_upload",
    )
    default_detect = ROOT / "incoming" / "anomaly_segment.csv"
    detect_path_text = st.text_input(
        "或直接填写本地文件路径",
        value=str(default_detect if default_detect.exists() else ""),
        key="detect_path_text",
    )

    chosen_path = normalize_path(detect_path_text)
    if uploaded is not None:
        chosen_path = save_uploaded_file(uploaded)
        st.success(f"已保存上传文件：{chosen_path}")

    if chosen_path:
        st.caption(f"当前输入文件：`{chosen_path}`")

    if st.button("运行单文件诊断", type="primary", use_container_width=True):
        if not chosen_path or not chosen_path.exists():
            st.error("请先上传文件或填写有效路径。")
            return
        if chosen_path.suffix.lower() not in SUPPORTED_EXTS:
            st.error("仅支持 CSV / XLS / XLSX。")
            return

        run_dir = TMP_OUTPUT_DIR / f"detect_{uuid.uuid4().hex[:8]}"
        run_dir.mkdir(parents=True, exist_ok=True)
        result_json = run_dir / "result.json"
        report_md = run_dir / "report.md"
        events_csv = run_dir / "events.csv"

        result = run_cli(
            [
                "detect",
                "--input",
                str(chosen_path),
                "--save-json",
                str(result_json),
                "--save-report",
                str(report_md),
                "--save-events-csv",
                str(events_csv),
            ],
            "运行单文件诊断",
        )
        render_cli_output(result)

        if result["returncode"] != 0:
            st.error("单文件诊断失败。请展开查看 CLI 输出。")
            return

        if not result_json.exists():
            st.error("CLI 执行成功，但未找到 result.json。")
            return

        doc = read_json(result_json)
        events = doc.get("events", [])
        explanations = doc.get("explanations", [])
        highest = explanations[0]["severity_label"] if explanations else "未发现异常"

        st.success("单文件诊断完成。")
        c1, c2 = st.columns(2)
        c1.metric("事件总数", len(events))
        c2.metric("最高风险等级", highest)

        st.markdown("**Top 3 事件摘要**")
        top_events = detect_top_events(doc, limit=3)
        if not top_events:
            st.info("未发现异常事件。")
        else:
            for idx, item in enumerate(top_events, start=1):
                title = item.get("title") or item.get("event_type") or item.get("event_id") or f"事件 {idx}"
                summary = item.get("summary") or "无摘要"
                severity = item.get("severity_label") or "未标注"
                st.markdown(f"{idx}. **{title}** [{severity}]")
                st.caption(summary)

        if report_md.exists():
            st.markdown("**Markdown 报告预览**")
            st.markdown(try_read_markdown(report_md))

        cols = st.columns(3)
        with cols[0]:
            render_download(result_json, "下载 result.json", "application/json")
        with cols[1]:
            render_download(report_md, "下载 report.md", "text/markdown")
        with cols[2]:
            render_download(events_csv, "下载 events.csv", "text/csv")


def render_scan_tab() -> None:
    st.subheader("批量扫描")
    st.caption("这一层解决的是：当文件很多时，先用规则内核快速普查，筛出最值得看的文件。")

    default_input_dir = ROOT / "incoming"
    input_dir_text = st.text_input(
        "输入目录 input_dir",
        value=str(default_input_dir if default_input_dir.exists() else ROOT),
        key="scan_input_dir",
    )
    output_dir_text = st.text_input(
        "输出目录 output_dir",
        value=str(SCAN_DEMO_DIR),
        key="scan_output_dir",
    )
    existing_index_text = st.text_input(
        "或直接填写已有 scan_index.csv 路径",
        value=str((ROOT / "scan_real_out" / "scan_index.csv") if (ROOT / "scan_real_out" / "scan_index.csv").exists() else ""),
        key="existing_scan_index",
    )

    if st.button("运行批量扫描", type="primary", use_container_width=True):
        input_dir = normalize_path(input_dir_text)
        output_dir = normalize_path(output_dir_text)
        if not input_dir or not input_dir.exists() or not input_dir.is_dir():
            st.error("请输入有效的输入目录。")
            return
        if not output_dir:
            st.error("请输入有效的输出目录。")
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
                "20",
            ],
            "运行批量扫描",
        )
        render_cli_output(result)
        if result["returncode"] != 0:
            st.error("批量扫描失败。请展开查看 CLI 输出。")
            return
        index_path = output_dir / "scan_index.csv"
        if not index_path.exists():
            st.error("批量扫描完成，但未找到 scan_index.csv。")
            return
        st.session_state["latest_scan_index"] = str(index_path)
        st.success(f"批量扫描完成：{index_path}")

    index_path = resolve_demo_scan_index(existing_index_text)
    if not index_path:
        st.info("请先运行批量扫描，或指定一个已有的 scan_index.csv。")
        return

    st.caption(f"当前 scan_index：`{index_path}`")
    try:
        df = safe_read_csv(index_path)
    except Exception as exc:
        st.error(f"读取 scan_index.csv 失败：{exc}")
        return

    st.session_state["latest_scan_index"] = str(index_path)
    st.session_state["latest_scan_df"] = df
    summary = build_scan_summary(df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总文件数", summary["total"])
    c2.metric("成功", summary["ok"])
    c3.metric("跳过", summary["skipped"])
    c4.metric("失败", summary["failed"])

    st.markdown("**Top 10 高风险文件**")
    top_df = select_scan_table(df)
    st.dataframe(top_df, use_container_width=True, hide_index=True)

    md_candidates = [
        str(path)
        for path in df.get("md_path", pd.Series(dtype="object")).dropna().tolist()
        if str(path).strip()
    ]
    if md_candidates:
        selected_md = st.selectbox("选择报告预览", md_candidates, key="scan_md_preview")
        md_path = normalize_path(selected_md)
        if md_path and md_path.exists():
            st.markdown("**报告预览**")
            st.markdown(try_read_markdown(md_path))


def render_review_tab() -> None:
    st.subheader("AI 复核")
    st.caption("这一层解决的是：不对所有文件都调用大模型，而是只对 scan 筛出的重点文件做 AI 复核。")

    suggested_index = resolve_demo_scan_index()
    scan_index_text = st.text_input(
        "scan_index.csv 路径",
        value=str(suggested_index) if suggested_index else "",
        key="review_scan_index",
    )
    output_dir_text = st.text_input(
        "输出目录 output_dir",
        value=str(REVIEW_DEMO_DIR),
        key="review_output_dir",
    )
    top_n = st.number_input("Top N", min_value=1, max_value=20, value=3, step=1, key="review_top_n")

    if not os.getenv("OPENAI_API_KEY"):
        st.warning("当前未检测到 OPENAI_API_KEY。可以先演示 scan，再说明 AI 复核需要配置模型密钥。")

    if st.button("运行 AI 复核", type="primary", use_container_width=True):
        scan_index = normalize_path(scan_index_text)
        output_dir = normalize_path(output_dir_text)
        if not scan_index or not scan_index.exists():
            st.error("请提供有效的 scan_index.csv 路径。")
            return
        if not output_dir:
            st.error("请输入有效的输出目录。")
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
            "运行 AI 复核",
        )
        render_cli_output(result)
        if result["returncode"] != 0:
            stderr = (result.get("stderr") or "").lower()
            if "openai" in stderr or "api key" in stderr or "authentication" in stderr:
                st.warning("AI 复核调用失败，通常是因为未配置 API Key 或模型服务不可用。")
            else:
                st.error("AI 复核失败。请展开查看 CLI 输出。")
            return

        st.session_state["latest_review_dir"] = str(output_dir)
        st.success(f"AI 复核完成：{output_dir}")

    review_dir = normalize_path(st.session_state.get("latest_review_dir")) or REVIEW_DEMO_DIR
    summary_md = review_dir / "review_summary.md"
    summary_json = review_dir / "review_summary.json"

    if summary_md.exists():
        st.markdown("**review_summary.md**")
        st.markdown(try_read_markdown(summary_md))
        render_download(summary_md, "下载 review_summary.md", "text/markdown")
    elif review_dir.exists():
        st.info("当前目录下还没有 review_summary.md。")

    if summary_json.exists():
        try:
            review_doc = read_json(summary_json)
        except Exception as exc:
            st.warning(f"review_summary.json 读取失败：{exc}")
            return

        records = review_doc.get("file_results") or review_doc.get("records")
        if isinstance(records, list) and records:
            st.markdown("**Top N 文件结论摘要**")
            rows = []
            for item in records:
                rows.append(
                    {
                        "file_name": item.get("file_name", ""),
                        "status": item.get("status", ""),
                        "risk_rank_score": item.get("risk_rank_score", ""),
                        "event_count": item.get("event_count", ""),
                        "max_severity_label": item.get("max_severity_label", ""),
                        "ai_summary": item.get("ai_summary", ""),
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_investigate_tab() -> None:
    st.subheader("ReAct 停机追查")
    st.caption(
        "这一层解决的是：高风险文件里可能有几百个碎事件，ReAct 追查会把它们归并成少数可人工核查的停机案例。"
    )

    latest_scan_df = st.session_state.get("latest_scan_df")
    scan_choices: list[str] = []
    if isinstance(latest_scan_df, pd.DataFrame) and "file_path" in latest_scan_df.columns:
        scan_choices = [
            str(item)
            for item in latest_scan_df.sort_values(
                by=["risk_rank_score", "event_count"],
                ascending=[False, False],
                kind="stable",
            )["file_path"].dropna().head(10).tolist()
        ]

    selected_scan_file = st.selectbox(
        "可直接从批量扫描 Top 文件中选择",
        [""] + scan_choices,
        key="investigation_scan_choice",
    )
    default_file = ROOT / "sample2.xls"
    file_path_text = st.text_input(
        "或直接填写文件路径",
        value=selected_scan_file or str(default_file if default_file.exists() else ""),
        key="investigation_file_path",
    )
    output_dir_text = st.text_input(
        "输出目录 output_dir",
        value=str(INVESTIGATION_DEMO_DIR),
        key="investigation_output_dir",
    )
    max_iterations = st.number_input(
        "max_iterations",
        min_value=1,
        max_value=50,
        value=12,
        step=1,
        key="investigation_iterations",
    )

    if st.button("运行停机案例追查", type="primary", use_container_width=True):
        file_path = normalize_path(selected_scan_file or file_path_text)
        output_dir = normalize_path(output_dir_text)
        if not file_path or not file_path.exists():
            st.error("请提供有效的输入文件路径。")
            return
        if not output_dir:
            st.error("请输入有效的输出目录。")
            return
        output_dir.mkdir(parents=True, exist_ok=True)

        result = run_cli(
            [
                "investigate",
                "--input",
                str(file_path),
                "--output-dir",
                str(output_dir),
                "--max-iterations",
                str(int(max_iterations)),
            ],
            "运行停机案例追查",
        )
        render_cli_output(result)
        if result["returncode"] != 0:
            st.error("停机案例追查失败。请展开查看 CLI 输出。")
            return
        st.session_state["latest_investigation_dir"] = str(output_dir)
        st.success(f"停机案例追查完成：{output_dir}")

    out_dir = normalize_path(st.session_state.get("latest_investigation_dir")) or INVESTIGATION_DEMO_DIR
    report_path = out_dir / "investigation_report.md"
    memory_path = out_dir / "case_memory.json"

    if report_path.exists():
        st.markdown("**investigation_report.md**")
        st.markdown(try_read_markdown(report_path))
        render_download(report_path, "下载 investigation_report.md", "text/markdown")

    if not memory_path.exists():
        if out_dir.exists():
            st.info("未发现明显停机追查目标")
        return

    try:
        cases = read_json(memory_path)
    except Exception as exc:
        st.error(f"读取 case_memory.json 失败：{exc}")
        return

    if not cases:
        st.info("未发现明显停机追查目标")
        return

    st.markdown("**case_memory.json 摘要**")
    rows = []
    for item in cases:
        reasons = item.get("reasons", [])
        if isinstance(reasons, list):
            reason_text = "；".join(str(reason) for reason in reasons[:3])
        else:
            reason_text = str(reasons)
        rows.append(
            {
                "case_id": item.get("case_id", ""),
                "start_time": item.get("start_time", ""),
                "end_time": item.get("end_time", ""),
                "duration_seconds": item.get("duration_seconds", ""),
                "case_type": item.get("case_type", ""),
                "confidence": item.get("confidence", ""),
                "reasons": reason_text,
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    render_download(memory_path, "下载 case_memory.json", "application/json")


def main() -> None:
    ensure_demo_dirs()
    st.set_page_config(page_title="TBM CLI 演示 GUI", page_icon="TBM", layout="wide")
    st.title("TBM CLI 演示 GUI")
    st.caption("本地演示入口：用 Streamlit 包装现有 CLI，适合老师现场点选查看。")

    tabs = st.tabs(
        [
            "项目说明 / 演示路线",
            "单文件诊断",
            "批量扫描",
            "AI 复核",
            "ReAct 停机追查",
        ]
    )

    with tabs[0]:
        render_intro_tab()
    with tabs[1]:
        render_detect_tab()
    with tabs[2]:
        render_scan_tab()
    with tabs[3]:
        render_review_tab()
    with tabs[4]:
        render_investigate_tab()


if __name__ == "__main__":
    main()
