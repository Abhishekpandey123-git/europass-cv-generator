"""
Turn whatever the client's website sends into a clean CV.

Websites and forms send data in many shapes: dates as "05/2021" or "2021-05-01",
names in capitals, nationality as one string, descriptions with "•" bullets...
normalize_cv() accepts all of that and returns (cv, warnings). Warnings are shown
to staff in the dashboard so they know what to check.

Two input shapes are understood:
  * the canonical format (see samples/sample_cv.json)
  * the chatbot format from the europass-cv-ai project (personal_info, about_me,
    other_languages, profile_image_base64 ...)
"""

from __future__ import annotations

import copy
import re

from europass_import import fill_codes

CEFR = {"A1", "A2", "B1", "B2", "C1", "C2"}
LEVEL_KEYS = ("listening", "reading", "spoken_production", "spoken_interaction", "writing")
ONGOING = {"", "present", "current", "ongoing", "till date", "till now", "now", "today", "continuing", "pursuing"}
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


# ------------------------------------------------------------------ text ---

def clean(value) -> str:
    if value is None:
        return ""
    return re.sub(r"[ \t]+", " ", str(value)).strip()


def fix_case(name: str) -> str:
    """'RAHUL SHARMA' / 'rahul sharma' -> 'Rahul Sharma'; mixed case is left alone."""
    name = clean(name)
    if name and (name.isupper() or name.islower()):
        return " ".join(w[:1].upper() + w[1:].lower() for w in name.split(" "))
    return name


def to_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [clean(v) for v in re.split(r"[,;\n]", value) if clean(v)]
    return [clean(v) for v in value if clean(v)]


def to_bullets(value):
    """Text with bullet marks or several lines becomes a list; a single paragraph stays text."""
    if isinstance(value, list):
        return [clean(re.sub(r"^\s*[•\-*·–]\s*", "", str(v))) for v in value if clean(v)]
    text = clean(value)
    if not text:
        return ""
    lines = [l for l in (clean(x) for x in str(value).splitlines()) if l]
    if len(lines) > 1 or re.match(r"^\s*[•\-*·–]\s+", text):
        return [re.sub(r"^[•\-*·–]\s*", "", l) for l in lines]
    return text


# ----------------------------------------------------------------- dates ---

def to_date(value, *, keep_day: bool = False) -> str | None:
    """Accepts 2021, 2021-05, 2021-05-14, 05/2021, 14/05/2021, 14-05-2021, 'May 2021', 'Present'."""
    text = clean(value).lower()
    if text in ONGOING:
        return None
    m = re.fullmatch(r"(\d{4})(?:[-/.](\d{1,2}))?(?:[-/.](\d{1,2}))?", text)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.fullmatch(r"(?:(\d{1,2})[-/.])?(\d{1,2})[-/.](\d{4})", text)
        if m:
            d, mo, y = m.groups()
        else:
            m = re.fullmatch(r"(?:(\d{1,2})\s+)?([a-z]{3})[a-z]*\.?,?\s+(\d{4})", text)
            if not m or m.group(2) not in MONTHS:
                raise ValueError(f"unrecognised date '{value}'")
            d, mo, y = m.group(1), str(MONTHS[m.group(2)]), m.group(3)
    if mo and not 1 <= int(mo) <= 12:
        raise ValueError(f"month out of range in '{value}'")
    if not mo:
        return y
    if keep_day and d:
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return f"{y}-{int(mo):02d}"


# ------------------------------------------------------------- EQF levels ---

EQF_RULES = [
    (8, r"\b(ph\.?\s?d|doctor(ate)?)\b"),
    (7, r"\b(master|m\.?\s?tech|m\.?\s?e\b|m\.?\s?sc|msc|mba|m\.?\s?a\b|m\.?\s?com|mca|m\.?\s?arch|llm)\b"),
    (6, r"\b(bachelor|b\.?\s?tech|b\.?\s?e\b|b\.?\s?sc|bsc|bba|bca|b\.?\s?com|b\.?\s?a\b|b\.?\s?arch|llb|mbbs|b\.?\s?pharm)\b"),
]


def guess_eqf(title: str) -> int | None:
    t = title.lower()
    for level, pattern in EQF_RULES:
        if re.search(pattern, t):
            return level
    return None


# ------------------------------------------------------ chatbot -> canonical ---

def from_chatbot_format(src: dict) -> dict:
    """Map the europass-cv-ai schema onto ours."""
    pi = src.get("personal_info") or {}
    addr = pi.get("address") or {}
    cv = {
        "personal": {
            "first_name": pi.get("first_name"), "last_name": pi.get("last_name"),
            "date_of_birth": pi.get("date_of_birth"), "gender": pi.get("gender"),
            "nationality": pi.get("nationality"), "phone": pi.get("phone"), "email": pi.get("email"),
            "address": {"street": addr.get("line1"), "postal_code": addr.get("postal_code"),
                        "city": addr.get("city"), "country": addr.get("country")} if addr else None,
            "photo": src.get("profile_image_base64"),
        },
        "about": src.get("about_me"),
        "work_experience": [
            {"title": w.get("title"), "employer": w.get("employer"), "city": w.get("city"),
             "country": w.get("country"), "start": w.get("start_date"), "end": w.get("end_date"),
             "description": w.get("description")} for w in src.get("work_experience") or []],
        "education": [
            {"title": e.get("title"), "organisation": e.get("organization"), "city": e.get("city"),
             "country": e.get("country"), "start": e.get("start_date"), "end": e.get("end_date"),
             "description": e.get("description")} for e in src.get("education") or []],
        "languages": {
            "mother_tongues": src.get("mother_tongues") or [],
            "other": [{"name": l.get("language"), **{k: l.get(k) for k in LEVEL_KEYS}}
                      for l in src.get("other_languages") or []],
        },
        "digital_skills": src.get("digital_skills") or [],
        **normalize_sections(src, date),
        "additional_sections": [],
    }
    if src.get("hobbies"):
        cv["additional_sections"].append({"title": "Hobbies and interests",
                                          "items": [{"heading": "", "text": ", ".join(src["hobbies"])}]})
    if src.get("other_info"):
        cv["additional_sections"].append({"title": "Additional information",
                                          "items": [{"heading": "", "text": src["other_info"]}]})
    return cv


# ------------------------------------------------------------- main entry ---

def skill_groups(value):
    """
    Skills are either a flat list, or named groups the way Europass shows them:
    [{"title": "Digital skills", "items": [...]}, ...]. Groups are kept as
    groups; anything else becomes a plain list. "items" is the key used
    everywhere else for a group's contents, so accept "skills" too but always
    return "items".
    """
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        groups = []
        for g in value:
            items = to_list(g.get("items") or g.get("skills"))
            if items:
                groups.append({"title": clean(g.get("title")), "items": items})
        return groups
    return to_list(value)



# Typed sections: the fields each one keeps. Anything not listed is dropped, so
# a stray key from a website payload cannot reach the XML writer unchecked.
SECTION_FIELDS = {
    "certifications":   ("title", "organisation", "date", "mode", "description", "url"),
    "honours_awards":   ("title", "organisation", "date", "description"),
    "conferences":      ("title", "start", "end", "location", "description", "url"),
    "creative_works":   ("title", "start", "end", "description", "url"),
    "projects":         ("title", "start", "end", "description", "url"),
    "publications":     ("title", "year", "reference", "doi", "authors", "journal",
                         "publisher", "volume", "description"),
    "recommendations":  ("name", "role", "email", "phone", "phone_dialing",
                         "phone_country", "description"),
    "social_political": ("title", "start", "end", "location", "description"),
    "volunteering":     ("title", "start", "end", "location", "description"),
    "networks":         ("title", "start", "end", "location", "description"),
    "hobbies":          ("title", "description"),
}
DATE_FIELDS = {"start", "end", "date"}


def normalize_sections(src: dict, date_fn) -> dict:
    """Clean the typed sections, keeping only known fields."""
    out = {}
    for key, fields in SECTION_FIELDS.items():
        rows = []
        for i, item in enumerate(src.get(key) or [], start=1):
            if not isinstance(item, dict):
                continue
            row = {}
            for field in fields:
                value = item.get(field)
                if field in DATE_FIELDS:
                    if value:
                        row[field] = date_fn(value, f"{key.replace('_', ' ').title()} {i} {field}",
                                             keep_day=(field == "date"))
                elif field == "description":
                    if value:
                        row[field] = to_bullets(value)
                elif clean(value):
                    row[field] = clean(value)
            if any(row.values()):
                rows.append(row)
        out[key] = rows
    return out


def normalize_cv(data: dict) -> tuple[dict, list[str]]:
    if not isinstance(data, dict):
        raise ValueError("The CV data must be a JSON object.")
    src = copy.deepcopy(data)
    if "personal_info" in src and "personal" not in src:
        src = from_chatbot_format(src)

    warnings: list[str] = []
    warn = warnings.append

    def date(value, where, keep_day=False):
        try:
            return to_date(value, keep_day=keep_day)
        except ValueError as exc:
            warn(f"{where}: {exc}; left empty.")
            return None

    # --- personal ------------------------------------------------------------
    p = src.get("personal") or {}
    first, last = fix_case(p.get("first_name")), fix_case(p.get("last_name"))
    if not first and not last and p.get("name"):
        parts = fix_case(p["name"]).rsplit(" ", 1)
        first, last = parts[0], parts[1] if len(parts) > 1 else ""
    personal = {"first_name": first, "last_name": last}
    if not first or not last:
        warn("Personal details: first or last name is missing.")

    if p.get("date_of_birth"):
        personal["date_of_birth"] = date(p["date_of_birth"], "Date of birth", keep_day=True)
    if p.get("gender"):
        g = clean(p["gender"]).lower()
        personal["gender"] = {"m": "Male", "male": "Male", "f": "Female", "female": "Female"}.get(g, clean(p["gender"]).capitalize())

    nats = p.get("nationalities")
    if nats is None:
        nats = to_list(p.get("nationality"))
    personal["nationalities"] = [n if isinstance(n, dict) else {"name": fix_case(n)} for n in nats if n]

    phone = p.get("phone")
    if isinstance(phone, str) and clean(phone):
        raw = clean(phone)
        # accept "+91 ...", "(+91) ...", "0091 ...", "91-..." etc.
        m = (re.match(r"^\(?\+(\d{1,3})\)?[\s-]*(.*)$", raw)
             or re.match(r"^00(\d{1,3})[\s-]+(.*)$", raw))
        dialing = m.group(1) if m else ""
        number = re.sub(r"\D", "", m.group(2) if m else raw)      # digits only, no spaces
        personal["phone"] = {"type": "Mobile", "country_dialing": dialing, "number": number}
    elif isinstance(phone, dict) and phone.get("number"):
        personal["phone"] = {"type": clean(phone.get("type")) or "Mobile",
                             "country_dialing": re.sub(r"\D", "", str(phone.get("country_dialing") or "")),
                             "number": re.sub(r"\D", "", str(phone["number"]))}
        if clean(phone.get("country_code")):
            personal["phone"]["country_code"] = clean(phone["country_code"]).lower()

    if p.get("email"):
        personal["email"] = clean(p["email"]).lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", personal["email"]):
            warn(f"Email '{personal['email']}' does not look valid.")
    if p.get("website"):
        personal["website"] = clean(p["website"])
    if p.get("passport") or p.get("passport_number"):
        personal["passport"] = clean(p.get("passport") or p.get("passport_number"))
    if clean(p.get("document_type")):
        personal["document_type"] = clean(p["document_type"])
    if clean(p.get("work_permit")):
        personal["work_permit"] = clean(p["work_permit"])
    if clean(p.get("work_permit_country")):
        personal["work_permit_country"] = clean(p["work_permit_country"]).lower()

    # Europass allows several of each contact detail.
    for key in ("extra_phones", "extra_emails", "extra_websites"):
        values = [clean(v) for v in (p.get(key) or []) if clean(v)]
        if values:
            personal[key] = values
    for key, value_field in (("social_media", "url"), ("instant_messaging", "value")):
        rows = []
        for item in p.get(key) or []:
            if not isinstance(item, dict):
                continue
            value = clean(item.get(value_field) or item.get("value") or item.get("url"))
            if value:
                row = {"type": clean(item.get("type")) or "Other", value_field: value}
                if clean(item.get("username")):
                    row["username"] = clean(item["username"])
                rows.append(row)
        if rows:
            personal[key] = rows
    pob = p.get("place_of_birth")
    if isinstance(pob, str) and clean(pob):
        personal["place_of_birth"] = {"city": fix_case(pob)}
    elif isinstance(pob, dict) and any(clean(v) for v in pob.values() if isinstance(v, str)):
        personal["place_of_birth"] = {"city": fix_case(pob.get("city")),
                                      "country": fix_case(pob.get("country"))}

    addr = p.get("address")
    if isinstance(addr, str) and clean(addr):
        personal["address"] = {"street": clean(addr), "type": "Home"}
    elif isinstance(addr, dict) and any(clean(v) for v in addr.values() if isinstance(v, str)):
        personal["address"] = {
            "street": clean(addr.get("street") or addr.get("line1")),
            "street2": clean(addr.get("street2") or addr.get("line2")),
            "postal_code": clean(addr.get("postal_code") or addr.get("zip") or addr.get("pincode")),
            "city": fix_case(addr.get("city")),
            "country": fix_case(addr.get("country")),
            "type": clean(addr.get("type")) or "Home",
        }
        lines = [clean(v) for v in (addr.get("address_lines") or []) if clean(v)]
        if lines:
            personal["address"]["address_lines"] = lines

    photo = p.get("photo")
    if photo:
        photo = str(photo).strip()
        if len(photo) > 7_000_000:          # ~5 MB image once decoded
            warn("Photo is larger than 5 MB; photo skipped.")
        elif photo.startswith("data:image"):
            personal["photo"] = photo
        elif re.fullmatch(r"[A-Za-z0-9+/=\s]{200,}", photo):
            personal["photo"] = "data:image/jpeg;base64," + re.sub(r"\s", "", photo)
        else:
            warn("Photo: only base64 images are accepted (not links); photo skipped.")

    # --- experience & education ---------------------------------------------
    def entries(key, org_keys, label):
        out = []
        for i, item in enumerate(src.get(key) or [], start=1):
            where = f"{label} {i}"
            e = {
                "title": clean(item.get("title") or item.get("position") or item.get("qualification")),
                org_keys[0]: clean(next((item.get(k) for k in org_keys if item.get(k)), "")),
                "city": fix_case(item.get("city")),
                "country": fix_case(item.get("country")),
                "start": date(item.get("start") or item.get("start_date") or item.get("from"), f"{where} start"),
                "end": date(item.get("end") or item.get("end_date") or item.get("to"), f"{where} end"),
            }
            if not e["title"]:
                warn(f"{where}: title is missing.")
            if not e["start"]:
                warn(f"{where}: start date is missing.")
            if e["start"] and e["end"] and e["end"] < e["start"]:
                warn(f"{where}: ends before it starts ({e['start']} → {e['end']}).")
            if item.get("description"):
                e["description"] = to_bullets(item["description"])
            for extra in ("website", "department", "sector", "email", "url",
                          "industry_code", "position_city", "position_country"):
                if clean(item.get(extra)):
                    e[extra] = clean(item[extra])
            lines = [clean(v) for v in (item.get("address_lines") or []) if clean(v)]
            if lines:
                e["address_lines"] = lines
            out.append(e)
        return out

    work = entries("work_experience", ("employer", "company", "organisation", "organization"), "Work experience")
    education = entries("education", ("organisation", "organization", "institution", "school", "university"), "Education")
    for i, (item, e) in enumerate(zip(src.get("education") or [], education), start=1):
        for key in ("field", "final_grade", "thesis", "website", "program_concentration",
                    "degree_form", "credits", "credit_type", "national_classification"):
            if clean(item.get(key)):
                e[key] = clean(item[key])
        level = item.get("eqf_level")
        if str(level or "").strip().isdigit() and 1 <= int(level) <= 8:
            e["eqf_level"] = int(level)
        elif (guess := guess_eqf(e["title"])):
            e["eqf_level"] = guess
            warn(f"Education {i}: EQF level {guess} was assumed from “{e['title']}”. Please confirm.")
        if isinstance(e.get("description"), list):
            e["description"] = " ".join(e["description"])

    # Europass lists the most recent first
    newest_first = lambda e: (e["end"] or "9999", e["start"] or "")   # ongoing entries on top
    work.sort(key=newest_first, reverse=True)
    education.sort(key=newest_first, reverse=True)

    # --- languages -------------------------------------------------------------
    langs = src.get("languages") or {}
    mother = [m if isinstance(m, dict) else {"name": fix_case(m)} for m in (
        langs.get("mother_tongues") if isinstance(langs.get("mother_tongues"), list) else to_list(langs.get("mother_tongues")))]
    other = []
    for l in langs.get("other") or []:
        name = fix_case(l.get("name") or l.get("language"))
        entry = {"name": name}
        if l.get("code"):
            entry["code"] = l["code"]
        overall = clean(l.get("level")).upper()
        bad = []
        for k in LEVEL_KEYS:
            v = clean(l.get(k)).upper() or overall
            if v in CEFR:
                entry[k] = v
            elif v and v not in bad:
                bad.append(v)
        if bad:
            warn(f"{name}: {', '.join(repr(b) for b in bad)} is not a CEFR level (A1–C2); left empty.")
        other.append(entry)

    cv = {
        "language": src.get("language") or "en",
        "personal": personal,
        "about": clean(src.get("about")),
        "work_experience": work,
        "education": education,
        "languages": {"mother_tongues": mother, "other": other},
        "digital_skills": skill_groups(src.get("digital_skills")),
        "driving_licence": [c.upper() for c in to_list(src.get("driving_licence"))],
        **normalize_sections(src, date),
        "additional_sections": [
            {"title": clean(s.get("title")) or "Additional information",
             "items": [{"heading": clean(i.get("heading")), "text": clean(i.get("text"))} for i in s.get("items") or []]}
            for s in src.get("additional_sections") or []],
    }
    if src.get("design"):
        cv["design"] = src["design"]
    closing = src.get("closing_statement")
    if isinstance(closing, dict) and clean(closing.get("text")):
        cv["closing_statement"] = {"text": clean(closing["text"]),
                                   "place": clean(closing.get("place")),
                                   "date": clean(closing.get("date"))}
    elif isinstance(closing, str) and clean(closing):
        cv["closing_statement"] = {"text": clean(closing), "place": "", "date": ""}
    return fill_codes(cv), warnings