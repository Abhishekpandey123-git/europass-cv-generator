#!/usr/bin/env python3
"""
Check the editor's on-screen preview, not just the PDF.

The PDF and the preview are rendered by different engines - WeasyPrint and
the browser - from the same stylesheet, and they disagree about
position: fixed. WeasyPrint repeats a fixed box on every page, which is how
Template 3's frame and Template 2's sidebar reach every sheet in the PDF. A
browser pins it to the viewport instead, so in the editor the frame sat still
while the CV scrolled underneath and the blue bars cut through the middle of
the content. Every PDF measurement passed while the preview was visibly wrong.

This opens the real editor in Chromium and asserts that the frame colour only
ever appears in the bands and corner brackets of a sheet - never over content.

    python tools/editor_check.py

Needs Playwright with Chromium. If it is not installed the check reports that
and exits 0, so it never blocks a deploy on a machine without a browser.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

PORT = 8749
REFERENCE = BASE / "samples/reference/real_cv_will_almost_all_feilds.pdf"

FRAME_BLUE = (130, 172, 217)      # Template 3's bracket frame
SIDEBAR_GREY = (245, 245, 245)    # Templates 1 and 2
BAR_MM = 5.93
ARM_MM = 23.9
SHEET_MM = 297.0
# Slack around a sheet's own edges, for antialiasing and sub-pixel sheet
# positions. Well inside the 10mm page margin, so frame colour landing on
# actual content is still caught.
TOLERANCE_MM = 3.0


def start_server():
    import uvicorn
    import app as application
    server = uvicorn.Server(uvicorn.Config(application.app, host="127.0.0.1",
                                           port=PORT, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(40):
        time.sleep(0.25)
        if getattr(server, "started", False):
            return
    time.sleep(2)


def seed(template: str) -> str:
    from fastapi.testclient import TestClient
    import app as application
    client = TestClient(application.app)
    with REFERENCE.open("rb") as fh:
        r = client.post("/api/cvs/import", files={"file": ("ref.pdf", fh, "application/pdf")})
    cv_id = r.json()["id"]
    doc = client.get(f"/api/cvs/{cv_id}").json()
    cv = doc.get("cv") or doc.get("data") or doc
    cv.setdefault("design", {})["template"] = template
    client.put(f"/api/cvs/{cv_id}", json={"cv": cv})
    return cv_id


def check_sheet_blue(png: Path, rects: list[dict], doc_width: float) -> list[str]:
    """Frame colour must fall inside a band or corner bracket of some sheet.

    Everything is measured from the sheet elements themselves rather than
    assumed: the editor's body is 210mm of content plus its page padding, so
    the captured iframe is wider than a sheet and any mm-per-pixel guess based
    on 210mm is out by the margin.
    """
    import numpy as np
    from PIL import Image

    a = np.array(Image.open(png).convert("RGB"))
    H, W = a.shape[:2]
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    # Tight tolerance on purpose: the section-heading rule is rgb(121,162,206),
    # only about 10 per channel from the frame's rgb(130,172,217), so a loose
    # mask counts every heading underline as frame and the check cries wolf.
    blue = ((abs(r - FRAME_BLUE[0]) < 6) & (abs(g - FRAME_BLUE[1]) < 6)
            & (abs(b - FRAME_BLUE[2]) < 6))
    if not blue.any():
        return ["frame colour not found on screen at all"]

    scale = W / doc_width                      # captured px per iframe CSS px
    allowed = np.zeros_like(blue)
    for rect in rects:
        x0 = rect["left"] * scale
        y0 = rect["top"] * scale
        w = rect["width"] * scale
        h = rect["height"] * scale
        px_per_mm = w / 210.0
        tol = TOLERANCE_MM * px_per_mm
        bar = BAR_MM * px_per_mm
        arm = ARM_MM * px_per_mm
        left, right = int(max(0, x0 - tol)), int(min(W, x0 + w + tol))
        allowed[int(max(0, y0 - tol)):int(min(H, y0 + bar + tol)), left:right] = True
        allowed[int(max(0, y0 + h - bar - tol)):int(min(H, y0 + h + tol)), left:right] = True
        for a0, a1 in ((y0, y0 + arm), (y0 + h - arm, y0 + h)):
            yy0, yy1 = int(max(0, a0 - tol)), int(min(H, a1 + tol))
            allowed[yy0:yy1, left:int(min(W, x0 + bar + tol))] = True
            allowed[yy0:yy1, int(max(0, x0 + w - bar - tol)):right] = True

    stray = blue & ~allowed
    if stray.sum() > 40:          # a few antialiased pixels are not a failure
        ys, xs = np.where(stray)
        ppm = (rects[0]["width"] * scale) / 210.0
        return [f"{stray.sum()} frame pixels over content, between "
                f"y={ys.min() / ppm:.1f}-{ys.max() / ppm:.1f}mm and "
                f"x={xs.min() / ppm:.1f}-{xs.max() / ppm:.1f}mm"]
    return []


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed - skipping the on-screen check.")
        return 0

    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="editor-check-"))
    os.environ["ADMIN_PASSWORD"] = ""
    os.chdir(BASE)

    failures: list[str] = []
    ids = {t: seed(t) for t in ("template1", "template2", "template3", "template4")}
    start_server()

    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1200})
        for template, cv_id in ids.items():
            page.goto(f"http://127.0.0.1:{PORT}/edit/{cv_id}", wait_until="load")
            page.wait_for_timeout(3500)

            info = page.evaluate("""() => {
                const f = document.querySelector("#page");
                const doc = f.contentDocument;
                const body = doc.body;
                const frames = [...doc.querySelectorAll('.page-frame')];
                const fixed = [...doc.querySelectorAll('.frame, .sidebar-band')]
                    .filter(el => getComputedStyle(el).display !== 'none').length;
                const mm = doc.querySelector('.page-frame')
                    ? doc.querySelector('.page-frame').getBoundingClientRect().width / 210 : 0;
                const bodyRect = body.getBoundingClientRect();
                return {
                    sheets: frames.map(el => parseFloat(el.style.top) || 0),
                    rects: frames.map(el => {
                        const b = el.getBoundingClientRect();
                        return {left: b.left - bodyRect.left, top: b.top - bodyRect.top,
                                width: b.width, height: b.height};
                    }),
                    docWidth: body.scrollWidth,
                    painted: frames.filter(el =>
                        getComputedStyle(el).backgroundImage !== 'none').length,
                    fixedVisible: fixed,
                    pxPerMm: body.scrollWidth && frames.length
                        ? frames[0].getBoundingClientRect().width / 210 : 0,
                };
            }""")

            name = template.replace("template", "Template ")
            if info["fixedVisible"]:
                failures.append(f"{name}: {info['fixedVisible']} viewport-fixed frame element(s) "
                                f"visible on screen - they will float over the content")
            if not info["sheets"]:
                failures.append(f"{name}: the editor drew no page sheets")
                continue

            needs_paint = template in ("template2", "template3")
            if needs_paint and info["painted"] != len(info["sheets"]):
                failures.append(f"{name}: {info['painted']}/{len(info['sheets'])} sheets carry "
                                f"the frame; every sheet needs it")

            if template == "template3":
                shot = Path(tmp) / f"{template}.png"
                page.locator("#page").screenshot(path=str(shot))
                # the element shot is scaled to the editor's zoom, so derive
                # mm from the sheet width actually captured
                failures += [f"{name}: {m}" for m in
                             check_sheet_blue(shot, info["rects"], info["docWidth"])]

            print(f"  OK  {name}: {len(info['sheets'])} sheet(s), no viewport-fixed frame")
        browser.close()

    for f in failures:
        print(f"  FAIL {f}")
    print(f"\n{'PASS' if not failures else 'FAIL'}: on-screen preview, "
          f"{len(failures)} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
