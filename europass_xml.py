"""
Build Europass "Candidate" XML from the canonical CV JSON.

The structure follows the XML that the current Europass editor embeds in its
PDFs (HR-Open / EURES based, namespaces below). Europass does not publish this
format as a stable public contract, so treat the element mapping here as a
starting point and verify it with a round-trip test:

    1. python extract.py real_europass_cv.pdf  -> reference XML
    2. compare tag structure with our output
    3. import our generated PDF into the Europass editor and check every field

All tag names are kept in this one file so adjustments are quick.
"""

from __future__ import annotations

import re
import uuid

import sections
import xml.etree.ElementTree as ET

from europass_import import _BY_NAME

NS = {
    "": "http://www.europass.eu/1.0",
    "oa": "http://www.openapplications.org/oagis/9",
    "eures": "http://www.europass_eures.eu/1.0",
    "hr": "http://www.hr-xml.org/3",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def q(tag: str) -> str:
    """'hr:FamilyName' -> '{uri}FamilyName'; 'Candidate' -> default namespace."""
    prefix, _, local = tag.rpartition(":")
    return f"{{{NS[prefix]}}}{local}"


def sub(parent: ET.Element, tag: str, text=None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, q(tag), {k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


def _iso(value: str | None) -> str | None:
    """
    Pass the date through at the precision it was given.

    Europass writes '2021' for a year-only date, not '2021-01-01'; padding it
    would make the CV claim a January start that the student never entered.
    """
    if not value:
        return None
    parts = str(value).split("-")[:3]
    return "-".join(parts)


def _period(parent, wrapper_tag, start_tag, end_tag, current_tag, start, end):
    period = sub(parent, wrapper_tag)
    if start:
        sub(sub(period, start_tag), "hr:FormattedDateTime", _iso(start))
    if end:
        sub(sub(period, end_tag), "hr:FormattedDateTime", _iso(end))
    sub(period, current_tag, "false" if end else "true")


def _location(parent, city, country_code):
    if not (city or country_code):
        return
    addr = sub(sub(sub(parent, "OrganizationContact"), "Communication"), "Address")
    if city:
        sub(addr, "oa:CityName", city)
    if country_code:
        sub(addr, "CountryCode", country_code.lower())


def _org_contact(parent, city, country_code):
    """Return the OrganizationContact element (creating address if given)."""
    contact = sub(parent, "OrganizationContact")
    if city or country_code:
        addr = sub(sub(contact, "Communication"), "Address")
        if city:
            sub(addr, "oa:CityName", city)
        if country_code:
            sub(addr, "CountryCode", country_code.lower())
    return contact


def _desc_html(desc) -> str:
    """Europass stores descriptions as HTML. A list becomes bullet points."""
    if isinstance(desc, list):
        return "<ul>" + "".join(f"<li>{d}</li>" for d in desc) + "</ul>"
    return str(desc or "")


_LANG3 = {
    "english": "eng", "italian": "ita", "french": "fra", "german": "deu", "spanish": "spa",
    "portuguese": "por", "hindi": "hin", "urdu": "urd", "bengali": "ben", "tamil": "tam",
    "telugu": "tel", "marathi": "mar", "gujarati": "guj", "punjabi": "pan", "malayalam": "mal",
    "kannada": "kan", "nepali": "nep", "arabic": "ara", "chinese": "zho", "japanese": "jpn",
    "russian": "rus", "turkish": "tur", "polish": "pol", "romanian": "ron", "dutch": "nld",
    "greek": "ell", "persian": "fas", "swedish": "swe",
}


def _lang3(lang: dict) -> str:
    """Europass uses 3-letter ISO 639 codes for languages (eng, ita...)."""
    name = (lang.get("name") or "").strip().lower()
    return _LANG3.get(name, (lang.get("code") or name[:3] or "und"))


def _person_name(parent, p):
    name = sub(parent, "PersonName")
    sub(name, "oa:GivenName", p.get("first_name", ""))
    sub(name, "hr:FamilyName", p.get("last_name", ""))


def build_xml(cv: dict) -> bytes:
    p = cv.get("personal", {})
    doc_id = str(uuid.uuid4())

    root = ET.Element(q("Candidate"))
    root.set(q("xsi:schemaLocation"), "http://www.europass.eu/1.0 Candidate.xsd")

    sub(root, "hr:DocumentID", schemeID=doc_id, schemeName="DocumentIdentifier",
        schemeAgencyName="EUROPASS", schemeVersionID="4.0")

    # --- Supplier (document owner) --------------------------------------
    supplier = sub(root, "CandidateSupplier")
    sub(supplier, "hr:PartyID", schemeID=doc_id, schemeName="PartyID",
        schemeAgencyName="EUROPASS", schemeVersionID="1.0")
    sub(supplier, "hr:PartyName", "Owner")
    contact = sub(supplier, "PersonContact")
    _person_name(contact, p)
    if p.get("email"):
        c = sub(contact, "Communication")
        sub(c, "ChannelCode", "Email")
        sub(c, "oa:URI", p["email"])
    sub(supplier, "hr:PrecedenceCode", "1")

    # --- Person ----------------------------------------------------------
    person = sub(root, "CandidatePerson")
    _person_name(person, p)

    phone = p.get("phone")
    if phone:
        c = sub(person, "Communication")
        sub(c, "ChannelCode", "Telephone")
        sub(c, "UseCode", (phone.get("type") or "mobile").lower())
        dialing = re.sub(r"\D", "", str(phone.get("country_dialing") or ""))
        number = re.sub(r"\D", "", str(phone.get("number") or ""))     # Europass wants digits only
        if not dialing and number.startswith("00"):
            dialing, number = number[2:4], number[4:]
        if dialing:
            sub(c, "CountryDialing", dialing)
        sub(c, "oa:DialNumber", number)
        code = (p.get("address") or {}).get("country_code") or ""
        if code:
            sub(c, "CountryCode", code.lower())

    if p.get("email"):
        c = sub(person, "Communication")
        sub(c, "ChannelCode", "Email")
        sub(c, "oa:URI", p["email"])

    if p.get("website"):
        c = sub(person, "Communication")
        sub(c, "ChannelCode", "Web")
        sub(c, "oa:URI", p["website"])

    # Europass allows several of each contact detail, each as its own
    # Communication block with the right channel code.
    for extra in p.get("extra_emails") or []:
        c = sub(person, "Communication")
        sub(c, "ChannelCode", "Email")
        sub(c, "oa:URI", extra)
    for extra in p.get("extra_websites") or []:
        c = sub(person, "Communication")
        sub(c, "ChannelCode", "Web")
        sub(c, "oa:URI", extra)
    for extra in p.get("extra_phones") or []:
        digits = re.sub(r"\D", "", str(extra))
        if digits:
            c = sub(person, "Communication")
            sub(c, "ChannelCode", "Telephone")
            sub(c, "oa:DialNumber", digits)
    # Europass writes "Social Media" with a space and "InstantMessage"
    # singular; other spellings are dropped silently on import.
    for item in p.get("social_media") or []:
        c = sub(person, "Communication")
        sub(c, "ChannelCode", "Social Media")
        if item.get("username"):
            sub(c, "MediaUsername", item["username"])
        sub(c, "UseCode", str(item.get("type") or "Other").lower())
        sub(c, "oa:URI", item.get("url", ""))
    for item in p.get("instant_messaging") or []:
        c = sub(person, "Communication")
        sub(c, "ChannelCode", "InstantMessage")
        sub(c, "UseCode", str(item.get("type") or "Other").lower())
        sub(c, "oa:URI", item.get("value", ""))

    addr = p.get("address")
    if addr:
        c = sub(person, "Communication")
        use = (addr.get("type") or "home").lower()
        sub(c, "UseCode", use)
        a = sub(c, "Address", type=use)
        for line in addr.get("address_lines") or ([addr["street"]] if addr.get("street") else []):
            if line:
                sub(a, "oa:AddressLine", line)
        if addr.get("city"):
            sub(a, "oa:CityName", addr["city"])
        if addr.get("country_code"):
            sub(a, "CountryCode", addr["country_code"].lower())
        if addr.get("postal_code"):
            sub(a, "oa:PostalCode", addr["postal_code"])

    for nat in p.get("nationalities", []):
        if nat.get("code"):
            sub(person, "NationalityCode", nat["code"].lower())
    if p.get("date_of_birth"):
        sub(person, "hr:BirthDate", _iso(p["date_of_birth"]))
    birth = p.get("place_of_birth") or {}
    if birth.get("city") or birth.get("country_code") or birth.get("country"):
        bp = sub(person, "BirthPlace")
        if birth.get("city"):
            sub(bp, "oa:CityName", birth["city"])
        code = birth.get("country_code") or _BY_NAME.get(str(birth.get("country", "")).strip().lower(), "")
        if code:
            sub(bp, "CountryCode", code.lower())
    if p.get("gender"):
        sub(person, "GenderCode", p["gender"].lower())         # Europass uses "male"/"female"
    for mt in cv.get("languages", {}).get("mother_tongues", []):
        sub(person, "PrimaryLanguageCode", _lang3(mt))
    passport = p.get("passport") or p.get("passport_number")
    if passport:
        doc = sub(person, "LegalDocument")
        sub(doc, "DocumentTypeCode", p.get("document_type") or "Passport")
        sub(doc, "DocumentID", passport)
    # Work permit: Europass records only the country that issued it.
    permit = p.get("work_permit_country") or ""
    if not permit and p.get("work_permit"):
        permit = _BY_NAME.get(str(p["work_permit"]).strip().lower(), "")
    if permit:
        sub(sub(person, "Visa"), "hr:IssuingCountryCode", permit.lower())

    # --- Profile -----------------------------------------------------------
    # Child order and the empty section containers below match a genuine
    # Europass export exactly; the importer rejects the file otherwise.
    profile = sub(root, "CandidateProfile", languageCode=cv.get("language", "en"))
    sub(profile, "hr:ID", schemeID=doc_id, schemeName="CandidateProfileID",
        schemeAgencyName="EUROPASS", schemeVersionID="1.0")
    sub(profile, "hr:ExecutiveSummary", cv.get("about") or "")

    def section_items(*names):
        """Items of the first additional_section whose title matches."""
        for sec in cv.get("additional_sections") or []:
            title = (sec.get("title") or "").strip().lower()
            if any(title.startswith(n) for n in names):
                return sec.get("items") or []
        return []

    def fill(parent, entry_tag, items, titled_only=False):
        """Write items as <entry_tag><Title/><Description/></entry_tag>."""
        for item in items:
            title = (item.get("heading") or "").strip()
            body = (item.get("text") or "").strip()
            if not title and not body:
                continue
            el = sub(parent, entry_tag)
            sub(el, "Title", title or body[:80])
            if body and not titled_only:
                sub(el, "Description", _desc_html(body))

    history = sub(profile, "EmploymentHistory")
    for job in cv.get("work_experience") or []:
        eh = sub(history, "EmployerHistory")
        sub(eh, "hr:OrganizationName", job.get("employer", ""))
        contact = sub(eh, "OrganizationContact")
        # Europass always writes one address Communication per employer, even
        # when the address itself is blank; omitting it loses an element path.
        lines = job.get("address_lines") or []
        addr = sub(sub(contact, "Communication"), "Address")
        for line in lines:
            sub(addr, "oa:AddressLine", line)
        if job.get("city"):
            sub(addr, "oa:CityName", job["city"])
        if job.get("country_code"):
            sub(addr, "CountryCode", job["country_code"].lower())
        if job.get("website"):
            c = sub(contact, "Communication")
            sub(c, "ChannelCode", "Web")
            sub(c, "oa:URI", job["website"])
        if job.get("email"):
            c = sub(contact, "Communication")
            sub(c, "ChannelCode", "Email")
            sub(c, "oa:URI", job["email"])
        if job.get("industry_code"):
            sub(eh, "hr:IndustryCode", job["industry_code"])
        ph = sub(eh, "PositionHistory")
        sub(ph, "PositionTitle", job.get("title", ""), typeCode="FREETEXT")
        _period(ph, "eures:EmploymentPeriod", "eures:StartDate", "eures:EndDate",
                "hr:CurrentIndicator", job.get("start"), job.get("end"))
        desc = job.get("description")
        if desc:
            sub(ph, "oa:Description", _desc_html(desc))
        if job.get("position_city") or job.get("city"):
            sub(ph, "City", job.get("position_city") or job["city"])
        if job.get("position_country") or job.get("country_code"):
            sub(ph, "Country", (job.get("position_country") or job["country_code"]).lower())
        if job.get("department"):
            sub(eh, "Department", job["department"])
        if job.get("url"):
            sub(eh, "Link", job["url"])

    edu = sub(profile, "EducationHistory")
    for ed in cv.get("education") or []:
        att = sub(edu, "EducationOrganizationAttendance")
        sub(att, "hr:OrganizationName", ed.get("organisation", ""))
        contact = _org_contact(att, ed.get("city"), ed.get("country_code"))
        if ed.get("website"):
            c = sub(contact, "Communication")
            sub(c, "ChannelCode", "Web")
            sub(c, "oa:URI", ed["website"])
        if ed.get("eqf_level"):
            sub(att, "EducationLevelCode", ed["eqf_level"])
        _period(att, "AttendancePeriod", "StartDate", "EndDate",
                "Ongoing", ed.get("start"), ed.get("end"))
        # Europass puts the degree in ep:EducationDegree, not hr:.
        degree = sub(att, "EducationDegree")
        sub(degree, "hr:DegreeName", ed.get("title", ""))
        # Europass writes the field of study two ways. Newer exports use
        # FieldOfStudy/MainFieldOfStudy/ProgramConcentration with an ISCED
        # code; older ones use OccupationalSkillsCovered with free text.
        # Reproduce whichever the source used so a re-import matches.
        form = ed.get("degree_form") or ("field_of_study" if ed.get("program_concentration")
                                          else "occupational" if ed.get("field") else "")
        if form == "occupational":
            occ = sub(degree, "OccupationalSkillsCovered")
            if ed.get("field"):
                sub(occ, "hr:Description", ed["field"])
        elif form == "field_of_study" or ed.get("program_concentration"):
            field = sub(sub(degree, "FieldOfStudy"), "MainFieldOfStudy")
            sub(field, "ProgramConcentration", ed.get("program_concentration") or ed.get("field"))
            # Europass emits these three as empty placeholders when unused.
            sub(degree, "NationalClassification", ed.get("national_classification") or None)
            sub(degree, "CreditType", ed.get("credit_type") or None)
            sub(degree, "NumberOfCredit", ed.get("credits") or None)
        if ed.get("final_grade"):
            sub(degree, "hr:DegreeGrade", ed["final_grade"])
        if ed.get("description") or ed.get("thesis"):
            sub(att, "oa:Description", _desc_html(ed.get("description") or f"Thesis: {ed['thesis']}"))

    sections.emit_licences(profile, cv)
    sections.emit(profile, cv, "honours_awards")
    sections.emit(profile, cv, "publications")

    quals = sub(profile, "PersonQualifications")
    dims = [
        ("listening", "CEF-Understanding-Listening"),
        ("reading", "CEF-Understanding-Reading"),
        ("spoken_production", "CEF-Speaking-Production"),
        ("spoken_interaction", "CEF-Speaking-Interaction"),
        ("writing", "CEF-Writing-Production"),
    ]
    for lang in cv.get("languages", {}).get("other", []):
        comp = sub(quals, "PersonCompetency")
        sub(comp, "CompetencyID", _lang3(lang), schemeName="NORMAL")
        sub(comp, "hr:TaxonomyID", "language")
        for key, code in dims:
            if lang.get(key):
                d = sub(comp, "eures:CompetencyDimension")
                sub(d, "hr:CompetencyDimensionTypeCode", code)
                sub(sub(d, "eures:Score"), "hr:ScoreText", lang[key])

    sections.emit(profile, cv, "recommendations")
    # The official export carries the profile picture inside the XML as a
    # base64 data URI, so the photo survives a re-import into Europass.
    attachment = sub(profile, "eures:Attachment")
    photo = (p.get("photo") or "").strip()
    if photo.startswith("data:image"):
        import base64 as _b64
        sub(attachment, "oa:EmbeddedData", _b64.b64encode(photo.encode()).decode())
        sub(attachment, "oa:FileType", "photo")
        sub(attachment, "hr:Instructions", "ProfilePicture")

    sections.emit(profile, cv, "hobbies")

    sections.emit(profile, cv, "creative_works")
    sections.emit(profile, cv, "projects")
    sections.emit(profile, cv, "social_political")

    # Skills go under Skills > SkillsGroup, not PersonQualifications. Each
    # group keeps its own title ("Analytical Skills"...), as Europass does;
    # a plain list of names becomes one untitled group.
    skills = sub(profile, "Skills")

    def skill_group(title, names):
        names = [n for n in names if str(n).strip()]
        if not names:
            return
        group = sub(skills, "SkillsGroup")
        sub(group, "Title", title or "Digital skills")
        for name in names:
            comp = sub(group, "PersonCompetency")
            sub(comp, "hr:TaxonomyID", "Digital_Skill")
            sub(comp, "hr:CompetencyName", name)

    digital = cv.get("digital_skills") or []
    if digital and isinstance(digital[0], dict):
        for entry in digital:
            skill_group(entry.get("title"), entry.get("items") or [])
    else:
        skill_group(None, digital)

    sections.emit(profile, cv, "networks")
    sections.emit(profile, cv, "conferences")
    sections.emit(profile, cv, "volunteering")
    sections.emit(profile, cv, "certifications")

    # --- Rendering information (with the section order the editor shows) ----
    rendering = sub(root, "RenderingInformation")
    design = sub(rendering, "Design")
    sub(design, "Template", "Template1")
    sub(design, "Color", "Default")
    sub(design, "FontSize", "Medium")
    sub(design, "Logo", "FirstPage")
    sub(design, "PageNumbers", "true" if (cv.get("design") or {}).get("page_numbers", True) else "false")
    closing = cv.get("closing_statement") or {}
    if closing.get("text"):
        cs = sub(rendering, "ClosingStatement")
        sub(cs, "Statement", closing["text"])
        if closing.get("place"):
            sub(cs, "Place", closing["place"])
        if closing.get("date"):
            sub(sub(cs, "Date"), "hr:FormattedDateTime", _iso(closing["date"]))

    order = sub(design, "SectionsOrder")
    for name in ("education-training", "work-experience", "profile-skills", "language",
                 "certifications", "conference-seminar", "creative-works", "driving-licence",
                 "hobbies-interests", "honour-award", "membership", "projects",
                 "publication", "recommendation", "social-or-political-activity",
                 "volunteering"):
        sub(sub(order, "Section"), "Title", name)

    ET.indent(root, space="    ")
    # ElementTree keeps one global prefix table, and other libraries (WeasyPrint
    # among them) overwrite the empty prefix when they are imported. Registering
    # again here means the result never depends on what else has been loaded;
    # without it the default namespace comes out as "ns0:" and Europass rejects
    # every element in it.
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)
    body = ET.tostring(root, encoding="UTF-8", xml_declaration=False)
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body