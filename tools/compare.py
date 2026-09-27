#!/usr/bin/env python3
"""
Visual diff between an official Europass PDF and ours (same candidate data).

    python tools/compare.py official.pdf ours.pdf -o diff/

Writes one PNG per page (red = differences) and prints % of differing pixels.
Iterate on templates/europass_cv.css until the numbers are close to zero.
"""
import argparse
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops


def render(path, dpi=100):
    doc = pymupdf.open(path)
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        yield Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reference")
    ap.add_argument("candidate")
    ap.add_argument("-o", "--out", default="diff")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(exist_ok=True)

    ref_pages, cand_pages = list(render(args.reference)), list(render(args.candidate))
    if len(ref_pages) != len(cand_pages):
        print(f"Page count differs: reference {len(ref_pages)}, ours {len(cand_pages)}")

    for i, (a, b) in enumerate(zip(ref_pages, cand_pages), start=1):
        b = b.resize(a.size)
        diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 40 else 0)
        pct = 100 * diff.histogram()[255] / (a.width * a.height)
        overlay = Image.blend(a.convert("RGB"), b.convert("RGB"), 0.5)
        overlay.paste((220, 30, 30), mask=diff)
        overlay.save(out / f"page_{i}.png")
        print(f"Page {i}: {pct:.2f}% pixels differ -> {out / f'page_{i}.png'}")


if __name__ == "__main__":
    main()
