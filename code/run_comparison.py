"""Browser Comparison Agent — entry script.

Runs a comparison task through the growing-graph orchestrator and then
generates an HTML replay report showing all 8 required elements.

Default task: Compare the top 3 Hugging Face text-generation models
sorted by likes (requires browser interaction: filter by task,
sort by most likes, extract model cards).

Usage:
    # Run with the default task (top 3 HuggingFace text-gen models):
    python run_comparison.py

    # Run with a custom query:
    python run_comparison.py "Compare 5 AI coding tools by free plan and paid plan"

    # Resume a previous session:
    python run_comparison.py --resume <session_id>

    # Only generate the HTML report for an existing session:
    python run_comparison.py --report <session_id>

Output:
    - Terminal output from the orchestrator (live progress)
    - replay_report_<session_id>.html — self-contained HTML replay report
"""
from __future__ import annotations

import asyncio
import sys
import os

# Add code/ directory to path when run from repository root
sys.path.insert(0, os.path.dirname(__file__))


DEFAULT_QUERY = (
    "Compare the top 3 Hugging Face text-generation models sorted by most likes. "
    "Show model name, number of likes, number of downloads, and any available "
    "description or task tags."
)


def run_query(query: str, session_id: str | None = None, resume: bool = False) -> str:
    from flow import Executor
    return asyncio.run(
        Executor().run(query, session_id=session_id, resume=resume)
    )


def generate_report(session_id: str) -> None:
    from replay_report import generate
    from pathlib import Path
    out = Path(f"replay_report_{session_id}.html")
    generate(session_id, out)
    print(f"\n[run_comparison] HTML report: {out.resolve()}")


def main() -> None:
    args = sys.argv[1:]

    # --report <sid>: just (re-)generate the HTML report for an existing session
    if args and args[0] == "--report":
        sid = args[1] if len(args) > 1 else None
        if not sid:
            print("usage: python run_comparison.py --report <session_id>")
            sys.exit(1)
        generate_report(sid)
        return

    # --resume <sid> [query]: resume a paused session
    if args and args[0] == "--resume":
        sid = args[1] if len(args) > 1 else None
        query = " ".join(args[2:]) if len(args) > 2 else ""
        if not sid:
            print("usage: python run_comparison.py --resume <session_id>")
            sys.exit(1)
        print(f"[run_comparison] resuming session {sid}")
        run_query(query, session_id=sid, resume=True)
        generate_report(sid)
        return

    # Normal run: use provided query or the default
    query = " ".join(args) if args else DEFAULT_QUERY
    print("=" * 78)
    print("Browser Comparison Agent")
    print("=" * 78)
    print(f"Task: {query}")
    print()
    print("The orchestrator will:")
    print("  1. Planner  — decompose the query into a DAG")
    print("  2. Researcher — find candidate URLs")
    print("  3. Browser  — navigate & interact with the site (a11y or vision layers)")
    print("  4. Distiller — extract structured comparison fields")
    print("  5. Replay Viewer — aggregate all outputs")
    print("  6. Formatter — produce the final comparison table")
    print()

    # Run the orchestrator; session_id is auto-generated
    from flow import Executor
    import uuid
    sid = f"cmp-{uuid.uuid4().hex[:8]}"
    print(f"[run_comparison] session id: {sid}")

    asyncio.run(Executor().run(query, session_id=sid))

    print("\n[run_comparison] Run complete. Generating HTML replay report …")
    generate_report(sid)


if __name__ == "__main__":
    main()
