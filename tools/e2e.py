#!/usr/bin/env python3
"""
End-to-end check of the staff workflow, through the real HTTP API.

Upload an official Europass PDF, confirm every section arrives, edit a field,
save, export all four formats, and re-import the exported PDF to prove the
round trip survives the whole app and not just the library calls.

    python tools/e2e.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

REFERENCE = BASE / "samples/reference/real_cv_will_almost_all_feilds.pdf"

SECTIONS = ("certifications", "honours_awards", "conferences", "creative_works",
            "projects", "publications", "recommendations", "social_political",
            "volunteering", "networks", "hobbies")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK ' if ok else 'FAIL'} {label}{(' - ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    # A scratch data directory so a test run never touches real student records.
    tmp = tempfile.mkdtemp(prefix="europass-e2e-")
    import os
    os.environ["DATA_DIR"] = tmp
    os.environ["ADMIN_PASSWORD"] = ""          # auth off for the test run

    from fastapi.testclient import TestClient
    import app as application

    client = TestClient(application.app)

    print("\nUpload an official Europass PDF")
    with REFERENCE.open("rb") as fh:
        r = client.post("/api/cvs/import", files={"file": (REFERENCE.name, fh, "application/pdf")})
    check("import accepted", r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}")
    if r.status_code not in (200, 201):
        return 1
    cv_id = r.json().get("id") or r.json().get("cv_id")
    check("record created", bool(cv_id), repr(r.json())[:200])

    print("\nEvery section survived the import")
    r = client.get(f"/api/cvs/{cv_id}")
    check("record readable", r.status_code == 200, str(r.status_code))
    cv = r.json().get("cv") or r.json().get("data") or r.json()
    for key in SECTIONS:
        check(f"section {key}", bool(cv.get(key)), "empty")
    check("photo kept", bool((cv.get("personal") or {}).get("photo")))
    check("driving licences kept", bool(cv.get("driving_licence")))

    print("\nEdit and save")
    cv["personal"]["first_name"] = "Edited"
    cv["certifications"][0]["title"] = "Edited certificate"
    r = client.put(f"/api/cvs/{cv_id}", json={"cv": cv})
    check("save accepted", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    r = client.get(f"/api/cvs/{cv_id}")
    saved = r.json().get("cv") or r.json().get("data") or r.json()
    check("edit persisted", saved["personal"]["first_name"] == "Edited")
    check("section edit persisted", saved["certifications"][0]["title"] == "Edited certificate")

    print("\nExport every format")
    blobs = {}
    for fmt, head in (("pdf", b"%PDF"), ("xml", b"<?xml"), ("docx", b"PK"), ("json", b"{")):
        r = client.get(f"/api/cvs/{cv_id}/export/{fmt}")
        ok = r.status_code == 200 and r.content.startswith(head)
        check(f"export {fmt}", ok, f"{r.status_code} {r.content[:40]!r}")
        if ok:
            blobs[fmt] = r.content

    print("\nOur own PDF is re-importable (the revision path)")
    if "pdf" in blobs:
        from europass_import import pdf_to_cv
        back, _ = pdf_to_cv(blobs["pdf"])
        check("PDF carries its XML", bool(back.get("personal")))
        check("name survives", back["personal"].get("first_name") == "Edited")
        for key in SECTIONS:
            check(f"re-import {key}", bool(back.get(key)), "empty")
        check("re-import photo", bool((back.get("personal") or {}).get("photo")))

    print("\nEditor page renders")
    r = client.get(f"/edit/{cv_id}")
    check("editor loads", r.status_code == 200, str(r.status_code))
    r = client.get("/")
    check("dashboard loads", r.status_code == 200, str(r.status_code))

    print(f"\n{'PASS' if not failures else 'FAIL'}: "
          f"{len(failures)} failing check(s)" + (": " + ", ".join(failures) if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
