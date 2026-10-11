#!/usr/bin/env python3
"""
Measure our rendered templates against the official Europass exports.

Renders the same CV in all four templates, then measures the page the same way
the references were measured - colour masks over a 150 dpi raster for fills,
pdftotext word boxes for text - and reports the difference in millimetres.

    python tools/template_check.py

Exit code 0 when every measurement is within tolerance.
"""
from __future__ import annotations

import copy
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

MM_PER_PX = 25.4 / 150.0
MM_PER_PT = 25.4 / 72.0
TOLERANCE_MM = 0.7

# What a genuine Europass export measures. See references/template-specs.md.
EXPECTED = {
    1: {"band height": 76.88, "photo diameter": 29.5, "photo left": 5.08, "photo top": 16.43,
        "logo width": 55.37, "logo right": 5.25, "logo top": 4.91},
    2: {"sidebar width": 67.39, "photo diameter": 34.04, "photo left": 16.26, "photo top": 6.77,
        "logo width": 55.37, "logo right": 6.10, "logo top": 6.94},
    3: {"top bar": 5.93, "bottom bar": 5.93, "top arm": 23.9, "bottom arm": 23.9,
        "photo diameter": 35.4, "photo top": 22.86,
        "logo width": 55.37, "logo right": 9.65, "logo top": 10.33},
    4: {"label right edge": 53.2, "body column": 57.6,
        "logo width": 55.37, "logo right": 5.25, "logo top": 4.91},
}


def mm(px):
    return round(px * MM_PER_PX, 2)


def runs(mask):
    out, start = [], None
    for i, on in enumerate(mask):
        if on and start is None:
            start = i
        elif not on and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def raster(pdf: Path, out_dir: Path) -> Image.Image:
    subprocess.run(["pdftoppm", "-r", "150", "-png", "-f", "1", "-l", "1",
                    str(pdf), str(out_dir / "p")], check=True, capture_output=True)
    return Image.open(next(out_dir.glob("p*.png"))).convert("RGB")


def words(pdf: Path, out_dir: Path):
    xml = out_dir / "w.xml"
    subprocess.run(["pdftotext", "-bbox-layout", "-f", "1", "-l", "1", str(pdf), str(xml)],
                   check=True, capture_output=True)
    text = xml.read_text(encoding="utf-8", errors="replace")
    return [(float(a), float(b), float(c), float(d), w) for a, b, c, d, w in re.findall(
        r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', text)]


def measure(number: int, pdf: Path, out_dir: Path) -> dict:
    img = raster(pdf, out_dir)
    a = np.array(img)
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    got = {}

    # The photo is a magenta stand-in so it cannot be confused with text
    # antialiasing, which sits in the same grey range as a real portrait.
    photo = (r > 230) & (g < 40) & (b > 230)
    if photo.any():
        ys, xs = np.where(photo)
        got["photo diameter"] = mm(xs.max() - xs.min() + 1)
        got["photo left"] = mm(xs.min())
        got["photo top"] = mm(ys.min())

    # The Europass logo: its wordmark purple and flag navy, in the top-right
    # band only, so blue section headings elsewhere cannot be mistaken for it.
    logo = (((abs(r - 108) < 30) & (abs(g - 48) < 30) & (abs(b - 136) < 30))
            | ((abs(r - 22) < 30) & (abs(g - 65) < 30) & (abs(b - 148) < 30)))
    window = np.zeros_like(logo)
    window[0:int(25 / MM_PER_PX), int(a.shape[1] * 0.5):] = True
    logo = logo & window
    if logo.any():
        ys, xs = np.where(logo)
        got["logo width"] = mm(xs.max() - xs.min() + 1)
        got["logo right"] = mm(a.shape[1] - 1 - xs.max())
        got["logo top"] = mm(ys.min())

    band = (abs(r - 245) < 5) & (abs(g - 245) < 5) & (abs(b - 245) < 5)
    if number == 1 and band.any():
        tall = [t for t in runs(band[:, a.shape[1] - 12]) if t[1] - t[0] > 20]
        if tall:
            got["band height"] = mm(tall[0][1] - tall[0][0] + 1)
    if number == 2 and band.any():
        wide = [t for t in runs(band[a.shape[0] // 2]) if t[1] - t[0] > 20]
        if wide:
            got["sidebar width"] = mm(wide[0][1] - wide[0][0] + 1)

    if number == 3:
        frame = (abs(r - 130) < 14) & (abs(g - 172) < 14) & (abs(b - 217) < 14)
        middle = [t for t in runs(frame[:, a.shape[1] // 2]) if t[1] - t[0] > 2]
        if len(middle) >= 2:
            got["top bar"] = mm(middle[0][1] - middle[0][0] + 1)
            got["bottom bar"] = mm(middle[-1][1] - middle[-1][0] + 1)
        edge = [t for t in runs(frame[:, 5]) if t[1] - t[0] > 2]
        if len(edge) >= 2:
            got["top arm"] = mm(edge[0][1] - edge[0][0] + 1)
            got["bottom arm"] = mm(edge[-1][1] - edge[-1][0] + 1)

    if number == 4:
        ws = words(pdf, out_dir)
        # section labels only: they sit in the left column, body text does not
        # Pick the section labels by name, not by where they already are:
        # filtering on "already near the left" is how an earlier version of
        # this check missed EDUCATION AND TRAINING and WORK EXPERIENCE sitting
        # in the content column instead of the label column.
        LABEL_WORDS = {"ABOUT", "ME", "EDUCATION", "TRAINING", "WORK",
                       "EXPERIENCE", "SKILLS", "LANGUAGE", "AND"}
        labels = [w for w in ws if w[4].isupper() and w[4] in LABEL_WORDS]
        if labels:
            got["label right edge"] = round(max(w[2] for w in labels) * MM_PER_PT, 2)
        body = [w for w in ws if not w[4].isupper() and w[0] * MM_PER_PT > 54]
        if body:
            got["body column"] = round(min(w[0] for w in body) * MM_PER_PT, 2)
    return got


def main() -> int:
    from extract import extract
    import europass_import
    from normalize import normalize_cv
    from generate import build_pdf

    reference = BASE / "samples/reference/real_cv_will_almost_all_feilds.pdf"
    xml = next(iter({n: d for n, d in extract(reference).items() if n.endswith(".xml")}.values()))
    cv, _ = europass_import.xml_to_cv(xml)
    cv, _ = normalize_cv(cv)
    # A flat magenta square stands in for the portrait so the mask is exact.
    cv["personal"]["photo"] = ("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcv"
                               "MjAwMC9zdmciIHdpZHRoPSIyMDAiIGhlaWdodD0iMjAwIj48cmVjdCB3aWR0aD0i"
                               "MjAwIiBoZWlnaHQ9IjIwMCIgZmlsbD0iI2ZmMDBmZiIvPjwvc3ZnPg==")

    failures, checks = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for number in (1, 2, 3, 4):
            work = Path(tmp) / f"t{number}"
            work.mkdir()
            variant = copy.deepcopy(cv)
            # No margin_mm: each template uses its own measured page margin.
            # frame stays on, so the Europass logo is drawn as the official
            # exports do (<Logo>FirstPage</Logo>).
            variant["design"] = {"template": f"template{number}", "page_numbers": False}
            pdf = work / "out.pdf"
            pdf.write_bytes(build_pdf(variant))
            got = measure(number, pdf, work)

            print(f"\nTemplate {number}")
            for label, target in EXPECTED[number].items():
                checks += 1
                value = got.get(label)
                if value is None:
                    print(f"   SKIP {label:18s} target {target:7}  (not measurable)")
                    failures.append(f"T{number} {label}: not measured")
                    continue
                delta = round(value - target, 2)
                ok = abs(delta) <= TOLERANCE_MM
                print(f"   {'OK ' if ok else 'OFF'} {label:18s} target {target:7}  got {value:7}  diff {delta:+}")
                if not ok:
                    failures.append(f"T{number} {label}: {value} vs {target}")

        # Template 2 changes shape after page 1: the sidebar narrows from
        # 67.39mm to 10.84mm and the text column moves left to 13mm. Page 1
        # alone cannot show that, and the official background images do.
        work = Path(tmp) / "t2-cont"
        work.mkdir()
        variant = copy.deepcopy(cv)
        variant["design"] = {"template": "template2", "page_numbers": False}
        pdf = work / "out.pdf"
        pdf.write_bytes(build_pdf(variant))
        subprocess.run(["pdftoppm", "-r", "150", "-png", "-f", "2", "-l", "2",
                        str(pdf), str(work / "p")], check=True, capture_output=True)
        page2 = next(work.glob("p*.png"))
        img = np.array(Image.open(page2).convert("RGB"))
        h, w = img.shape[:2]
        grey = ((abs(img[:, :, 0].astype(int) - 245) < 6)
                & (abs(img[:, :, 1].astype(int) - 245) < 6)
                & (abs(img[:, :, 2].astype(int) - 245) < 6))
        narrow = (grey.sum(axis=0) / h > 0.95).sum() * MM_PER_PX
        subprocess.run(["pdftotext", "-bbox-layout", "-f", "2", "-l", "2",
                        str(pdf), str(work / "w.xml")], check=True, capture_output=True)
        txt = (work / "w.xml").read_text(encoding="utf-8", errors="replace")
        xs = [float(x) for x in re.findall(r'<word xMin="([\d.]+)"', txt)]
        print("\nTemplate 2, page 2")
        for label, target, value in (("sidebar narrows", 10.84, round(narrow, 2)),
                                     ("text column", 13.0, round(min(xs) * MM_PER_PT, 2) if xs else None)):
            checks += 1
            if value is None:
                failures.append(f"T2 page 2 {label}: not measured")
                continue
            delta = round(value - target, 2)
            ok = abs(delta) <= TOLERANCE_MM
            print(f"   {'OK ' if ok else 'OFF'} {label:18s} target {target:7}  got {value:7}  diff {delta:+}")
            if not ok:
                failures.append(f"T2 page 2 {label}: {value} vs {target}")

    print(f"\n{checks - len(failures)}/{checks} measurements within {TOLERANCE_MM}mm of the official export.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
