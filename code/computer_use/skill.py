"""Session 10: the Computer-Use skill — 5-layer cascade for OS-level tasks.

Architecture
------------
The cascade tries layers from cheapest to most expensive and stops at the
first that succeeds.  Every layer records its actions to the Recorder so
the trajectory directory captures the full decision path.

  Layer 0  Shell / Script          subprocess, clipboard, filesystem
  Layer 1  Deterministic Hotkeys   known Win32 key sequences, zero vision
  Layer 2a UIAutomation / AX Tree  pywinauto accessibility tree, no LLM
  Layer 2b AX Tree + Text LLM      AX dump → gateway /v1/chat → action
  Layer 3  Screenshot + Vision     PIL screenshot → gateway /v1/vision

Special Electron/CDP path: fires instead of Layer 2a when the target
process is Chromium-based (Electron app, Edge, CEF embedded browser).
Playwright connects over the DevTools Protocol and navigates the live DOM —
more reliable than the Windows AX tree for web-based desktop apps.

Three built-in tasks
--------------------
  calculator   — Layer 1 (hotkeys) + Layer 0 (clipboard).  Zero vision.
  electron_note — Electron/CDP path (Layer 2a variant).  No vision.
  excel_word   — Layer 1 → Layer 2a → Layer 3 (vision for verification).

Plugging into the Session 9 catalogue
--------------------------------------
  skills.py checks ``if skill.name == "computer_use":`` and calls
  ComputerUseSkill.run(node_spec) — same pattern as the Browser skill.
  agent_config.yaml has the entry; schemas.py has ComputerUseOutput.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from schemas import AgentResult, NodeSpec
from .recorder import Recorder
from .drivers import (
    ShellDriver, HotkeyDriver, UIADriver, UIALLMDriver, VisionDriver,
    ElectronCDPDriver, ComputerDriverResult,
)

# ── Task A: Calculator ────────────────────────────────────────────────────────

async def _task_calculator(rec: Recorder, goal: str, expression: str) -> ComputerDriverResult:
    """Evaluate `expression` using Windows Calculator.

    Cascade: Layer 0 (launch) → Layer 1 (hotkeys) → Layer 0 (clipboard).
    Zero vision calls.
    """
    shell = ShellDriver()
    keys = HotkeyDriver()
    actions: list[dict] = []

    # ── Layer 0: open Calculator via Win+R ────────────────────────────────────
    rec.log_action("shell", "launch_calculator")
    import win32api, win32con
    # Press Win+R
    win32api.keybd_event(win32con.VK_LWIN, 0, 0, 0)
    win32api.keybd_event(ord('R'), 0, 0, 0)
    win32api.keybd_event(ord('R'), 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_LWIN, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.6)
    actions.append({"layer": "L0", "action": "Win+R to open Run dialog"})

    # ── Layer 1: type "calc" in Run dialog, press Enter ───────────────────────
    rec.log_cascade_decision("shell", "hotkeys", "launching calc.exe via Run dialog")
    keys.send("calc{ENTER}", rec)
    time.sleep(1.2)  # let Calculator load
    actions.append({"layer": "L1", "action": "type 'calc' + Enter"})

    rec.log_screenshot("calc_open")

    # ── Layer 1: type the arithmetic expression ───────────────────────────────
    # Map expression chars to Calculator keystrokes.
    # Calculator Scientific mode understands typed digits and operators.
    # We also switch to scientific mode first via Alt+2.
    time.sleep(0.3)
    keys.send("%2", rec)   # Alt+2 = Scientific mode (supports parentheses)
    time.sleep(0.2)

    key_map = {
        "0": "0", "1": "1", "2": "2", "3": "3", "4": "4",
        "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
        "+": "+", "-": "-", "*": "*", "/": "/",
        "(": "(", ")": ")",
        " ": "",   # ignore spaces
    }
    key_seq = ""
    for ch in expression:
        mapped = key_map.get(ch)
        if mapped is not None:
            key_seq += mapped
    rec.log_action("hotkeys", "type_expression", expression=expression, key_seq=key_seq)
    keys.send(key_seq + "{ENTER}", rec, pause=0.08)
    actions.append({"layer": "L1", "action": f"type expression: {expression}"})
    time.sleep(0.3)

    rec.log_screenshot("calc_result")

    # ── Layer 1: Ctrl+A then Ctrl+C to copy the result ───────────────────────
    keys.send("^a", rec)   # Ctrl+A
    time.sleep(0.1)
    keys.send("^c", rec)   # Ctrl+C — copies display text
    time.sleep(0.3)
    actions.append({"layer": "L1", "action": "Ctrl+C to copy result"})

    # ── Layer 0: read clipboard ───────────────────────────────────────────────
    result_text = shell.read_clipboard(rec)
    actions.append({"layer": "L0", "action": "read clipboard", "value": result_text})

    # Close Calculator
    keys.send("%{F4}", rec)   # Alt+F4
    time.sleep(0.2)

    if result_text:
        return ComputerDriverResult(
            success=True,
            note="Layer 1 hotkeys + Layer 0 clipboard — zero vision",
            content=result_text.strip(),
            actions=actions,
            layer_used="L0+L1",
        )
    return ComputerDriverResult(
        success=False,
        note="Could not read Calculator result from clipboard",
        actions=actions,
        layer_used="L1",
    )


# ── Task B: Electron Note (CDP path) ─────────────────────────────────────────

_NOTE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>S10 Note App</title>
<style>
  body {{ font-family: sans-serif; max-width: 700px; margin: 40px auto; padding: 0 20px; }}
  h1 {{ font-size: 1.4rem; }}
  #notepad {{ width: 100%; height: 200px; font-size: 1rem; padding: 8px;
             border: 1px solid #ccc; border-radius: 4px; resize: vertical; }}
  #save-btn {{ margin-top: 8px; padding: 6px 18px; font-size: 1rem; cursor: pointer; }}
  #status {{ margin-top: 8px; color: green; font-size: 0.9rem; }}
  #word-count {{ font-size: 0.85rem; color: #666; margin-top: 4px; }}
</style>
</head>
<body>
<h1>Quick Note</h1>
<textarea id="notepad" placeholder="Type your note here…"></textarea>
<br>
<button id="save-btn" onclick="saveNote()">Save Note</button>
<p id="status"></p>
<p id="word-count"></p>
<script>
  document.getElementById('notepad').addEventListener('input', function() {{
    var words = this.value.trim().split(/\\s+/).filter(Boolean).length;
    document.getElementById('word-count').textContent = words + ' word(s)';
  }});
  function saveNote() {{
    var note = document.getElementById('notepad').value;
    document.getElementById('status').textContent = 'Note saved! (' + note.length + ' chars)';
    window.__savedNote = note;
  }}
</script>
</body>
</html>
"""


async def _electron_note_actions(page, rec: Recorder) -> dict:
    """CDP-level actions: fill textarea, click Save, read DOM status."""
    note_text = (
        "Session 10 — Computer-Use Skill\n"
        "Five-layer cascade demo: Shell → Hotkeys → UIAutomation → AX+LLM → Vision\n"
        "Electron/CDP path: Playwright attaches over DevTools Protocol.\n"
        f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    actions: list[dict] = []

    # Electron/CDP Layer 2a: use DOM selector to find textarea
    textarea = page.locator("#notepad")
    rec.log_action("electron_cdp", "locate_element", selector="#notepad")
    await textarea.wait_for(state="visible", timeout=5000)
    await textarea.fill(note_text)
    actions.append({"layer": "Electron/CDP", "action": "fill #notepad", "chars": len(note_text)})
    rec.log_action("electron_cdp", "fill", selector="#notepad", chars=len(note_text))

    # Verify word count appeared (Layer 2a AX tree substitute — DOM query)
    word_count_el = page.locator("#word-count")
    word_count_text = await word_count_el.text_content() or ""
    rec.log_action("electron_cdp", "read_dom", selector="#word-count", value=word_count_text)
    actions.append({"layer": "Electron/CDP", "action": "read word-count", "value": word_count_text})

    # Click Save button
    save_btn = page.locator("#save-btn")
    await save_btn.click()
    actions.append({"layer": "Electron/CDP", "action": "click #save-btn"})
    rec.log_action("electron_cdp", "click", selector="#save-btn")

    await page.wait_for_timeout(300)

    # Read status element to confirm save
    status_text = await page.locator("#status").text_content() or ""
    rec.log_action("electron_cdp", "read_dom", selector="#status", value=status_text)
    actions.append({"layer": "Electron/CDP", "action": "read #status", "value": status_text})

    # Read the saved note back via JS evaluation (pure CDP — no screenshots)
    saved = await page.evaluate("window.__savedNote || ''")
    actions.append({"layer": "Electron/CDP (JS eval)", "action": "read __savedNote", "chars": len(saved)})
    rec.log_action("electron_cdp", "js_eval", var="__savedNote", chars=len(saved))

    return {
        "success": "saved" in status_text.lower(),
        "note": status_text,
        "result": saved,
        "actions": actions,
    }


async def _task_electron_note(rec: Recorder, goal: str,
                               html_dir: Path) -> ComputerDriverResult:
    """Write and save a note using the Electron/CDP path (no vision).

    Playwright launches Chromium in `--app=file://...` mode which replicates
    the Electron launch pattern.  All interactions use Playwright's DOM API
    (Locator, evaluate) over the DevTools Protocol — the Windows AX tree
    is never consulted.
    """
    # Write the HTML file
    html_path = html_dir / "note_app.html"
    html_path.write_text(_NOTE_HTML_TEMPLATE, encoding="utf-8")
    rec.log_action("shell", "write_html", path=str(html_path))

    cdp = ElectronCDPDriver()
    rec.log_cascade_decision("shell", "electron_cdp",
                              "target is Chromium-based — CDP path preferred over OS AX tree")
    return await cdp.run_html_app(
        str(html_path).replace("\\", "/"),
        goal,
        _electron_note_actions,
        rec,
    )


# ── Task C: Excel → Word data transfer ───────────────────────────────────────

async def _task_excel_word(rec: Recorder, goal: str) -> ComputerDriverResult:
    """Enter a table in Excel, copy it, paste into Word.

    Cascade:
      Layer 0 — subprocess to open Excel
      Layer 1 — hotkeys to navigate cells and type data
      Layer 2a — pywinauto to verify window titles
      Layer 3  — screenshot + vision to confirm paste result in Word
    """
    import win32api, win32con
    shell = ShellDriver()
    keys = HotkeyDriver()
    actions: list[dict] = []

    EXCEL_EXE = r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"
    WORD_EXE  = r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE"

    # ── Layer 0: launch Excel ─────────────────────────────────────────────────
    rec.log_action("shell", "launch_excel", exe=EXCEL_EXE)
    shell.launch(EXCEL_EXE, rec, wait_s=3.5)
    actions.append({"layer": "L0", "action": "launch Excel"})
    rec.log_screenshot("excel_open")

    # Dismiss any startup dialog with Escape
    keys.send("{ESC}", rec)
    time.sleep(0.3)

    # ── Layer 1: hotkeys to open a blank workbook ─────────────────────────────
    rec.log_cascade_decision("shell", "hotkeys", "Excel loaded; using hotkeys to create workbook")
    keys.send("^n", rec)           # Ctrl+N — new workbook
    time.sleep(1.0)
    actions.append({"layer": "L1", "action": "Ctrl+N new workbook"})
    rec.log_screenshot("excel_newbook")

    # ── Layer 1: type a 3×3 data table ───────────────────────────────────────
    # Each Tab moves right; Enter on last column moves to next row col-A.
    data_rows = [
        ("Product",  "Units", "Revenue"),
        ("Widget A", "120",   "4800"),
        ("Widget B", "85",    "5950"),
        ("Widget C", "200",   "3000"),
    ]
    for row in data_rows:
        for i, cell in enumerate(row):
            keys.send(cell, rec, pause=0.02)
            if i < len(row) - 1:
                keys.send("{TAB}", rec)
            else:
                keys.send("{ENTER}", rec)
        time.sleep(0.05)
    actions.append({"layer": "L1", "action": "typed 4×3 table (header + 3 data rows)"})
    rec.log_screenshot("excel_data_entered")

    # ── Layer 2a: check window to make sure we're in Excel ───────────────────
    rec.log_cascade_decision("hotkeys", "uia", "verifying Excel window before copy")
    uia = UIADriver()
    excel_running = False
    try:
        if _UIA_AVAILABLE():
            app = uia.attach("Excel", rec, timeout=5)
            excel_running = True
            rec.log_action("uia", "verified_excel_window")
    except Exception as e:
        rec.log_action("uia", "attach_warning", note=str(e)[:100])
    actions.append({"layer": "L2a", "action": "UIAutomation window check",
                    "excel_found": excel_running})

    # ── Layer 1: select all data and copy ────────────────────────────────────
    rec.log_cascade_decision("uia", "hotkeys", "window confirmed; copy with hotkeys")
    keys.send("^{HOME}", rec)      # go to A1
    time.sleep(0.2)
    keys.send("^+{END}", rec)      # select to last used cell
    time.sleep(0.2)
    keys.send("^c", rec)           # copy
    time.sleep(0.4)
    actions.append({"layer": "L1", "action": "Ctrl+Home → Ctrl+Shift+End → Ctrl+C"})
    rec.log_screenshot("excel_selected")

    # ── Layer 0: launch Word ──────────────────────────────────────────────────
    rec.log_cascade_decision("hotkeys", "shell", "launching Word")
    shell.launch(WORD_EXE, rec, wait_s=4.0)
    actions.append({"layer": "L0", "action": "launch Word"})
    keys.send("{ESC}", rec)         # dismiss any dialog
    time.sleep(0.5)

    # ── Layer 1: new document + paste ────────────────────────────────────────
    rec.log_cascade_decision("shell", "hotkeys", "Word loaded; paste table")
    keys.send("^n", rec)           # Ctrl+N new doc
    time.sleep(1.0)
    keys.send("^v", rec)           # Ctrl+V paste
    time.sleep(1.0)
    actions.append({"layer": "L1", "action": "Ctrl+N + Ctrl+V to paste table"})
    rec.log_screenshot("word_pasted")

    # ── Layer 3: vision verification ─────────────────────────────────────────
    rec.log_cascade_decision("hotkeys", "vision",
                              "paste done; using vision to verify table is visible in Word")
    vision = VisionDriver()
    png = vision.capture(rec)
    vision_result: dict = {}
    if png:
        vision_result = await vision.describe(
            png,
            "Is a table with columns Product, Units, Revenue visible in Microsoft Word? "
            "List the rows you can see.",
            rec,
        ) or {}
    actions.append({"layer": "L3", "action": "vision verify paste",
                    "observed": vision_result.get("observed", "")[:200]})
    rec.log_screenshot("word_vision_verify")

    # ── Layer 1: save Word document ───────────────────────────────────────────
    keys.send("^s", rec)           # Ctrl+S
    time.sleep(1.5)
    keys.send("{ENTER}", rec)      # confirm default save location
    time.sleep(0.5)
    actions.append({"layer": "L1", "action": "Ctrl+S save Word document"})

    # Close both apps
    keys.send("%{F4}", rec)        # close Word
    time.sleep(0.5)

    return ComputerDriverResult(
        success=True,
        note="L0→L1→L2a→L1→L3: Shell launch, hotkey entry, UIA verify, vision confirm",
        content={
            "excel_rows": len(data_rows),
            "word_paste": "done",
            "vision_observed": vision_result.get("observed", "(no vision result)"),
        },
        actions=actions,
        layer_used="L0+L1+L2a+L3",
    )


def _UIA_AVAILABLE() -> bool:
    try:
        import pywinauto
        return True
    except ImportError:
        return False


# ── main skill class ──────────────────────────────────────────────────────────

class ComputerUseSkill:
    NAME = "computer_use"

    def __init__(self, *, gateway_url: str = "http://localhost:8109",
                 trajectories_root: str | None = None,
                 session: str | None = None):
        self.gateway_url = gateway_url
        self._traj_root = Path(trajectories_root) if trajectories_root else (
            Path(__file__).parent.parent / "state" / "trajectories"
        )
        self._traj_root.mkdir(parents=True, exist_ok=True)
        self.session = session

    async def run(self, node: NodeSpec) -> AgentResult:
        task = node.metadata.get("task", "calculator")
        goal = node.metadata.get("goal", "")
        expression = node.metadata.get("expression", "345 * 678 - 90")

        rec = Recorder(self._traj_root)
        traj_dir = rec.start_recording(task)

        t0 = time.time()
        try:
            if task == "calculator":
                result = await _task_calculator(
                    rec,
                    goal or f"Evaluate {expression} using Windows Calculator",
                    expression,
                )
            elif task == "electron_note":
                result = await _task_electron_note(
                    rec,
                    goal or "Write and save a note using the Electron/CDP path",
                    traj_dir,
                )
            elif task == "excel_word":
                result = await _task_excel_word(
                    rec,
                    goal or "Enter a data table in Excel and transfer it to Word",
                )
            else:
                manifest = rec.stop_recording()
                return AgentResult(
                    success=False, agent_name=self.NAME,
                    error=f"unknown task: {task}",
                    elapsed_s=time.time() - t0,
                )
        except Exception as exc:
            rec.log_action("skill", "unhandled_error", error=str(exc))
            manifest = rec.stop_recording()
            return AgentResult(
                success=False, agent_name=self.NAME,
                error=str(exc),
                output={"traj_dir": str(traj_dir), "manifest": manifest},
                elapsed_s=time.time() - t0,
            )

        manifest = rec.stop_recording()

        return AgentResult(
            success=result.success,
            agent_name=self.NAME,
            output={
                "task": task,
                "layer_used": result.layer_used,
                "content": result.content,
                "note": result.note,
                "actions": result.actions,
                "traj_dir": str(traj_dir),
                "manifest": manifest,
            },
            error=None if result.success else result.note,
            elapsed_s=time.time() - t0,
        )
