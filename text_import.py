"""
Read a CV out of almost any document.

The service prefers structured sources (Europass XML inside a PDF, our JSON, a
filled Student Information Form). This module is the fallback for everything
else: a CV someone wrote in Word, a PDF exported from Canva, a text file, a
web page, a spreadsheet row, even a photo of a printed CV.

Two steps:

    extract_text()   any file  ->  plain text
    text_to_cv()     plain text -> the fields we can recognise

The second step is guesswork, so every field it finds is reported as a warning
for staff to check. It never invents anything: whatever it cannot read is left
empty rather than filled with something plausible.

Optional extras, used when installed and skipped politely when not:
    openpyxl     .xlsx spreadsheets
    odfpy        .odt documents
    pytesseract  OCR for images and scanned PDFs (needs the Tesseract program)
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import zipfile
from datetime import datetime

import pymupdf

# Files we will not try to read, with the reason shown to the user.
REJECT = {
    "video": (".mp4 .mov .avi .mkv .wmv .flv .webm .m4v .mpg .mpeg .3gp .ogv",
              "Video files cannot contain a CV that we can read."),
    "audio": (".mp3 .wav .m4a .aac .flac .ogg .wma .opus",
              "Audio files cannot contain a CV that we can read."),
    "archive": (".zip .rar .7z .tar .gz .bz2 .xz",
                "Unpack the archive first and upload the document inside it."),
    "program": (".exe .msi .dll .bat .cmd .sh .apk .dmg .iso .jar",
                "Programs cannot be uploaded."),
}

IMAGES = ".png .jpg .jpeg .webp .bmp .tif .tiff .gif .heic"
PLAIN = ".txt .md .markdown .log .rst .csv .tsv .json .yml .yaml .ini"


def _ext(filename: str) -> str:
    name = (filename or "").lower().strip()
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


def rejected_reason(filename: str) -> str | None:
    ext = _ext(filename)
    for exts, reason in REJECT.values():
        if ext in exts.split():
            return f"{ext} files are not supported. {reason}"
    return None


# ----------------------------------------------------------- text from file ---

def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<(br|/p|/div|/li|/tr|/h[1-6])[^>]*>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    import html as html_mod
    return html_mod.unescape(text)


def _rtf_to_text(rtf: str) -> str:
    rtf = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), rtf)
    rtf = re.sub(r"\\par[d]?|\\line", "\n", rtf)
    rtf = re.sub(r"\{\\\*.*?\}", " ", rtf, flags=re.S)
    rtf = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", rtf)
    return rtf.replace("{", " ").replace("}", " ")


def _ocr(image_bytes: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise ValueError("This looks like a picture. Reading text from images needs the "
                         "OCR add-on (pytesseract + Tesseract). Upload a PDF or Word file "
                         "instead, or ask your developer to install it.") from exc
    try:
        return pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)))
    except Exception as exc:
        raise ValueError("The text in this image could not be read. Try a clearer scan, "
                         "or upload the original PDF or Word file.") from exc


def _pdf_text(data: bytes) -> str:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("This file could not be opened as a PDF. It may be damaged.") from exc
    pages = [page.get_text("text") for page in doc]
    text = "\n".join(pages).strip()
    if len(text) >= 80:
        return text
    # a scanned CV: the pages are pictures, so read them with OCR
    shots = []
    for page in doc[:6]:
        pix = page.get_pixmap(dpi=200)
        shots.append(_ocr(pix.tobytes("png")))
    return "\n".join(shots).strip()


def _docx_text(data: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(data))
    lines = [p.text.strip() for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            seen, unique = set(), []
            for c in cells:                      # merged cells repeat their text
                if c and c not in seen:
                    seen.add(c)
                    unique.append(c)
            if unique:
                lines.append(": ".join(unique) if len(unique) == 2 else "  ".join(unique))
    return "\n".join(l for l in lines if l)


def _odt_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("content.xml").decode("utf-8", "replace")
    except Exception as exc:
        raise ValueError("This .odt file could not be read.") from exc
    xml = re.sub(r"(?i)</text:(p|h)>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _xlsx_text(data: bytes) -> str:
    try:
        import openpyxl
    except ImportError as exc:
        raise ValueError("Reading .xlsx files needs the openpyxl add-on. Save the sheet "
                         "as .csv and upload that instead.") from exc
    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for sheet in book.worksheets:
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c not in (None, "")]
            if cells:
                lines.append(": ".join(cells) if len(cells) == 2 else "  ".join(cells))
    return "\n".join(lines)


def _table_text(data: bytes, delimiter: str | None) -> str:
    text = _decode(data)
    sample = text[:4000]
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(sample, ",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if len(rows) == 2 and len(rows[0]) > 3:          # header row + one record
        return "\n".join(f"{h.strip()}: {v.strip()}" for h, v in zip(rows[0], rows[1]) if v.strip())
    return "\n".join("  ".join(c.strip() for c in r if c.strip()) for r in rows if any(r))


def _json_text(data: bytes) -> str:
    """A JSON file that isn't our CV format: flatten it to 'key: value' lines."""
    try:
        obj = json.loads(_decode(data))
    except json.JSONDecodeError as exc:
        raise ValueError(f"The JSON file is not valid: {exc}") from exc
    lines: list[str] = []

    def walk(node, prefix=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}{k} ")
        elif isinstance(node, list):
            for item in node:
                walk(item, prefix)
        elif str(node).strip():
            lines.append(f"{prefix.strip()}: {node}")

    walk(obj)
    return "\n".join(lines)


def extract_text(filename: str, data: bytes) -> str:
    """Any supported document -> plain text. Raises ValueError with a readable reason."""
    reason = rejected_reason(filename)
    if reason:
        raise ValueError(reason)

    ext = _ext(filename)
    if ext == ".pdf" or data[:5] == b"%PDF-":
        text = _pdf_text(data)
    elif ext == ".docx" or data[:4] == b"PK\x03\x04" and ext not in (".xlsx", ".odt"):
        try:
            text = _docx_text(data)
        except Exception:
            text = _odt_text(data) if ext == ".odt" else ""
    elif ext == ".xlsx" or ext == ".xlsm":
        text = _xlsx_text(data)
    elif ext == ".odt":
        text = _odt_text(data)
    elif ext == ".doc":
        raise ValueError("Old .doc files are not supported. Open it in Word and save as "
                         ".docx (or PDF), then upload again.")
    elif ext in IMAGES.split():
        text = _ocr(data)
    elif ext in (".html", ".htm", ".xhtml"):
        text = _html_to_text(_decode(data))
    elif ext == ".rtf":
        text = _rtf_to_text(_decode(data))
    elif ext in (".csv", ".tsv"):
        text = _table_text(data, "\t" if ext == ".tsv" else None)
    elif ext == ".json":
        text = _json_text(data)
    elif ext in PLAIN.split() or not ext:
        text = _decode(data)
    else:
        raise ValueError(f"{ext} files are not supported. Upload a PDF, Word, text or "
                         "image file, or a Europass PDF or XML.")

    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text.strip()) < 30:
        raise ValueError("No readable text was found in this file. If it is a scan, try a "
                         "clearer image; otherwise upload the original document.")
    return text.strip()


# ------------------------------------------------------------ text -> fields ---

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(\+?\d[\d\s().-]{7,17}\d)")
URL = re.compile(r"(?:https?://|www\.)[^\s,;]+", re.I)
DOB = re.compile(r"(?:date of birth|d\.?o\.?b\.?|born)\s*[:\-]?\s*([0-9]{1,2}[-/. ][0-9]{1,2}[-/. ][0-9]{2,4}|"
                 r"[0-9]{1,2}\s+[A-Za-z]{3,9},?\s+[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})", re.I)
NAME_LABEL = re.compile(
    r"^[ \t]*(?:\w+[ \t]+)?(?:full[ _]?|student[ _]?|candidate[ _]?|applicant[ _]?|first[ _]?)?name"
    r"[ \t]*[:\-][ \t]*(.+)$", re.I | re.M)
NATIONALITY = re.compile(r"nationality\s*[:\-]?\s*([A-Za-z ]{3,30})", re.I)

MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE_PART = rf"(?:{MONTH}\s*,?\s*\d{{4}}|\d{{1,2}}[/.-]\d{{4}}|\d{{4}}[/.-]\d{{1,2}}|\d{{4}})"
ONGOING = r"(?:present|current|now|till\s*date|ongoing|pursuing|date)"
RANGE = re.compile(rf"({DATE_PART})\s*(?:[-–—]|to|until)\s*({DATE_PART}|{ONGOING})", re.I)

HEADINGS = [
    ("work", r"(work|professional|employment)\s+(experience|history)|^experience|^internships?|^employment|"
             r"^work$|career (history|summary)"),
    ("education", r"^education|educational (background|qualification)|academic|^qualifications?$"),
    ("languages", r"^languages?( skills?| known| proficiency)?$|language skills"),
    ("skills", r"^(technical |digital |it |computer |core |key )?skills|technologies|competenc"),
    ("about", r"^(about me|profile|summary|objective|career objective|professional summary|personal statement)"),
    ("licence", r"driving licen[cs]e"),
    ("projects", r"^projects?$|^academic projects?|^personal projects?"),
    ("certificates", r"^certificat|^courses|^training"),
    ("contact", r"^(personal (details|information)|contact( details| information)?)$"),
    ("skip", r"^(references?|declaration|hobbies|interests|awards|achievements|publications|"
             r"extra.?curricular|volunteer)"),
]
HEADINGS = [(name, re.compile(pattern, re.I)) for name, pattern in HEADINGS]

LANG_LINE = re.compile(r"^\s*([A-Z][a-zA-Z]{2,15})\s*[:\-–(]*\s*"
                       r"(A1|A2|B1|B2|C1|C2|native|mother ?tongue|fluent|proficient|advanced|"
                       r"intermediate|basic|beginner|elementary)\b", re.I)
LEVEL_WORDS = {"native": None, "mother tongue": None, "fluent": "C1", "proficient": "C1",
               "advanced": "C1", "intermediate": "B1", "basic": "A2", "beginner": "A1",
               "elementary": "A2"}

SKILL_STOP = re.compile(r"^(and|with|using|the|a|an|in|of|for|to)$", re.I)
NAME_BAD = re.compile(r"curriculum|vitae|resume|^cv$|profile|contact|address|@|\d{4}|^page\b", re.I)


def _heading(line: str) -> str | None:
    text = line.strip().strip(":").strip()
    if not text or len(text) > 48:
        return None
    letters = [c for c in text if c.isalpha()]
    looks_like_heading = (text.isupper() and len(letters) > 2) or len(text.split()) <= 5
    if not looks_like_heading:
        return None
    for name, pattern in HEADINGS:
        if pattern.search(text):
            return name
    return None


def _guess_name(lines: list[str]) -> str:
    for line in lines[:12]:
        text = line.strip(" |·-–—")
        if not text or NAME_BAD.search(text) or EMAIL.search(text) or len(text) > 48:
            continue
        words = [w for w in text.replace(",", " ").split() if w]
        if 2 <= len(words) <= 5 and all(re.fullmatch(r"[A-Za-z][A-Za-z.'\-]*", w) for w in words):
            return text
    return ""


def _entries(block: list[str]) -> list[dict]:
    """Split a section into entries; each date range starts a new one."""
    entries: list[dict] = []
    current: dict | None = None
    for line in block:
        raw = line.strip()
        bullet = bool(re.match(r"^[•·\-–—*]\s+", raw))
        text = raw.strip(" •·-–—*\t")
        if not text:
            continue
        if bullet:
            text = "• " + text
        found = None if bullet else RANGE.search(text)
        if found:
            current = {"from": found.group(1), "to": "" if re.fullmatch(ONGOING, found.group(2), re.I)
                       else found.group(2), "lines": []}
            entries.append(current)
            rest = (text[:found.start()] + " " + text[found.end():]).strip(" |,–—-·")
            if rest:
                current["lines"].append(rest)
        elif current is not None:
            current["lines"].append(text)
        else:                                   # text before any date
            current = {"from": "", "to": "", "lines": [text]}
            entries.append(current)
    return entries


def _split_entry(entry: dict, org_key: str) -> dict:
    lines = [l for l in entry["lines"] if l]
    out = {"from": entry["from"], "to": entry["to"]}
    if lines:
        first = lines[0]
        parts = [p.strip() for p in re.split(r"\s*,\s+|\s+[|–—]\s+|\s+at\s+|\s+[-–]\s+", first, maxsplit=1)
                 if p.strip()]
        out["title" if org_key == "company" else "qualification"] = parts[0][:120]
        if len(parts) > 1:
            out[org_key] = parts[1][:120]
        elif len(lines) > 1 and len(lines[1]) < 90 and not lines[1].startswith("•"):
            out[org_key] = lines[1][:120]
            lines = lines[:1] + lines[2:]
    body = [l for l in lines[1:] if len(l) > 3]
    if body:
        out["description"] = "\n".join(body[:12])
    return {k: v for k, v in out.items() if v}


def text_to_cv(text: str) -> tuple[dict, list[str]]:
    lines = [l.rstrip() for l in text.split("\n")]
    header = "\n".join(lines[:15])

    cv: dict = {"personal": {}, "education": [], "work_experience": [],
                "languages": {"mother_tongues": [], "other": []}, "additional_sections": []}
    p = cv["personal"]

    name = ""
    if (m := NAME_LABEL.search(text)):            # "Full name: Priya Sharma" (forms, tables, JSON)
        candidate = m.group(1).strip(" .,:;|")
        if 1 < len(candidate) <= 60 and not EMAIL.search(candidate):
            name = candidate
    name = name or _guess_name(lines)
    if name:
        p["name"] = name
    if (m := EMAIL.search(text)):
        p["email"] = m.group(0)
    for candidate in PHONE.findall(header) or PHONE.findall(text):
        digits = re.sub(r"\D", "", candidate)
        if 8 <= len(digits) <= 15:
            p["phone"] = candidate.strip()
            break
    for url in URL.findall(header):
        if "@" not in url:
            p["website"] = url.rstrip(".,);")
            break
    if (m := DOB.search(text)):
        p["date_of_birth"] = m.group(1)
    if (m := NATIONALITY.search(text)):
        p["nationality"] = m.group(1).strip()

    # cut the text into sections
    sections: dict[str, list[str]] = {}
    current = "top"
    for line in lines:
        found = _heading(line)
        if found:
            current = found
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    if sections.get("about"):
        about = " ".join(l.strip() for l in sections["about"] if l.strip())
        if about:
            cv["about"] = about[:900]

    for key, target, org in (("work", "work_experience", "company"),
                             ("education", "education", "organisation")):
        for entry in _entries(sections.get(key, [])):
            item = _split_entry(entry, org)
            if item.get("title") or item.get("qualification"):
                cv[target].append(item)

    for line in sections.get("languages", []) + lines:
        m = LANG_LINE.match(line)
        if not m:
            continue
        language, raw = m.group(1).strip(), m.group(2).lower()
        if language.lower() in ("language", "languages", "level", "skills"):
            continue
        seen = {str(x).lower() for x in cv["languages"]["mother_tongues"]}
        seen |= {str(l.get("language", "")).lower() for l in cv["languages"]["other"]}
        if language.lower() in seen:
            continue
        if raw in ("native", "mother tongue", "mother tongue"):
            cv["languages"]["mother_tongues"].append(language)
        else:
            level = raw.upper() if re.fullmatch(r"[abc][12]", raw) else LEVEL_WORDS.get(raw)
            if level:
                cv["languages"]["other"].append({"language": language, "level": level})

    skills: list[str] = []
    for line in sections.get("skills", []):
        for piece in re.split(r"[,;|·•]|\s{3,}", line):
            piece = piece.strip(" .-–—:")
            piece = re.sub(r"^(programming languages?|tools?|technologies|frameworks?|databases?)\s*:?\s*", "",
                           piece, flags=re.I)
            if 1 < len(piece) <= 32 and not SKILL_STOP.match(piece) and piece not in skills:
                skills.append(piece)
    if skills:
        cv["digital_skills"] = skills[:30]

    licence_text = " ".join(sections.get("licence", []))
    if (m := re.search(r"\b(?:categor(?:y|ies)\s*)?([A-D][E1]?(?:\s*,\s*[A-D][E1]?)*)\b", licence_text)):
        cv["driving_licence"] = m.group(1)

    for key, title in (("projects", "Projects"), ("certificates", "Certificates")):
        items = [l.strip(" •·-–—") for l in sections.get(key, []) if len(l.strip()) > 3]
        if items:
            cv["additional_sections"].append(
                {"title": title, "items": [{"heading": "", "text": i} for i in items[:12]]})

    if not (p.get("name") or p.get("email")):
        raise ValueError("No CV could be recognised in this file. It has readable text, but "
                         "no name or email address was found near the top.")
    return cv, _report(cv)


def _report(cv: dict) -> list[str]:
    found = []
    if cv["work_experience"]:
        found.append(f"{len(cv['work_experience'])} job(s)")
    if cv["education"]:
        found.append(f"{len(cv['education'])} qualification(s)")
    if cv["languages"]["other"] or cv["languages"]["mother_tongues"]:
        found.append("languages")
    if cv.get("digital_skills"):
        found.append(f"{len(cv['digital_skills'])} skill(s)")
    summary = ", ".join(found) or "personal details only"
    return ["Read from a free-form document, so the layout had to be guessed: "
            f"found {summary}. Please check every field against the original, and add "
            "anything that is missing."]


def file_to_cv(filename: str, data: bytes) -> tuple[dict, list[str]]:
    """Any document -> (raw CV fields, warnings). normalize_cv() cleans them afterwards."""
    return text_to_cv(extract_text(filename, data))
