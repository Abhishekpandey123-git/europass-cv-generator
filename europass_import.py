"""
Read Europass XML (or a Europass PDF that carries it) into the CV JSON format.

Matching is done on local tag names, ignoring namespaces, so small differences
between Europass versions don't break the import. Anything unrecognised is
skipped and reported as a warning rather than failing the whole import.
"""

from __future__ import annotations

import html
import io
import re
import xml.etree.ElementTree as ET

from pypdf import PdfReader

COUNTRIES = {
    "at": "Austria", "be": "Belgium", "bg": "Bulgaria", "hr": "Croatia", "cy": "Cyprus",
    "cz": "Czechia", "dk": "Denmark", "ee": "Estonia", "fi": "Finland", "fr": "France",
    "de": "Germany", "gr": "Greece", "el": "Greece", "hu": "Hungary", "ie": "Ireland",
    "it": "Italy", "lv": "Latvia", "lt": "Lithuania", "lu": "Luxembourg", "mt": "Malta",
    "nl": "Netherlands", "pl": "Poland", "pt": "Portugal", "ro": "Romania", "sk": "Slovakia",
    "si": "Slovenia", "es": "Spain", "se": "Sweden", "no": "Norway", "ch": "Switzerland",
    "is": "Iceland", "uk": "United Kingdom", "gb": "United Kingdom", "us": "United States",
    "ca": "Canada", "au": "Australia", "in": "India", "pk": "Pakistan", "bd": "Bangladesh",
    "np": "Nepal", "lk": "Sri Lanka", "cn": "China", "jp": "Japan", "tr": "Türkiye",
    "ae": "United Arab Emirates", "sa": "Saudi Arabia", "eg": "Egypt", "ng": "Nigeria",
    "za": "South Africa", "br": "Brazil", "mx": "Mexico", "ru": "Russia", "ua": "Ukraine",
    "ir": "Iran", "id": "Indonesia", "ph": "Philippines", "vn": "Vietnam", "ma": "Morocco",
    "gh": "Ghana", "ke": "Kenya", "al": "Albania", "rs": "Serbia",
}

NATIONALITIES = {
    "it": "Italian", "in": "Indian", "fr": "French", "de": "German", "es": "Spanish",
    "pt": "Portuguese", "gb": "British", "uk": "British", "us": "American", "pk": "Pakistani",
    "bd": "Bangladeshi", "np": "Nepalese", "cn": "Chinese", "tr": "Turkish", "ng": "Nigerian",
    "eg": "Egyptian", "ir": "Iranian", "gr": "Greek", "el": "Greek", "ro": "Romanian", "pl": "Polish",
    "nl": "Dutch", "be": "Belgian", "ie": "Irish", "at": "Austrian", "lk": "Sri Lankan",
}

LANGUAGES = {
    "eng": "English", "ita": "Italian", "fra": "French", "fre": "French", "deu": "German",
    "ger": "German", "spa": "Spanish", "por": "Portuguese", "hin": "Hindi", "urd": "Urdu",
    "ben": "Bengali", "tam": "Tamil", "tel": "Telugu", "mar": "Marathi", "guj": "Gujarati",
    "pan": "Punjabi", "mal": "Malayalam", "kan": "Kannada", "nep": "Nepali", "ara": "Arabic",
    "zho": "Chinese", "chi": "Chinese", "jpn": "Japanese", "rus": "Russian", "tur": "Turkish",
    "pol": "Polish", "ron": "Romanian", "rum": "Romanian", "nld": "Dutch", "dut": "Dutch",
    "ell": "Greek", "gre": "Greek", "fas": "Persian", "per": "Persian", "swe": "Swedish",
}

# order matters: "Writing-Production" must match writing before production
DIMENSIONS = {
    "writing": "writing", "listening": "listening", "reading": "reading",
    "interaction": "spoken_interaction", "production": "spoken_production",
}


# ------------------------------------------------------------ xml helpers ---

def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def children(el, name):
    return [c for c in el if local(c.tag) == name] if el is not None else []


def child(el, name):
    found = children(el, name)
    return found[0] if found else None


def find(el, *path):
    """Follow a path of local names, returning the first match."""
    for name in path:
        el = child(el, name)
        if el is None:
            return None
    return el


def descendants(el, name):
    return [d for d in el.iter() if local(d.tag) == name] if el is not None else []


def text(el, *path) -> str:
    node = find(el, *path) if path else el
    return (node.text or "").strip() if node is not None else ""


def any_text(el, name) -> str:
    for d in descendants(el, name):
        if (d.text or "").strip():
            return d.text.strip()
    return ""


def clean_html(value: str) -> str | list[str]:
    """Europass stores descriptions as HTML. Lists become bullet lists."""
    if not value:
        return ""
    value = html.unescape(value)
    items = re.findall(r"<li[^>]*>(.*?)</li>", value, flags=re.S | re.I)
    strip = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()
    if items:
        return [strip(i) for i in items if strip(i)]
    value = re.sub(r"<br\s*/?>|</p>", "\n", value, flags=re.I)
    return "\n".join(strip(line) for line in value.split("\n") if strip(line))


def short_date(value: str, keep_day: bool = False) -> str | None:
    if not value:
        return None
    m = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", value)
    if not m:
        return None
    y, mo, d = m.groups()
    if keep_day and mo and d:
        return f"{y}-{mo}-{d}"
    return f"{y}-{mo}" if mo else y


def period(el, wrapper):
    p = child(el, wrapper) or find(el, wrapper)
    if p is None:
        return None, None
    start = short_date(any_text(child(p, "StartDate"), "FormattedDateTime") or text(p, "StartDate"))
    end = short_date(any_text(child(p, "EndDate"), "FormattedDateTime") or text(p, "EndDate"))
    current = any_text(p, "CurrentIndicator").lower() == "true"
    return start, (None if current else end)


def country_name(code: str) -> str:
    return COUNTRIES.get(code.lower(), code.upper()) if code else ""


# ---------------------------------------------------------------- mapping ---

def xml_to_cv(xml_bytes: bytes) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    root = ET.fromstring(xml_bytes)
    if local(root.tag) != "Candidate":
        found = descendants(root, "Candidate")
        if not found:
            raise ValueError("This XML is not a Europass CV (no <Candidate> element).")
        root = found[0]

    person = child(root, "CandidatePerson")
    profile = child(root, "CandidateProfile")
    if person is None:
        raise ValueError("This Europass XML has no personal information block.")

    cv: dict = {"language": (profile.get("languageCode") if profile is not None else None) or "en"}

    # --- personal -----------------------------------------------------------
    p: dict = {
        "first_name": text(person, "PersonName", "GivenName"),
        "last_name": text(person, "PersonName", "FamilyName"),
    }
    for comm in children(person, "Communication"):
        channel = text(comm, "ChannelCode").lower()
        use = text(comm, "UseCode")
        address = child(comm, "Address")
        if channel in ("telephone", "mobiletelephone", "phone") and "phone" not in p:
            p["phone"] = {
                "type": (use or "Mobile").capitalize(),
                "country_dialing": text(comm, "CountryDialing"),
                "number": text(comm, "DialNumber"),
            }
        elif channel == "email" and "email" not in p:
            p["email"] = text(comm, "URI")
        elif channel in ("web", "website") and "website" not in p:
            p["website"] = text(comm, "URI")
        elif address is not None and "address" not in p:
            code = text(address, "CountryCode")
            p["address"] = {
                "street": " ".join(t for t in (text(a) for a in children(address, "AddressLine")) if t),
                "postal_code": text(address, "PostalCode"),
                "city": text(address, "CityName"),
                "country": country_name(code),
                "country_code": code.lower(),
                "type": (use or address.get("type") or "Home").capitalize(),
            }

    nats = [text(n) for n in children(person, "NationalityCode") if text(n)]
    if nats:
        p["nationalities"] = [{"name": NATIONALITIES.get(c.lower(), c.upper()), "code": c.lower()} for c in nats]
    if text(person, "BirthDate"):
        p["date_of_birth"] = short_date(text(person, "BirthDate"), keep_day=True)
    gender = text(person, "GenderCode").upper()
    if gender:
        p["gender"] = {"M": "Male", "F": "Female"}.get(gender[:1], "Other")
    cv["personal"] = p

    mother = []
    for lang in children(person, "PrimaryLanguageCode"):
        code = text(lang)
        mother.append({"name": lang.get("name") or LANGUAGES.get(code.lower(), code), "code": code.lower()})

    if profile is None:
        warnings.append("No profile block found: only personal details were imported.")
        cv["languages"] = {"mother_tongues": mother, "other": []}
        return cv, warnings

    summary = any_text(profile, "ExecutiveSummary")
    if summary:
        about = clean_html(summary)
        cv["about"] = " ".join(about) if isinstance(about, list) else about

    # --- work experience ---------------------------------------------------
    jobs = []
    for eh in descendants(profile, "EmployerHistory"):
        org = text(eh, "OrganizationName")
        org_addr = find(eh, "OrganizationContact", "Communication", "Address")
        for ph in children(eh, "PositionHistory") or [eh]:
            start, end = period(ph, "EmploymentPeriod")
            city = text(org_addr, "CityName") or text(ph, "City")
            code = text(org_addr, "CountryCode") or text(ph, "Country")
            jobs.append({
                "title": text(ph, "PositionTitle"),
                "employer": org,
                "city": city,
                "country": country_name(code),
                "country_code": code.lower(),
                "start": start,
                "end": end,
                "description": clean_html(text(ph, "Description")),
            })
    cv["work_experience"] = jobs

    # --- education ---------------------------------------------------------
    education = []
    for att in descendants(profile, "EducationOrganizationAttendance"):
        start, end = period(att, "AttendancePeriod")
        addr = find(att, "OrganizationContact", "Communication", "Address")
        code = text(addr, "CountryCode")
        degree = child(att, "EducationDegree")
        eqf = re.sub(r"\D", "", text(att, "EducationLevelCode"))
        entry = {
            "title": text(degree, "DegreeName") or text(att, "DegreeName"),
            "organisation": text(att, "OrganizationName"),
            "city": text(addr, "CityName"),
            "country": country_name(code),
            "country_code": code.lower(),
            "start": start,
            "end": end,
            "field": any_text(child(degree, "OccupationalSkillsCovered"), "Description") if degree is not None else "",
            "final_grade": any_text(degree, "DegreeGrade") if degree is not None else "",
            "eqf_level": int(eqf) if eqf and 1 <= int(eqf) <= 8 else None,
        }
        desc = clean_html(text(att, "Description"))
        if desc:
            entry["description"] = " ".join(desc) if isinstance(desc, list) else desc
        education.append({k: v for k, v in entry.items() if v not in ("", None)})
    cv["education"] = education

    # --- skills ------------------------------------------------------------
    other_langs, digital, licences = [], [], []
    for comp in descendants(profile, "PersonCompetency"):
        taxonomy = text(comp, "TaxonomyID").lower()
        cid = text(comp, "CompetencyID")
        name = text(comp, "CompetencyName")
        if "language" in taxonomy:
            lang = {"name": name or LANGUAGES.get(cid.lower(), cid), "code": cid.lower()}
            for dim in children(comp, "CompetencyDimension"):
                dtype = text(dim, "CompetencyDimensionTypeCode").lower()
                score = any_text(dim, "ScoreText").upper()
                for needle, key in DIMENSIONS.items():
                    if needle in dtype and score:
                        lang[key] = score
                        break
            other_langs.append(lang)
        elif "digital" in taxonomy:
            digital.append(name or cid)
        elif "driving" in taxonomy:
            licences.append(cid)
        elif name:
            warnings.append(f"Skipped skill '{name}' (type '{taxonomy or 'unknown'}').")

    cv["languages"] = {"mother_tongues": mother, "other": other_langs}
    cv["digital_skills"] = [d for d in digital if d]
    cv["driving_licence"] = [l for l in licences if l]
    return cv, warnings


def pdf_to_cv(pdf_bytes: bytes) -> tuple[dict, list[str]]:
    try:
        attachments = PdfReader(io.BytesIO(pdf_bytes)).attachments
    except Exception as exc:
        raise ValueError("This file could not be opened as a PDF. It may be damaged.") from exc
    for name, data in attachments.items():
        if name.lower().endswith(".xml"):
            return xml_to_cv(data[0])
    raise ValueError(
        "This PDF has no Europass data inside. Only PDFs downloaded from Europass "
        "(or made with this tool) can be imported."
    )


# ------------------------------------------------------------ code filling ---

_BY_NAME = {v.lower(): k for k, v in COUNTRIES.items() if k not in ("gb", "el")}
_NAT_BY_NAME = {v.lower(): k for k, v in NATIONALITIES.items() if k not in ("uk", "el")}
_LANG_BY_NAME = {}
for _c, _n in LANGUAGES.items():
    _LANG_BY_NAME.setdefault(_n.lower(), _c)


def fill_codes(cv: dict) -> dict:
    """The editor works with names; Europass XML needs ISO codes. Fill any that are missing."""
    p = cv.get("personal") or {}
    addr = p.get("address") or {}
    if addr.get("country") and not addr.get("country_code"):
        addr["country_code"] = _BY_NAME.get(addr["country"].strip().lower(), "")
    for nat in p.get("nationalities") or []:
        name = (nat.get("name") or "").strip().lower()
        if name and not nat.get("code"):
            nat["code"] = _NAT_BY_NAME.get(name) or _BY_NAME.get(name, "")
    for key in ("work_experience", "education"):
        for item in cv.get(key) or []:
            if item.get("country") and not item.get("country_code"):
                item["country_code"] = _BY_NAME.get(item["country"].strip().lower(), "")
    langs = cv.get("languages") or {}
    for lang in (langs.get("mother_tongues") or []) + (langs.get("other") or []):
        if lang.get("name") and not lang.get("code"):
            lang["code"] = _LANG_BY_NAME.get(lang["name"].strip().lower(), "")
    return cv
