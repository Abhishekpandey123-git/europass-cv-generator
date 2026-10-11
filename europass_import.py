"""
Read Europass XML (or a Europass PDF that carries it) into the CV JSON format.

Matching is done on local tag names, ignoring namespaces, so small differences
between Europass versions don't break the import. Anything unrecognised is
skipped and reported as a warning rather than failing the whole import.
"""

from __future__ import annotations

import sections as cv_sections

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
    current = (any_text(p, "CurrentIndicator") or any_text(p, "Ongoing")).lower() == "true"
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
    # Europass allows any number of Communication blocks. The first of each
    # kind becomes the primary field the templates show; the rest are kept as
    # extras so a re-export reproduces all of them.
    p.setdefault("extra_emails", [])
    p.setdefault("extra_websites", [])
    p.setdefault("extra_phones", [])
    p.setdefault("social_media", [])
    p.setdefault("instant_messaging", [])
    for comm in children(person, "Communication"):
        channel = text(comm, "ChannelCode").lower().replace(" ", "")
        use = text(comm, "UseCode")
        address = child(comm, "Address")
        if channel in ("socialmedia", "social"):
            p["social_media"].append({
                "type": use or "Other",
                "username": text(comm, "MediaUsername"),
                "url": text(comm, "URI"),
            })
        elif channel in ("instantmessage", "instantmessaging", "im"):
            p["instant_messaging"].append({
                "type": use or "Other",
                "value": text(comm, "URI"),
            })
        elif channel in ("telephone", "mobiletelephone", "phone") and "phone" not in p:
            p["phone"] = {
                "type": (use or "Mobile").capitalize(),
                "country_dialing": text(comm, "CountryDialing"),
                "number": text(comm, "DialNumber"),
                "country_code": text(comm, "CountryCode").lower(),
            }
        elif channel in ("telephone", "mobiletelephone", "phone"):
            p["extra_phones"].append(text(comm, "DialNumber"))
        elif channel == "email" and "email" not in p:
            p["email"] = text(comm, "URI")
        elif channel == "email":
            p["extra_emails"].append(text(comm, "URI"))
        elif channel in ("web", "website") and "website" not in p:
            p["website"] = text(comm, "URI")
        elif channel in ("web", "website"):
            p["extra_websites"].append(text(comm, "URI"))
        elif address is not None and "address" not in p:
            code = text(address, "CountryCode")
            p["address"] = {
                "street": " ".join(t for t in (text(a) for a in children(address, "AddressLine")) if t),
                "address_lines": [t for t in (text(a) for a in children(address, "AddressLine")) if t],
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

    birth = child(person, "BirthPlace")
    if birth is not None:
        city = text(birth, "CityName")
        code = text(birth, "CountryCode")
        if city or code:
            p["place_of_birth"] = {k: v for k, v in
                                   (("city", city), ("country", country_name(code))) if v}

    for doc in descendants(person, "LegalDocument"):
        number = text(doc, "DocumentID")
        if number:
            p["passport"] = number
            p["document_type"] = text(doc, "DocumentTypeCode") or "Passport"
            break
    visa = child(person, "Visa")
    if visa is not None:
        issuing = any_text(visa, "IssuingCountryCode")
        if issuing:
            p["work_permit_country"] = issuing.lower()
            p["work_permit"] = country_name(issuing)
    gender = text(person, "GenderCode").upper()
    if gender:
        p["gender"] = {"M": "Male", "F": "Female"}.get(gender[:1], "Other")
    cv["personal"] = p

    mother = []
    for lang in children(person, "PrimaryLanguageCode"):
        value = text(lang)                       # "Bengali", or a code like "ben"
        marker = (lang.get("name") or "").strip()
        if marker and marker.upper() not in ("FREE_TEXT", "NORMAL"):
            name, code = marker, value.lower()   # older files: name in the attribute
        else:
            name = LANGUAGES.get(value.lower(), value)   # current files: name is the text
            code = value.lower() if len(value) <= 3 else ""
        if name:
            mother.append({"name": name, "code": code})

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
            comms = list(descendants(eh, "Communication"))
            jobs.append({
                "title": text(ph, "PositionTitle"),
                "employer": org,
                "city": city,
                "country": country_name(code),
                "country_code": code.lower(),
                "start": start,
                "end": end,
                "description": clean_html(text(ph, "Description")),
                "department": text(eh, "Department"),
                "url": text(eh, "Link"),
                "industry_code": any_text(eh, "IndustryCode"),
                "website": next((text(c, "URI") for c in comms
                                 if text(c, "ChannelCode").lower() in ("web", "website")), ""),
                "email": next((text(c, "URI") for c in comms
                               if text(c, "ChannelCode").lower() == "email"), ""),
                "address_lines": [t for t in (text(a) for a in descendants(eh, "AddressLine")) if t],
                "position_city": text(ph, "City"),
                "position_country": text(ph, "Country"),
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
            "website": next((text(c, "URI") for c in descendants(att, "Communication")
                             if text(c, "ChannelCode").lower() in ("web", "website")), ""),
            "program_concentration": any_text(child(degree, "FieldOfStudy"), "ProgramConcentration") if degree is not None else "",
            "degree_form": ("field_of_study" if (degree is not None and child(degree, "FieldOfStudy") is not None)
                            else "occupational" if (degree is not None and child(degree, "OccupationalSkillsCovered") is not None)
                            else ""),
            "national_classification": any_text(degree, "NationalClassification") if degree is not None else "",
            "credits": any_text(degree, "NumberOfCredit") if degree is not None else "",
            "credit_type": any_text(degree, "CreditType") if degree is not None else "",
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
            digital.append(name or cid)          # flat fallback, see groups below
        elif "driving" in taxonomy:
            licences.append(cid)
        elif name:
            warnings.append(f"Skipped skill '{name}' (type '{taxonomy or 'unknown'}').")

    cv["languages"] = {"mother_tongues": mother, "other": other_langs}
    # Europass groups skills under <SkillsGroup><Title>, and the group titles
    # are shown on the CV ("social skill", "other skills"), so keep them.
    groups = []
    for holder in descendants(profile, "Skills"):
        for group in children(holder, "SkillsGroup"):
            names = [text(c, "CompetencyName") or text(c, "CompetencyID")
                     for c in children(group, "PersonCompetency")]
            names = [n for n in names if n]
            if names:
                groups.append({"title": text(group, "Title"), "items": names})
    cv["digital_skills"] = groups if groups else [d for d in digital if d]
    cv["driving_licence"] = [l for l in licences if l]

    # Anything in the file we have no field for is reported rather than dropped
    # in silence, so a Europass change shows up as a warning on the dashboard
    # instead of a student's CV quietly losing a section.
    KNOWN = {
        "Candidate", "DocumentID", "CandidateSupplier", "PartyID", "PartyName",
        "PersonContact", "PrecedenceCode", "CandidatePerson", "PersonName",
        "GivenName", "FamilyName", "Communication", "ChannelCode", "UseCode",
        "CountryDialing", "DialNumber", "URI", "Address", "AddressLine",
        "CityName", "CountryCode", "PostalCode", "NationalityCode", "BirthDate",
        "BirthPlace", "GenderCode", "PrimaryLanguageCode", "LegalDocument",
        "DocumentTypeCode", "CandidateProfile", "ID", "ExecutiveSummary",
        "EmploymentHistory", "EmployerHistory", "OrganizationName",
        "OrganizationContact", "PositionHistory", "PositionTitle",
        "EmploymentPeriod", "StartDate", "EndDate", "FormattedDateTime",
        "CurrentIndicator", "Ongoing", "Description", "City", "Country",
        "EducationHistory", "EducationOrganizationAttendance", "AttendancePeriod",
        "EducationDegree", "DegreeName", "DegreeGrade", "EducationLevelCode",
        "OccupationalSkillsCovered", "PersonQualifications", "PersonCompetency",
        "CompetencyID", "TaxonomyID", "CompetencyName", "CompetencyDimension",
        "CompetencyDimensionTypeCode", "Score", "ScoreText", "Skills",
        "SkillsGroup", "Title", "Licenses", "Certifications", "Certification",
        "PublicationHistory", "Publication", "EmploymentReferences",
        "EmploymentReference", "Attachment", "HobbiesAndInterests",
        "HobbyOrInterest", "CreativeWorks", "CreativeWork", "Projects", "Project",
        "SocialAndPoliticalActivities", "SocialOrPoliticalActivity",
        "NetworksAndMemberships", "NetworkOrMembership", "ConferencesAndSeminars",
        "ConferenceOrSeminar", "VoluntaryWorks", "VoluntaryWork",
        "CourseCertifications", "CourseCertification", "RenderingInformation",
        "Design", "Template", "Color", "FontSize", "Logo", "PageNumbers",
        "SectionsOrder", "Section", "Name", "ClosingStatement", "Statement",
        "Place", "Date", "Location", "EmbeddedData", "FileType", "Instructions",
        "CertificationName", "IssuingAuthority", "IssuingOrganisation", "ModeOfLearning", "FirstIssuedDate", "Authors", "Journal", "Publisher", "Volume", "Year", "Reference", "DOI", "Link", "FormattedPublicationDescription", "Referee", "Role", "Comment", "Activity", "Ongoing", "StartDate", "EndDate", "FormattedDateTime", "Licenses", "License", "LicenseTypeCode", "Attachment", "PersonName", "GivenName", "FamilyName", "Communication", "ChannelCode", "URI", "DialNumber", "CountryDialing", "CountryCode", "SocialAndPoliticalActivity", "NetworkAndMembership", "ConferenceAndSeminar", "Title", "Description", "Others", "Other",
    }
    closing = child(root, "RenderingInformation")
    closing = find(closing, "ClosingStatement") if closing is not None else None
    if closing is not None:
        statement = text(closing, "Statement")
        if statement:
            cv["closing_statement"] = {
                "text": statement,
                "place": text(closing, "Place"),
                "date": short_date(any_text(closing, "FormattedDateTime"), keep_day=True) or "",
            }

    unknown = sorted({local(el.tag) for el in root.iter()
                      if local(el.tag) not in KNOWN and (el.text or "").strip()})
    if unknown:
        warnings.append("This CV contains fields this tool does not know yet, so they were "
                        "not imported: " + ", ".join(unknown[:8])
                        + ("…" if len(unknown) > 8 else "") + ". Please add them by hand.")

    # Typed sections. Each Europass container has its own fields - dates,
    # locations, links, a publication's journal and volume - so they are read
    # into their own shape rather than flattened to {heading, text}. The
    # generic version of this lost 116 of 234 element paths on a full CV.
    cv.update(cv_sections.blank())
    cv_sections.read(profile, cv)

    # Anything in a container we do not model stays available to staff rather
    # than being silently dropped.
    leftovers = []
    for holder in descendants(profile, "Others"):
        for el in descendants(holder, "Other"):
            title = text(el, "Title") or any_text(el, "Name")
            body = clean_html(text(el, "Description") or any_text(el, "Description"))
            if isinstance(body, list):
                body = "\n".join(body)
            if title or body:
                leftovers.append({"heading": title, "text": body})
    if leftovers:
        cv["additional_sections"] = [{"title": "Additional information", "items": leftovers}]

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