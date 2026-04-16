"""
watcher.py — 目录轮询监听器

功能：
- 每隔 N 秒扫描输入目录中的 *.csv 文件
- 对新文件自动运行 detect 流程（复用现有主链路）
- 每个文件产出：{stem}.json / {stem}_report.md / {stem}_events.csv
- 已处理记录持久化到 state_file（JSON），避免重复处理
- Ctrl+C 安全退出

不引入任何额外依赖，纯标准库 + 项目内模块。
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Windows 控制台默认 GBK，强制 stdout/stderr 使用 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger(__name__)


# ── 状态管理 ───────────────────────────────────────────────────────────────────

class ProcessedState:
    """
    已处理文件的持久化记录。

    格式（JSON）：
      {
        "processed": {
          "/abs/path/to/file.csv": {
            "processed_at": "2024-01-01T08:00:00",
            "status": "ok" | "error",
            "output_dir": "...",
            "error": "..."   # 仅 status=error 时存在
          }
        }
      }
    """

    def __init__(self, state_file: Path) -> None:
        self._path = state_file
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._data = raw.get("processed", {})
                logger.debug("State loaded: %d entries from %s", len(self._data), self._path)
            except Exception as exc:
                logger.warning("Failed to load state file %s: %s — starting fresh", self._path, exc)
                self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"processed": self._data}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def is_processed(self, csv_path: Path) -> bool:
        return str(csv_path.resolve()) in self._data

    def mark_ok(self, csv_path: Path, output_dir: Path) -> None:
        self._data[str(csv_path.resolve())] = {
            "processed_at": datetime.now().isoformat(),
            "status": "ok",
            "output_dir": str(output_dir),
        }
        self._save()

    def mark_error(self, csv_path: Path, error: str) -> None:
        self._data[str(csv_path.resolve())] = {
            "processed_at": datetime.now().isoformat(),
            "status": "error",
            "error": error,
        }
        self._save()

    def __len__(self) -> int:
        return len(self._data)


# ── 单文件处理 ─────────────────────────────────────────────────────────────────

def _process_one(csv_path: Path, output_dir: Path, cfg: "Any" = None) -> None:
    """
    对单个 CSV 文件运行完整 detect 流程并导出三种结果。

    复用现有主链路：load_csv → clean → enrich_features → detect
                    → segment_events → extract_evidence → explain
                    → to_json / to_markdown / to_events_csv

    Raises:
        任何异常都向上抛出，由调用方记录到 state。
    """
    # 延迟导入，避免循环依赖
    from tbm_diag.cleaning import clean
    from tbm_diag.config import DiagConfig
    from tbm_diag.detector import detect
    from tbm_diag.evidence import extract_evidence
    from tbm_diag.explainer import TemplateExplainer
    from tbm_diag.exporter import ResultBundle, to_events_csv, to_json, to_markdown
    from tbm_diag.feature_engine import enrich_features
    from tbm_diag.ingestion import load_csv
    from tbm_diag.segmenter import segment_events

    if cfg is None:
        cfg = DiagConfig()

    stem = csv_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    cc = cfg.cleaning
    resample_freq = None if (cc.resample or "").strip().lower() == "none" else cc.resample

    # ── 加载 ──────────────────────────────────────────────────────────────────
    ingestion = load_csv(str(csv_path))

    # ── 清洗 ──────────────────────────────────────────────────────────────────
    df, cleaning = clean(
        ingestion.df,
        resample_freq=resample_freq,
        spike_k=cc.spike_k,
        fill_method=cc.fill,
        max_gap_fill=cc.max_gap,
    )

    # ── 特征 + 检测 ───────────────────────────────────────────────────────────
    enriched = enrich_features(df, window=cfg.feature.rolling_window)
    detection = detect(enriched, config=cfg.detector)

    # ── 分段 + 证据 + 解释 ────────────────────────────────────────────────────
    events = segment_events(detection.df, config=cfg.segmenter)
    evidences = extract_evidence(enriched, events)
    explanations = TemplateExplainer().explain_all(evidences)

    # ── 导出 ──────────────────────────────────────────────────────────────────
    bundle = ResultBundle(
        input_file=str(csv_path),
        ingestion=ingestion,
        cleaning=cleaning,
        detection=detection,
        events=events,
        evidences=evidences,
        explanations=explanations,
    )

    to_json(bundle,        output_dir / f"{stem}.json")
    to_markdown(bundle,    output_dir / f"{stem}_report.md")
    to_events_csv(bundle,  output_dir / f"{stem}_events.csv")


# ── 主循环 ─────────────────────────────────────────────────────────────────────

def run_watch_loop(
    input_dir: Path,
    output_dir: Path,
    interval: float = 3.0,
    state_file: Optional[Path] = None,
    cfg: "Any" = None,
) -> None:
    """
    轮询监听 input_dir，对新 CSV 文件自动运行 detect 流程。

    Args:
        input_dir:  监听的输入目录
        output_dir: 结果输出目录
        interval:   轮询间隔（秒）；None 时从 cfg.cli.watch_interval 读取
        state_file: 已处理记录文件路径；None 时默认放在 output_dir/.watcher_state.json
        cfg:        DiagConfig；None 时使用全默认值
    """
    from tbm_diag.config import DiagConfig
    if cfg is None:
        cfg = DiagConfig()
    # interval 参数优先；若调用方传入默认值 3.0 且配置文件有不同值，以配置文件为准
    # 这里约定：调用方显式传入时覆盖配置，否则用配置值
    # （CLI 层已处理优先级，此处直接使用传入值）

    input_dir  = input_dir.resolve()
    output_dir = output_dir.resolve()

    if not input_dir.exists():
        input_dir.mkdir(parents=True, exist_ok=True)
        print(f"  已创建输入目录: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    if state_file is None:
        state_file = output_dir / ".watcher_state.json"

    state = ProcessedState(state_file)

    # ── 注册 Ctrl+C 处理 ──────────────────────────────────────────────────────
    _stop = [False]

    def _on_sigint(sig, frame):  # noqa: ANN001
        _stop[0] = True

    signal.signal(signal.SIGINT, _on_sigint)

    print(f"\n[watcher] 开始监听")
    print(f"  输入目录 : {input_dir}")
    print(f"  输出目录 : {output_dir}")
    print(f"  轮询间隔 : {interval}s")
    print(f"  状态文件 : {state_file}")
    print(f"  历史记录 : {len(state)} 个文件已处理")
    print(f"  按 Ctrl+C 退出\n")

    while not _stop[0]:
        csv_files = sorted(input_dir.glob("*.csv"))
        new_files = [f for f in csv_files if not state.is_processed(f)]

        if new_files:
            print(f"[{_now()}] 发现 {len(new_files)} 个新文件")

        for csv_path in new_files:
            if _stop[0]:
                break
            print(f"  → 处理: {csv_path.name} …", end="", flush=True)
            try:
                _process_one(csv_path, output_dir, cfg=cfg)
                state.mark_ok(csv_path, output_dir)
                stem = csv_path.stem
                print(
                    f" OK  "
                    f"[{stem}.json / {stem}_report.md / {stem}_events.csv]"
                )
            except Exception as exc:
                state.mark_error(csv_path, str(exc))
                print(f" FAIL  {exc}")
                logger.exception("Failed to process %s", csv_path)

        # 等待下一轮，每 0.2s 检查一次 stop 标志以保证 Ctrl+C 响应及时
        elapsed = 0.0
        while elapsed < interval and not _stop[0]:
            time.sleep(0.2)
            elapsed += 0.2

    print(f"\n[watcher] 已停止（共处理 {len(state)} 个文件）")


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")
