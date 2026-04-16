"""
agent.py — OpenAI-compatible Tool-Using Agent Layer

职责：
- 通过 function calling 调用现有本地工具（inspect / detect / summarize / export）
- LLM 不接触原始 DataFrame，只看结构化摘要
- 任何失败（无 SDK、无 key、超时、API 报错、超轮数）均优雅降级
- 不修改任何现有检测链路

依赖：openai SDK（可选，未安装时给出友好提示）
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── AgentConfig ────────────────────────────────────────────────────────────────

@dataclass
class AgentConfig:
    model: str = "MiniMax-M2.7"
    max_tokens: int = 2048
    temperature: float = 0.2
    api_key_env: str = "OPENAI_API_KEY"
    base_url_env: str = "OPENAI_BASE_URL"
    timeout_seconds: int = 60
    max_tool_rounds: int = 6
    reasoning_split: bool = True
    """MiniMax 专用：是否在请求中传入 extra_body={"reasoning_split": True}。
    若目标服务不支持此参数，会自动 fallback 重试一次不带该参数。"""


# ── 结果 dataclass ─────────────────────────────────────────────────────────────

@dataclass
class AgentResult:
    final_report: Optional[str]
    tool_calls_made: list[str] = field(default_factory=list)
    error: Optional[str] = None
    exported_paths: list[str] = field(default_factory=list)


# ── Session cache ──────────────────────────────────────────────────────────────
# key: file_path (str) → dict with pipeline results

_SESSION: dict[str, dict] = {}


def _get_cached(file_path: str) -> Optional[dict]:
    return _SESSION.get(str(Path(file_path).resolve()))


def _set_cached(file_path: str, data: dict) -> None:
    _SESSION[str(Path(file_path).resolve())] = data


# ── Tool implementations ───────────────────────────────────────────────────────

def _tool_inspect_file(file_path: str) -> str:
    """加载并检查文件，返回字段识别情况、行数、时间范围、清洗摘要。"""
    try:
        from tbm_diag.ingestion import load_csv
        from tbm_diag.cleaning import clean
        from tbm_diag.config import DiagConfig
        cfg = DiagConfig()

        result = load_csv(file_path)
        df, report = clean(result.df,
                           resample_freq=cfg.cleaning.resample,
                           spike_k=cfg.cleaning.spike_k,
                           fill_method=cfg.cleaning.fill,
                           max_gap_fill=cfg.cleaning.max_gap)

        time_start = time_end = ""
        if "timestamp" in df.columns:
            ts = df["timestamp"].dropna()
            if not ts.empty:
                time_start = str(ts.iloc[0])[:19]
                time_end   = str(ts.iloc[-1])[:19]

        out = {
            "status": "ok",
            "file": file_path,
            "encoding": result.encoding_used,
            "raw_rows": result.df.shape[0],
            "raw_cols": result.df.shape[1],
            "cleaned_rows": report.rows_output,
            "recognized_fields": len(result.recognized),
            "unrecognized_fields": len(result.unrecognized),
            "time_start": time_start,
            "time_end": time_end,
            "spikes_removed": sum(report.spike_removed.values()),
            "warnings": report.warnings[:3],
        }
        # cache cleaned df for reuse
        cached = _get_cached(file_path) or {}
        cached["cleaned_df"] = df
        cached["ingestion"] = result
        cached["cleaning"] = report
        _set_cached(file_path, cached)
        return json.dumps(out, ensure_ascii=False)
    except FileNotFoundError:
        return json.dumps({"status": "error", "error": f"文件不存在: {file_path}"})
    except Exception as exc:
        logger.debug("inspect_file failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


def _tool_detect_file(file_path: str) -> str:
    """运行完整检测流程，返回事件级摘要。"""
    try:
        from tbm_diag.feature_engine import enrich_features
        from tbm_diag.detector import detect
        from tbm_diag.segmenter import segment_events
        from tbm_diag.state_engine import STATE_LABELS, classify_states, summarize_event_state
        from tbm_diag.evidence import extract_evidence
        from tbm_diag.explainer import TemplateExplainer
        from tbm_diag.config import DiagConfig
        cfg = DiagConfig()

        cached = _get_cached(file_path) or {}

        # reuse cleaned df if available, else reload
        if "cleaned_df" not in cached:
            from tbm_diag.ingestion import load_csv
            from tbm_diag.cleaning import clean
            result = load_csv(file_path)
            df, report = clean(result.df)
            cached["cleaned_df"] = df
            cached["ingestion"] = result
            cached["cleaning"] = report

        df = cached["cleaned_df"]
        enriched = enrich_features(df, window=cfg.feature.rolling_window)
        det_result = detect(enriched, config=cfg.detector)
        events = segment_events(det_result.df, config=cfg.segmenter)

        event_states: dict = {}
        if events:
            enriched = classify_states(enriched, config=cfg.state)
            event_states = {e.event_id: summarize_event_state(enriched, e) for e in events}

        evidences = extract_evidence(enriched, events, event_states=event_states)
        explanations = TemplateExplainer().explain_all(evidences, event_states=event_states)

        # cache everything
        cached.update({
            "enriched": enriched,
            "det_result": det_result,
            "events": events,
            "event_states": event_states,
            "evidences": evidences,
            "explanations": explanations,
        })
        _set_cached(file_path, cached)

        _LABELS = {
            "suspected_excavation_resistance": "疑似掘进阻力异常",
            "low_efficiency_excavation":       "低效掘进",
            "attitude_or_bias_risk":           "姿态偏斜风险",
            "hydraulic_instability":           "液压系统不稳定",
        }
        sev_map = {e.event_id: e.severity_label for e in explanations}

        event_list = []
        for e in events:
            ds_key = event_states[e.event_id].dominant_state if e.event_id in event_states else ""
            event_list.append({
                "event_id":      e.event_id,
                "type":          _LABELS.get(e.event_type, e.event_type),
                "severity":      sev_map.get(e.event_id, ""),
                "start":         str(e.start_time)[:19] if e.start_time else "",
                "end":           str(e.end_time)[:19]   if e.end_time   else "",
                "duration_s":    round(e.duration_seconds) if e.duration_seconds else None,
                "dominant_state": STATE_LABELS.get(ds_key, ds_key),
            })

        type_counts: dict[str, int] = {}
        for e in events:
            label = _LABELS.get(e.event_type, e.event_type)
            type_counts[label] = type_counts.get(label, 0) + 1

        out = {
            "status": "ok",
            "total_events": len(events),
            "type_counts": type_counts,
            "events": event_list,
        }
        return json.dumps(out, ensure_ascii=False)
    except FileNotFoundError:
        return json.dumps({"status": "error", "error": f"文件不存在: {file_path}"})
    except Exception as exc:
        logger.debug("detect_file failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


def _tool_summarize_file(file_path: str) -> str:
    """返回事件解释摘要（一句话总结 + 前2条证据 + 前2条建议）。"""
    try:
        cached = _get_cached(file_path)
        if not cached or "explanations" not in cached:
            # trigger detect first
            _tool_detect_file(file_path)
            cached = _get_cached(file_path)

        if not cached or "explanations" not in cached:
            return json.dumps({"status": "error", "error": "检测结果不可用，请先调用 detect_file"})

        explanations = cached["explanations"]
        if not explanations:
            return json.dumps({"status": "ok", "message": "未检测到异常事件", "events": []})

        items = []
        for exp in explanations:
            items.append({
                "event_id":    exp.event_id,
                "title":       exp.title,
                "severity":    exp.severity_label,
                "summary":     exp.summary,
                "state_ctx":   exp.state_context,
                "evidence":    exp.evidence_bullets[:2],
                "actions":     exp.suggested_actions[:2],
            })

        return json.dumps({"status": "ok", "total": len(items), "events": items}, ensure_ascii=False)
    except Exception as exc:
        logger.debug("summarize_file failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


def _tool_export_results(
    file_path: str,
    output_json: Optional[str] = None,
    output_md: Optional[str] = None,
    output_csv: Optional[str] = None,
) -> str:
    """将检测结果导出为文件，复用缓存结果。"""
    try:
        cached = _get_cached(file_path)
        if not cached or "explanations" not in cached:
            _tool_detect_file(file_path)
            cached = _get_cached(file_path)

        if not cached or "events" not in cached:
            return json.dumps({"status": "error", "error": "无可导出的检测结果"})

        from tbm_diag.exporter import ResultBundle, to_json, to_markdown, to_events_csv
        bundle = ResultBundle(
            input_file=file_path,
            ingestion=cached["ingestion"],
            cleaning=cached["cleaning"],
            detection=cached["det_result"],
            events=cached["events"],
            evidences=cached["evidences"],
            explanations=cached["explanations"],
        )

        exported = []
        errors = []

        if output_json:
            try:
                to_json(bundle, Path(output_json))
                exported.append(output_json)
            except Exception as exc:
                errors.append(f"JSON: {exc}")

        if output_md:
            try:
                to_markdown(bundle, Path(output_md))
                exported.append(output_md)
            except Exception as exc:
                errors.append(f"Markdown: {exc}")

        if output_csv:
            try:
                to_events_csv(bundle, Path(output_csv))
                exported.append(output_csv)
            except Exception as exc:
                errors.append(f"CSV: {exc}")

        return json.dumps({
            "status": "ok",
            "exported": exported,
            "errors": errors,
        }, ensure_ascii=False)
    except Exception as exc:
        logger.debug("export_results failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


# ── Tool dispatch ──────────────────────────────────────────────────────────────

_TOOL_HANDLERS = {
    "inspect_file":   lambda args: _tool_inspect_file(args["file_path"]),
    "detect_file":    lambda args: _tool_detect_file(args["file_path"]),
    "summarize_file": lambda args: _tool_summarize_file(args["file_path"]),
    "export_results": lambda args: _tool_export_results(
        args["file_path"],
        output_json=args.get("output_json"),
        output_md=args.get("output_md"),
        output_csv=args.get("output_csv"),
    ),
}

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "inspect_file",
            "description": "加载并检查 CSV/XLS 文件，返回字段识别情况、行数、时间范围、清洗摘要。第一步必须调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "输入文件路径"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_file",
            "description": "对文件运行完整检测流程（特征提取 + 规则检测 + 事件分段 + 工况识别），返回事件列表摘要。必须在 inspect_file 之后调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "输入文件路径"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_file",
            "description": "获取所有事件的详细解释（一句话总结、证据、建议、工况上下文）。必须在 detect_file 之后调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "输入文件路径"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_results",
            "description": "将检测结果导出为文件（JSON / Markdown / events CSV）。必须在 detect_file 之后调用。output_json / output_md / output_csv 均为可选。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path":   {"type": "string", "description": "输入文件路径"},
                    "output_json": {"type": "string", "description": "JSON 输出路径（可选）"},
                    "output_md":   {"type": "string", "description": "Markdown 报告路径（可选）"},
                    "output_csv":  {"type": "string", "description": "事件表 CSV 路径（可选）"},
                },
                "required": ["file_path"],
            },
        },
    },
]


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是一名盾构/TBM 施工数据分析助手。你有以下工具可以调用：

- inspect_file：检查文件基本情况（第一步必须调用）
- detect_file：运行异常检测，获取事件列表（第二步）
- summarize_file：获取事件详细解释（第三步）
- export_results：导出结果文件（可选，若用户指定了导出路径则调用）

工作流程要求：
1. 必须先调用 inspect_file
2. 再调用 detect_file
3. 再调用 summarize_file
4. 若有导出路径，调用 export_results
5. 最后输出一份面向现场工程师的中文诊断报告

最终报告要求：
- 整体评估（2~3句，说明本次数据的整体状态）
- 主要风险（3~5条，基于事件结果归纳，不要逐条重复工具返回的原文）
- 建议关注（3~5条，可操作的具体建议）
- 若有导出，说明已导出到哪些路径

注意：
- 只基于工具返回的数据，不要编造原始数据中不存在的指标
- 语言简洁务实，面向现场工程师
- 不要输出 markdown 代码块，直接输出纯文本报告"""


# ── OpenAI-compatible client ───────────────────────────────────────────────────

def _call_llm(
    messages: list[dict],
    tools: list[dict],
    cfg: AgentConfig,
    client: Any,
) -> Optional[dict]:
    """
    调用 OpenAI-compatible API，返回完整 assistant message dict 或 None（失败时）。

    MiniMax 适配要点：
    - 支持 extra_body={"reasoning_split": True}，若服务不接受则自动 fallback
    - 当模型返回 tool_calls 时，content 保持 None（不强转为空字符串）
    - reasoning_details 仅在 debug 日志中输出，不进入主流程
    """
    def _do_call(with_reasoning: bool) -> Any:
        kwargs: dict[str, Any] = {
            "model":       cfg.model,
            "messages":    messages,
            "max_tokens":  cfg.max_tokens,
            "temperature": cfg.temperature,
            "timeout":     cfg.timeout_seconds,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if with_reasoning:
            kwargs["extra_body"] = {"reasoning_split": True}
        return client.chat.completions.create(**kwargs)

    try:
        # 第一次尝试（带 reasoning_split，若 cfg.reasoning_split=False 则直接跳过）
        try:
            response = _do_call(with_reasoning=cfg.reasoning_split)
        except Exception as exc:
            err_str = str(exc).lower()
            # 若是参数不支持类错误，fallback 不带 extra_body 重试一次
            if cfg.reasoning_split and any(k in err_str for k in (
                "extra_body", "reasoning_split", "unknown", "invalid", "unexpected", "parameter"
            )):
                logger.warning("_call_llm: reasoning_split not supported, retrying without it")
                response = _do_call(with_reasoning=False)
            else:
                raise

        msg = response.choices[0].message

        # reasoning_details：仅 debug 日志，不进主流程
        if hasattr(msg, "reasoning_details") and msg.reasoning_details:
            logger.debug("reasoning_details: %s", str(msg.reasoning_details)[:300])

        # 构造完整 assistant message dict
        # 关键：tool_calls 存在时 content 保持 None，不转为 ""
        # 这样多轮对话历史中 assistant message 格式与 OpenAI spec 一致
        has_tool_calls = bool(getattr(msg, "tool_calls", None))
        result: dict[str, Any] = {
            "role":    "assistant",
            "content": msg.content if msg.content else (None if has_tool_calls else ""),
        }
        if has_tool_calls:
            result["tool_calls"] = [
                {
                    "id":   tc.id,
                    "type": "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        return result

    except Exception as exc:
        logger.warning("_call_llm failed (%s: %s)", type(exc).__name__, exc)
        return None


# ── Agent loop ─────────────────────────────────────────────────────────────────

def run_agent(
    file_path: str,
    cfg: AgentConfig,
    save_json: Optional[str] = None,
    save_report: Optional[str] = None,
    save_events_csv: Optional[str] = None,
    verbose: bool = False,
) -> AgentResult:
    """
    运行 agent loop。

    Returns:
        AgentResult，失败时 final_report=None，error 有说明。
    """
    # ── 检查 openai SDK ────────────────────────────────────────────────────────
    try:
        from openai import OpenAI
    except ImportError:
        msg = "openai SDK 未安装，请运行：pip install openai"
        print(f"✗ {msg}", file=sys.stderr)
        return AgentResult(final_report=None, error=msg)

    # ── 读取 API key ───────────────────────────────────────────────────────────
    api_key = os.environ.get(cfg.api_key_env, "").strip()
    if not api_key:
        msg = f"未找到环境变量 {cfg.api_key_env}，请设置后重试"
        print(f"✗ {msg}", file=sys.stderr)
        return AgentResult(final_report=None, error=msg)

    base_url = os.environ.get(cfg.base_url_env, "").strip() or None

    client = OpenAI(api_key=api_key, base_url=base_url)

    # ── 构造初始消息 ───────────────────────────────────────────────────────────
    export_hint = ""
    if any([save_json, save_report, save_events_csv]):
        parts = []
        if save_json:        parts.append(f"JSON: {save_json}")
        if save_report:      parts.append(f"Markdown: {save_report}")
        if save_events_csv:  parts.append(f"CSV: {save_events_csv}")
        export_hint = f"\n请在分析完成后调用 export_results 导出结果，路径：{', '.join(parts)}"

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": f"请分析文件：{file_path}{export_hint}"},
    ]

    tool_calls_made: list[str] = []
    exported_paths: list[str] = []

    # ── Agent loop ─────────────────────────────────────────────────────────────
    for round_num in range(1, cfg.max_tool_rounds + 1):
        response = _call_llm(messages, TOOLS_SCHEMA, cfg, client)

        if response is None:
            return AgentResult(
                final_report=_fallback_report(file_path),
                tool_calls_made=tool_calls_made,
                error="LLM API 调用失败，已生成降级报告",
                exported_paths=exported_paths,
            )

        messages.append(response)

        # 没有 tool_calls → 模型输出最终文本
        if "tool_calls" not in response or not response["tool_calls"]:
            final_text = response.get("content", "").strip()
            if final_text:
                return AgentResult(
                    final_report=final_text,
                    tool_calls_made=tool_calls_made,
                    exported_paths=exported_paths,
                )
            # 空文本，降级
            return AgentResult(
                final_report=_fallback_report(file_path),
                tool_calls_made=tool_calls_made,
                error="模型返回空文本，已生成降级报告",
                exported_paths=exported_paths,
            )

        # 执行所有 tool calls
        for tc in response["tool_calls"]:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}

            # inject export paths if model calls export_results without them
            if fn_name == "export_results":
                if save_json and "output_json" not in fn_args:
                    fn_args["output_json"] = save_json
                if save_report and "output_md" not in fn_args:
                    fn_args["output_md"] = save_report
                if save_events_csv and "output_csv" not in fn_args:
                    fn_args["output_csv"] = save_events_csv

            print(f"[agent] round {round_num} → {fn_name}({fn_args.get('file_path', '')})")
            tool_calls_made.append(fn_name)

            handler = _TOOL_HANDLERS.get(fn_name)
            if handler:
                tool_result = handler(fn_args)
            else:
                tool_result = json.dumps({"status": "error", "error": f"未知工具: {fn_name}"})

            # collect exported paths
            if fn_name == "export_results":
                try:
                    r = json.loads(tool_result)
                    exported_paths.extend(r.get("exported", []))
                except Exception:
                    pass

            if verbose:
                try:
                    parsed = json.loads(tool_result)
                    print(f"         ↳ {json.dumps(parsed, ensure_ascii=False)[:200]}")
                except Exception:
                    print(f"         ↳ {tool_result[:200]}")

            messages.append({
                "role":         "tool",
                "tool_call_id": tc["id"],
                "content":      tool_result,
            })

    # 超过 max_tool_rounds
    return AgentResult(
        final_report=_fallback_report(file_path),
        tool_calls_made=tool_calls_made,
        error=f"超过最大轮数 {cfg.max_tool_rounds}，已生成降级报告",
        exported_paths=exported_paths,
    )


# ── 降级报告 ───────────────────────────────────────────────────────────────────

def _fallback_report(file_path: str) -> str:
    """基于已有 tool 结果拼一个降级报告，不依赖 LLM。"""
    cached = _get_cached(file_path)
    if not cached:
        return f"[降级报告] 文件 {file_path} 未能完成分析，请检查文件路径和配置后重试。"

    lines = [f"[降级报告] 文件：{file_path}"]

    if "cleaning" in cached:
        r = cached["cleaning"]
        lines.append(f"数据概况：清洗后 {r.rows_output:,} 行（原始 {r.rows_input:,} 行）")

    events = cached.get("events", [])
    explanations = cached.get("explanations", [])

    if not events:
        lines.append("检测结果：未发现有效异常事件。")
    else:
        lines.append(f"检测结果：共发现 {len(events)} 个异常事件。")
        for exp in explanations[:3]:
            lines.append(f"  - [{exp.severity_label}] {exp.event_id} {exp.title}：{exp.summary}")

    lines.append("（LLM 报告生成失败，以上为规则检测结果摘要）")
    return "\n".join(lines)
