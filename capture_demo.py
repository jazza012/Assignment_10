"""
capture_demo.py — Playwright screen-capture of demo_presentation.html → MP4
Usage: python capture_demo.py
Output: D:\EAG3\Assignment_9\demo_video.mp4
"""

import io, sys, time
from pathlib import Path
import numpy as np
import cv2
from PIL import Image
from playwright.sync_api import sync_playwright

HTML_PATH = Path(__file__).parent / "demo_presentation.html"
OUTPUT_MP4 = Path(__file__).parent / "demo_video.mp4"
VIEWPORT_W, VIEWPORT_H = 1280, 720
FPS = 10   # frames per second in the output video

# (slide_number, dwell_before_ms, capture_duration_ms)
# dwell_before lets animations start before we begin saving frames
SLIDES = [
    (1, 200,  5500),   # terminal types in ~1.8s; show for 5.5s total
    (2, 200,  5500),   # DAG nodes animate in ~1.6s
    (3, 200,  4500),   # static cascade diagram
    (4, 200,  7500),   # 4 action items animate in, ~2.4s
    (5, 200,  4500),   # tool cards animate in ~1s
    (6, 200,  5000),   # comparison table — static
    (7, 200,  6500),   # 8 checklist items animate in ~1.75s
    (8, 200,  5000),   # counters count up
]

def screenshot_to_bgr(png_bytes: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    img = img.resize((VIEWPORT_W, VIEWPORT_H), Image.LANCZOS)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def capture_frames():
    frames = []
    file_url = HTML_PATH.as_uri()
    interval_ms = int(1000 / FPS)   # 100 ms between captures

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": VIEWPORT_W, "height": VIEWPORT_H})

        print(f"Loading {file_url} …")
        page.goto(file_url, wait_until="domcontentloaded")
        page.wait_for_timeout(800)   # let JS initialise

        for slide_num, dwell_ms, duration_ms in SLIDES:
            print(f"  Slide {slide_num}/8 — navigating …", end=" ", flush=True)
            page.evaluate(f"go({slide_num})")
            page.wait_for_timeout(dwell_ms)   # wait for animation kickoff

            num_frames = max(1, int(duration_ms / interval_ms))
            for _ in range(num_frames):
                frames.append(screenshot_to_bgr(page.screenshot()))
                page.wait_for_timeout(interval_ms)

            print(f"{num_frames} frames captured ({duration_ms/1000:.1f} s)")

        browser.close()

    return frames


def write_mp4(frames, out_path: Path):
    if not frames:
        print("No frames captured — aborting.")
        return
    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, FPS, (w, h))
    for f in frames:
        writer.write(f)
    writer.release()
    size_mb = out_path.stat().st_size / 1e6
    print(f"\n✓ Saved: {out_path}  ({len(frames)} frames, {len(frames)/FPS:.1f}s, {size_mb:.1f} MB)")


if __name__ == "__main__":
    t0 = time.time()
    print("=== Browser Comparison Agent — Demo Video Capture ===\n")
    frames = capture_frames()
    print(f"\nCompiling {len(frames)} frames @ {FPS} fps …")
    write_mp4(frames, OUTPUT_MP4)
    print(f"Total time: {time.time()-t0:.1f}s")
