#!/usr/bin/env python3
"""
Pull the embedded Europass XML out of a Europass PDF (official or ours).

    python extract.py cv.pdf              # writes cv.xml next to the PDF
    python extract.py cv.pdf -o ref.xml

Use it on a CV downloaded from europass.europa.eu to get the reference XML
for calibrating europass_xml.py, or to import existing candidates' data.
"""
import argparse
import sys
from pathlib import Path

from pypdf import PdfReader


def extract(pdf_path: Path) -> dict[str, bytes]:
    reader = PdfReader(str(pdf_path))
    return {name: data[0] for name, data in reader.attachments.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()

    attachments = extract(args.pdf)
    xml = {n: d for n, d in attachments.items() if n.lower().endswith(".xml")}
    if not xml:
        print("No XML attachment found - this PDF was not generated with Europass data.", file=sys.stderr)
        return 1
    name, data = next(iter(xml.items()))
    out = args.out or args.pdf.with_suffix(".xml")
    out.write_bytes(data)
    print(f"Extracted '{name}' ({len(data)} bytes) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
