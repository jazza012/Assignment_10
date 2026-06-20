"""Session 10 — Computer-Use skill entry point.

Runs all three tasks (or a selected subset) using the 5-layer cascade,
records every run to state/trajectories/, and prints a summary table.

Usage
-----
    # All three tasks
    python run_tasks.py

    # Single task
    python run_tasks.py --task calculator
    python run_tasks.py --task electron_note
    python run_tasks.py --task excel_word

    # Custom Calculator expression
    python run_tasks.py --task calculator --expr "123 * 456 + 789"

Output
------
    state/trajectories/<task>_<timestamp>/manifest.json
    state/trajectories/<task>_<timestamp>/screenshot_*.png
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from computer_use.skill import ComputerUseSkill
from schemas import NodeSpec


async def run_task(skill: ComputerUseSkill, task: str, **meta) -> dict:
    node = NodeSpec(skill="computer_use", inputs=[], metadata={"task": task, **meta})
    result = await skill.run(node)
    return {
        "task": task,
        "success": result.success,
        "layer_used": result.output.get("layer_used", "?"),
        "content": result.output.get("content"),
        "traj_dir": result.output.get("traj_dir", ""),
        "elapsed_s": round(result.elapsed_s, 2),
        "error": result.error,
    }


async def main(tasks: list[str], expr: str = "345 * 678 - 90") -> None:
    skill = ComputerUseSkill(
        trajectories_root=str(ROOT / "state" / "trajectories"),
    )

    print("\n" + "=" * 60)
    print("  Session 10 — Computer-Use Skill  (5-layer cascade)")
    print("=" * 60)
    print(f"  Tasks to run: {', '.join(tasks)}")
    print("=" * 60 + "\n")

    results = []
    for task in tasks:
        print(f"[RUN] Task: {task}")
        meta = {}
        if task == "calculator":
            meta["expression"] = expr
        try:
            r = await run_task(skill, task, **meta)
        except Exception as exc:
            r = {"task": task, "success": False, "error": str(exc),
                 "layer_used": "?", "elapsed_s": 0}
        results.append(r)

        status = "[OK]" if r["success"] else "[FAIL]"
        print(f"  {status}  layer={r['layer_used']}  t={r['elapsed_s']}s")
        if r.get("content"):
            content_str = json.dumps(r["content"])[:120]
            print(f"     result: {content_str}")
        if r.get("traj_dir"):
            print(f"     traj:   {r['traj_dir']}")
        if r.get("error"):
            print(f"     error:  {r['error'][:120]}")
        print()

    # Summary table
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  {'Task':<18} {'Layer':<18} {'OK':>4} {'Time':>7}")
    print("  " + "-" * 50)
    for r in results:
        ok = "Yes" if r["success"] else "No"
        print(f"  {r['task']:<18} {r.get('layer_used','?'):<18} {ok:>4} {r['elapsed_s']:>6}s")
    print("=" * 60 + "\n")

    # Write combined results JSON
    out_path = ROOT / "state" / "trajectories" / "run_summary.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"  Full results: {out_path}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Session 10 Computer-Use tasks")
    parser.add_argument(
        "--task", choices=["calculator", "electron_note", "excel_word", "all"],
        default="all", help="Which task to run (default: all)"
    )
    parser.add_argument(
        "--expr", default="345 * 678 - 90",
        help="Arithmetic expression for the calculator task"
    )
    args = parser.parse_args()

    task_list = (
        ["calculator", "electron_note", "excel_word"]
        if args.task == "all"
        else [args.task]
    )

    asyncio.run(main(task_list, expr=args.expr))
