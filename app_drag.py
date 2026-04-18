"""
app_drag.py — TBM CSV 诊断助手本地 GUI（单文件入口壳）

启动：
    streamlit run app_drag.py

功能：
- 上传单个 CSV / XLS / XLSX 文件
- 选择 detect 或 agent 模式
- 运行现有诊断链路（直接调用 Python 函数，不走 subprocess）
- 展示结果 + 提供三种格式下载
"""

from __future__ import annotations

import os
import sys
import uuid
import traceback
from pathlib import Path
from typing import Optional

# ── Windows stdout UTF-8 ──────────────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

import streamlit as st

# ── 常量 ──────────────────────────────────────────────────────────────────────
TMP_ROOT = Path("tmp_drag_runs")
ACCEPTED_TYPES = ["csv", "xls", "xlsx"]

_SEV_COLOR = {"高风险": "🔴", "中风险": "🟡", "低风险": "🟢", "观察": "⚪"}


# ── 辅助：准备 run 目录 ────────────────────────────────────────────────────────

def _make_run_dirs() -> tuple[Path, Path]:
    run_id = uuid.uuid4().hex[:8]
    in_dir  = TMP_ROOT / run_id / "input"
    out_dir = TMP_ROOT / run_id / "output"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    return in_dir, out_dir


def _save_upload(uploaded_file, in_dir: Path) -> Path:
    dest = in_dir / uploaded_file.name
    dest.write_bytes(uploaded_file.getbuffer())
    return dest


# ── detect 主流程 ─────────────────────────────────────────────────────────────

def _run_detect(file_path: Path, out_dir: Path, cfg) -> dict:
    from tbm_diag.cleaning import clean
    from tbm_diag.detector import detect
    from tbm_diag.evidence import extract_evidence
    from tbm_diag.explainer import TemplateExplainer
    from tbm_diag.exporter import ResultBundle, to_events_csv, to_json, to_markdown
    from tbm_diag.feature_engine import enrich_features
    from tbm_diag.ingestion import load_csv
    from tbm_diag.segmenter import segment_events
    from tbm_diag.semantic_layer import apply_to_evidences, SEMANTIC_LABELS
    from tbm_diag.state_engine import STATE_LABELS, classify_states, summarize_event_state

    cc = cfg.cleaning
    resample_freq = None if (cc.resample or "").strip().lower() == "none" else cc.resample

    ingestion = load_csv(str(file_path))
    df, cleaning = clean(
        ingestion.df,
        resample_freq=resample_freq,
        spike_k=cc.spike_k,
        fill_method=cc.fill,
        max_gap_fill=cc.max_gap,
    )
    enriched  = enrich_features(df, window=cfg.feature.rolling_window)
    detection = detect(enriched, config=cfg.detector)
    events    = segment_events(detection.df, config=cfg.segmenter)

    event_states: dict = {}
    if events:
        enriched = classify_states(enriched, config=cfg.state)
        event_states = {e.event_id: summarize_event_state(enriched, e) for e in events}

    evidences    = extract_evidence(enriched, events, event_states=event_states)
    apply_to_evidences(evidences)
    explanations = TemplateExplainer().explain_all(evidences, event_states=event_states)

    bundle = ResultBundle(
        input_file=str(file_path),
        ingestion=ingestion,
        cleaning=cleaning,
        detection=detection,
        events=events,
        evidences=evidences,
        explanations=explanations,
    )
    json_path = out_dir / "result.json"
    md_path   = out_dir / "report.md"
    csv_path  = out_dir / "events.csv"
    to_json(bundle, json_path)
    to_markdown(bundle, md_path)
    to_events_csv(bundle, csv_path)

    # 状态分布
    state_dist: dict[str, str] = {}
    if "machine_state" in enriched.columns:
        counts  = enriched["machine_state"].value_counts()
        n_total = len(enriched)
        for key in ["stopped", "low_load_operation", "normal_excavation", "heavy_load_excavation"]:
            n = counts.get(key, 0)
            state_dist[STATE_LABELS.get(key, key)] = f"{n / n_total * 100:.1f}%" if n_total else "0%"

    return {
        "events": events,
        "evidences": evidences,
        "explanations": explanations,
        "cleaning": cleaning,
        "detection": detection,
        "state_dist": state_dist,
        "json_path": json_path,
        "md_path":   md_path,
        "csv_path":  csv_path,
        "SEMANTIC_LABELS": SEMANTIC_LABELS,
        "STATE_LABELS": STATE_LABELS,
    }


# ── agent 主流程 ──────────────────────────────────────────────────────────────

def _run_agent(file_path: Path, out_dir: Path, cfg) -> dict:
    from tbm_diag.agent import run_agent
    result = run_agent(
        file_path=str(file_path),
        cfg=cfg.agent,
        save_json=str(out_dir / "result.json"),
        save_report=str(out_dir / "report.md"),
        save_events_csv=str(out_dir / "events.csv"),
    )
    return {
        "final_report": result.final_report,
        "error":        result.error,
        "json_path":    out_dir / "result.json",
        "md_path":      out_dir / "report.md",
        "csv_path":     out_dir / "events.csv",
    }


# ── 结果展示：detect ──────────────────────────────────────────────────────────

def _show_detect_results(res: dict, top_k: int) -> None:
    events       = res["events"]
    explanations = res["explanations"]
    state_dist   = res["state_dist"]
    SEM          = res["SEMANTIC_LABELS"]
    STATE        = res["STATE_LABELS"]
    cleaning     = res["cleaning"]

    # ── 总体结论 ──────────────────────────────────────────────────────────────
    st.subheader("总体结论")
    n = len(events)
    if n == 0:
        st.info("未检测到异常事件，数据质量良好。")
        return

    high = sum(1 for e in explanations if e.severity_label == "高风险")
    mid  = sum(1 for e in explanations if e.severity_label == "中风险")
    low  = sum(1 for e in explanations if e.severity_label in ("低风险", "观察"))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("异常事件", n)
    c2.metric("🔴 高风险", high)
    c3.metric("🟡 中风险", mid)
    c4.metric("🟢 低/观察", low)

    if state_dist:
        st.caption("工况分布：" + "  |  ".join(f"{k} {v}" for k, v in state_dist.items()))

    # ── 事件列表 ──────────────────────────────────────────────────────────────
    st.subheader("事件列表")
    ev_map = {ev.event_id: ev for ev in res["evidences"]}
    rows = []
    for e in events:
        ev  = ev_map.get(e.event_id)
        sem = (ev.semantic_event_type or e.event_type) if ev else e.event_type
        ds_key = ev.dominant_state if ev else ""
        rows.append({
            "事件ID":     e.event_id,
            "语义类型":   SEM.get(sem, sem),
            "严重度":     next((x.severity_label for x in explanations if x.event_id == e.event_id), ""),
            "主导工况":   STATE.get(ds_key, ds_key) if ds_key else "—",
            "开始时间":   str(e.start_time)[:19] if e.start_time else "—",
            "时长(s)":    f"{e.duration_seconds:.0f}" if e.duration_seconds else "—",
            "峰值分":     f"{e.peak_score:.3f}",
        })
    import pandas as pd
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Top-K 事件解释 ────────────────────────────────────────────────────────
    st.subheader(f"Top {min(top_k, len(explanations))} 事件解释")
    for exp in explanations[:top_k]:
        icon = _SEV_COLOR.get(exp.severity_label, "○")
        with st.expander(f"{icon} {exp.event_id} — {exp.title}  [{exp.severity_label}]", expanded=True):
            st.markdown(f"**总结**：{exp.summary}")
            if exp.state_context:
                st.caption(exp.state_context)
            if exp.evidence_bullets:
                st.markdown("**证据**")
                for b in exp.evidence_bullets:
                    st.markdown(f"- {b}")
            if exp.possible_causes:
                st.markdown("**可能原因**")
                for c in exp.possible_causes[:3]:
                    st.markdown(f"- {c}")
            if exp.suggested_actions:
                st.markdown("**建议关注**")
                for a in exp.suggested_actions[:3]:
                    st.markdown(f"- {a}")


# ── 下载区 ────────────────────────────────────────────────────────────────────

def _show_downloads(res: dict) -> None:
    st.subheader("导出下载")
    cols = st.columns(3)
    for col, (label, key, mime) in zip(cols, [
        ("result.json", "json_path", "application/json"),
        ("report.md",   "md_path",   "text/markdown"),
        ("events.csv",  "csv_path",  "text/csv"),
    ]):
        p: Path = res.get(key)
        if p and p.exists():
            col.download_button(
                label=f"⬇ {label}",
                data=p.read_bytes(),
                file_name=p.name,
                mime=mime,
                use_container_width=True,
            )
        else:
            col.caption(f"{label}（未生成）")


# ── 主页面 ────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(page_title="TBM CSV 诊断助手", page_icon="🛡️", layout="wide")
    st.title("🛡️ TBM CSV 诊断助手")
    st.caption("支持 CSV / XLS / XLSX 单文件分析 · 本地运行 · 无需联网（detect 模式）")

    # ── 上传区 ────────────────────────────────────────────────────────────────
    uploaded = st.file_uploader(
        "上传 TBM 数据文件（CSV / XLS / XLSX）",
        type=ACCEPTED_TYPES,
        help="拖动文件到此处，或点击选择文件",
    )

    # ── 参数区 ────────────────────────────────────────────────────────────────
    with st.expander("运行参数", expanded=True):
        col1, col2, col3 = st.columns(3)
        mode   = col1.radio("运行模式", ["detect（推荐）", "agent（需要 API Key）"], horizontal=True)
        top_k  = col2.slider("Top-K 事件解释", min_value=1, max_value=10, value=3)
        cfg_path = col3.text_input("配置文件路径（可选）", placeholder="sample_config.yaml")

    use_agent = mode.startswith("agent")

    # ── 运行按钮 ──────────────────────────────────────────────────────────────
    run_clicked = st.button("▶ 开始分析", type="primary", disabled=(uploaded is None))

    if uploaded is None:
        st.info("请先上传文件，然后点击「开始分析」。")
        return

    if run_clicked:
        # 清除上次结果
        for k in ("detect_res", "agent_res", "run_error"):
            st.session_state.pop(k, None)

        in_dir, out_dir = _make_run_dirs()
        file_path = _save_upload(uploaded, in_dir)

        from tbm_diag.config import load_config
        try:
            cfg = load_config(cfg_path.strip() or None)
        except Exception as e:
            st.error(f"配置文件加载失败：{e}")
            return

        if use_agent:
            api_key = os.environ.get(cfg.agent.api_key_env or "OPENAI_API_KEY", "").strip()
            if not api_key:
                st.warning(
                    f"agent 模式需要设置环境变量 `OPENAI_API_KEY`（和可选的 `OPENAI_BASE_URL`）。\n\n"
                    f"请在项目根目录创建 `.env` 文件（参考 `.env.example`），或在系统环境变量中设置后重启。"
                )
                return
            with st.spinner("Agent 分析中，请稍候…"):
                try:
                    st.session_state["agent_res"] = _run_agent(file_path, out_dir, cfg)
                except Exception:
                    st.session_state["run_error"] = traceback.format_exc()
        else:
            with st.spinner("检测分析中，请稍候…"):
                try:
                    st.session_state["detect_res"] = _run_detect(file_path, out_dir, cfg)
                    st.session_state["detect_top_k"] = top_k
                except Exception:
                    st.session_state["run_error"] = traceback.format_exc()

    # ── 展示结果 ──────────────────────────────────────────────────────────────
    if "run_error" in st.session_state:
        st.error("分析过程中发生错误：")
        st.code(st.session_state["run_error"], language="python")

    elif "detect_res" in st.session_state:
        st.divider()
        _show_detect_results(st.session_state["detect_res"], st.session_state.get("detect_top_k", 3))
        st.divider()
        _show_downloads(st.session_state["detect_res"])

    elif "agent_res" in st.session_state:
        res = st.session_state["agent_res"]
        st.divider()
        st.subheader("Agent 诊断报告")
        if res.get("error"):
            st.warning(f"Agent 运行出现问题：{res['error']}")
        if res.get("final_report"):
            st.text_area("报告全文", value=res["final_report"], height=400)
        else:
            st.info("Agent 未生成最终报告。")
        st.divider()
        _show_downloads(res)


if __name__ == "__main__":
    main()
