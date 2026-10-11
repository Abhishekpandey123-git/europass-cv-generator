"""
Read a filled-in Student Information Form (.docx) and turn it into CV data.

The form is a series of two-column tables: the left cell is the question, the
right cell the student's answer. Headings above the tables say which part of
the CV the answers belong to ("3. Education", "Qualification 1", "Role 2"...).
Languages come from a six-column table (language + five CEFR levels).

The reading is deliberately forgiving, because staff edit these files by hand:

  * question labels are matched loosely, so "Job title", "job title:" and
    "Position / job title" all work
  * any number of Qualification / Role blocks is accepted
  * a block whose answers were left as the green example text is skipped
  * rows the form doesn't recognise are collected and reported, so nothing is
    silently dropped

The result goes through normalize.normalize_cv like any other source, which is
what fixes dates, names, phone numbers and levels.
"""

from __future__ import annotations

import io
import re

from docx import Document

from normalize import normalize_cv

# Text from the blank/example form that means "not filled in".
PLACEHOLDER = re.compile(
    r"^(|-|\u2014|n/?a|none|nil|tbd|to be (filled|confirmed)|your answer|"
    r"\[.*\]|\(.*\)|x+|\.+|_+)$", re.I)

SECTION_WORDS = {
    "personal": "personal", "about": "about", "education": "education",
    "work": "work", "employment": "work", "experience": "work",
    "language": "languages", "digital": "skills", "technical": "skills",
    "skill": "skills", "driving": "licence", "licence": "licence",
    "license": "licence", "anything else": "extra", "additional": "extra",
    "other section": "extra", "project": "extra", "certificate": "extra",
    "document": "ignore", "note": "ignore", "attach": "ignore",
}

# question label -> field name, per section
FIELDS = {
    "personal": {
        "full name": "name", "name": "name", "first name": "first_name",
        "last name": "last_name", "surname": "last_name",
        "date of birth": "date_of_birth", "dob": "date_of_birth", "born": "date_of_birth",
        "gender": "gender", "sex": "gender",
        "nationality": "nationality", "citizenship": "nationality",
        "phone": "phone", "mobile": "phone", "contact number": "phone",
        "email": "email", "e-mail": "email",
        "website": "website", "linkedin": "website",
        "street": "street", "address": "street",
        "city": "city", "town": "city",
        "postal": "pincode", "pin": "pincode", "zip": "pincode",
        "country": "country",
        "passport": "_passport",          # checked by staff, never on the CV
        "photo": "_photo",                # the file is attached separately
    },
    "education": {
        "qualification": "qualification", "degree": "qualification",
        "course": "qualification", "title": "qualification",
        "school": "organisation", "university": "organisation",
        "college": "organisation", "institution": "organisation",
        "organisation": "organisation", "organization": "organisation",
        "city": "city", "country": "country",
        "from": "from", "start": "from", "to": "to", "end": "to",
        "field": "field", "subject": "field", "specialis": "field",
        "final grade": "final_grade", "grade": "final_grade",
        "percentage": "final_grade", "cgpa": "final_grade",
        "thesis": "thesis", "project": "thesis",
        "eqf": "eqf_level",
    },
    "work": {
        "job title": "position", "position": "position", "role": "position", "title": "position",
        "employer": "company", "company": "company", "organisation": "company",
        "organization": "company",
        "city": "city", "country": "country",
        "from": "from", "start": "from", "to": "to", "end": "to",
        "what you did": "description", "description": "description",
        "responsib": "description", "duties": "description", "achievement": "description",
    },
    "languages": {
        "mother tongue": "mother_tongues", "native": "mother_tongues",
        "first language": "mother_tongues",
        "test": "_test", "ielts": "_test", "toefl": "_test",
    },
    "skills": {"skill": "digital_skills", "software": "digital_skills", "tool": "digital_skills"},
    "licence": {"categor": "driving_licence", "licence": "driving_licence", "license": "driving_licence"},
    "extra": {
        "section title": "_title", "title": "_title",
        "heading": "heading", "description": "text", "text": "text", "detail": "text",
    },
}

CEFR = re.compile(r"^[ABC][12]$", re.I)
BLOCK_START = re.compile(r"^(qualification|role|job|position|entry|item|experience)\s*(\d+)?\b", re.I)


def _is_hint(paragraph) -> bool:
    """The form prints a grey italic hint under some answers ("DD/MM/YYYY")."""
    runs = [r for r in paragraph.runs if (r.text or "").strip()]
    if not runs:
        return False
    return all(r.italic or (r.font.color and getattr(r.font.color, "rgb", None)
                            and str(r.font.color.rgb).upper() in ("565656", "9AA5B1")) for r in runs)


def _cell_text(cell) -> str:
    paras = [p for p in cell.paragraphs if p.text.strip()]
    kept = [p for p in paras if not _is_hint(p)] or paras   # never drop everything
    return "\n".join(p.text.strip() for p in kept).strip()


def _label_key(text: str) -> str:
    # "Item 1 — heading" -> "heading";  "Phone number:" -> "phone number"
    text = re.split(r"[\u2013\u2014]", text)[-1]
    return re.sub(r"[^a-z ]", " ", text.lower()).strip()


def _match(label: str, table: dict) -> str | None:
    key = _label_key(label)
    if not key:
        return None
    for needle, field in table.items():
        if needle in key:
            return field
    return None


def _filled(value: str) -> bool:
    return bool(value) and not PLACEHOLDER.match(value.strip())


def _bullets(text: str):
    lines = [re.sub(r"^[\u2022\u2023\u25E6\-\*\u00B7]\s*", "", l).strip() for l in text.split("\n")]
    lines = [l for l in lines if l]
    if len(lines) > 1 or text.lstrip().startswith(("\u2022", "-", "*")):
        return lines
    return lines[0] if lines else ""


def form_to_cv(data: bytes) -> tuple[dict, list[str]]:
    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:
        raise ValueError("This file could not be read as a Word document. "
                         "Save it as .docx (not .doc) and try again.") from exc

    cv: dict = {"personal": {}, "education": [], "work_experience": [],
                "languages": {"mother_tongues": "", "other": []},
                "additional_sections": []}
    unread: list[str] = []
    section = "personal"
    block: dict | None = None          # current education / work entry
    extra: dict | None = None          # current custom section
    item: dict | None = None           # current custom item

    def close_block():
        nonlocal block
        if block and any(_filled(str(v)) for v in block.values()):
            (cv["education"] if section == "education" else cv["work_experience"]).append(block)
        block = None

    def close_item():
        nonlocal item
        if item and (item.get("heading") or item.get("text")):
            extra["items"].append(item)
        item = None

    # Walk paragraphs and tables in document order.
    body = doc.element.body
    tables = iter(doc.tables)
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]

        if tag == "p":
            text = "".join(node.text or "" for node in child.iter() if node.tag.endswith("}t")).strip()
            if not text:
                continue
            low = text.lower()
            if BLOCK_START.match(text):
                close_block()
                close_item()
                block = {}
                continue
            for word, name in SECTION_WORDS.items():
                if word in low and len(text) < 60:
                    close_block()
                    close_item()
                    if extra and extra["items"]:
                        cv["additional_sections"].append(extra)
                    extra = None
                    section = name
                    break
            continue

        if tag != "tbl":
            continue
        table = next(tables, None)
        if table is None:
            continue

        # language grid: 6 columns, CEFR values
        cols = len(table.columns)
        if section == "languages" and cols >= 6:
            for r in table.rows[1:]:
                cells = [_cell_text(c) for c in r.cells]
                name, levels = cells[0], cells[1:6]
                if not _filled(name) or not any(CEFR.match(l) for l in levels):
                    continue
                keys = ("listening", "reading", "spoken_production",
                        "spoken_interaction", "writing")
                given = [v.upper() for v in levels if CEFR.match(v)]
                lang = {"language": name}
                if len(given) == 1:
                    # one level written for the whole language - use it for all five
                    lang.update(dict.fromkeys(keys, given[0]))
                else:
                    for key, value in zip(keys, levels):
                        if CEFR.match(value):
                            lang[key] = value.upper()
                cv["languages"]["other"].append(lang)
            continue

        if cols < 2 or section == "ignore":
            continue

        if section == "extra":
            extra = extra or {"title": "", "items": []}

        for r in table.rows:
            cells = [_cell_text(c) for c in r.cells]
            label, value = cells[0], cells[1]
            if not label or label.lower() in ("form question", "language"):
                continue
            if not _filled(value):
                continue

            field = _match(label, FIELDS.get(section, {}))
            if field is None:
                # "Summary" under About me, or a free note
                if section == "about":
                    cv["about"] = value
                else:
                    unread.append(f"{label}: {value[:60]}")
                continue
            if field.startswith("_"):
                if field == "_title" and section == "extra":
                    close_item()
                    if extra["items"]:
                        cv["additional_sections"].append(extra)
                    extra = {"title": value, "items": []}
                continue                                   # passport, photo, test score

            if section == "personal":
                cv["personal"][field] = value
            elif section in ("education", "work"):
                if block is None:
                    block = {}
                if field in block:                          # a new block without a heading
                    close_block()
                    block = {}
                block[field] = _bullets(value) if field == "description" else value
            elif section == "languages":
                cv["languages"]["mother_tongues"] = value
            elif section == "skills":
                cv["digital_skills"] = value
            elif section == "licence":
                cv["driving_licence"] = value
            elif section == "extra":
                if field == "heading":
                    close_item()
                    item = {"heading": value, "text": ""}
                elif field == "text":
                    item = item or {"heading": "", "text": ""}
                    item["text"] = value
        close_block()

    close_item()
    if extra and extra["items"]:
        cv["additional_sections"].append(extra)

    # address pieces -> the address object the CV expects
    p = cv["personal"]
    address = {k: p.pop(k) for k in ("street", "city", "pincode", "country") if k in p}
    if address:
        p["address"] = address

    if not (p.get("name") or p.get("first_name")):
        raise ValueError("No student name was found. Is this the Student Information Form, "
                         "and is the name filled in?")

    cv, warnings = normalize_cv(cv)
    if unread:
        warnings.append("Some answers were not recognised and were left out: "
                        + "; ".join(unread[:5]) + ("\u2026" if len(unread) > 5 else ""))
    return cv, warnings


# ===================================================================== #
# The same form, but as text: a PDF export, a printout that was scanned,
# or the .docx pasted into an email. Word tables become "label / value /
# hint" lines, so the labels themselves tell us where each answer is.
# ===================================================================== #

SECTION_HEADING = re.compile(
    r"^\s*\d+\s*[.)]\s*(personal|about|education|work|language|digital|driving|anything)", re.I)

STOP_HEADING = re.compile(r"^\s*(9|10)\s*[.)]\s*(documents to attach|notes for)", re.I)

# Instructions printed on the form; never an answer.
HINT_LINE = re.compile(
    r"^\s*(\*|page \d+ of \d+|"
    r"as it should appear|dd/mm/yyyy|mm/yyyy|male, female|separate (several|with)|"
    r"include the country code|used to check|optional\.|the exact name|as shown on|"
    r"one point per line|for example|most recent first|copy the block|two or three sentences|"
    r"mother tongue\(s\), then|levels: a1|a single level|if an ielts|optional extra sections|"
    r"give each a title|this is a filled-in example|everything needed to build|"
    r"staff check the answers|this page is not for students|only the name is required|"
    r"or first_name|text or a list|title plus items|base64 data|most date formats|"
    r"a leading \+|one comma-separated line|street, city|qualification, university|"
    r"position, company|language plus level|used only for checking)", re.I)

# The five CEFR columns, written one per line in a PDF export.
LEVEL_RUN = re.compile(r"^(A1|A2|B1|B2|C1|C2)$", re.I)

# "Qualification 2", "Role 1" - a block heading, never the label "Qualification *"
BLOCK_HEADING = re.compile(r"^(qualification|role|job|position|entry|item|experience)\s*\d+\s*$", re.I)

# column headings of the language grid
GRID_WORD = re.compile(r"^(language|listening|reading|speaking|interaction|writing|levels?)$", re.I)

LABELS_BY_SECTION = {
    "personal": ["full name", "first name", "last name", "date of birth", "gender", "nationality",
                 "phone number", "email address", "website or linkedin", "website",
                 "street and number", "postal code / pin", "postal code", "city", "country",
                 "passport number", "photo"],
    "about": ["summary"],
    "education": ["qualification", "school or university", "city", "country", "from", "to",
                  "field of study", "final grade", "thesis or project"],
    "work": ["job title", "employer", "city", "country", "from", "to", "what you did"],
    "languages": ["mother tongue(s)", "mother tongue", "english test result"],
    "skills": ["skills"],
    "licence": ["categories held"],
    "extra": ["section title", "heading", "description"],
}


def _section_of(line: str) -> str | None:
    m = SECTION_HEADING.match(line)
    if not m:
        return None
    word = m.group(1).lower()
    return {"personal": "personal", "about": "about", "education": "education", "work": "work",
            "language": "languages", "digital": "skills", "driving": "licence",
            "anything": "extra"}[word]


def _label_of(line: str, section: str) -> str | None:
    """'Item 1 — heading' -> 'heading';  'From *' -> 'from'.  None if not a label."""
    text = re.sub(r"\s*\*\s*$", "", line.strip()).rstrip(":").strip()
    if not text or len(text) > 40:
        return None
    text = re.split(r"[\u2013\u2014]", text)[-1].strip()      # "Item 1 — heading"
    low = text.lower()
    return low if low in LABELS_BY_SECTION.get(section, []) else None


def looks_like_form(text: str) -> bool:
    head = text[:400].lower()
    if "student information form" in head:
        return True
    hits = sum(1 for l in ("full name", "date of birth", "job title", "school or university",
                           "mother tongue", "what you did", "categories held")
               if l in text.lower())
    return hits >= 4


def form_text_to_cv(text: str) -> tuple[dict, list[str]]:
    """Read the Student Information Form from plain text (PDF export, scan, paste)."""
    lines = [l.strip() for l in text.split("\n")]

    cv: dict = {"personal": {}, "education": [], "work_experience": [],
                "languages": {"mother_tongues": "", "other": []},
                "additional_sections": []}
    section = "personal"
    block: dict | None = None
    extra: dict | None = None
    item: dict | None = None
    label: str | None = None
    value: list[str] = []

    def flush():
        """Store the answer collected for the current label."""
        nonlocal label, value, block, extra, item
        if not label:
            value = []
            return
        text_value = "\n".join(v for v in value if v).strip()
        value = []
        if not _filled(text_value):
            label = None
            return
        field = _match(label, FIELDS.get(section, {}))
        if section == "about" and (field is None or label == "summary"):
            # a PDF export wraps the paragraph, so join the lines back together
            cv["about"] = re.sub(r"\s*\n\s*", " ", text_value)
            label = None
            return
        if field == "_title" and section == "extra":
            close_item()
            if extra and extra["items"]:
                cv["additional_sections"].append(extra)
            extra = {"title": text_value, "items": []}
        elif field and not field.startswith("_"):
            if section == "personal":
                cv["personal"][field] = text_value
            elif section in ("education", "work"):
                block = {} if block is None else block
                if field in block:
                    close_block()
                    block = {}
                block[field] = _bullets(text_value) if field == "description" else text_value
            elif section == "languages":
                cv["languages"]["mother_tongues"] = text_value
            elif section == "skills":
                cv["digital_skills"] = text_value
            elif section == "licence":
                cv["driving_licence"] = text_value
            elif section == "extra":
                extra = extra or {"title": "", "items": []}
                if field == "heading":
                    close_item()
                    item = {"heading": text_value, "text": ""}
                elif field == "text":
                    item = item or {"heading": "", "text": ""}
                    item["text"] = re.sub(r"\s*\n\s*", " ", text_value)
        label = None

    def close_block():
        nonlocal block
        if block and any(_filled(str(v)) for v in block.values()):
            (cv["education"] if section == "education" else cv["work_experience"]).append(block)
        block = None

    def close_item():
        nonlocal item
        if item and (item.get("heading") or item.get("text")) and extra is not None:
            extra["items"].append(item)
        item = None

    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line:
            continue
        if STOP_HEADING.match(line):
            break

        new_section = _section_of(line)
        if new_section:
            flush()
            close_block()
            close_item()
            if extra and extra["items"]:
                cv["additional_sections"].append(extra)
                extra = None
            section = new_section
            continue

        if BLOCK_HEADING.match(line) and section in ("education", "work"):
            flush()
            close_block()
            block = {}
            continue

        if section == "languages" and GRID_WORD.match(line):
            flush()                      # the grid starts: stop adding to "Mother tongue(s)"
            continue

        # the language grid, written one cell per line
        if section == "languages" and LEVEL_RUN.match(lines[i] if i < len(lines) else ""):
            name = line
            levels = []
            while i < len(lines) and LEVEL_RUN.match(lines[i]) and len(levels) < 5:
                levels.append(lines[i].upper())
                i += 1
            if levels and name.lower() not in ("language", "levels", "level"):
                keys = ("listening", "reading", "spoken_production", "spoken_interaction", "writing")
                lang = {"language": name}
                lang.update(dict.fromkeys(keys, levels[0]) if len(set(levels)) == 1 and len(levels) < 5
                            else dict(zip(keys, levels)))
                cv["languages"]["other"].append(lang)
            continue

        found = _label_of(line, section)
        if found:
            flush()
            label = found
            continue

        if HINT_LINE.match(line):
            continue
        if label:
            value.append(line)

    flush()
    close_block()
    close_item()
    if extra and extra["items"]:
        cv["additional_sections"].append(extra)

    p = cv["personal"]
    address = {k: p.pop(k) for k in ("street", "city", "pincode", "country") if k in p}
    if address:
        p["address"] = address

    if not (p.get("name") or p.get("first_name")):
        raise ValueError("This looks like the Student Information Form, but no student name "
                         "was found. Check that the name is filled in.")

    cv, warnings = normalize_cv(cv)
    return cv, warnings
