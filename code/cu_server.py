"""Computer-Use Skill Dashboard Server  (Session 10).

Endpoints
---------
GET  /                          serve cu_dashboard.html
GET  /api/cu/tasks              task states + trajectory metadata (no image data)
GET  /api/cu/stream?task=X&since=N   SSE: new log lines since index N
POST /api/cu/run                {"task":"calculator","expr":"..."} -> start task
GET  /img/<task>/<filename>     serve individual PNG screenshots from trajectory dirs

Design: screenshots are never base64-inlined into JSON; the browser fetches
each PNG separately via /img/... so the initial API response stays small.
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

TRAJ_ROOT = ROOT / "state" / "trajectories"
FRONTEND  = ROOT / "frontend"
PORT      = 8080

# ── shared state ──────────────────────────────────────────────────────────────
_lock = threading.Lock()
_STATE: dict[str, dict] = {
    "calculator":    {"status": "idle", "layer": "L0+L1",        "desc": "Windows Calculator - zero vision"},
    "electron_note": {"status": "idle", "layer": "electron_cdp", "desc": "Electron/CDP - Playwright DOM - no OS AX tree"},
    "excel_word":    {"status": "idle", "layer": "L0+L1+L2a+L3", "desc": "Excel to Word - multi-app - vision verify"},
}
_LIVE_LOGS: dict[str, list[str]] = {k: [] for k in _STATE}

# ── background asyncio loop ───────────────────────────────────────────────────
_BG_LOOP: asyncio.AbstractEventLoop | None = None

def _start_bg_loop() -> None:
    global _BG_LOOP
    _BG_LOOP = asyncio.new_event_loop()
    _BG_LOOP.run_forever()

threading.Thread(target=_start_bg_loop, daemon=True, name="cu-async").start()
time.sleep(0.15)


# ── trajectory helpers ────────────────────────────────────────────────────────

def _latest_traj(task: str) -> dict | None:
    """Return lightweight trajectory metadata (no image bytes)."""
    dirs = sorted(TRAJ_ROOT.glob(f"{task}_*"), reverse=True)
    if not dirs:
        return None
    traj_dir = dirs[0]
    manifest_path = traj_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except Exception:
        return None

    # Build URL-accessible screenshot list — browser fetches via /img/...
    rel = traj_dir.name   # e.g. "calculator_20260619_125517"
    screenshots = [
        {"name": p.name, "url": f"/img/{rel}/{p.name}"}
        for p in sorted(traj_dir.glob("*.png"))
    ]

    return {
        "traj_dir":       str(traj_dir),
        "traj_rel":       rel,
        "elapsed_s":      manifest.get("elapsed_s", 0),
        "action_count":   manifest.get("action_count", 0),
        "screenshot_count": len(screenshots),
        "screenshots":    screenshots,
        "actions":        manifest.get("actions", []),
    }


# ── task runner ───────────────────────────────────────────────────────────────

async def _run_task(task: str, extra: dict) -> None:
    from computer_use.skill import ComputerUseSkill
    from schemas import NodeSpec

    with _lock:
        _STATE[task].update({"status": "running", "started_at": time.time(),
                              "result": None, "error": None, "traj": None})
    _LIVE_LOGS[task].clear()

    def log(msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        _LIVE_LOGS[task].append(f"[{ts}]  {msg}")
        if len(_LIVE_LOGS[task]) > 400:
            _LIVE_LOGS[task].pop(0)

    log(f"Starting: {task}")
    try:
        sk = ComputerUseSkill(trajectories_root=str(TRAJ_ROOT))
        meta: dict = {"task": task}
        if task == "calculator":
            meta["expression"] = extra.get("expr", "345 * 678 - 90")
        node = NodeSpec(skill="computer_use", inputs=[], metadata=meta)
        t0 = time.time()
        result = await sk.run(node)
        elapsed = round(time.time() - t0, 2)

        traj = _latest_traj(task)
        if traj:
            for act in traj.get("actions", []):
                layer  = act.get("layer", "?")
                action = act.get("action", "?")
                extras = "  ".join(
                    f"{k}={str(v)[:50]}"
                    for k, v in act.items()
                    if k not in ("t", "layer", "action")
                )
                log(f"[{layer}] {action}  {extras}")

        with _lock:
            _STATE[task].update({
                "status":    "success" if result.success else "failed",
                "elapsed_s": elapsed,
                "result":    result.output.get("content"),
                "layer":     result.output.get("layer_used", _STATE[task]["layer"]),
                "error":     result.error,
                "traj":      traj,
            })
        log(f"Done in {elapsed}s - {'OK' if result.success else 'FAILED'}")

    except Exception as exc:
        log(f"ERROR: {exc}")
        with _lock:
            _STATE[task].update({"status": "failed", "error": str(exc)})


def submit_task(task: str, extra: dict) -> None:
    assert _BG_LOOP is not None
    asyncio.run_coroutine_threadsafe(_run_task(task, extra), _BG_LOOP)


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass  # suppress access log

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj) -> None:
        self._send(200, "application/json", json.dumps(obj, default=str).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        qs     = parse_qs(parsed.query)

        # ── dashboard HTML ────────────────────────────────────────────────────
        if path in ("/", "/cu_dashboard.html"):
            data = (FRONTEND / "cu_dashboard.html").read_bytes()
            self._send(200, "text/html; charset=utf-8", data)

        # ── task state API ────────────────────────────────────────────────────
        elif path == "/api/cu/tasks":
            with _lock:
                snap = json.loads(json.dumps(_STATE, default=str))
            # fill traj for idle/done tasks that haven't been populated yet
            for task, state in snap.items():
                if "traj" not in state or state["traj"] is None:
                    t = _latest_traj(task)
                    if t:
                        snap[task]["traj"] = t
                        if snap[task]["status"] == "idle":
                            snap[task]["status"] = "success"
            self._json(snap)

        # ── SSE log stream ────────────────────────────────────────────────────
        elif path == "/api/cu/stream":
            task  = qs.get("task", [""])[0]
            since = int(qs.get("since", ["0"])[0])
            lines = _LIVE_LOGS.get(task, [])
            new   = lines[since:]
            body  = "".join(f"data: {json.dumps(l)}\n\n" for l in new) or ": keep-alive\n\n"
            self._send(200, "text/event-stream", body.encode())

        # ── screenshot file server ────────────────────────────────────────────
        # URL pattern: /img/<traj_dir_name>/<filename.png>
        elif path.startswith("/img/"):
            parts = path[5:].split("/", 1)   # strip leading "/img/"
            if len(parts) == 2:
                traj_rel, fname = parts
                img_path = TRAJ_ROOT / traj_rel / fname
                if img_path.exists() and img_path.suffix in (".png", ".jpg", ".jpeg"):
                    data = img_path.read_bytes()
                    self._send(200, "image/png", data)
                    return
            self._send(404, "text/plain", b"image not found")

        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        if urlparse(self.path).path == "/api/cu/run":
            length  = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            task    = payload.get("task", "calculator")
            extra   = {k: v for k, v in payload.items() if k != "task"}
            with _lock:
                if _STATE.get(task, {}).get("status") == "running":
                    self._json({"status": "already_running", "task": task})
                    return
            submit_task(task, extra)
            self._json({"status": "started", "task": task})
        else:
            self._send(404, "text/plain", b"not found")


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Pre-populate results + elapsed from last run_summary.json
    summary_path = TRAJ_ROOT / "run_summary.json"
    if summary_path.exists():
        try:
            for s in json.loads(summary_path.read_bytes()):
                task = s.get("task")
                if task in _STATE:
                    _STATE[task]["result"]    = s.get("content")
                    _STATE[task]["elapsed_s"] = s.get("elapsed_s")
                    _STATE[task]["layer"]     = s.get("layer_used", _STATE[task]["layer"])
        except Exception:
            pass
    # Pre-load trajectory metadata (screenshot lists, action counts)
    for task in _STATE:
        traj = _latest_traj(task)
        if traj:
            _STATE[task]["traj"]   = traj
            _STATE[task]["status"] = "success"

    server = HTTPServer(("", PORT), Handler)
    print(f"\n  Computer-Use Dashboard  ->  http://localhost:{PORT}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
