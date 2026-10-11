#!/usr/bin/env python3
"""
Structural diff between an official Europass XML and the XML we generate from
the same candidate data.

The round-trip check in fidelity.py compares a fixed list of ~30 readable
fields. This goes the other way: it walks every element path the European
Commission's own export contains and asks whether ours contains it too. That
is what catches a section being written into a generic <Others> bucket, or a
field we collect in the editor but never serialise.

    python tools/xml_diff.py samples/reference/*.pdf
    python tools/xml_diff.py --json

Exit code 0 when every path in the official file is present in ours.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lxml import etree  # noqa: E402

import europass_import  # noqa: E402
import europass_xml  # noqa: E402
from extract import extract  # noqa: E402

NS = {
    "http://www.europass.eu/1.0": "ep",
    "http://www.openapplications.org/oagis/9": "oa",
    "http://www.hr-xml.org/3": "hr",
    "http://www.europass_eures.eu/1.0": "eures",
}

# Paths that legitimately differ and are not data loss.
IGNORE_PREFIXES = (
    "/ep:Candidate/ep:CandidateSupplier",   # who generated the file
    "/ep:Candidate/hr:DocumentID",          # per-document identifier
)


def short(tag: str) -> str:
    if not tag.startswith("{"):
        return tag
    uri, local = tag[1:].split("}")
    return f"{NS.get(uri, '?')}:{local}"


def paths(root) -> Counter:
    found: Counter = Counter()

    def walk(el, trail):
        p = f"{trail}/{short(el.tag)}"
        found[p] += 1
        for child in el:
            walk(child, p)

    walk(root, "")
    return found


def ignored(path: str) -> bool:
    return any(path.startswith(p) for p in IGNORE_PREFIXES)


def compare(pdf: Path) -> dict:
    attachments = {n: d for n, d in extract(pdf).items() if n.lower().endswith(".xml")}
    if not attachments:
        return {"file": pdf.name, "error": "no embedded XML"}
    official_bytes = next(iter(attachments.values()))

    cv, _warnings = europass_import.xml_to_cv(official_bytes)
    ours_bytes = europass_xml.build_xml(cv)
    if isinstance(ours_bytes, str):
        ours_bytes = ours_bytes.encode("utf-8")

    official = paths(etree.fromstring(official_bytes))
    ours = paths(etree.fromstring(ours_bytes))

    missing = sorted(p for p in official if p not in ours and not ignored(p))
    extra = sorted(p for p in ours if p not in official and not ignored(p))
    thin = sorted(
        f"{p} ({ours[p]}/{official[p]})"
        for p in official
        if p in ours and ours[p] < official[p] and not ignored(p)
    )
    return {
        "file": pdf.name,
        "official_paths": len(official),
        "our_paths": len(ours),
        "missing": missing,
        "extra": extra,
        "undercount": thin,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    files = args.files or sorted((Path(__file__).resolve().parent.parent / "samples/reference").glob("*.pdf"))
    results = [compare(f) for f in files]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            if r.get("error"):
                print(f"\n  {r['file']}: {r['error']}")
                continue
            ok = not r["missing"] and not r["undercount"]
            mark = "OK " if ok else "GAP"
            print(f"\n{mark} {r['file']}  ({r['our_paths']}/{r['official_paths']} element paths)")
            for p in r["missing"]:
                print(f"      missing   {p}")
            for p in r["undercount"]:
                print(f"      too few   {p}")

    bad = sum(1 for r in results if r.get("missing") or r.get("undercount") or r.get("error"))
    print(f"\n{len(results) - bad}/{len(results)} file(s) reproduce every official element path.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
