"""memory.py — 轻量 case 级别结构化记忆

输出到 investigation_out/case_memory.json，
保存 case 级别结果供跨文件比较复用。
不使用 embedding / 向量数据库。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tbm_diag.investigation.state import InvestigationState

logger = logging.getLogger(__name__)


def save_case_memory(state: InvestigationState, output_dir: str | Path) -> Path:
    """将 case 级别结果写入 case_memory.json。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "case_memory.json"

    records = []
    for file_path, cases in state.stoppage_cases.items():
        for case in cases:
            cls = state.case_classifications.get(case.case_id)
            ta = state.transition_analyses.get(case.case_id)

            record: dict[str, Any] = {
                "case_id": case.case_id,
                "file_path": case.file_path,
                "start_time": case.start_time,
                "end_time": case.end_time,
                "duration_seconds": case.duration_seconds,
                "merged_event_count": case.merged_event_count,
                "merged_event_ids": case.merged_event_ids,
            }

            if cls:
                record["case_type"] = cls.case_type
                record["confidence"] = cls.confidence
                record["reasons"] = cls.reasons

            if ta:
                record["pre_has_ser"] = ta.pre_has_ser
                record["pre_has_hyd"] = ta.pre_has_hyd
                record["pre_has_heavy_load"] = ta.pre_has_heavy_load
                record["post_has_anomaly"] = ta.post_has_anomaly

            records.append(record)

    out_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("case_memory saved: %d cases → %s", len(records), out_path)
    return out_path
