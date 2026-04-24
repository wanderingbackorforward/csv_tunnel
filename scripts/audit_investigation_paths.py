"""audit_investigation_paths.py — 对比多个文件的 investigate action 序列。

用法：
    python scripts/audit_investigation_paths.py \
        --inputs incoming/normal_segment.csv incoming/anomaly_segment.csv sample2.xls \
        --output-dir investigation_audit_compare
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run_one(file_path: str, output_dir: Path, max_iterations: int = 12) -> dict:
    from tbm_diag.investigation.controller import run_investigation
    result = run_investigation(
        input_files=[file_path],
        mode="single_file",
        output_dir=str(output_dir),
        use_llm=False,
        max_iterations=max_iterations,
        planner_audit=True,
    )
    actions = [a.action for a in result.state.actions_taken]
    reasons = [a.rationale for a in result.state.actions_taken]
    rejected_per_round = []
    for ar in result.state.audit_log:
        rejected_per_round.append(
            [f"{a}({r})" for a, r in zip(ar.rejected_actions, ar.rejected_reasons)]
        )
    return {
        "file": Path(file_path).name,
        "rounds": result.state.iteration_count,
        "action_sequence": actions,
        "reasons": reasons,
        "stop_reason": result.state.stop_reason,
        "rejected_per_round": rejected_per_round,
    }
# PLACEHOLDER_MAIN


def main():
    parser = argparse.ArgumentParser(description="对比多个文件的 investigate action 序列")
    parser.add_argument("--inputs", nargs="+", required=True, help="输入文件列表")
    parser.add_argument("--output-dir", default="investigation_audit_compare", help="输出目录")
    parser.add_argument("--max-iterations", type=int, default=12)
    args = parser.parse_args()

    output_base = Path(args.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    results = []
    for fp in args.inputs:
        p = Path(fp)
        if not p.exists():
            p = ROOT / fp
        if not p.exists():
            print(f"SKIP: {fp} not found")
            continue
        sub_dir = output_base / p.stem
        if sub_dir.exists():
            shutil.rmtree(sub_dir)
        print(f"\n{'='*60}")
        print(f"Running: {p.name}")
        print(f"{'='*60}")
        r = run_one(str(p), sub_dir, max_iterations=args.max_iterations)
        results.append(r)

    # 输出对比表
    print(f"\n\n{'='*80}")
    print("ACTION SEQUENCE COMPARISON")
    print(f"{'='*80}\n")

    header = f"{'file':<30} {'rounds':>6}  {'action_sequence':<60} {'stop_reason'}"
    print(header)
    print("-" * len(header))
    for r in results:
        seq = " → ".join(r["action_sequence"])
        print(f"{r['file']:<30} {r['rounds']:>6}  {seq:<60} {r['stop_reason']}")

    # 判定是否相同
    sequences = [tuple(r["action_sequence"]) for r in results]
    unique = set(sequences)
    print(f"\n唯一 action 序列数: {len(unique)} / {len(results)} 个文件")

    if len(unique) == 1 and len(results) > 1:
        print("\n*** 判定：所有文件走完全相同路径 — 当前不是真正动态 ReAct ***")
    elif len(unique) == len(results):
        print("\n*** 判定：每个文件走不同路径 — 路径选择基于文件特征 ***")
    else:
        print(f"\n*** 判定：{len(unique)} 种不同路径 — 部分动态 ***")

    # 详细对比
    print(f"\n{'='*80}")
    print("PER-FILE DETAIL")
    print(f"{'='*80}")
    for r in results:
        print(f"\n--- {r['file']} ({r['rounds']} rounds) ---")
        for i, (action, reason) in enumerate(zip(r["action_sequence"], r["reasons"])):
            rej = r["rejected_per_round"][i] if i < len(r["rejected_per_round"]) else []
            rej_str = f"  rejected: {rej}" if rej else ""
            print(f"  {i+1}. {action} — {reason}{rej_str}")

    # 保存 JSON
    compare_path = output_base / "comparison.json"
    compare_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n结果已保存: {compare_path}")


if __name__ == "__main__":
    main()