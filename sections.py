"""
Typed CV sections: read them out of official Europass XML, write them back.

Why this module exists
----------------------
The first version of this converter kept everything that was not education,
work, languages or skills in one generic ``additional_sections`` list of
``{heading, text}`` pairs, matched to Europass containers by title prefix.
That shape cannot hold a date, a location, a link, or a publication's
journal and volume, so all of it was dropped on export. A structural diff
against the European Commission's own files showed 116 of 234 element paths
missing on a fully populated CV - the "Europass only loads half of it"
symptom, reproduced exactly.

Every field name and the order of every child element below was read out of
genuine Europass exports (see tools/xml_diff.py, which fails the build if we
stop reproducing them).

Two Europass containers are easy to confuse:

* ``Certifications``       - honours and awards. CertificationName,
                             IssuingAuthority, FirstIssuedDate.
* ``CourseCertifications`` - what the editor calls Certifications. Title,
                             IssuingOrganisation, FirstIssuedDate,
                             ModeOfLearning, Link.
"""
from __future__ import annotations

# Section key -> the Europass container and entry element it maps to.
CONTAINERS = {
    "honours_awards":   ("Certifications", "Certification"),
    "certifications":   ("CourseCertifications", "CourseCertification"),
    "conferences":      ("ConferencesAndSeminars", "ConferenceAndSeminar"),
    "creative_works":   ("CreativeWorks", "CreativeWork"),
    "projects":         ("Projects", "Project"),
    "publications":     ("PublicationHistory", "Publication"),
    "recommendations":  ("EmploymentReferences", "Referee"),
    "social_political": ("SocialAndPoliticalActivities", "SocialAndPoliticalActivity"),
    "volunteering":     ("VoluntaryWorks", "VoluntaryWork"),
    "networks":         ("NetworksAndMemberships", "NetworkAndMembership"),
    "hobbies":          ("HobbiesAndInterests", "HobbyOrInterest"),
}

# Sections whose entry is <Title><Date><Location><Description><Link>.
DATED_FLAT = ("conferences", "volunteering")
# Sections that nest everything bar the location inside <Activity>.
DATED_ACTIVITY = ("social_political", "networks")
# Sections that are <Title><Date><Description>[<Link>] with no location.
DATED_SIMPLE = ("creative_works", "projects")

ALL_KEYS = tuple(CONTAINERS) + ("driving_licence",)


def blank() -> dict:
    """Empty typed sections, so every CV dict has the same shape."""
    return {key: [] for key in CONTAINERS}


# ------------------------------------------------------------------ read ---

def read(profile, cv: dict) -> None:
    """Fill cv[...] from a <CandidateProfile> element, in place."""
    import europass_import as imp

    def entries(container_name, entry_name):
        container = imp.child(profile, container_name)
        if container is None:
            return []
        return imp.children(container, entry_name)

    def dates(el, wrapper="Date"):
        return imp.period(el, wrapper)

    def desc(el, *names):
        for name in names:
            value = imp.any_text(el, name)
            if value:
                return imp.clean_html(value)
        return ""

    # --- honours and awards -------------------------------------------
    out = []
    for el in entries("Certifications", "Certification"):
        issued = imp.child(el, "FirstIssuedDate")
        out.append({
            "title": imp.any_text(el, "CertificationName"),
            "organisation": imp.any_text(imp.child(el, "IssuingAuthority"), "Name") if imp.child(el, "IssuingAuthority") is not None else "",
            "date": imp.short_date(imp.any_text(issued, "FormattedDateTime") if issued is not None else "", keep_day=True),
            "description": desc(el, "Description"),
        })
    cv["honours_awards"] = [e for e in out if any(e.values())]

    # --- certifications (courses) --------------------------------------
    out = []
    for el in entries("CourseCertifications", "CourseCertification"):
        issued = imp.child(el, "FirstIssuedDate")
        out.append({
            "title": imp.any_text(el, "Title"),
            "organisation": imp.any_text(el, "IssuingOrganisation"),
            "date": imp.short_date(imp.any_text(issued, "FormattedDateTime") if issued is not None else "", keep_day=True),
            "mode": imp.any_text(el, "ModeOfLearning"),
            "description": desc(el, "Description"),
            "url": imp.any_text(el, "Link"),
        })
    cv["certifications"] = [e for e in out if any(e.values())]

    # --- conferences and volunteering: flat, dated, located -------------
    for key in DATED_FLAT:
        container, entry = CONTAINERS[key]
        out = []
        for el in entries(container, entry):
            start, end = dates(el)
            out.append({
                "title": imp.any_text(el, "Title"),
                "start": start, "end": end,
                "location": imp.any_text(el, "Location"),
                "description": desc(el, "Description"),
                "url": imp.any_text(el, "Link"),
            })
        cv[key] = [e for e in out if any(e.values())]

    # --- social/political and networks: nested in <Activity> ------------
    for key in DATED_ACTIVITY:
        container, entry = CONTAINERS[key]
        out = []
        for el in entries(container, entry):
            activity = imp.child(el, "Activity")
            if activity is None:
                continue
            start, end = dates(activity)
            out.append({
                "title": imp.any_text(activity, "Title"),
                "start": start, "end": end,
                "location": imp.any_text(el, "Location"),
                "description": desc(activity, "Description"),
            })
        cv[key] = [e for e in out if any(e.values())]

    # --- creative works and projects: dated, no location ----------------
    for key in DATED_SIMPLE:
        container, entry = CONTAINERS[key]
        out = []
        for el in entries(container, entry):
            start, end = dates(el)
            out.append({
                "title": imp.any_text(el, "Title"),
                "start": start, "end": end,
                "description": desc(el, "Description"),
                "url": imp.any_text(el, "Link"),
            })
        cv[key] = [e for e in out if any(e.values())]

    # --- publications ---------------------------------------------------
    out = []
    for el in entries("PublicationHistory", "Publication"):
        doi = imp.child(el, "DOI")
        out.append({
            "title": imp.any_text(el, "Title"),
            "year": imp.any_text(el, "Year"),
            "reference": imp.any_text(el, "Reference"),
            "doi": imp.any_text(doi, "Link") if doi is not None else "",
            "authors": imp.any_text(el, "Authors"),
            "journal": imp.any_text(el, "Journal"),
            "publisher": imp.any_text(el, "Publisher"),
            "volume": imp.any_text(el, "Volume"),
            "description": desc(el, "FormattedPublicationDescription", "Description"),
        })
    cv["publications"] = [e for e in out if any(e.values())]

    # --- referees -------------------------------------------------------
    out = []
    for el in entries("EmploymentReferences", "Referee"):
        name_el = imp.child(el, "PersonName")
        entry = {
            "name": " ".join(x for x in [
                imp.any_text(name_el, "GivenName") if name_el is not None else "",
                imp.any_text(name_el, "FamilyName") if name_el is not None else "",
            ] if x).strip(),
            "role": imp.any_text(el, "Role"),
            "email": "", "phone": "", "phone_dialing": "", "phone_country": "",
            "description": desc(el, "Comment", "Description"),
        }
        for comm in imp.children(el, "Communication"):
            channel = (imp.any_text(comm, "ChannelCode") or "").lower()
            if channel == "email":
                entry["email"] = imp.any_text(comm, "URI")
            elif channel == "telephone":
                entry["phone"] = imp.any_text(comm, "DialNumber")
                entry["phone_dialing"] = imp.any_text(comm, "CountryDialing")
                entry["phone_country"] = imp.any_text(comm, "CountryCode")
        out.append(entry)
    cv["recommendations"] = [e for e in out if any(e.values())]

    # --- hobbies ---------------------------------------------------------
    out = []
    for el in entries("HobbiesAndInterests", "HobbyOrInterest"):
        out.append({
            "title": imp.any_text(el, "Title"),
            "description": desc(el, "Description"),
        })
    cv["hobbies"] = [e for e in out if any(e.values())]

    # --- driving licences -------------------------------------------------
    licences = imp.child(profile, "Licenses")
    codes = []
    if licences is not None:
        for lic in imp.children(licences, "License"):
            code = imp.any_text(lic, "LicenseTypeCode")
            if code:
                codes.append(code)
    if codes:
        cv["driving_licence"] = codes

    # --- profile picture ---------------------------------------------------
    attachment = imp.child(profile, "Attachment")
    if attachment is not None:
        import base64
        data = imp.any_text(attachment, "EmbeddedData")
        if data:
            try:
                decoded = base64.b64decode(data).decode("utf-8", "replace")
            except Exception:
                decoded = ""
            if decoded.startswith("data:image"):
                cv.setdefault("personal", {})["photo"] = decoded


# ----------------------------------------------------------------- write ---

def emit(profile, cv: dict, key: str) -> None:
    """Append one typed section's container to <CandidateProfile>.

    One section at a time, because the official profile interleaves these with
    containers built elsewhere (PersonQualifications, Attachment, Skills) and
    the Europass importer is order-sensitive. europass_xml.build_xml calls
    these in the order a genuine export uses.
    """
    import europass_xml as X

    sub, desc_html, iso = X.sub, X._desc_html, X._iso

    def date_block(parent, start, end):
        block = sub(parent, "Date")
        if start:
            sub(sub(block, "StartDate"), "hr:FormattedDateTime", iso(start))
        if end:
            sub(sub(block, "EndDate"), "hr:FormattedDateTime", iso(end))
        sub(block, "Ongoing", "false" if end else "true")

    def put(parent, tag, value):
        if value:
            sub(parent, tag, value)

    entries = [e for e in (cv.get(key) or []) if isinstance(e, dict) and any(e.values())]
    container_name, entry_tag = CONTAINERS[key]
    container = sub(profile, container_name)

    if key == "honours_awards":
        for e in entries:
            el = sub(container, entry_tag)
            put(el, "hr:CertificationName", e.get("title"))
            if e.get("date"):
                sub(sub(el, "eures:FirstIssuedDate"), "hr:FormattedDateTime", iso(e["date"]))
            if e.get("organisation"):
                sub(sub(el, "eures:IssuingAuthority"), "oa:Name", e["organisation"])
            if e.get("description"):
                sub(el, "oa:Description", desc_html(e["description"]))

    elif key == "publications":
        for e in entries:
            el = sub(container, entry_tag)
            if e.get("description"):
                sub(el, "hr:FormattedPublicationDescription", desc_html(e["description"]))
            put(el, "Title", e.get("title"))
            put(el, "Year", e.get("year"))
            put(el, "Reference", e.get("reference"))
            if e.get("doi"):
                sub(sub(el, "DOI"), "Link", e["doi"])
            put(el, "Authors", e.get("authors"))
            put(el, "Journal", e.get("journal"))
            put(el, "Publisher", e.get("publisher"))
            put(el, "Volume", e.get("volume"))

    elif key == "recommendations":
        for e in entries:
            el = sub(container, entry_tag)
            if e.get("name"):
                sub(sub(el, "eures:PersonName"), "oa:GivenName", e["name"])
            if e.get("email"):
                c = sub(el, "Communication")
                sub(c, "ChannelCode", "Email")
                sub(c, "oa:URI", e["email"])
            if e.get("phone"):
                c = sub(el, "Communication")
                sub(c, "ChannelCode", "Telephone")
                put(c, "CountryDialing", e.get("phone_dialing"))
                sub(c, "oa:DialNumber", e["phone"])
                if e.get("phone_country"):
                    sub(c, "CountryCode", str(e["phone_country"]).lower())
            if e.get("description"):
                sub(el, "hr:Comment", desc_html(e["description"]))
            put(el, "Role", e.get("role"))

    elif key == "hobbies":
        for e in entries:
            el = sub(container, entry_tag)
            put(el, "Title", e.get("title"))
            if e.get("description"):
                sub(el, "Description", desc_html(e["description"]))

    elif key in DATED_SIMPLE:
        for e in entries:
            el = sub(container, entry_tag)
            put(el, "Title", e.get("title"))
            date_block(el, e.get("start"), e.get("end"))
            if e.get("description"):
                sub(el, "Description", desc_html(e["description"]))
            put(el, "Link", e.get("url"))

    elif key in DATED_ACTIVITY:
        for e in entries:
            el = sub(container, entry_tag)
            activity = sub(el, "Activity")
            put(activity, "Title", e.get("title"))
            date_block(activity, e.get("start"), e.get("end"))
            if e.get("description"):
                sub(activity, "Description", desc_html(e["description"]))
            put(el, "Location", e.get("location"))

    elif key in DATED_FLAT:
        for e in entries:
            el = sub(container, entry_tag)
            put(el, "Title", e.get("title"))
            date_block(el, e.get("start"), e.get("end"))
            put(el, "Location", e.get("location"))
            if e.get("description"):
                sub(el, "Description", desc_html(e["description"]))
            put(el, "Link", e.get("url"))

    elif key == "certifications":
        for e in entries:
            el = sub(container, entry_tag)
            put(el, "Title", e.get("title"))
            put(el, "IssuingOrganisation", e.get("organisation"))
            if e.get("date"):
                sub(sub(el, "eures:FirstIssuedDate"), "hr:FormattedDateTime", iso(e["date"]))
            put(el, "ModeOfLearning", str(e.get("mode") or "").lower() or None)
            if e.get("description"):
                sub(el, "oa:Description", desc_html(e["description"]))
            put(el, "Link", e.get("url"))


def emit_licences(profile, cv: dict) -> None:
    """<eures:Licenses> - one <License> per driving licence category."""
    import europass_xml as X
    container = X.sub(profile, "eures:Licenses")
    for code in cv.get("driving_licence") or []:
        code = str(code).strip()
        if code:
            X.sub(X.sub(container, "eures:License"), "hr:LicenseTypeCode", code)
