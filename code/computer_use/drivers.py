"""Five-layer driver implementations for the Computer-Use skill.

Each driver class maps to one layer in the cascade.  Drivers are pure
callables — they receive a task config dict and a Recorder, attempt the
work, and return a ComputerDriverResult.  The skill.py cascade calls them
in order and stops at the first success.

Layer map
---------
Layer 0  Shell/Script          — subprocess, clipboard, filesystem
Layer 1  Hotkeys               — deterministic Win32 key sequences
Layer 2a UIAutomation/AX Tree  — pywinauto accessibility tree (no LLM)
Layer 2b AX Tree + Text LLM   — AX tree dump → gateway /v1/chat → action
Layer 3  Screenshot + Vision  — PIL screenshot → gateway /v1/vision → coord

Special Electron/CDP path: used instead of Layer 2a when the target
process is Chromium-based (Electron, Edge, CEF…).  Playwright connects
over the DevTools Protocol and navigates the DOM directly — no OS AX tree.
"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

from .recorder import Recorder

# ── optional heavy imports (graceful degradation in CI) ───────────────────────
try:
    import pyperclip as _clip
    _CLIP_OK = True
except ImportError:
    _CLIP_OK = False

try:
    import pywinauto
    from pywinauto import Application
    from pywinauto.keyboard import send_keys
    _UIA_OK = True
except ImportError:
    _UIA_OK = False

try:
    from PIL import ImageGrab
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

try:
    import win32gui
    import win32con
    import win32api
    _WIN32_OK = True
except ImportError:
    _WIN32_OK = False


# ── shared result type ─────────────────────────────────────────────────────────

@dataclass
class ComputerDriverResult:
    success: bool
    note: str = ""
    content: Any = None
    actions: list = field(default_factory=list)
    layer_used: str = ""


# ── Layer 0: Shell / Script ───────────────────────────────────────────────────

class ShellDriver:
    """Pure Python/system calls — no GUI interaction."""
    LAYER = "shell"

    def read_clipboard(self, rec: Recorder) -> str:
        """Return current clipboard text (empty string on failure)."""
        if not _CLIP_OK:
            rec.log_action(self.LAYER, "clipboard_read", error="pyperclip unavailable")
            return ""
        text = _clip.paste() or ""
        rec.log_action(self.LAYER, "clipboard_read", chars=len(text))
        return text

    def write_clipboard(self, text: str, rec: Recorder) -> None:
        if _CLIP_OK:
            _clip.copy(text)
            rec.log_action(self.LAYER, "clipboard_write", chars=len(text))

    def launch(self, exe: str | list[str], rec: Recorder, wait_s: float = 1.5) -> subprocess.Popen:
        cmd = exe if isinstance(exe, list) else [exe]
        rec.log_action(self.LAYER, "launch", cmd=cmd)
        proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW
                                if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
        time.sleep(wait_s)
        return proc


# ── Layer 1: Deterministic Hotkeys ────────────────────────────────────────────

class HotkeyDriver:
    """Send known key sequences to the foreground window via pywinauto send_keys.

    This layer never reads UI state — it fires a hard-coded sequence and
    trusts the app to respond.  Escalate to Layer 2a when the foreground
    window is uncertain or the sequence might differ across app versions.
    """
    LAYER = "hotkeys"

    def send(self, keys: str, rec: Recorder, pause: float = 0.05) -> None:
        rec.log_action(self.LAYER, "send_keys", keys=repr(keys))
        if _UIA_OK:
            send_keys(keys, pause=pause)
        else:
            # Fallback: ctypes keybd_event for simple ASCII keys
            import ctypes
            for ch in keys:
                vk = ctypes.windll.user32.VkKeyScanW(ord(ch)) & 0xFF
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
                time.sleep(0.05)

    def press(self, key: str, rec: Recorder) -> None:
        """Send a single key or combo e.g. '^c' for Ctrl+C."""
        self.send(key, rec)


# ── Layer 2a: UIAutomation / AX Tree ─────────────────────────────────────────

class UIADriver:
    """Walk the Windows accessibility tree with pywinauto.

    Finds controls by title, auto_id, or class_name; clicks/types without
    any LLM involvement.  Escalate to Layer 2b when the tree structure is
    ambiguous or the desired control name is not known in advance.
    """
    LAYER = "uia"

    def attach(self, title_re: str, rec: Recorder, timeout: float = 10.0):
        """Attach to a window whose title matches `title_re`."""
        if not _UIA_OK:
            raise RuntimeError("pywinauto not available")
        app = Application(backend="uia")
        app.connect(title_re=title_re, timeout=timeout)
        rec.log_action(self.LAYER, "attach", title_re=title_re)
        return app

    def dump_tree(self, window, depth: int = 4) -> str:
        """Return a compact text representation of the AX tree."""
        lines: list[str] = []
        self._walk(window.wrapper_object(), lines, 0, depth)
        return "\n".join(lines)

    def _walk(self, elem, lines, level, max_depth):
        if level > max_depth:
            return
        try:
            name = elem.window_text() or ""
            ctrl = elem.friendly_class_name() or elem.class_name() or ""
            auto_id = ""
            try:
                auto_id = elem.automation_id() or ""
            except Exception:
                pass
            indent = "  " * level
            parts = [f"{indent}[{ctrl}]"]
            if name:
                parts.append(f'name="{name}"')
            if auto_id:
                parts.append(f'id="{auto_id}"')
            lines.append(" ".join(parts))
        except Exception:
            pass
        try:
            for child in elem.children():
                self._walk(child, lines, level + 1, max_depth)
        except Exception:
            pass

    def find_and_click(self, app, title: str, rec: Recorder, timeout: float = 5.0):
        """Find a button/control by title text and click it."""
        dlg = app.top_window()
        ctrl = dlg.child_window(title=title, found_index=0)
        ctrl.wait("visible", timeout=timeout)
        ctrl.click_input()
        rec.log_action(self.LAYER, "click", title=title)

    def find_and_type(self, app, auto_id: str, text: str, rec: Recorder):
        """Type into a control identified by automation_id."""
        dlg = app.top_window()
        ctrl = dlg.child_window(auto_id=auto_id)
        ctrl.wait("visible", timeout=5)
        ctrl.set_edit_text(text)
        rec.log_action(self.LAYER, "type", auto_id=auto_id, text=text[:80])


# ── Layer 2b: AX Tree + Text LLM ─────────────────────────────────────────────

class UIALLMDriver:
    """Dump AX tree → send to gateway /v1/chat → parse next action.

    Uses a cheap text model (no vision).  The LLM receives the full tree
    dump plus the goal and returns a JSON action: {action, title/id, value}.
    """
    LAYER = "uia_llm"

    def __init__(self, gateway_url: str = "http://localhost:8109",
                 agent_tag: str = "computer_use"):
        self.gateway_url = gateway_url
        self.agent_tag = agent_tag

    async def decide(self, tree_text: str, goal: str, history: list[str],
                     rec: Recorder) -> dict | None:
        """Ask the LLM what to do next given the AX tree and goal."""
        history_block = "\n".join(f"  - {h}" for h in history[-5:])
        prompt = f"""You are a desktop-automation assistant.  Given the Windows UI tree and the goal, emit the NEXT single action as JSON.

GOAL: {goal}

RECENT ACTIONS:
{history_block or "  (none yet)"}

UI TREE (pywinauto accessibility dump):
{tree_text[:3000]}

Respond with ONLY a JSON object like:
{{"action": "click", "title": "Button Name"}}
or
{{"action": "type", "auto_id": "elementId", "text": "the text to type"}}
or
{{"action": "done", "result": "value that satisfies the goal"}}

If you cannot determine the action, respond with {{"action": "fail", "reason": "..."}}
"""
        rec.log_action(self.LAYER, "llm_request", goal=goal, tree_chars=len(tree_text))
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.gateway_url}/v1/chat",
                    json={
                        "prompt": prompt,
                        "agent": self.agent_tag,
                        "max_tokens": 256,
                        "temperature": 0.0,
                    },
                )
                resp.raise_for_status()
                text = resp.json().get("text", "")
                rec.log_action(self.LAYER, "llm_response", text=text[:200])
        except Exception as exc:
            rec.log_action(self.LAYER, "llm_error", error=str(exc))
            return None

        # Parse JSON from the response
        t = text.strip().strip("`")
        if t.startswith("json"):
            t = t[4:].strip()
        try:
            return json.loads(t)
        except Exception:
            start, end = t.find("{"), t.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(t[start:end + 1])
                except Exception:
                    pass
        return None


# ── Layer 3: Screenshot + Vision LLM ─────────────────────────────────────────

class VisionDriver:
    """Capture screenshot → send to gateway /v1/vision → parse action.

    The vision LLM sees the full desktop and can point at coordinates or
    read text the AX tree does not expose (canvas, custom-rendered widgets).
    """
    LAYER = "vision"

    def __init__(self, gateway_url: str = "http://localhost:8109",
                 agent_tag: str = "computer_use"):
        self.gateway_url = gateway_url
        self.agent_tag = agent_tag

    def capture(self, rec: Recorder) -> bytes | None:
        """Capture full desktop and return PNG bytes."""
        if not _PIL_OK:
            rec.log_action(self.LAYER, "capture_error", reason="Pillow unavailable")
            return None
        try:
            img = ImageGrab.grab()
            buf = BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as exc:
            rec.log_action(self.LAYER, "capture_error", reason=str(exc))
            return None

    async def describe(self, png_bytes: bytes, goal: str, rec: Recorder) -> dict | None:
        """Send screenshot to vision endpoint and get action."""
        b64 = base64.b64encode(png_bytes).decode()
        prompt = f"""Look at this desktop screenshot and help complete the goal.

GOAL: {goal}

Return ONLY a JSON object describing what you observe and the recommended next action:
{{"observed": "what you see on screen", "action": "click|type|read|done", "coordinates": [x, y] or null, "text": "text to type if action=type", "result": "extracted value if action=done"}}
"""
        rec.log_action(self.LAYER, "vision_request", goal=goal,
                       png_kb=round(len(png_bytes) / 1024, 1))
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self.gateway_url}/v1/vision",
                    json={
                        "prompt": prompt,
                        "image_b64": b64,
                        "agent": self.agent_tag,
                        "max_tokens": 512,
                    },
                )
                resp.raise_for_status()
                text = resp.json().get("text", "")
                rec.log_action(self.LAYER, "vision_response", text=text[:300])
        except Exception as exc:
            rec.log_action(self.LAYER, "vision_error", error=str(exc))
            return None

        t = text.strip().strip("`")
        if t.startswith("json"):
            t = t[4:].strip()
        try:
            return json.loads(t)
        except Exception:
            start, end = t.find("{"), t.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(t[start:end + 1])
                except Exception:
                    pass
        return None


# ── Electron / CDP path ───────────────────────────────────────────────────────

class ElectronCDPDriver:
    """Connect to a Chromium-based app via Playwright / DevTools Protocol.

    Works for Electron apps, Edge, VS Code, etc. — any process exposing a
    CDP endpoint.  When the remote-debugging port is known, Playwright can
    attach and navigate the live DOM directly, bypassing the Windows AX tree.

    Usage pattern
    -------------
    1. Launch the Electron app with --remote-debugging-port=<port>
       (or let Playwright launch it via electron.launch()).
    2. Construct ElectronCDPDriver(debug_port=<port>).
    3. Call async run_task(page_url, goal, actions_fn, rec) to execute
       DOM-level actions through the CDP session.

    For the Session 10 demo we launch a local HTML file via Playwright's
    Chromium binary in `--app` mode — this replicates the Electron launch
    pattern without requiring a real Electron runtime.
    """
    LAYER = "electron_cdp"

    def __init__(self, debug_port: int = 9222):
        self.debug_port = debug_port

    async def run_html_app(self, html_path: str, goal: str,
                           actions_fn, rec: Recorder) -> ComputerDriverResult:
        """Launch a local HTML file in Chromium app-mode and execute actions_fn.

        `actions_fn(page) -> dict` is an async callable that receives the
        Playwright Page and returns {success, result, actions}.
        """
        from playwright.async_api import async_playwright

        rec.log_action(self.LAYER, "launch_html_app", html=html_path, goal=goal)
        result_holder: dict = {}
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                args=[
                    f"--app=file:///{html_path}",
                    "--disable-extensions",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                headless=False,
            )
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            pages = ctx.pages
            page = pages[0] if pages else await ctx.new_page()
            if not pages:
                await page.goto(f"file:///{html_path}")
            await asyncio.sleep(0.8)
            rec.log_action(self.LAYER, "page_loaded", url=page.url)
            try:
                result_holder = await actions_fn(page, rec)
            except Exception as exc:
                rec.log_action(self.LAYER, "actions_error", error=str(exc))
                result_holder = {"success": False, "result": str(exc), "actions": []}
            finally:
                await asyncio.sleep(0.5)
                await browser.close()

        return ComputerDriverResult(
            success=result_holder.get("success", False),
            note=result_holder.get("note", ""),
            content=result_holder.get("result"),
            actions=result_holder.get("actions", []),
            layer_used=self.LAYER,
        )
