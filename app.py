#!/usr/bin/env python3
"""
Europass CV editor - local web app.

    python app.py            then open http://localhost:8000

Endpoints
  GET  /                    the editor
  GET  /api/meta            fonts, section names, default design
  GET  /api/sample          sample CV
  GET  /api/blank           empty CV
  POST /api/render          {cv} -> editable HTML for the canvas
  POST /api/import          upload .json / Europass .pdf / Europass .xml -> {cv, warnings}
  POST /api/export/{fmt}    {cv} -> file (pdf, docx, png, html, xml, json)
"""

from __future__ import annotations

import base64
import io
import json
import re
import webbrowser
from pathlib import Path
from threading import Timer

import pymupdf
import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from cv_design import DEFAULT_DESIGN, FONTS, SECTION_LABELS, ensure_ids
from docx_export import build_docx
from europass_import import fill_codes, pdf_to_cv, xml_to_cv
from europass_xml import build_xml
from generate import BASE, TEMPLATES, build_pdf, file_stem, render_html, validate

STATIC = BASE / "static"
MAX_UPLOAD = 25 * 1024 * 1024

app = FastAPI(title="Europass CV editor")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/fonts", StaticFiles(directory=TEMPLATES / "fonts"), name="fonts")

BLANK_CV = {
    "language": "en",
    "personal": {"first_name": "First name", "last_name": "Last name", "nationalities": [],
                 "phone": {"type": "Mobile", "country_dialing": "", "number": ""},
                 "address": {"type": "Home"}},
    "about": "",
    "work_experience": [],
    "education": [],
    "languages": {"mother_tongues": [], "other": []},
    "digital_skills": [],
    "driving_licence": [],
    "additional_sections": [],
    "design": DEFAULT_DESIGN,
}


def cv_from_body(body: dict) -> dict:
    cv = body.get("cv") if isinstance(body, dict) else None
    if not isinstance(cv, dict):
        raise HTTPException(400, "Request body must be {\"cv\": {...}}.")
    cv.setdefault("personal", {})
    return fill_codes(ensure_ids(cv))


# ------------------------------------------------------------------ pages ---

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta():
    return {
        "fonts": {k: v["label"] for k, v in FONTS.items()},
        "sections": SECTION_LABELS,
        "design": DEFAULT_DESIGN,
    }


@app.get("/api/sample")
def sample():
    return json.loads((BASE / "samples" / "sample_cv.json").read_text(encoding="utf-8"))


@app.get("/api/blank")
def blank():
    return BLANK_CV


@app.post("/api/render")
def render(body: dict):
    return {"html": render_html(cv_from_body(body), editable=True)}


# ----------------------------------------------------------------- import ---

@app.post("/api/import")
async def import_file(file: UploadFile):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 25 MB.")
    name = (file.filename or "").lower()
    try:
        if name.endswith(".json"):
            cv, warnings = json.loads(data.decode("utf-8")), []
        elif name.endswith(".pdf"):
            cv, warnings = pdf_to_cv(data)
        elif name.endswith(".xml"):
            cv, warnings = xml_to_cv(data)
        else:
            raise ValueError("Upload a .json, Europass .pdf or Europass .xml file.")
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"The JSON file is not valid: {exc}") from exc
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"cv": ensure_ids(cv), "warnings": warnings}


# ----------------------------------------------------------------- export ---

def html_standalone(cv: dict) -> str:
    """HTML with fonts embedded so the file works on its own."""
    html = render_html(cv)

    def inline(match):
        font = TEMPLATES / "fonts" / match.group(1)
        if not font.exists():
            return match.group(0)
        return f'url("data:font/ttf;base64,{base64.b64encode(font.read_bytes()).decode()}")'

    html = re.sub(r'url\("fonts/([^"]+)"\)', inline, html)
    screen = ("<style>@media screen{html{background:#e7e9ec}body{width:210mm;margin:24px auto;"
              "padding:10mm var(--page-margin) 12mm;background:#fff;box-shadow:0 2px 12px rgba(0,0,0,.12)}}</style>")
    return html.replace("</head>", screen + "</head>", 1)


def png_pages(pdf: bytes) -> bytes:
    """All pages stacked into one tall PNG."""
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=150)
        pages.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    gap = 24
    width = max(p.width for p in pages)
    sheet = Image.new("RGB", (width, sum(p.height for p in pages) + gap * (len(pages) - 1)), (231, 233, 236))
    y = 0
    for p in pages:
        sheet.paste(p, (0, y))
        y += p.height + gap
    out = io.BytesIO()
    sheet.save(out, "PNG", optimize=True)
    return out.getvalue()


EXPORTS = {
    "pdf": ("application/pdf", "pdf"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "png": ("image/png", "png"),
    "html": ("text/html; charset=utf-8", "html"),
    "xml": ("application/xml", "xml"),
    "json": ("application/json", "json"),
}


@app.post("/api/export/{fmt}")
def export(fmt: str, body: dict):
    if fmt not in EXPORTS:
        raise HTTPException(404, f"Unknown format '{fmt}'.")
    cv = cv_from_body(body)
    errors = validate(cv, "CV")
    if errors and fmt in ("pdf", "docx", "png", "xml"):
        raise HTTPException(422, "Fix before downloading: " + "; ".join(e.split(": ", 1)[-1] for e in errors) + ".")

    if fmt == "pdf":
        data = build_pdf(cv)
    elif fmt == "docx":
        data = build_docx(cv)
    elif fmt == "png":
        data = png_pages(build_pdf(cv, embed=False))
    elif fmt == "html":
        data = html_standalone(cv).encode("utf-8")
    elif fmt == "xml":
        data = build_xml(cv)
    else:
        data = json.dumps(cv, indent=2, ensure_ascii=False).encode("utf-8")

    mime, ext = EXPORTS[fmt]
    return Response(data, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{file_stem(cv)}.{ext}"',
    })


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


if __name__ == "__main__":
    url = "http://localhost:8000"
    print(f"\n  Europass CV editor running at {url}  (Ctrl+C to stop)\n")
    Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
