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

import uuid
import xml.etree.ElementTree as ET

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
    """Normalise 'YYYY', 'YYYY-MM' or 'YYYY-MM-DD' to a full date."""
    if not value:
        return None
    parts = str(value).split("-")
    while len(parts) < 3:
        parts.append("01")
    return "-".join(parts[:3])


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
        if phone.get("type"):
            sub(c, "UseCode", phone["type"].lower())
        if phone.get("country_dialing"):
            sub(c, "CountryDialing", phone["country_dialing"])
        sub(c, "oa:DialNumber", phone.get("number", ""))

    if p.get("email"):
        c = sub(person, "Communication")
        sub(c, "ChannelCode", "Email")
        sub(c, "oa:URI", p["email"])

    if p.get("website"):
        c = sub(person, "Communication")
        sub(c, "ChannelCode", "Web")
        sub(c, "oa:URI", p["website"])

    addr = p.get("address")
    if addr:
        c = sub(person, "Communication")
        use = (addr.get("type") or "home").lower()
        sub(c, "UseCode", use)
        a = sub(c, "Address", type=use)
        if addr.get("street"):
            sub(a, "oa:AddressLine", addr["street"])
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
    if p.get("gender"):
        sub(person, "hr:GenderCode", {"male": "M", "female": "F"}.get(p["gender"].lower(), "O"))
    for mt in cv.get("languages", {}).get("mother_tongues", []):
        sub(person, "PrimaryLanguageCode", mt.get("code", ""), name=mt.get("name", ""))

    # --- Profile -----------------------------------------------------------
    profile = sub(root, "CandidateProfile", languageCode=cv.get("language", "en"))
    sub(profile, "hr:ID", schemeID=doc_id, schemeName="CandidateProfileID",
        schemeAgencyName="EUROPASS", schemeVersionID="1.0")
    if cv.get("about"):
        sub(profile, "hr:ExecutiveSummary", cv["about"])

    jobs = cv.get("work_experience") or []
    if jobs:
        history = sub(profile, "EmploymentHistory")
        for job in jobs:
            eh = sub(history, "EmployerHistory")
            sub(eh, "hr:OrganizationName", job.get("employer", ""))
            _location(eh, job.get("city"), job.get("country_code"))
            ph = sub(eh, "PositionHistory")
            sub(ph, "PositionTitle", job.get("title", ""), typeCode="FREETEXT")
            _period(ph, "eures:EmploymentPeriod", "eures:StartDate", "eures:EndDate",
                    "hr:CurrentIndicator", job.get("start"), job.get("end"))
            desc = job.get("description")
            if desc:
                html = desc if isinstance(desc, str) else \
                    "<ul>" + "".join(f"<li>{d}</li>" for d in desc) + "</ul>"
                sub(ph, "oa:Description", html)
            if job.get("city"):
                sub(ph, "City", job["city"])
            if job.get("country_code"):
                sub(ph, "Country", job["country_code"].lower())

    education = cv.get("education") or []
    if education:
        history = sub(profile, "EducationHistory")
        for ed in education:
            att = sub(history, "EducationOrganizationAttendance")
            sub(att, "hr:OrganizationName", ed.get("organisation", ""))
            _location(att, ed.get("city"), ed.get("country_code"))
            if ed.get("eqf_level"):
                sub(att, "EducationLevelCode", ed["eqf_level"])
            _period(att, "AttendancePeriod", "StartDate", "EndDate",
                    "hr:CurrentIndicator", ed.get("start"), ed.get("end"))
            degree = sub(att, "hr:EducationDegree")
            sub(degree, "hr:DegreeName", ed.get("title", ""))
            if ed.get("field"):
                sub(sub(degree, "OccupationalSkillsCovered"), "hr:Description", ed["field"])
            if ed.get("final_grade"):
                sub(degree, "hr:DegreeGrade", ed["final_grade"])
            if ed.get("description") or ed.get("thesis"):
                sub(att, "oa:Description", ed.get("description") or f"Thesis: {ed['thesis']}")

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
        sub(comp, "CompetencyID", lang.get("code", ""))
        sub(comp, "hr:TaxonomyID", "language")
        sub(comp, "hr:CompetencyName", lang.get("name", ""))
        for key, code in dims:
            if lang.get(key):
                d = sub(comp, "eures:CompetencyDimension")
                sub(d, "hr:CompetencyDimensionTypeCode", code)
                sub(sub(d, "eures:Score"), "hr:ScoreText", lang[key])

    for skill in cv.get("digital_skills") or []:
        comp = sub(quals, "PersonCompetency")
        sub(comp, "CompetencyID", skill)
        sub(comp, "hr:TaxonomyID", "DigitalSkill")
        sub(comp, "hr:CompetencyName", skill)

    for licence in cv.get("driving_licence") or []:
        comp = sub(quals, "PersonCompetency")
        sub(comp, "CompetencyID", licence)
        sub(comp, "hr:TaxonomyID", "DrivingLicence")

    # --- Rendering hints ---------------------------------------------------
    design = sub(sub(root, "RenderingInformation"), "Design")
    sub(design, "Template", "Template1")
    sub(design, "Color", "Default")
    sub(design, "FontSize", "Medium")
    sub(design, "PageNumbers", "true")

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)
