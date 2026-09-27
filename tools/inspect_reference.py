#!/usr/bin/env python3
"""
Report fonts, sizes and colours used in a real Europass PDF, so the tokens at
the top of templates/europass_cv.css can be set to exact values.

    python tools/inspect_reference.py real_europass_cv.pdf
"""
import sys
from collections import Counter

import pymupdf


def main(path: str) -> None:
    doc = pymupdf.open(path)
    page = doc[0]
    print(f"Page size: {page.rect.width:.1f} x {page.rect.height:.1f} pt\n")

    styles = Counter()
    samples = {}
    min_x, max_x = page.rect.width, 0
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                key = (span["font"], round(span["size"], 1), f"#{span['color']:06x}")
                styles[key] += len(text)
                samples.setdefault(key, text[:40])
                min_x = min(min_x, span["bbox"][0])
                max_x = max(max_x, span["bbox"][2])

    print(f"{'font':<32}{'size':>6}  {'colour':<9} sample")
    for (font, size, color), _ in styles.most_common():
        print(f"{font:<32}{size:>6}  {color:<9} {samples[(font, size, color)]}")

    mm = 25.4 / 72
    print(f"\nText left edge  ≈ {min_x * mm:.1f} mm")
    print(f"Text right edge ≈ {(page.rect.width - max_x) * mm:.1f} mm from right")

    colors = Counter()
    for d in page.get_drawings():
        for c in (d.get("color"), d.get("fill")):
            if c:
                colors["#%02x%02x%02x" % tuple(int(v * 255) for v in c[:3])] += 1
    if colors:
        print("\nLine / fill colours:", ", ".join(c for c, _ in colors.most_common(6)))


if __name__ == "__main__":
    main(sys.argv[1])
