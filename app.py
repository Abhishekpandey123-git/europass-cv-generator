#!/usr/bin/env python3
"""
Europass CV service.

    python app.py            then open http://localhost:8000

Two ways in:

1. Client website -> /api/v1/...  (header X-API-Key, see INTEGRATION.md)
   The website sends a student's details; the service cleans them, stores a CV
   and answers with its id, an edit link for staff and a PDF link.

2. Staff -> the dashboard at /  (password from ADMIN_PASSWORD)
   Lists every CV, opens it in the editor (/edit/<id>) for manual changes,
   and downloads PDF / Word / Europass XML / PNG / HTML / JSON.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import re
import time
import webbrowser
from collections import defaultdict, deque
from threading import Timer

import pymupdf
import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

import storage
from config import ADMIN_PASSWORD, API_KEYS, HOST, PORT, PUBLIC_URL, ROOT_PATH, SECRET_KEY
from cv_design import DEFAULT_DESIGN, FONTS, SECTION_LABELS, ensure_ids, with_standard_sections
from docx_export import build_docx
from europass_import import fill_codes, pdf_to_cv, xml_to_cv
from form_import import form_text_to_cv, form_to_cv, looks_like_form
from text_import import extract_text, file_to_cv, rejected_reason, text_to_cv
from europass_xml import build_xml
from generate import BASE, TEMPLATES, build_pdf, file_stem, render_html, validate
from normalize import normalize_cv

STATIC = BASE / "static"
MAX_UPLOAD = 25 * 1024 * 1024
COOKIE = "cv_staff"
SESSION_HOURS = 12

app = FastAPI(
    title="Europass CV service",
    description="API for the client's website. Send a student's details, get a Europass CV back. "
                "Every request needs the header `X-API-Key`.",
    version="1.0",
    root_path=ROOT_PATH,          # e.g. "/cv" when served under a sub-path
)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/fonts", StaticFiles(directory=TEMPLATES / "fonts"), name="fonts")


class NeedLogin(Exception):
    pass


# ================================================================ security ===

def _sign(value: str) -> str:
    return hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def _is_staff(request: Request) -> bool:
    if not ADMIN_PASSWORD:
        return True                      # local use without a password
    token = request.cookies.get(COOKIE, "")
    expires, _, sig = token.partition(".")
    return (expires.isdigit() and int(expires) > time.time()
            and hmac.compare_digest(sig, _sign(f"staff:{expires}")))


def staff_api(request: Request):
    if not _is_staff(request):
        raise HTTPException(401, "Please sign in again.")


def staff_page(request: Request):
    if not _is_staff(request):
        raise NeedLogin()


def api_key(request: Request):
    if not API_KEYS:
        raise HTTPException(503, "The website API is switched off. Set API_KEYS in the .env file.")
    key = request.headers.get("X-API-Key", "")
    if not any(hmac.compare_digest(key, k) for k in API_KEYS):
        raise HTTPException(401, "Missing or wrong X-API-Key header.")


_login_attempts: dict[str, deque] = defaultdict(deque)


@app.exception_handler(NeedLogin)
async def _need_login(request: Request, _):
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


@app.exception_handler(HTTPException)
async def _http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.middleware("http")
async def _headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


# ================================================================= helpers ===

def body_cv(body: dict) -> dict:
    cv = body.get("cv") if isinstance(body, dict) else None
    if not isinstance(cv, dict):
        raise HTTPException(400, 'Request body must be {"cv": {...}}.')
    cv.setdefault("personal", {})
    return fill_codes(ensure_ids(cv))


def get_record(cv_id: str) -> dict:
    record = storage.get(cv_id)
    if not record:
        raise HTTPException(404, "No CV with this id.")
    return record


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
              "padding:10mm var(--page-margin) 12mm;background-color:#fff;box-shadow:0 2px 12px rgba(0,0,0,.12)}}</style>")
    return html.replace("</head>", screen + "</head>", 1)


def png_pages(pdf: bytes) -> bytes:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=150)
        pages.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    gap = 24
    sheet = Image.new("RGB", (max(p.width for p in pages), sum(p.height for p in pages) + gap * (len(pages) - 1)),
                      (231, 233, 236))
    y = 0
    for p in pages:
        sheet.paste(p, (0, y))
        y += p.height + gap
    out = io.BytesIO()
    sheet.save(out, "PNG", optimize=True)
    return out.getvalue()


EXPORTS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png",
    "html": "text/html; charset=utf-8",
    "xml": "application/xml",
    "json": "application/json",
}


def export_response(cv: dict, fmt: str) -> Response:
    if fmt not in EXPORTS:
        raise HTTPException(404, f"Unknown format '{fmt}'. Use one of: {', '.join(EXPORTS)}.")
    cv = fill_codes(ensure_ids(cv))
    if fmt in ("pdf", "docx", "png", "xml"):
        errors = validate(cv, "CV")
        if errors:
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
    return Response(data, media_type=EXPORTS[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{file_stem(cv)}.{fmt}"'})


def parse_upload(filename: str, data: bytes) -> tuple[dict, list[str]]:
    """
    Read an uploaded file. Structured sources first (they are exact); anything
    else falls back to reading the text and guessing the fields, which staff
    then check. Only video, audio, archives and programs are refused.
    """
    name = (filename or "").lower()
    reason = rejected_reason(name)
    if reason:
        raise HTTPException(415, reason)
    try:
        if name.endswith(".json"):
            raw = json.loads(data.decode("utf-8-sig"))
            raw = raw.get("cv", raw) if isinstance(raw, dict) else raw
            if isinstance(raw, dict) and ("personal" in raw or "personal_info" in raw):
                return normalize_cv(raw)            # our own format
            return normalize_free(*file_to_cv(filename, data))
        if name.endswith(".xml"):
            return xml_to_cv(data)
        if name.endswith(".pdf"):
            try:
                return pdf_to_cv(data)              # Europass PDF: exact data inside
            except ValueError:
                pass
        if name.endswith(".docx"):
            try:
                return form_to_cv(data)             # our Student Information Form
            except ValueError:
                pass
        # everything else: read the text, then the form layout if we recognise it
        text = extract_text(filename, data)
        if looks_like_form(text):
            return form_text_to_cv(text)
        return normalize_free(*text_to_cv(text))
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"The JSON file is not valid: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def normalize_free(raw: dict, notes: list[str]) -> tuple[dict, list[str]]:
    cv, warnings = normalize_cv(raw)
    return cv, notes + warnings


def public_links(cv_id: str) -> dict:
    return {
        "edit_url": f"{PUBLIC_URL}/edit/{cv_id}",
        "downloads": {fmt: f"{PUBLIC_URL}/api/v1/cvs/{cv_id}/{fmt}" for fmt in ("pdf", "docx", "xml", "json")},
    }


# =================================================== 1. API for the website ===

@app.post("/api/v1/cvs", tags=["Website API"], dependencies=[Depends(api_key)], status_code=201)
async def api_create(request: Request):
    """
    Send a student's details. Body: `{"external_id": "your-id", "cv": {...}}`
    (or the CV object on its own). Sending the same `external_id` again updates
    that CV, unless staff have already started editing it; then a new CV is
    created so their work is not overwritten.
    """
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Body must be JSON.") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object.")
    raw = body.get("cv", body)
    external_id = str(body.get("external_id") or "").strip() or None
    try:
        cv, warnings = normalize_cv(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    existing = storage.find_external(external_id) if external_id else None
    if existing and existing["status"] == "new":
        record = storage.update(existing["id"], cv=cv, original=raw, warnings=warnings)
        created = False
    else:
        if existing:
            warnings.append(f"Sent again by the website; the earlier CV ({existing['id']}) had already been edited and was kept.")
        record = storage.create(with_standard_sections(cv), source="website", external_id=external_id, original=raw, warnings=warnings)
        created = True

    return JSONResponse({
        "id": record["id"], "external_id": external_id, "status": record["status"],
        "created": created, "warnings": warnings, **public_links(record["id"]),
    }, status_code=201 if created else 200)


@app.get("/api/v1/cvs", tags=["Website API"], dependencies=[Depends(api_key)])
def api_find(external_id: str):
    """Look up the CV made for one of your own ids."""
    record = storage.find_external(external_id)
    if not record:
        raise HTTPException(404, "No CV for this external_id.")
    return {k: record[k] for k in ("id", "external_id", "status", "name", "updated_at")} | public_links(record["id"])


@app.get("/api/v1/cvs/{cv_id}", tags=["Website API"], dependencies=[Depends(api_key)])
def api_get(cv_id: str):
    """Status and data of one CV (status: new, in_review or ready)."""
    record = get_record(cv_id)
    return {k: record[k] for k in ("id", "external_id", "status", "name", "warnings", "created_at", "updated_at", "cv")} \
        | public_links(cv_id)


@app.get("/api/v1/cvs/{cv_id}/{fmt}", tags=["Website API"], dependencies=[Depends(api_key)])
def api_download(cv_id: str, fmt: str):
    """Download the CV as pdf, docx, xml, json, png or html."""
    return export_response(get_record(cv_id)["cv"], fmt)


# ============================================================ 2. staff UI ===

LOGIN_PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Sign in · Europass CV service</title>
<link rel="icon" href="/static/favicon.ico" sizes="any"><link rel="icon" type="image/png" href="/static/favicon-32.png"><link rel="stylesheet" href="/static/editor.css"><style>
body{{display:grid;place-items:center;min-height:100vh;height:auto}}
form{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:28px;width:min(360px,92vw)}}
h1{{font-size:18px;margin:0 0 4px}} p{{color:var(--ink-soft);margin:0 0 20px}}
.error{{color:var(--danger);margin:-6px 0 14px}}</style></head><body>
<form method="post" action="/login"><h1>Europass CV service</h1><p>Sign in to manage CVs.</p>
{error}<label class="field"><span>Password</span><input type="password" name="password" autofocus required></label>
<input type="hidden" name="next" value="{next}"><button class="btn btn-primary full" type="submit">Sign in</button></form>
</body></html>"""


def _safe_next(target: str) -> str:
    return target if target.startswith("/") and not target.startswith("//") else "/"


# ------------------------------------------------- student form (public) ---

FORM_PREFIX = "form:"


def form_token() -> str:
    """A signed token so only links we issued open the form."""
    return _sign(FORM_PREFIX + "v1")[:32]


def check_form_token(token: str) -> None:
    if not hmac.compare_digest(token or "", form_token()):
        raise HTTPException(404, "This link is not valid. Ask the office for a new one.")


@app.get("/apply/{token}", include_in_schema=False)
def student_form(token: str):
    """The page a student opens from the link staff send them."""
    check_form_token(token)
    return FileResponse(STATIC / "apply.html")


@app.post("/apply/{token}", include_in_schema=False, status_code=201)
async def student_form_submit(token: str, request: Request):
    """A student's answers arrive here and become a CV for staff to review."""
    check_form_token(token)
    try:
        raw = await request.json()
    except Exception as exc:
        raise HTTPException(400, "The form could not be read. Please try again.") from exc
    if not isinstance(raw, dict):
        raise HTTPException(400, "The form could not be read. Please try again.")
    try:
        cv, warnings = normalize_cv(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    name = f"{cv['personal'].get('first_name', '')} {cv['personal'].get('last_name', '')}".strip()
    warnings.insert(0, f"Filled in by the student through the shared form{' (' + name + ')' if name else ''}. "
                       "Please check every field before sending.")
    record = storage.create(fill_codes(ensure_ids(with_standard_sections(cv))),
                            source="student", original=raw, warnings=warnings)
    return {"id": record["id"]}


@app.get("/api/form-link", include_in_schema=False, dependencies=[Depends(staff_api)])
def form_link():
    """The link staff copy and send to a student."""
    return {"url": f"{PUBLIC_URL}/apply/{form_token()}"}


@app.get("/login", include_in_schema=False)
def login_page(next: str = "/"):
    if not ADMIN_PASSWORD:
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(LOGIN_PAGE.format(error="", next=_safe_next(next)))


@app.post("/login", include_in_schema=False)
def login(request: Request, password: str = Form(...), next: str = Form("/")):
    ip = request.client.host if request.client else "?"
    attempts = _login_attempts[ip]
    while attempts and time.time() - attempts[0] > 300:
        attempts.popleft()
    if len(attempts) >= 8:
        return HTMLResponse(LOGIN_PAGE.format(error='<p class="error">Too many attempts. Wait 5 minutes.</p>', next="/"), 429)
    if not ADMIN_PASSWORD or not hmac.compare_digest(password, ADMIN_PASSWORD):
        attempts.append(time.time())
        return HTMLResponse(LOGIN_PAGE.format(error='<p class="error">Wrong password.</p>', next=_safe_next(next)), 401)
    expires = str(int(time.time() + SESSION_HOURS * 3600))
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(COOKIE, f"{expires}.{_sign(f'staff:{expires}')}", httponly=True, samesite="lax",
                        secure=PUBLIC_URL.startswith("https"), max_age=SESSION_HOURS * 3600)
    return response


@app.post("/logout", include_in_schema=False)
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response


@app.get("/", include_in_schema=False, dependencies=[Depends(staff_page)])
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


@app.get("/edit/{cv_id}", include_in_schema=False, dependencies=[Depends(staff_page)])
def editor(cv_id: str):
    if not storage.get(cv_id):
        return RedirectResponse("/?missing=1", status_code=303)
    return FileResponse(STATIC / "index.html")


# ----------------------------------------------------------- staff API ---

staff = [Depends(staff_api)]


@app.get("/api/meta", include_in_schema=False, dependencies=staff)
def meta():
    return {"fonts": {k: v["label"] for k, v in FONTS.items()}, "sections": SECTION_LABELS, "design": DEFAULT_DESIGN,
            "password": bool(ADMIN_PASSWORD), "website_api": bool(API_KEYS)}


@app.get("/api/cvs", include_in_schema=False, dependencies=staff)
def list_cvs(q: str = "", status: str = "", limit: int = 100, offset: int = 0):
    items, total = storage.list_cvs(q.strip(), status, min(limit, 500), offset)
    return {"items": items, "total": total, "counts": storage.counts()}


@app.post("/api/cvs", include_in_schema=False, dependencies=staff, status_code=201)
def new_cv(body: dict | None = None):
    body = body or {}
    if body.get("template") == "sample":
        cv = json.loads((BASE / "samples" / "sample_cv.json").read_text(encoding="utf-8"))
    else:
        cv = {"personal": {"first_name": "First name", "last_name": "Last name"},
              "work_experience": [], "education": [], "languages": {"mother_tongues": [], "other": []}}
    return storage.create(fill_codes(ensure_ids(with_standard_sections(cv))), status="in_review")


@app.post("/api/cvs/import", include_in_schema=False, dependencies=staff, status_code=201)
async def import_new(file: UploadFile):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 25 MB.")
    cv, warnings = parse_upload(file.filename, data)
    return storage.create(fill_codes(ensure_ids(with_standard_sections(cv))), source="upload", warnings=warnings, status="in_review")


@app.get("/api/cvs/{cv_id}", include_in_schema=False, dependencies=staff)
def get_cv(cv_id: str):
    return get_record(cv_id)


@app.put("/api/cvs/{cv_id}", include_in_schema=False, dependencies=staff)
def save_cv(cv_id: str, body: dict):
    get_record(cv_id)
    cv = body_cv(body) if "cv" in body else None
    status = body.get("status")
    if cv is not None and status is None and storage.get(cv_id)["status"] == "new":
        status = "in_review"            # first manual edit
    try:
        record = storage.update(cv_id, cv=cv, status=status,
                                warnings=body.get("warnings") if isinstance(body.get("warnings"), list) else None)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {k: record[k] for k in ("id", "status", "name", "updated_at", "warnings")}


@app.delete("/api/cvs/{cv_id}", include_in_schema=False, dependencies=staff)
def delete_cv(cv_id: str):
    if not storage.delete(cv_id):
        raise HTTPException(404, "No CV with this id.")
    return {"deleted": cv_id}


@app.get("/api/cvs/{cv_id}/export/{fmt}", include_in_schema=False, dependencies=staff)
def download_saved(cv_id: str, fmt: str):
    return export_response(get_record(cv_id)["cv"], fmt)


@app.post("/api/render", include_in_schema=False, dependencies=staff)
def render(body: dict):
    html = render_html(body_cv(body), editable=True)
    # the editor page lives at /edit/<id>, so font links must be absolute
    return {"html": html.replace('url("fonts/', 'url("/fonts/')}


@app.post("/api/export/{fmt}", include_in_schema=False, dependencies=staff)
def export(fmt: str, body: dict):
    return export_response(body_cv(body), fmt)


@app.post("/api/import", include_in_schema=False, dependencies=staff)
async def import_into_editor(file: UploadFile):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 25 MB.")
    cv, warnings = parse_upload(file.filename, data)
    return {"cv": ensure_ids(with_standard_sections(cv)), "warnings": warnings}


if __name__ == "__main__":
    print(f"\n  Europass CV service running at {PUBLIC_URL}  (Ctrl+C to stop)")
    print(f"  Staff login: {'password required' if ADMIN_PASSWORD else 'NO PASSWORD SET (local use only)'}")
    print(f"  Website API: {'on' if API_KEYS else 'off (set API_KEYS in .env)'}   Docs: {PUBLIC_URL}/docs\n")
    if HOST in ("127.0.0.1", "localhost"):
        Timer(1.2, lambda: webbrowser.open(PUBLIC_URL)).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")