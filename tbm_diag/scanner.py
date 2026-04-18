"""
scanner.py — 批量扫描层 v1

对目录中的所有 CSV/XLS/XLSX 文件批量运行规则诊断内核，
生成每文件的结构化结果和总索引表。

用法：
    python -m tbm_diag.cli scan --input-dir data_dir --output-dir scan_out

特性：
- 断点续跑：基于文件指纹（大小 + mtime）跳过未变化的已处理文件
- 原子写入：状态文件通过 .tmp → rename 保证不损坏
- 单线程：v1 默认，先保证正确性
- 扩展点：include_llm_summary / include_agent 预留，v1 不默认开启
"""

from __future__ import annotations

import csv
import json
import logging
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── ScanConfig ─────────────────────────────────────────────────────────────────

@dataclass
class ScanConfig:
    file_patterns: list = field(default_factory=lambda: ["*.csv", "*.xls", "*.xlsx"])
    """要扫描的文件通配符列表。"""
    recursive: bool = True
    """是否递归扫描子目录。"""
    overwrite: bool = False
    """True 时强制重新处理所有文件，忽略已有状态。"""
    max_workers: int = 1
    """并发数，v1 固定为 1（单线程）。"""
    include_llm_summary: bool = False
    """是否为每个文件生成 LLM 跨事件总结（大批量场景不推荐默认开启）。"""
    include_agent: bool = False
    """是否为每个文件运行 agent 模式（大批量场景不推荐默认开启）。"""
    max_file_size_mb: float = 0.0
    """单文件大小上限（MB）；0 表示不限制。超过则跳过并标记 file_too_large。"""


# ── ScanRecord ─────────────────────────────────────────────────────────────────

@dataclass
class ScanRecord:
    """单文件扫描结果，用于写入 scan_index.csv。"""
    file_name: str
    file_path: str
    file_size: int
    mtime: float
    status: str                    # ok / error / skipped
    processed_at: str = ""
    total_rows: int = 0
    event_count: int = 0
    max_severity_label: str = ""
    dominant_state_top1: str = ""
    top_event_type: str = ""
    top_event_summary: str = ""
    json_path: str = ""
    md_path: str = ""
    events_csv_path: str = ""
    error_message: str = ""
    error_type: str = ""           # file_not_found / parse_error / empty_file / file_too_large / runtime_error
    elapsed_seconds: float = 0.0
    risk_rank_score: float = 0.0   # 数值越大越值得优先查看
    is_high_priority: bool = False


# ── ScanState ──────────────────────────────────────────────────────────────────

_STATE_FILE_NAME = ".scan_state.json"


class ScanState:
    """
    管理 .scan_state.json，记录每个文件的处理状态和指纹。

    格式：
      {
        "records": {
          "/abs/path/file.csv": {
            "file_size": 12345, "mtime": 1234567890.0,
            "status": "ok", "processed_at": "...", "error_message": "",
            "outputs": {"json": "...", "md": "...", "events_csv": "..."},
            "metrics": { ... }
          }
        }
      }
    """

    def __init__(self, state_file: Path) -> None:
        self._path = state_file
        self._records: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._records = raw.get("records", {})
                logger.debug("ScanState loaded: %d entries from %s", len(self._records), self._path)
            except Exception as exc:
                logger.warning("Failed to load scan state %s: %s — starting fresh", self._path, exc)
                self._records = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"records": self._records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def should_skip(self, file_path: Path, overwrite: bool) -> bool:
        """若 overwrite=False 且文件未变化（大小+mtime 一致），返回 True。"""
        if overwrite:
            return False
        key = str(file_path.resolve())
        rec = self._records.get(key)
        if rec is None or rec.get("status") != "ok":
            return False
        try:
            stat = file_path.stat()
            return (rec.get("file_size") == stat.st_size
                    and abs(rec.get("mtime", 0) - stat.st_mtime) < 1.0)
        except OSError:
            return False

    def mark(self, record: ScanRecord) -> None:
        key = str(Path(record.file_path).resolve())
        self._records[key] = {
            "file_size":     record.file_size,
            "mtime":         record.mtime,
            "status":        record.status,
            "processed_at":  record.processed_at,
            "error_message": record.error_message,
            "error_type":    record.error_type,
            "elapsed_seconds": record.elapsed_seconds,
            "outputs": {
                "json":       record.json_path,
                "md":         record.md_path,
                "events_csv": record.events_csv_path,
            },
            "metrics": {
                "total_rows":          record.total_rows,
                "event_count":         record.event_count,
                "max_severity_label":  record.max_severity_label,
                "dominant_state_top1": record.dominant_state_top1,
                "top_event_type":      record.top_event_type,
                "top_event_summary":   record.top_event_summary,
                "risk_rank_score":     record.risk_rank_score,
                "is_high_priority":    record.is_high_priority,
            },
        }
        self._save()

    def get_saved(self, file_path: Path) -> dict:
        return self._records.get(str(file_path.resolve()), {})

    def __len__(self) -> int:
        return len(self._records)


# ── 文件发现 ───────────────────────────────────────────────────────────────────

def discover_files(input_dir: Path, config: ScanConfig) -> list[Path]:
    """扫描 input_dir，返回匹配 file_patterns 的文件列表（稳定排序）。"""
    found: set[Path] = set()
    for pattern in config.file_patterns:
        if config.recursive:
            found.update(input_dir.rglob(pattern))
        else:
            found.update(input_dir.glob(pattern))
    return sorted(p for p in found if p.is_file())


# ── 辅助函数 ───────────────────────────────────────────────────────────────────

def _classify_error(error_message: str) -> str:
    """将 error_message 归类为标准 error_type。"""
    msg = error_message.lower()
    if any(k in msg for k in ("not found", "no such file", "filenotfound", "找不到")):
        return "file_not_found"
    if any(k in msg for k in ("parse", "decode", "encoding", "codec", "unicode", "utf", "gbk", "解析")):
        return "parse_error"
    if any(k in msg for k in ("unsupported", "format", "extension", "格式不支持")):
        return "unsupported_format"
    if any(k in msg for k in ("empty", "no data", "0 rows", "no rows", "空文件", "无数据")):
        return "empty_file"
    if "too large" in msg or "file_too_large" in msg:
        return "file_too_large"
    return "runtime_error"


def _compute_risk_score(record: ScanRecord) -> tuple[float, bool]:
    """
    计算风险排序分和高优先级标志。

    评分规则（简单实用）：
      高风险基础分 100 + event_count * 10
      中风险基础分  50 + event_count *  5
      低风险基础分  20 + event_count *  2
      观察基础分    10 + event_count *  1
      无事件         0

    is_high_priority: score >= 50
    """
    base = _SEVERITY_ORDER.get(record.max_severity_label, 0)
    multiplier = {4: (100, 10), 3: (50, 5), 2: (20, 2), 1: (10, 1)}.get(base, (0, 0))
    score = multiplier[0] + record.event_count * multiplier[1]
    return float(score), score >= 50


# ── 单文件处理 ─────────────────────────────────────────────────────────────────

_SEVERITY_ORDER = {"高风险": 4, "中风险": 3, "低风险": 2, "观察": 1}
_ANOMALY_LABELS = {
    "suspected_excavation_resistance": "疑似掘进阻力异常",
    "low_efficiency_excavation":       "低效掘进",
    "attitude_or_bias_risk":           "姿态偏斜风险",
    "hydraulic_instability":           "液压系统不稳定",
}
_STATE_LABELS_ZH = {
    "stopped":               "停机/静止",
    "low_load_operation":    "低负载运行",
    "normal_excavation":     "正常推进",
    "heavy_load_excavation": "重载推进",
}


def process_file(
    file_path: Path,
    output_dir: Path,
    shared_cfg: Any = None,
) -> ScanRecord:
    """
    对单个文件运行完整检测链路，导出三种结果，返回 ScanRecord。

    Raises:
        任何异常都向上抛出，由调用方捕获并记录到 ScanRecord.error_message。
    """
    import time
    from tbm_diag.cleaning import clean
    from tbm_diag.config import DiagConfig
    from tbm_diag.detector import detect
    from tbm_diag.evidence import extract_evidence
    from tbm_diag.explainer import TemplateExplainer
    from tbm_diag.exporter import ResultBundle, to_events_csv, to_json, to_markdown
    from tbm_diag.feature_engine import enrich_features
    from tbm_diag.ingestion import load_csv
    from tbm_diag.segmenter import segment_events
    from tbm_diag.state_engine import classify_states, summarize_event_state
    from tbm_diag.semantic_layer import apply_to_evidences

    t0 = time.monotonic()

    if shared_cfg is None:
        shared_cfg = DiagConfig()

    cfg = shared_cfg
    cc = cfg.cleaning
    resample_freq = None if (cc.resample or "").strip().lower() == "none" else cc.resample

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = file_path.stem

    # 加载 + 清洗
    ingestion = load_csv(str(file_path))
    df, cleaning = clean(
        ingestion.df,
        resample_freq=resample_freq,
        spike_k=cc.spike_k,
        fill_method=cc.fill,
        max_gap_fill=cc.max_gap,
    )

    # 特征 + 检测 + 分段
    enriched = enrich_features(df, window=cfg.feature.rolling_window)
    detection = detect(enriched, config=cfg.detector)
    events = segment_events(detection.df, config=cfg.segmenter)

    # 工况状态
    event_states: dict = {}
    if events:
        enriched = classify_states(enriched, config=cfg.state)
        event_states = {e.event_id: summarize_event_state(enriched, e) for e in events}

    dominant_state_top1 = ""
    if "machine_state" in enriched.columns:
        vc = enriched["machine_state"].value_counts()
        if not vc.empty:
            dominant_state_top1 = _STATE_LABELS_ZH.get(vc.index[0], vc.index[0])

    # 证据 + 语义重分类 + 解释
    evidences = extract_evidence(enriched, events, event_states=event_states)
    apply_to_evidences(evidences)
    explanations = TemplateExplainer().explain_all(evidences, event_states=event_states)

    # 导出
    bundle = ResultBundle(
        input_file=str(file_path),
        ingestion=ingestion,
        cleaning=cleaning,
        detection=detection,
        events=events,
        evidences=evidences,
        explanations=explanations,
    )
    json_path       = output_dir / f"{stem}.result.json"
    md_path         = output_dir / f"{stem}.report.md"
    events_csv_path = output_dir / f"{stem}.events.csv"
    to_json(bundle,       json_path)
    to_markdown(bundle,   md_path)
    to_events_csv(bundle, events_csv_path)

    # 提取索引字段
    max_sev = ""
    if explanations:
        max_sev = max(
            (e.severity_label for e in explanations),
            key=lambda s: _SEVERITY_ORDER.get(s, 0),
        )
    top_event_type = top_event_summary = ""
    if explanations:
        top = explanations[0]
        top_event_type    = _ANOMALY_LABELS.get(top.event_type, top.event_type)
        top_event_summary = top.summary

    elapsed = time.monotonic() - t0
    stat = file_path.stat()
    rec = ScanRecord(
        file_name=file_path.name,
        file_path=str(file_path.resolve()),
        file_size=stat.st_size,
        mtime=stat.st_mtime,
        status="ok",
        processed_at=datetime.now().isoformat(),
        total_rows=cleaning.rows_output,
        event_count=len(events),
        max_severity_label=max_sev,
        dominant_state_top1=dominant_state_top1,
        top_event_type=top_event_type,
        top_event_summary=top_event_summary,
        json_path=str(json_path),
        md_path=str(md_path),
        events_csv_path=str(events_csv_path),
        elapsed_seconds=round(elapsed, 2),
    )
    rec.risk_rank_score, rec.is_high_priority = _compute_risk_score(rec)
    return rec


# ── 索引写入 ───────────────────────────────────────────────────────────────────

_INDEX_FIELDS = [
    "file_name", "file_path", "status", "processed_at",
    "total_rows", "event_count", "max_severity_label",
    "dominant_state_top1", "top_event_type", "top_event_summary",
    "risk_rank_score", "is_high_priority",
    "elapsed_seconds", "file_size",
    "json_path", "md_path", "events_csv_path",
    "error_type", "error_message",
]


def _write_scan_index(records: list[ScanRecord], output_dir: Path) -> Path:
    """将所有 ScanRecord 写入 scan_index.csv，返回路径。"""
    index_path = output_dir / "scan_index.csv"
    with open(index_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_INDEX_FIELDS)
        writer.writeheader()
        for rec in records:
            writer.writerow({
                "file_name":           rec.file_name,
                "file_path":           rec.file_path,
                "status":              rec.status,
                "processed_at":        rec.processed_at,
                "total_rows":          rec.total_rows,
                "event_count":         rec.event_count,
                "max_severity_label":  rec.max_severity_label,
                "dominant_state_top1": rec.dominant_state_top1,
                "top_event_type":      rec.top_event_type,
                "top_event_summary":   rec.top_event_summary,
                "risk_rank_score":     rec.risk_rank_score,
                "is_high_priority":    rec.is_high_priority,
                "elapsed_seconds":     rec.elapsed_seconds,
                "file_size":           rec.file_size,
                "json_path":           rec.json_path,
                "md_path":             rec.md_path,
                "events_csv_path":     rec.events_csv_path,
                "error_type":          rec.error_type,
                "error_message":       rec.error_message,
            })
    logger.info("Scan index written → %s (%d records)", index_path, len(records))
    return index_path


# ── 扫描总结 ───────────────────────────────────────────────────────────────────

def _write_scan_summary(
    records: list[ScanRecord],
    total_elapsed: float,
    output_dir: Path,
) -> Path:
    """生成 scan_summary.json，包含整体统计、最慢文件、错误聚合、高优先级文件。"""
    ok_recs    = [r for r in records if r.status == "ok"]
    err_recs   = [r for r in records if r.status == "error"]
    skip_recs  = [r for r in records if r.status == "skipped"]

    avg_s = (sum(r.elapsed_seconds for r in ok_recs) / len(ok_recs)) if ok_recs else 0.0

    # 最慢 10 个
    slowest = sorted(ok_recs, key=lambda r: r.elapsed_seconds, reverse=True)[:10]

    # 错误原因聚合
    error_counts: dict[str, int] = {}
    for r in err_recs:
        error_counts[r.error_type or "unknown"] = error_counts.get(r.error_type or "unknown", 0) + 1

    # 高优先级文件（按 risk_rank_score 降序）
    high_pri = sorted(
        [r for r in records if r.is_high_priority],
        key=lambda r: r.risk_rank_score,
        reverse=True,
    )[:20]

    doc = {
        "generated_at": datetime.now().isoformat(),
        "statistics": {
            "total_files":          len(records),
            "ok_count":             len(ok_recs),
            "error_count":          len(err_recs),
            "skipped_count":        len(skip_recs),
            "total_elapsed_seconds": round(total_elapsed, 2),
            "avg_seconds_per_file": round(avg_s, 2),
        },
        "top10_slowest": [
            {"file": r.file_name, "elapsed_s": r.elapsed_seconds, "rows": r.total_rows}
            for r in slowest
        ],
        "error_type_counts": error_counts,
        "error_details": [
            {"file": r.file_name, "error_type": r.error_type, "message": r.error_message[:200]}
            for r in err_recs
        ],
        "high_priority_files": [
            {
                "file":              r.file_name,
                "risk_rank_score":   r.risk_rank_score,
                "max_severity":      r.max_severity_label,
                "event_count":       r.event_count,
                "top_event_type":    r.top_event_type,
                "top_event_summary": r.top_event_summary[:100],
                "md_path":           r.md_path,
            }
            for r in high_pri
        ],
    }

    summary_path = output_dir / "scan_summary.json"
    tmp = summary_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(summary_path)
    logger.info("Scan summary written → %s", summary_path)
    return summary_path


def _print_post_summary(
    records: list[ScanRecord],
    total_elapsed: float,
    summary_path: Path,
    index_path: Path,
) -> None:
    """扫描结束后打印可读摘要。"""
    ok_recs   = [r for r in records if r.status == "ok"]
    err_recs  = [r for r in records if r.status == "error"]
    skip_recs = [r for r in records if r.status == "skipped"]
    avg_s = (sum(r.elapsed_seconds for r in ok_recs) / len(ok_recs)) if ok_recs else 0.0

    print()
    print("┌─ 扫描总结 " + "─" * 58)
    print(f"  总文件数   : {len(records)}")
    print(f"  成功       : {len(ok_recs)}")
    print(f"  失败       : {len(err_recs)}")
    print(f"  跳过       : {len(skip_recs)}")
    print(f"  总耗时     : {total_elapsed:.1f}s")
    print(f"  平均每文件 : {avg_s:.2f}s")

    if ok_recs:
        slowest = sorted(ok_recs, key=lambda r: r.elapsed_seconds, reverse=True)[:5]
        print()
        print("  最慢 5 个文件：")
        for r in slowest:
            print(f"    {r.elapsed_seconds:6.2f}s  {r.file_name}")

    if err_recs:
        error_counts: dict[str, int] = {}
        for r in err_recs:
            k = r.error_type or "unknown"
            error_counts[k] = error_counts.get(k, 0) + 1
        print()
        print("  失败原因分布：")
        for etype, cnt in sorted(error_counts.items(), key=lambda x: -x[1]):
            print(f"    {etype:<20s}: {cnt}")
        print()
        print("  失败文件（前 5）：")
        for r in err_recs[:5]:
            print(f"    {r.file_name}  [{r.error_type}] {r.error_message[:60]}")

    high_pri = sorted(
        [r for r in records if r.is_high_priority],
        key=lambda r: r.risk_rank_score,
        reverse=True,
    )[:10]
    if high_pri:
        print()
        print(f"  高优先级文件（Top {len(high_pri)}，建议优先人工查看）：")
        for r in high_pri:
            print(f"    [{r.max_severity_label}] score={r.risk_rank_score:.0f}"
                  f"  events={r.event_count}  {r.file_name}")

    print()
    print(f"  索引文件   : {index_path}")
    print(f"  总结文件   : {summary_path}")


# ── 主入口 ─────────────────────────────────────────────────────────────────────

def run_scan(
    input_dir: Path,
    output_dir: Path,
    scan_cfg: ScanConfig,
    shared_cfg: Any = None,
) -> list[ScanRecord]:
    """
    批量扫描 input_dir，对每个文件运行规则诊断，生成 scan_index.csv 和 scan_summary.json。

    Returns:
        所有文件的 ScanRecord 列表（含跳过和失败）。
    """
    import time
    from tbm_diag.config import DiagConfig
    if shared_cfg is None:
        shared_cfg = DiagConfig()

    input_dir  = input_dir.resolve()
    output_dir = output_dir.resolve()

    if not input_dir.exists():
        print(f"✗ 输入目录不存在: {input_dir}", file=sys.stderr)
        sys.exit(2)

    output_dir.mkdir(parents=True, exist_ok=True)

    state_file = output_dir / _STATE_FILE_NAME
    state = ScanState(state_file)

    files = discover_files(input_dir, scan_cfg)
    if not files:
        print(f"⚠ 未在 {input_dir} 中找到匹配文件（patterns: {scan_cfg.file_patterns}）")
        return []

    # ── 扫描前摘要 ────────────────────────────────────────────────────────────
    ext_counts: dict[str, int] = {}
    total_size_mb = 0.0
    for f in files:
        ext = f.suffix.lower()
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
        try:
            total_size_mb += f.stat().st_size / (1024 * 1024)
        except OSError:
            pass

    print(f"\n[scan] 批量扫描启动")
    print(f"  输入目录   : {input_dir}")
    print(f"  输出目录   : {output_dir}")
    print(f"  递归扫描   : {scan_cfg.recursive}")
    print(f"  overwrite  : {scan_cfg.overwrite}")
    print(f"  文件总数   : {len(files)}")
    print(f"  总大小     : {total_size_mb:.1f} MB")
    for ext, cnt in sorted(ext_counts.items()):
        print(f"    {ext:<8s}: {cnt} 个")
    if scan_cfg.max_file_size_mb > 0:
        print(f"  大小限制   : {scan_cfg.max_file_size_mb} MB（超过则跳过）")
    print()

    # Ctrl+C 处理
    _stop = [False]

    def _on_sigint(sig, frame):  # noqa: ANN001
        _stop[0] = True
        print("\n[scan] 收到中断信号，正在安全退出…", file=sys.stderr)

    signal.signal(signal.SIGINT, _on_sigint)

    all_records: list[ScanRecord] = []
    n_ok = n_skip = n_err = 0
    width = len(str(len(files)))
    scan_start = time.monotonic()

    for i, file_path in enumerate(files, 1):
        if _stop[0]:
            break

        prefix = f"  [{i:>{width}}/{len(files)}]"

        # 文件大小检查
        if scan_cfg.max_file_size_mb > 0:
            try:
                size_mb = file_path.stat().st_size / (1024 * 1024)
                if size_mb > scan_cfg.max_file_size_mb:
                    stat = file_path.stat()
                    rec = ScanRecord(
                        file_name=file_path.name,
                        file_path=str(file_path.resolve()),
                        file_size=stat.st_size,
                        mtime=stat.st_mtime,
                        status="skipped",
                        processed_at=datetime.now().isoformat(),
                        error_type="file_too_large",
                        error_message=f"文件大小 {size_mb:.1f}MB 超过限制 {scan_cfg.max_file_size_mb}MB",
                    )
                    state.mark(rec)
                    all_records.append(rec)
                    n_skip += 1
                    print(f"{prefix} SKIP  {file_path.name}  (too large: {size_mb:.1f}MB)")
                    continue
            except OSError:
                pass

        # 断点续跑检查
        if state.should_skip(file_path, scan_cfg.overwrite):
            saved = state.get_saved(file_path)
            metrics = saved.get("metrics", {})
            outputs = saved.get("outputs", {})
            stat = file_path.stat()
            rec = ScanRecord(
                file_name=file_path.name,
                file_path=str(file_path.resolve()),
                file_size=stat.st_size,
                mtime=stat.st_mtime,
                status="skipped",
                processed_at=saved.get("processed_at", ""),
                total_rows=metrics.get("total_rows", 0),
                event_count=metrics.get("event_count", 0),
                max_severity_label=metrics.get("max_severity_label", ""),
                dominant_state_top1=metrics.get("dominant_state_top1", ""),
                top_event_type=metrics.get("top_event_type", ""),
                top_event_summary=metrics.get("top_event_summary", ""),
                json_path=outputs.get("json", ""),
                md_path=outputs.get("md", ""),
                events_csv_path=outputs.get("events_csv", ""),
                elapsed_seconds=saved.get("elapsed_seconds", 0.0),
                risk_rank_score=metrics.get("risk_rank_score", 0.0),
                is_high_priority=metrics.get("is_high_priority", False),
            )
            all_records.append(rec)
            n_skip += 1
            print(f"{prefix} SKIP  {file_path.name}")
            continue

        print(f"{prefix} 处理: {file_path.name} …", end="", flush=True)
        try:
            rec = process_file(file_path, output_dir, shared_cfg=shared_cfg)
            state.mark(rec)
            all_records.append(rec)
            n_ok += 1
            sev_tag = f"[{rec.max_severity_label}]" if rec.max_severity_label else "[无事件]"
            print(f" OK  {sev_tag} events={rec.event_count}  {rec.elapsed_seconds:.2f}s")
        except KeyboardInterrupt:
            _stop[0] = True
            print(" 中断", file=sys.stderr)
            stat = file_path.stat()
            rec = ScanRecord(
                file_name=file_path.name,
                file_path=str(file_path.resolve()),
                file_size=stat.st_size,
                mtime=stat.st_mtime,
                status="error",
                processed_at=datetime.now().isoformat(),
                error_type="runtime_error",
                error_message="用户中断",
            )
            all_records.append(rec)
            break
        except Exception as exc:
            err_msg = str(exc)
            err_type = _classify_error(err_msg)
            print(f" FAIL  [{err_type}] {err_msg[:60]}")
            logger.exception("Failed to process %s", file_path)
            stat = file_path.stat()
            rec = ScanRecord(
                file_name=file_path.name,
                file_path=str(file_path.resolve()),
                file_size=stat.st_size,
                mtime=stat.st_mtime,
                status="error",
                processed_at=datetime.now().isoformat(),
                error_type=err_type,
                error_message=err_msg,
            )
            state.mark(rec)
            all_records.append(rec)
            n_err += 1

    total_elapsed = time.monotonic() - scan_start

    index_path   = _write_scan_index(all_records, output_dir)
    summary_path = _write_scan_summary(all_records, total_elapsed, output_dir)

    _print_post_summary(all_records, total_elapsed, summary_path, index_path)

    return all_records
