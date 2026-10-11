#!/usr/bin/env python3
"""
Round-trip fidelity checking.

The problem this solves: a converter silently drops fields. You only find out
when a student's CV reaches a university with half of it missing.

The standard defence is a round trip. Take a document, read it in, write it
back out, read it in again, and compare. Anything that does not survive the
journey is a bug, and the comparison finds it automatically instead of someone
noticing months later.

    python fidelity.py                     check every PDF/XML in samples/reference
    python fidelity.py a_real_europass.pdf check one file
    python fidelity.py --json              machine-readable, for CI

Exit code is 0 when nothing was lost and 1 when something was, so this can run
in a deployment pipeline and block a release that would lose data.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parent

# Fields worth comparing. Each is a readable name and how to pull it out of a
# CV dict, so a missing field is reported as "passport", not "personal[3]".
PROBES: dict = {
    "first name":        lambda c: c.get("personal", {}).get("first_name"),
    "last name":         lambda c: c.get("personal", {}).get("last_name"),
    "date of birth":     lambda c: c.get("personal", {}).get("date_of_birth"),
    "gender":            lambda c: c.get("personal", {}).get("gender"),
    "passport":          lambda c: c.get("personal", {}).get("passport"),
    "place of birth":    lambda c: (c.get("personal", {}).get("place_of_birth") or {}).get("country"),
    "email":             lambda c: c.get("personal", {}).get("email"),
    "phone number":      lambda c: (c.get("personal", {}).get("phone") or {}).get("number"),
    "phone country code": lambda c: (c.get("personal", {}).get("phone") or {}).get("country_dialing"),
    "website":           lambda c: c.get("personal", {}).get("website"),
    "address city":      lambda c: (c.get("personal", {}).get("address") or {}).get("city"),
    "address country":   lambda c: (c.get("personal", {}).get("address") or {}).get("country"),
    "nationality":       lambda c: [n.get("name") for n in c.get("personal", {}).get("nationalities") or []],
    "about me":          lambda c: (c.get("about") or "")[:120],
    "education count":   lambda c: len(c.get("education") or []),
    "education titles":  lambda c: [e.get("title") for e in c.get("education") or []],
    "education orgs":    lambda c: [e.get("organisation") for e in c.get("education") or []],
    "education dates":   lambda c: [(e.get("start"), e.get("end")) for e in c.get("education") or []],
    "work count":        lambda c: len(c.get("work_experience") or []),
    "work titles":       lambda c: [w.get("title") for w in c.get("work_experience") or []],
    "work employers":    lambda c: [w.get("employer") for w in c.get("work_experience") or []],
    "mother tongues":    lambda c: [m.get("name") for m in (c.get("languages") or {}).get("mother_tongues") or []],
    "other languages":   lambda c: [l.get("name") for l in (c.get("languages") or {}).get("other") or []],
    "language levels":   lambda c: [l.get("listening") for l in (c.get("languages") or {}).get("other") or []],
    "skills":            lambda c: sorted(
        n for g in (c.get("digital_skills") or [])
        for n in (g.get("items", []) if isinstance(g, dict) else [g])),
    "skill groups":      lambda c: [g.get("title") for g in (c.get("digital_skills") or [])
                                    if isinstance(g, dict)],

    # Typed sections. These are the ones that used to be flattened into
    # {heading, text} pairs and lost their dates, locations and links.
    "photo":             lambda c: bool((c.get("personal") or {}).get("photo")),
    "document type":     lambda c: (c.get("personal") or {}).get("document_type"),
    "work permit":       lambda c: (c.get("personal") or {}).get("work_permit_country"),
    "social media":      lambda c: [(s.get("type"), s.get("username"), s.get("url"))
                                    for s in (c.get("personal") or {}).get("social_media") or []],
    "instant messaging": lambda c: [(s.get("type"), s.get("value"))
                                    for s in (c.get("personal") or {}).get("instant_messaging") or []],
    "driving licences":  lambda c: sorted(c.get("driving_licence") or []),
    "employer websites": lambda c: [j.get("website") for j in c.get("work_experience") or []],
    "employer emails":   lambda c: [j.get("email") for j in c.get("work_experience") or []],
    "departments":       lambda c: [j.get("department") for j in c.get("work_experience") or []],
    "education websites": lambda c: [e.get("website") for e in c.get("education") or []],
    "education credits": lambda c: [e.get("credits") for e in c.get("education") or []],
    "certifications":    lambda c: [(e.get("title"), e.get("organisation"), e.get("date"),
                                     e.get("mode"), e.get("url")) for e in c.get("certifications") or []],
    "honours":           lambda c: [(e.get("title"), e.get("organisation"), e.get("date"))
                                    for e in c.get("honours_awards") or []],
    "conferences":       lambda c: [(e.get("title"), e.get("start"), e.get("end"),
                                     e.get("location"), e.get("url")) for e in c.get("conferences") or []],
    "creative works":    lambda c: [(e.get("title"), e.get("start"), e.get("end"), e.get("url"))
                                    for e in c.get("creative_works") or []],
    "projects":          lambda c: [(e.get("title"), e.get("start"), e.get("end"))
                                    for e in c.get("projects") or []],
    "publications":      lambda c: [(e.get("title"), e.get("year"), e.get("authors"), e.get("journal"),
                                     e.get("publisher"), e.get("volume"), e.get("doi"), e.get("reference"))
                                    for e in c.get("publications") or []],
    "referees":          lambda c: [(e.get("name"), e.get("role"), e.get("email"), e.get("phone"))
                                    for e in c.get("recommendations") or []],
    "social/political":  lambda c: [(e.get("title"), e.get("start"), e.get("end"), e.get("location"))
                                    for e in c.get("social_political") or []],
    "volunteering":      lambda c: [(e.get("title"), e.get("start"), e.get("end"), e.get("location"))
                                    for e in c.get("volunteering") or []],
    "networks":          lambda c: [(e.get("title"), e.get("start"), e.get("end"), e.get("location"))
                                    for e in c.get("networks") or []],
    "hobbies":           lambda c: [(e.get("title"), (e.get("description") or "")[:60])
                                    for e in c.get("hobbies") or []],
    "driving licence":   lambda c: sorted(c.get("driving_licence") or []),
    "extra sections":    lambda c: sorted((s.get("title") or "") for s in c.get("additional_sections") or []),
    "extra items":       lambda c: sum(len(s.get("items") or []) for s in c.get("additional_sections") or []),
    "closing statement": lambda c: ((c.get("closing_statement") or {}).get("text") or "")[:80],
    "closing place":     lambda c: (c.get("closing_statement") or {}).get("place"),
}


def _blanks_alike(value):
    """None and "" mean the same thing here: the field is empty.

    The top-level rule below already treats an empty value that stays empty as
    no loss. Inside a list of tuples - one per certification, say - a single
    absent key would otherwise make the whole section look changed, hiding the
    real losses among the noise.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return [_blanks_alike(v) for v in value]
    if isinstance(value, dict):
        return {k: _blanks_alike(v) for k, v in value.items()}
    return value


def compare(before: dict, after: dict) -> list[dict]:
    """Return one entry per field that changed on the round trip."""
    losses = []
    for name, probe in PROBES.items():
        try:
            was, now = probe(before), probe(after)
        except Exception as exc:                      # a probe must never crash the run
            losses.append({"field": name, "before": "?", "after": "?", "note": f"probe failed: {exc}"})
            continue
        if was == now or _blanks_alike(was) == _blanks_alike(now):
            continue
        # An empty value that stays empty in another shape is not a loss.
        if not was and not now:
            continue
        losses.append({"field": name, "before": was, "after": now,
                       "note": "lost" if was and not now else "changed"})
    return losses


def round_trip(path: Path) -> tuple[list[dict], str]:
    """Read the file, write a PDF, read that back, and compare the two."""
    from europass_import import pdf_to_cv, xml_to_cv
    from generate import build_pdf
    from normalize import normalize_cv

    data = path.read_bytes()
    first = xml_to_cv(data)[0] if path.suffix.lower() == ".xml" else pdf_to_cv(data)[0]
    normalised = normalize_cv(first)[0]
    rebuilt = pdf_to_cv(build_pdf(normalised))[0]
    return compare(normalised, rebuilt), path.name


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help="Europass PDF or XML files to check")
    ap.add_argument("--json", action="store_true", help="machine-readable output for CI")
    args = ap.parse_args()

    files = args.files or sorted((BASE / "samples" / "reference").glob("*.pdf"))
    if not files:
        print("No files to check. Put accepted Europass CVs in samples/reference/,\n"
              "or pass one on the command line.", file=sys.stderr)
        return 1

    report, failed = [], 0
    for path in files:
        try:
            losses, name = round_trip(path)
        except Exception as exc:
            report.append({"file": path.name, "error": str(exc)})
            failed += 1
            continue
        report.append({"file": name, "losses": losses})
        if losses:
            failed += 1

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 1 if failed else 0

    for entry in report:
        if entry.get("error"):
            print(f"\n✗ {entry['file']}: could not be read - {entry['error']}")
            continue
        losses = entry["losses"]
        if not losses:
            print(f"\n✓ {entry['file']}: nothing lost ({len(PROBES)} fields checked)")
            continue
        print(f"\n✗ {entry['file']}: {len(losses)} field(s) changed")
        for loss in losses:
            print(f"    {loss['field']}")
            print(f"        before: {loss['before']!r}")
            print(f"        after:  {loss['after']!r}")

    print(f"\n{len(report) - failed}/{len(report)} file(s) survived the round trip.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())