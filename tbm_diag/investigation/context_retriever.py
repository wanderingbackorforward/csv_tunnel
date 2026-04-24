"""context_retriever.py — 轻量上下文检索 (v1: 关键词 + 时间范围)

默认查找 context/ops_notes.md 和 context/*.csv。
不存在时返回 context_found=false。
不使用 embedding。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_KEYWORDS = [
    "停机", "换刀", "检修", "故障", "卡机", "地层", "班次", "交接",
]

_CONTEXT_DIR = Path("context")


def search_context(
    time_range: Optional[tuple[str, str]] = None,
    keywords: Optional[list[str]] = None,
    context_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """从 context/ 目录检索施工日志。"""
    ctx_dir = context_dir or _CONTEXT_DIR

    if not ctx_dir.exists():
        return {
            "status": "ok",
            "context_found": False,
            "message": f"上下文目录 {ctx_dir} 不存在，跳过施工日志检索",
        }

    kw_list = keywords or _DEFAULT_KEYWORDS
    matches: list[dict[str, str]] = []

    for f in sorted(ctx_dir.iterdir()):
        if f.suffix not in (".md", ".csv", ".txt"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for line_num, line in enumerate(text.splitlines(), 1):
            hit_kw = [kw for kw in kw_list if kw in line]
            if not hit_kw:
                continue
            if time_range:
                start, end = time_range
                if start not in line and end not in line:
                    date_match = re.search(r"\d{4}-\d{2}-\d{2}", line)
                    if date_match:
                        d = date_match.group()
                        if not (start[:10] <= d <= end[:10]):
                            continue
            matches.append({
                "file": f.name,
                "line": line_num,
                "text": line.strip()[:200],
                "keywords": hit_kw,
            })

    return {
        "status": "ok",
        "context_found": bool(matches),
        "matches_count": len(matches),
        "matches": matches[:20],
    }
