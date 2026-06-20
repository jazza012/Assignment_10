"""Generate a self-contained cu_dashboard.html with trajectory data embedded.

Reads the latest trajectory for each task, resizes screenshots to 280×175
thumbnails, base64-encodes them, and writes a standalone HTML file that
works from file:// (Launch preview panel) without a running server.

Run:  python generate_dashboard.py
Out:  frontend/cu_dashboard.html  (updated in-place)
"""
from __future__ import annotations
import base64, io, json
from pathlib import Path

ROOT      = Path(__file__).parent
TRAJ_ROOT = ROOT / "state" / "trajectories"
TEMPLATE  = ROOT / "frontend" / "cu_dashboard_template.html"
OUT       = ROOT / "frontend" / "cu_dashboard.html"
THUMB_W, THUMB_H = 280, 175

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


def thumb_b64(png_path: Path) -> str:
    if not PIL_OK:
        return ""
    img = Image.open(png_path).convert("RGB")
    img.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=72, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def latest_traj(task: str) -> dict | None:
    dirs = sorted(TRAJ_ROOT.glob(f"{task}_*"), reverse=True)
    if not dirs:
        return None
    traj_dir = dirs[0]
    manifest = traj_dir / "manifest.json"
    if not manifest.exists():
        return None
    data = json.loads(manifest.read_bytes())
    shots = []
    for p in sorted(traj_dir.glob("*.png")):
        shots.append({"name": p.name,
                      "url": f"/img/{traj_dir.name}/{p.name}",
                      "thumb": thumb_b64(p)})
    return {
        "traj_dir": str(traj_dir),
        "traj_rel": traj_dir.name,
        "elapsed_s": data.get("elapsed_s", 0),
        "action_count": data.get("action_count", 0),
        "screenshot_count": len(shots),
        "screenshots": shots,
        "actions": data.get("actions", []),
    }


def build_embedded() -> dict:
    tasks = ["calculator", "electron_note", "excel_word"]
    embedded: dict = {}

    # pull latest results from run_summary.json
    summary: dict = {}
    sp = TRAJ_ROOT / "run_summary.json"
    if sp.exists():
        for s in json.loads(sp.read_bytes()):
            summary[s["task"]] = s

    for task in tasks:
        traj = latest_traj(task)
        s    = summary.get(task, {})
        embedded[task] = {
            "status":    "success" if traj else "idle",
            "elapsed_s": s.get("elapsed_s"),
            "result":    s.get("content"),
            "layer":     s.get("layer_used", ""),
            "error":     s.get("error"),
            "traj":      traj,
        }
    return embedded


def generate() -> None:
    embedded = build_embedded()

    # Read the template (same file, marker replaced)
    src = TEMPLATE.read_text(encoding="utf-8") if TEMPLATE.exists() else OUT.read_text(encoding="utf-8")

    # Inject EMBEDDED_DATA into the <script> block
    json_blob = json.dumps(embedded, ensure_ascii=False)
    injection = f"\nconst EMBEDDED_DATA = {json_blob};\n"

    if "/* EMBEDDED_DATA_PLACEHOLDER */" in src:
        src = src.replace("/* EMBEDDED_DATA_PLACEHOLDER */", injection)
    else:
        # Insert before the closing </script> of the first script block
        src = src.replace(
            "// ── config ─",
            injection + "\n// ── config ─",
            1,
        )

    OUT.write_text(src, encoding="utf-8")
    total_shots = sum(
        len(v.get("traj", {}).get("screenshots", []) or [])
        for v in embedded.values()
    )
    print(f"Generated {OUT}  ({total_shots} thumbnails embedded)")


if __name__ == "__main__":
    generate()
