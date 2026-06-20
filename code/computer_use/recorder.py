"""Trajectory recorder for the Computer-Use skill.

Every task run calls start_recording() to open a new trajectory directory,
then logs() actions and screenshots as the cascade runs.  stop_recording()
finalises the manifest and returns a path-annotated summary dict.

Directory layout (one per task run):
    trajectories/<task_id>_<timestamp>/
        manifest.json         action log + cascade decisions
        screenshot_00.png     one PNG per log_screenshot call
        screenshot_01.png
        ...
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ── optional screenshot support ────────────────────────────────────────────────
try:
    import PIL.ImageGrab as _IG
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class Recorder:
    """Attach one Recorder per task run.  Thread-safe enough for the
    single-threaded async event loop we run inside."""

    def __init__(self, base_dir: Path | str):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._traj_dir: Path | None = None
        self._log: list[dict] = []
        self._screenshot_count = 0
        self._task_id: str = ""
        self._start_ts: float = 0.0

    # ── public API ─────────────────────────────────────────────────────────────

    def start_recording(self, task_id: str) -> Path:
        """Open a fresh trajectory directory and return its path."""
        self._task_id = task_id
        self._start_ts = time.time()
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self._traj_dir = self._base / f"{task_id}_{ts}"
        self._traj_dir.mkdir(parents=True, exist_ok=True)
        self._log = []
        self._screenshot_count = 0
        self._log_entry("recorder", "start_recording",
                        task_id=task_id, traj_dir=str(self._traj_dir))
        return self._traj_dir

    def log_action(self, layer: str, action: str, **kwargs: Any) -> None:
        """Record a single agent action with its layer and metadata."""
        self._log_entry(layer, action, **kwargs)

    def log_cascade_decision(self, from_layer: str, to_layer: str, reason: str) -> None:
        """Record a cascade escalation."""
        self._log_entry("cascade", "escalate",
                        from_layer=from_layer, to_layer=to_layer, reason=reason)

    def log_screenshot(self, name: str = "") -> str:
        """Capture the full desktop and save to the trajectory dir.
        Returns the saved file path (or '' if Pillow unavailable)."""
        if not self._traj_dir:
            return ""
        if not _PIL_OK:
            self._log_entry("recorder", "screenshot_skipped",
                            reason="Pillow not available")
            return ""
        fname = f"screenshot_{self._screenshot_count:02d}"
        if name:
            fname += f"_{name}"
        fname += ".png"
        path = self._traj_dir / fname
        try:
            img = _IG.grab()  # full desktop
            img.save(path)
            self._screenshot_count += 1
            self._log_entry("recorder", "screenshot", file=str(path))
            return str(path)
        except Exception as exc:
            self._log_entry("recorder", "screenshot_error", error=str(exc))
            return ""

    def stop_recording(self) -> dict:
        """Finalise manifest, write it to disk, return a summary dict."""
        if not self._traj_dir:
            return {}
        elapsed = time.time() - self._start_ts
        self._log_entry("recorder", "stop_recording", elapsed_s=round(elapsed, 2))
        manifest = {
            "task_id": self._task_id,
            "traj_dir": str(self._traj_dir),
            "elapsed_s": round(elapsed, 2),
            "action_count": len(self._log),
            "screenshot_count": self._screenshot_count,
            "actions": self._log,
        }
        (self._traj_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str)
        )
        return manifest

    # ── internal ───────────────────────────────────────────────────────────────

    def _log_entry(self, layer: str, action: str, **kwargs: Any) -> None:
        entry = {
            "t": round(time.time() - self._start_ts, 3) if self._start_ts else 0.0,
            "layer": layer,
            "action": action,
            **kwargs,
        }
        self._log.append(entry)
