"""Generate a self-contained HTML replay report from a completed session.

Reads the NodeState records from state/sessions/<sid>/ and the browser
artifacts (screenshots, legends) from state/sessions/<sid>/browser/ and
produces a single HTML file showing all 8 required report elements:

  1. Original user goal
  2. Planner DAG
  3. Browser path chosen
  4. Browser actions taken
  5. Screenshots or page-state logs
  6. Extracted data
  7. Final comparison table
  8. Turn count and cost summary

Usage:
    python replay_report.py <session_id>
    python replay_report.py <session_id> --out report.html
"""
from __future__ import annotations

import base64
import html as html_lib
import json
import sys
from pathlib import Path

from persistence import SessionStore, list_sessions
from schemas import NodeState


# ── helpers ───────────────────────────────────────────────────────────────────

def _esc(s: object) -> str:
    return html_lib.escape(str(s) if s is not None else "")


def _json_pretty(obj: object) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)


def _img_tag(path: Path) -> str:
    """Return an <img> tag with the image embedded as base64, or empty string."""
    if not path.exists():
        return ""
    try:
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode()
        ext = path.suffix.lstrip(".").lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
        return f'<img src="data:{mime};base64,{b64}" style="max-width:100%;border:1px solid #ccc;border-radius:4px;margin:4px 0;" />'
    except Exception:
        return ""


def _md_table_to_html(md: str) -> str:
    """Convert a markdown pipe-table to an HTML <table>. Best-effort."""
    lines = [l.strip() for l in md.strip().splitlines() if l.strip()]
    rows = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return f"<pre>{_esc(md)}</pre>"
    out = ['<table class="comparison-table">']
    header = rows[0]
    out.append("<thead><tr>" + "".join(f"<th>{_esc(c)}</th>" for c in header) + "</tr></thead>")
    out.append("<tbody>")
    for row in rows[2:]:  # skip separator row
        out.append("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


# ── data extraction from session ─────────────────────────────────────────────

def _collect_session(sid: str) -> dict:
    store = SessionStore(sid)
    query = store.read_query() or ""
    # Read node files explicitly with UTF-8 to avoid Windows cp1252 decode errors
    # on emoji/unicode content written by the orchestrator.
    nodes: list[NodeState] = []
    import sys as _sys
    for p in sorted(store.nodes_dir.glob("n_*.json")):
        try:
            nodes.append(NodeState.model_validate_json(p.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"[replay_report] WARNING: skipped {p.name}: {type(e).__name__}: {e}",
                  file=_sys.stderr)
    browser_root = store.dir / "browser"

    # Walk nodes in file order (n_001, n_002, …) — they were written
    # sequentially so this reflects execution order.
    dag_skills: list[str] = []
    planner_outputs: list[dict] = []
    browser_nodes: list[dict] = []
    distiller_nodes: list[dict] = []
    replay_output: dict = {}
    formatter_output: dict = {}
    critic_nodes: list[dict] = []
    total_elapsed = 0.0

    for ns in nodes:
        dag_skills.append(ns.skill)
        r = ns.result
        if r is None:
            continue
        total_elapsed += r.elapsed_s or 0.0
        o = r.output or {}

        if ns.skill == "planner":
            planner_outputs.append(o)
        elif ns.skill == "browser":
            browser_nodes.append({
                "node_id": ns.node_id,
                "url": o.get("url", ""),
                "goal": o.get("goal", ""),
                "path": o.get("path", "unknown"),
                "turns": o.get("turns", 0),
                "actions": o.get("actions") or [],
                "content_snippet": (o.get("content") or "")[:600],
                "final_url": o.get("final_url", ""),
                "success": r.success,
                "error": r.error,
            })
        elif ns.skill == "distiller":
            distiller_nodes.append({
                "node_id": ns.node_id,
                "fields": o.get("fields") or {},
                "rationale": o.get("rationale", ""),
            })
        elif ns.skill == "replay_viewer":
            replay_output = o
        elif ns.skill == "formatter":
            formatter_output = o
        elif ns.skill == "critic":
            verdict = o.get("verdict") or o.get("pass") or o.get("result", "")
            critic_nodes.append({
                "node_id": ns.node_id,
                "verdict": verdict,
                "rationale": o.get("rationale", ""),
            })

    # Collect screenshots/legends from browser artifact directory
    screenshots: list[Path] = []
    legends: list[tuple[str, str]] = []  # (filename, text)
    if browser_root.exists():
        for subdir in sorted(browser_root.iterdir()):
            if not subdir.is_dir():
                continue
            for layer_dir in sorted(subdir.iterdir()):
                if not layer_dir.is_dir():
                    continue
                for f in sorted(layer_dir.iterdir()):
                    if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                        screenshots.append(f)
                    elif f.name.endswith("_legend.txt"):
                        legends.append((f.name, f.read_text(errors="replace")))

    # Total browser turns across all browser nodes
    total_browser_turns = sum(b.get("turns", 0) for b in browser_nodes)
    browser_paths_used = list({b["path"] for b in browser_nodes})

    return {
        "sid": sid,
        "query": query,
        "dag_skills": dag_skills,
        "planner_outputs": planner_outputs,
        "browser_nodes": browser_nodes,
        "distiller_nodes": distiller_nodes,
        "replay_output": replay_output,
        "formatter_output": formatter_output,
        "critic_nodes": critic_nodes,
        "screenshots": screenshots,
        "legends": legends,
        "total_elapsed": total_elapsed,
        "total_browser_turns": total_browser_turns,
        "browser_paths_used": browser_paths_used,
        "node_count": len(nodes),
    }


# ── HTML report ───────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f5f5f5; color: #222; line-height: 1.5; }
.container { max-width: 1100px; margin: 0 auto; padding: 24px; }
h1 { font-size: 1.6rem; font-weight: 700; color: #1a1a2e; margin-bottom: 4px; }
.subtitle { color: #666; font-size: 0.9rem; margin-bottom: 28px; }
.section { background: #fff; border-radius: 10px; padding: 20px 24px;
           margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.section-title { font-size: 1.05rem; font-weight: 700; color: #1a1a2e;
                 border-left: 4px solid #4f46e5; padding-left: 10px;
                 margin-bottom: 14px; }
.badge { display:inline-block; padding:2px 8px; border-radius:4px;
         font-size:0.78rem; font-weight:600; margin-right:6px; }
.badge-a11y   { background:#dbeafe; color:#1d4ed8; }
.badge-vision { background:#ede9fe; color:#6d28d9; }
.badge-extract { background:#d1fae5; color:#065f46; }
.badge-deterministic { background:#fef9c3; color:#854d0e; }
.badge-blocked { background:#fee2e2; color:#991b1b; }
pre { background:#f8f8f8; border:1px solid #e5e5e5; border-radius:6px;
      padding:12px; font-size:0.78rem; overflow-x:auto; white-space:pre-wrap;
      word-break:break-word; }
code { font-family: 'JetBrains Mono', 'Fira Code', monospace; }
.dag-flow { display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
.dag-node { background:#f0f0ff; border:1px solid #c7c7f5; border-radius:20px;
            padding:3px 12px; font-size:0.82rem; color:#312e81; font-weight:500; }
.dag-arrow { color:#aaa; font-size:1.1rem; }
.action-table { width:100%; border-collapse:collapse; font-size:0.84rem; }
.action-table th { background:#f0f0ff; color:#312e81; font-weight:600;
                   padding:7px 12px; text-align:left; border:1px solid #e0e0ff; }
.action-table td { padding:6px 12px; border:1px solid #ebebeb; vertical-align:top; }
.action-table tr:nth-child(even) td { background:#fafafa; }
.comparison-table { width:100%; border-collapse:collapse; font-size:0.87rem; }
.comparison-table th { background:#4f46e5; color:#fff; padding:9px 14px;
                       text-align:left; font-weight:600; }
.comparison-table td { padding:8px 14px; border:1px solid #e0e0e0; vertical-align:top; }
.comparison-table tr:nth-child(even) td { background:#f8f8ff; }
.fields-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(250px,1fr));
               gap:10px; }
.field-card { background:#f8f8ff; border:1px solid #e0e0ff; border-radius:6px;
              padding:10px 14px; }
.field-name { font-size:0.75rem; font-weight:600; color:#6366f1; text-transform:uppercase;
              letter-spacing:.05em; margin-bottom:3px; }
.field-value { font-size:0.88rem; color:#222; }
.stat-row { display:flex; gap:20px; flex-wrap:wrap; }
.stat-box { background:#f8f8ff; border:1px solid #e0e0ff; border-radius:8px;
            padding:12px 18px; min-width:130px; }
.stat-label { font-size:0.72rem; font-weight:600; color:#6366f1; text-transform:uppercase;
              letter-spacing:.05em; }
.stat-value { font-size:1.4rem; font-weight:700; color:#1a1a2e; }
.screenshot-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(320px,1fr));
                   gap:12px; }
.screenshot-card { border:1px solid #e0e0ff; border-radius:8px; overflow:hidden; }
.screenshot-label { background:#f0f0ff; padding:6px 10px; font-size:0.78rem;
                    font-weight:600; color:#312e81; }
.final-answer { font-size:0.93rem; white-space:pre-wrap; }
"""

def _section(title: str, body: str) -> str:
    return (
        f'<div class="section">'
        f'<div class="section-title">{_esc(title)}</div>'
        f'{body}'
        f'</div>'
    )


def _path_badge(path: str) -> str:
    cls = {
        "a11y": "badge-a11y",
        "vision": "badge-vision",
        "extract": "badge-extract",
        "deterministic": "badge-deterministic",
        "blocked": "badge-blocked",
    }.get(path, "badge-extract")
    return f'<span class="badge {cls}">{_esc(path)}</span>'


def build_html(data: dict) -> str:
    sid = data["sid"]
    query = data["query"]
    dag_skills = data["dag_skills"]
    browser_nodes = data["browser_nodes"]
    distiller_nodes = data["distiller_nodes"]
    replay_output = data["replay_output"]
    formatter_output = data["formatter_output"]
    critic_nodes = data["critic_nodes"]
    screenshots = data["screenshots"]
    legends = data["legends"]
    total_elapsed = data["total_elapsed"]
    total_browser_turns = data["total_browser_turns"]
    browser_paths_used = data["browser_paths_used"]
    node_count = data["node_count"]

    sections: list[str] = []

    # ── 1. Original User Goal ──────────────────────────────────────────────
    goal_body = f'<p style="font-size:1.05rem;font-weight:600;color:#1a1a2e;">{_esc(query)}</p>'
    goal_body += f'<p style="color:#666;font-size:0.84rem;margin-top:8px;">Session: <code>{_esc(sid)}</code></p>'
    sections.append(_section("1. Original User Goal", goal_body))

    # ── 2. Planner DAG ────────────────────────────────────────────────────
    # Deduplicate while preserving order for DAG display
    seen, unique_skills = set(), []
    for s in dag_skills:
        if s not in seen:
            seen.add(s)
            unique_skills.append(s)
    dag_html = '<div class="dag-flow">'
    for i, s in enumerate(unique_skills):
        dag_html += f'<span class="dag-node">{_esc(s)}</span>'
        if i < len(unique_skills) - 1:
            dag_html += '<span class="dag-arrow">→</span>'
    dag_html += '</div>'

    # If replay_viewer emitted a planner_dag description, add it
    rv_dag = replay_output.get("planner_dag") or {}
    if isinstance(rv_dag, dict) and rv_dag.get("description"):
        dag_html += f'<p style="margin-top:10px;color:#555;font-size:0.85rem;">{_esc(rv_dag["description"])}</p>'
    sections.append(_section("2. Planner DAG", dag_html))

    # ── 3. Browser Path Chosen ────────────────────────────────────────────
    path_chosen = replay_output.get("browser_path") or (
        browser_nodes[0]["path"] if browser_nodes else "unknown"
    )
    path_body = _path_badge(path_chosen)
    if len(browser_paths_used) > 1:
        path_body += f'<p style="margin-top:8px;font-size:0.84rem;color:#555;">Layers tried: {", ".join(_esc(p) for p in browser_paths_used)}</p>'

    if browser_nodes:
        if len(browser_nodes) == 1:
            bn = browser_nodes[0]
            path_body += f'<p style="margin-top:8px;font-size:0.84rem;"><strong>URL:</strong> {_esc(bn["url"])}</p>'
            if bn.get("final_url") and bn["final_url"] != bn["url"]:
                path_body += f'<p style="font-size:0.84rem;"><strong>Final URL:</strong> {_esc(bn["final_url"])}</p>'
            if bn.get("goal"):
                path_body += f'<p style="font-size:0.84rem;"><strong>Goal:</strong> {_esc(bn["goal"])}</p>'
        else:
            # Multiple browser nodes — show all in a compact table
            path_body += '<table class="action-table" style="margin-top:10px;">'
            path_body += '<thead><tr><th>#</th><th>URL</th><th>Path</th><th>Turns</th><th>Goal</th></tr></thead><tbody>'
            for i, bn in enumerate(browser_nodes, 1):
                path_body += (
                    f'<tr><td>{i}</td>'
                    f'<td><a href="{_esc(bn["url"])}" style="color:#4f46e5;font-size:0.82rem;">{_esc(bn["url"][:60])}</a></td>'
                    f'<td>{_path_badge(bn["path"])}</td>'
                    f'<td>{bn["turns"]}</td>'
                    f'<td style="font-size:0.8rem;">{_esc((bn.get("goal") or "")[:80])}</td>'
                    f'</tr>'
                )
            path_body += '</tbody></table>'
    sections.append(_section("3. Browser Path Chosen", path_body))

    # ── 4. Browser Actions Taken ──────────────────────────────────────────
    rv_actions = replay_output.get("browser_actions") or []
    # Fall back to raw browser node actions
    if not rv_actions and browser_nodes:
        for bn in browser_nodes:
            for a in bn.get("actions") or []:
                acts = a.get("actions") or []
                act_str = "; ".join(
                    f"{x.get('type','?')}({x.get('mark') or x.get('value','')})"
                    for x in acts
                )
                rv_actions.append({
                    "turn": a.get("turn", "?"),
                    "action": act_str or "(no actions)",
                    "outcome": a.get("outcome", ""),
                })

    if rv_actions:
        rows = ""
        for a in rv_actions:
            rows += (
                f"<tr><td>{_esc(a.get('turn',''))}</td>"
                f"<td>{_esc(a.get('action',''))}</td>"
                f"<td>{_esc(a.get('outcome',''))}</td></tr>"
            )
        actions_body = (
            '<table class="action-table">'
            '<thead><tr><th>Turn</th><th>Action</th><th>Outcome</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )
    else:
        actions_body = '<p style="color:#888;">No browser actions recorded.</p>'

    page_log = replay_output.get("page_state_log") or ""
    if page_log:
        actions_body += f'<div style="margin-top:14px;"><strong>Page State Log:</strong><pre>{_esc(page_log)}</pre></div>'
    sections.append(_section("4. Browser Actions Taken", actions_body))

    # ── 5. Screenshots / Page-State Logs ─────────────────────────────────
    ss_body = ""
    if screenshots:
        ss_body += '<div class="screenshot-grid">'
        for p in screenshots[:20]:  # cap at 20
            tag = _img_tag(p)
            if tag:
                ss_body += (
                    f'<div class="screenshot-card">'
                    f'<div class="screenshot-label">{_esc(p.name)}</div>'
                    f'<div style="padding:8px;">{tag}</div>'
                    f'</div>'
                )
        ss_body += "</div>"

    if legends:
        ss_body += '<div style="margin-top:16px;">'
        for name, text in legends[:10]:
            ss_body += f'<details style="margin-bottom:8px;"><summary style="cursor:pointer;font-weight:600;font-size:0.84rem;">{_esc(name)}</summary><pre style="margin-top:6px;">{_esc(text[:3000])}</pre></details>'
        ss_body += "</div>"

    if not ss_body:
        ss_body = '<p style="color:#888;">No screenshots captured (extract path uses static HTML, no browser launch required).</p>'
        # Show content snippets from all browser nodes
        for bn in browser_nodes:
            snippet = bn.get("content_snippet") or ""
            if snippet:
                ss_body += (
                    f'<details style="margin-top:10px;"><summary style="cursor:pointer;font-weight:600;font-size:0.84rem;">'
                    f'Page content: {_esc(bn["url"][:70])}</summary>'
                    f'<pre style="margin-top:6px;">{_esc(snippet)}</pre></details>'
                )
    sections.append(_section("5. Screenshots / Page-State Logs", ss_body))

    # ── 6. Extracted Data ─────────────────────────────────────────────────
    rv_extracted = replay_output.get("extracted_data") or []
    extracted_body = ""

    if rv_extracted and isinstance(rv_extracted, list):
        for item in rv_extracted:
            if not isinstance(item, dict):
                continue
            item_name = item.get("item", "Item")
            fields = item.get("fields") or {}
            extracted_body += f'<h3 style="font-size:0.9rem;font-weight:700;color:#4f46e5;margin:12px 0 8px;">{_esc(item_name)}</h3>'
            extracted_body += '<div class="fields-grid">'
            for k, v in fields.items():
                extracted_body += (
                    f'<div class="field-card">'
                    f'<div class="field-name">{_esc(k)}</div>'
                    f'<div class="field-value">{_esc(v)}</div>'
                    f'</div>'
                )
            extracted_body += "</div>"
    elif distiller_nodes:
        for i, dn in enumerate(distiller_nodes, 1):
            extracted_body += f'<h3 style="font-size:0.9rem;font-weight:700;color:#4f46e5;margin:12px 0 8px;">Item {i} ({dn["node_id"]})</h3>'
            fields = dn.get("fields") or {}
            if fields:
                extracted_body += '<div class="fields-grid">'
                for k, v in fields.items():
                    extracted_body += (
                        f'<div class="field-card">'
                        f'<div class="field-name">{_esc(k)}</div>'
                        f'<div class="field-value">{_esc(v)}</div>'
                        f'</div>'
                    )
                extracted_body += "</div>"
    else:
        extracted_body = '<p style="color:#888;">No structured extracted data found.</p>'

    sections.append(_section("6. Extracted Data", extracted_body))

    # ── 7. Final Comparison Table ─────────────────────────────────────────
    table_md = replay_output.get("comparison_table_md") or ""
    final_answer = formatter_output.get("final_answer") or ""

    table_body = ""
    if table_md and "|" in table_md:
        table_body += _md_table_to_html(table_md)
    if final_answer:
        table_body += f'<div style="margin-top:{"16px" if table_body else "0"};"><strong>Formatted Answer:</strong><pre class="final-answer">{_esc(final_answer)}</pre></div>'

    if not table_body:
        table_body = '<p style="color:#888;">No comparison table generated.</p>'
    sections.append(_section("7. Final Comparison Table", table_body))

    # ── 8. Turn Count and Cost Summary ───────────────────────────────────
    rv_cost = replay_output.get("cost_summary") or {}
    rv_turn_count = replay_output.get("turn_count") or total_browser_turns
    critic_feedback = replay_output.get("critic_feedback") or (
        critic_nodes[0]["verdict"] if critic_nodes else "none"
    )

    stats_html = '<div class="stat-row">'
    stats_html += (
        f'<div class="stat-box"><div class="stat-label">Browser Turns</div>'
        f'<div class="stat-value">{_esc(rv_turn_count)}</div></div>'
    )
    stats_html += (
        f'<div class="stat-box"><div class="stat-label">Total Nodes</div>'
        f'<div class="stat-value">{node_count}</div></div>'
    )
    stats_html += (
        f'<div class="stat-box"><div class="stat-label">Total Time</div>'
        f'<div class="stat-value">{total_elapsed:.1f}s</div></div>'
    )
    stats_html += (
        f'<div class="stat-box"><div class="stat-label">Browser Path</div>'
        f'<div class="stat-value" style="font-size:1rem;">{_esc(path_chosen)}</div></div>'
    )
    stats_html += "</div>"

    if rv_cost.get("note"):
        stats_html += f'<p style="margin-top:12px;color:#555;font-size:0.85rem;">{_esc(rv_cost["note"])}</p>'
    if rv_cost.get("browser_layers_used"):
        layers = rv_cost["browser_layers_used"]
        stats_html += f'<p style="margin-top:6px;font-size:0.84rem;"><strong>Layers tried:</strong> {", ".join(_esc(l) for l in layers)}</p>'
    if critic_feedback and critic_feedback != "none":
        stats_html += f'<p style="margin-top:6px;font-size:0.84rem;"><strong>Critic verdict:</strong> {_esc(str(critic_feedback))}</p>'

    sections.append(_section("8. Turn Count and Cost Summary", stats_html))

    # ── assemble page ─────────────────────────────────────────────────────
    body = "\n".join(sections)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Browser Agent Replay — {_esc(sid)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
<h1>Browser Comparison Agent — Replay Report</h1>
<p class="subtitle">Session: {_esc(sid)} &nbsp;|&nbsp; Generated by replay_report.py</p>
{body}
</div>
</body>
</html>
"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def generate(session_id: str, out_path: Path | None = None) -> Path:
    data = _collect_session(session_id)
    html = build_html(data)
    if out_path is None:
        out_path = Path("replay_report_" + session_id + ".html")
    out_path.write_text(html, encoding="utf-8")
    print(f"[replay_report] wrote {out_path.resolve()}")
    return out_path


def main() -> int:
    args = sys.argv[1:]
    if not args:
        sessions = list_sessions()
        if not sessions:
            print("replay_report: no sessions under state/sessions/", file=sys.stderr)
            return 2
        print("available sessions:")
        for s in sessions:
            print(f"  {s}")
        print("\nusage: python replay_report.py <session_id> [--out report.html]")
        return 0

    sid = args[0]
    out = None
    if "--out" in args:
        idx = args.index("--out")
        if idx + 1 < len(args):
            out = Path(args[idx + 1])

    generate(sid, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
