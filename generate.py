#!/usr/bin/env python3
"""
Generate Europass-style CV PDFs from JSON.

    python generate.py samples/sample_cv.json               # one CV
    python generate.py data/ -o output/                     # every *.json in a folder
    python generate.py cv.json --logo assets/logo.png       # optional logo top-right
    python generate.py cv.json --html                       # also save the HTML (for tweaking CSS)

Each PDF gets the Europass XML embedded as 'attachment.xml', the same way the
official editor does, so it can be re-imported into europass.europa.eu.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import mimetypes
import sys
from pathlib import Path

import re

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
from pypdf import PdfReader, PdfWriter
from weasyprint import HTML

from cv_design import GENERIC_SECTIONS, SECTION_LABELS, design_css, ensure_ids, normalize, page_geometry
from europass_xml import build_xml

BASE = Path(__file__).resolve().parent
TEMPLATES = BASE / "templates"
EUROPASS_LOGO = BASE / "assets" / "europass-logo.png"
XML_ATTACHMENT_NAME = "attachment.xml"


# ---------------------------------------------------------------- helpers ---

def fmt_date(value, full: bool = False) -> str:
    """Europass display format: DD/MM/YYYY, MM/YYYY or YYYY."""
    if not value:
        return ""
    parts = str(value).split("-")
    if len(parts) == 3:
        y, m, d = parts
        return f"{d}/{m}/{y}"
    if len(parts) == 2:
        y, m = parts
        return f"{m}/{y}"
    return parts[0]


def to_data_uri(path: str | None, base_dir: Path) -> str | None:
    if not path:
        return None
    if str(path).startswith("data:"):
        return path
    file = Path(path)
    if not file.is_absolute():
        file = (base_dir / file).resolve()
    if not file.exists():
        print(f"  ! image not found, skipped: {file}", file=sys.stderr)
        return None
    mime = mimetypes.guess_type(file.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(file.read_bytes()).decode()}"


def validate(cv: dict, source: str) -> list[str]:
    errors = []
    p = cv.get("personal") or {}
    for field, label in (("first_name", "first name"), ("last_name", "last name")):
        if not str(p.get(field) or "").strip():
            errors.append(f"add a {label}")
    levels = {"A1", "A2", "B1", "B2", "C1", "C2", None, ""}
    for lang in (cv.get("languages") or {}).get("other", []):
        for key in ("listening", "reading", "spoken_production", "spoken_interaction", "writing"):
            if lang.get(key) not in levels:
                errors.append(f"{lang.get('name')}: '{lang.get(key)}' is not a CEFR level for {key.replace('_', ' ')}")
    return [f"{source}: {e}" for e in errors]


# -------------------------------------------------------------- rendering ---

# Text the editor may format: only these tags survive, so pasted or edited
# content can never inject anything into the page or the PDF.
RICH_TAGS = ("b", "strong", "i", "em", "u", "s", "br")
_TAG = re.compile(r"</?([a-zA-Z0-9]+)[^>]*>")


def clean_rich(value: str) -> str:
    """Keep simple formatting (bold, italic, underline, line breaks); drop the rest."""
    text = str(value or "")
    if "<" not in text:
        return str(escape(text)).replace("\n", "<br>")
    keep = []

    def repl(m):
        tag = m.group(1).lower()
        if tag in RICH_TAGS:
            closing = m.group(0).startswith("</")
            keep.append(tag)
            return f"</{tag}>" if closing else ("<br>" if tag == "br" else f"<{tag}>")
        return ""

    text = _TAG.sub(repl, text)
    # escape everything that is not one of the tags we just normalised
    parts = re.split(r"(<[^>]+>)", text)
    return "".join(p if p.startswith("<") and p.endswith(">") else escape(p) for p in parts)


def rich(value) -> Markup:
    return Markup(clean_rich(value))


env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
env.filters["fmt_date"] = fmt_date
env.filters["rich"] = rich


def render_html(cv: dict, base_dir: Path = BASE, logo: str | None = None, editable: bool = False) -> str:
    """Render the CV. editable=True adds the hooks used by the web editor."""
    ensure_ids(cv)
    design, sections = normalize(cv)
    labels = dict(SECTION_LABELS)
    labels.update({k: v for k, v in design["section_titles"].items() if k in labels})
    template = env.get_template("europass_cv.html")
    return template.render(
        cv=cv,
        p=cv.get("personal", {}),
        design=design,
        css=((TEMPLATES / "europass_cv.css").read_text(encoding="utf-8")
             + "\n" + (TEMPLATES / "europass_templates.css").read_text(encoding="utf-8")),
        template=design["template"],
        design_css=design_css(design),
        page=page_geometry(design),
        sections=sections,
        labels=labels,
        generic_sections=GENERIC_SECTIONS,
        editable=editable,
        photo_src=to_data_uri(cv.get("personal", {}).get("photo"), base_dir),
        # The official exports put the Europass logo on the first page, so it is
        # on by default; design.frame is the switch. A logo passed explicitly
        # (the --logo flag) still wins, for a differently branded CV.
        logo_src=(to_data_uri(logo, BASE) if logo
                  else to_data_uri(str(EUROPASS_LOGO), BASE) if design.get("frame") and EUROPASS_LOGO.exists()
                  else None),
    )


def build_pdf(cv: dict, base_dir: Path = BASE, logo: str | None = None, embed: bool = True) -> bytes:
    html = render_html(cv, base_dir, logo)
    pdf = HTML(string=html, base_url=str(TEMPLATES)).write_pdf()  # fonts/ resolve here
    return embed_xml(pdf, build_xml(cv), cv) if embed else pdf


def file_stem(cv: dict) -> str:
    p = cv.get("personal", {})
    name = f"{p.get('first_name', '')}_{p.get('last_name', '')}".strip("_") or "CV"
    return "Europass_CV_" + "".join(c if c.isalnum() or c in "_-" else "_" for c in name)


def embed_xml(pdf_bytes: bytes, xml_bytes: bytes, cv: dict) -> bytes:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)
    writer.add_attachment(XML_ATTACHMENT_NAME, xml_bytes)
    p = cv.get("personal", {})
    writer.add_metadata({
        "/Title": "Europass",          # the official export uses this exact title
        "/Author": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
        "/Subject": "Curriculum Vitae",
        "/Creator": "europass-cv-generator",
    })
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def generate(json_path: Path, out_dir: Path, logo: str | None, save_html: bool, embed: bool) -> Path:
    cv = json.loads(json_path.read_text(encoding="utf-8"))
    errors = validate(cv, json_path.name)
    if errors:
        raise ValueError("\n".join(errors))

    pdf = build_pdf(cv, json_path.parent, logo, embed)
    stem = file_stem(cv)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{stem}.pdf"
    pdf_path.write_bytes(pdf)
    if save_html:
        (out_dir / f"{stem}.html").write_text(render_html(cv, json_path.parent, logo), encoding="utf-8")
    return pdf_path


# -------------------------------------------------------------------- CLI ---

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="a CV .json file or a folder of them")
    ap.add_argument("-o", "--out", type=Path, default=BASE / "output", help="output folder")
    ap.add_argument("--logo", help="optional logo image shown top-right")
    ap.add_argument("--html", action="store_true", help="also write the intermediate HTML")
    ap.add_argument("--no-xml", action="store_true", help="do not embed Europass XML")
    args = ap.parse_args()

    files = sorted(args.input.glob("*.json")) if args.input.is_dir() else [args.input]
    if not files:
        print("No .json files found.", file=sys.stderr)
        return 1

    ok, failed = 0, 0
    for f in files:
        try:
            path = generate(f, args.out, args.logo, args.html, not args.no_xml)
            print(f"  ✓ {f.name} -> {path}")
            ok += 1
        except Exception as exc:  # keep going in batch mode
            print(f"  ✗ {f.name}: {exc}", file=sys.stderr)
            failed += 1

    print(f"\nDone: {ok} generated, {failed} failed.")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())