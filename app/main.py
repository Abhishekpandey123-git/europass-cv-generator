from __future__ import annotations

import html
import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import fitz
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from lxml import etree

load_dotenv()

ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT / "europass_template.xml"
MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))

app = FastAPI(title="Europass PDF → XML Converter", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT.parent / "static"), name="static")
templates = Jinja2Templates(directory=ROOT.parent / "templates")

NS = {
    "ep": "http://www.europass.eu/1.0",
    "oa": "http://www.openapplications.org/oagis/9",
    "hr": "http://www.hr-xml.org/3",
    "eures": "http://www.europass_eures.eu/1.0",
}
EP = "{" + NS["ep"] + "}"
OA = "{" + NS["oa"] + "}"
HR = "{" + NS["hr"] + "}"
EURES = "{" + NS["eures"] + "}"


def q(ns: str, tag: str) -> str:
    return "{" + NS[ns] + "}" + tag


def text_of(node) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def esc_html(s: str) -> str:
    return html.escape(s or "", quote=False)


def p_html(lines: list[str]) -> str:
    return "".join(f"<p>{esc_html(x)}</p>" for x in lines if x.strip())


def parse_pdf(file_bytes: bytes) -> str:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    parts = []
    for page in doc:
        parts.append(page.get_text("text"))
    doc.close()
    return "\n".join(parts).strip()


def heuristic_extract(text: str) -> dict[str, Any]:
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
    lines = [x for x in lines if x]
    joined = "\n".join(lines)
    email = (re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", joined) or [""])[0]
    phone_m = re.search(r"(?:\+\s*\d{1,3}[\s-]?)?(?:\d[\s-]?){8,14}\d", joined)
    phone = phone_m.group(0).strip() if phone_m else ""
    dob_m = re.search(r"(?:date of birth|dob)\s*[:|]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", joined, re.I)
    dob = dob_m.group(1) if dob_m else ""
    passport_m = re.search(r"passport\s*[:|]?\s*([A-Z0-9]{6,12})", joined, re.I)
    passport = passport_m.group(1) if passport_m else ""

    first_line = lines[0] if lines else "Candidate"
    if re.search(r"passport|date of birth|nationality|gender|phone|email", first_line, re.I):
        first_line = "Candidate"
    name = first_line
    if name.lower() in {"curriculum vitae", "europass curriculum vitae", "cv", "resume"} and len(lines) > 1:
        name = lines[1]
    parts = name.split()
    given = parts[0] if parts else "Candidate"
    family = " ".join(parts[1:]) if len(parts) > 1 else ""

    nationality = ""
    nat = re.search(r"nationality\s*[:|]?\s*([A-Za-z]+)", joined, re.I)
    if nat:
        nationality = nat.group(1)

    gender = ""
    gm = re.search(r"gender\s*[:|]?\s*(male|female|other)", joined, re.I)
    if gm:
        gender = gm.group(1).lower()

    summary = ""
    sm = re.search(r"(?:ABOUT ME|PROFILE|PERSONAL PROFILE|SUMMARY)\s*\n(.+?)(?=\n(?:EDUCATION|WORK EXPERIENCE|EMPLOYMENT|LANGUAGE|SKILLS)\b|$)", joined, re.I | re.S)
    if sm:
        summary = re.sub(r"\s+", " ", sm.group(1)).strip()

    skills = []
    km = re.search(r"(?:SKILLS|DIGITAL SKILLS)\s*\n(.+?)(?=\n(?:LANGUAGE|EDUCATION|WORK EXPERIENCE|CERTIFICATIONS|$))", joined, re.I | re.S)
    if km:
        skills = [x.strip(" •|,") for x in re.split(r"\||,|•", km.group(1)) if len(x.strip()) > 2]

    return {
        "given_name": given,
        "family_name": family,
        "email": email,
        "phone": phone,
        "date_of_birth": dob,
        "passport": passport,
        "nationality": nationality,
        "gender": gender,
        "address": "",
        "city": "",
        "postal_code": "",
        "country": "",
        "summary": summary,
        "education": [],
        "employment": [],
        "languages": [],
        "skills": skills,
        "custom_sections": [],
    }


def openrouter_extract(text: str) -> dict[str, Any]:
    """Extract structured CV data using OpenRouter's OpenAI-compatible API.

    The PDF itself is processed locally; only extracted text is sent to the
    configured OpenRouter model. If no API key is configured, use the local
    heuristic extractor instead.
    """
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return heuristic_extract(text)
    model = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
    schema_hint = {
        "given_name": "", "family_name": "", "email": "", "phone": "", "date_of_birth": "",
        "passport": "", "nationality": "", "gender": "", "address": "", "city": "",
        "postal_code": "", "country": "", "summary": "",
        "education": [{"institution":"", "degree":"", "start":"", "end":"", "city":"", "country":"", "field":"", "level":""}],
        "employment": [{"employer":"", "title":"", "start":"", "end":"", "current":False, "city":"", "country":"", "description":[]}],
        "languages": [{"name":"", "native":False, "listening":"", "reading":"", "writing":"", "spoken_production":"", "spoken_interaction":""}],
        "skills": [],
        "custom_sections": [{"title":"", "entries":[{"title":"", "start":"", "end":"", "description":[]}]}],
    }
    prompt = f"""Extract a CV into the JSON shape below. Use only facts present in the PDF text. Do not invent missing values. Dates should be YYYY-MM when possible; DOB should be YYYY-MM-DD. Preserve names and institutions.\n\nJSON shape:\n{json.dumps(schema_hint, ensure_ascii=False)}\n\nCV TEXT:\n{text[:60000]}"""
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv("APP_URL", "http://127.0.0.1:8000"),
            "X-Title": os.getenv("APP_NAME", "Europass PDF to XML Converter"),
        },
        json={
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a strict CV information extraction engine. Return only valid JSON matching the requested shape."},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=90,
    )
    r.raise_for_status()
    payload = r.json()
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"OpenRouter returned an unexpected response: {payload}") from exc
    data = json.loads(content)

    # Deterministic fields from the PDF win over LLM guesses. This is important
    # for identifiers and contact details where even a one-character error is bad.
    hard = heuristic_extract(text)
    for field in ("email", "phone", "date_of_birth", "passport"):
        if hard.get(field):
            data[field] = hard[field]
    return data


def clear_children(node, keep_tags: set[str] | None = None):
    keep_tags = keep_tags or set()
    for child in list(node):
        if child.tag not in keep_tags:
            node.remove(child)


def set_text(parent, tag, value: str, ns="ep", attrib=None):
    node = parent.find(q(ns, tag))
    if node is None:
        node = etree.SubElement(parent, q(ns, tag), attrib or {})
    node.text = value or ""
    return node


def replace_or_create(parent, tag, value: str, ns="ep"):
    node = parent.find(q(ns, tag))
    if node is None:
        node = etree.SubElement(parent, q(ns, tag))
    node.text = value or ""
    return node


def date_node(parent, tag: str, value: str):
    if not value:
        return
    d = etree.SubElement(parent, q("hr", tag)) if tag.startswith("hr:") else etree.SubElement(parent, q("ep", tag))
    etree.SubElement(d, q("hr", "FormattedDateTime")).text = value


def format_date(value: str) -> str:
    if not value:
        return ""
    m = re.search(r"(\d{4})[-/](\d{1,2})(?:[-/](\d{1,2}))?", value)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}" + (f"-{int(m.group(3)):02d}" if m.group(3) else "")
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", value)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return value


def make_xml(data: dict[str, Any]) -> bytes:
    root = etree.parse(str(TEMPLATE_PATH)).getroot()
    supplier = root.find(q("ep", "CandidateSupplier"))
    person = root.find(q("ep", "CandidatePerson"))
    profile = root.find(q("ep", "CandidateProfile"))
    supplier_name = supplier.find(q("ep", "PersonContact") + "/" + q("ep", "PersonName"))
    person_name = person.find(q("ep", "PersonName"))
    set_text(supplier_name, "GivenName", data.get("given_name", ""), "oa")
    set_text(supplier_name, "FamilyName", data.get("family_name", ""), "hr")
    set_text(person_name, "GivenName", data.get("given_name", ""), "oa")
    set_text(person_name, "FamilyName", data.get("family_name", ""), "hr")

    # Remove every old communication anywhere inside these two blocks.
    # The working Europass template can contain a communication inside
    # PersonContact as well as a direct child; removing only direct children
    # leaves stale/duplicate emails in the generated XML.
    for n in [supplier, person]:
        for c in list(n.iter(q("ep", "Communication"))):
            parent = c.getparent()
            if parent is not None:
                parent.remove(c)

    # Never keep a template DOB alongside the extracted DOB.
    for old_dob in list(person.iter(q("hr", "BirthDate"))):
        parent = old_dob.getparent()
        if parent is not None:
            parent.remove(old_dob)
    if data.get("email"):
        c = etree.SubElement(supplier, q("ep", "Communication")); etree.SubElement(c, q("ep", "ChannelCode")).text = "Email"; etree.SubElement(c, q("oa", "URI")).text = data["email"]
        c = etree.SubElement(person, q("ep", "Communication")); etree.SubElement(c, q("ep", "ChannelCode")).text = "Email"; etree.SubElement(c, q("oa", "URI")).text = data["email"]
    if data.get("phone"):
        c = etree.SubElement(person, q("ep", "Communication")); etree.SubElement(c, q("ep", "ChannelCode")).text = "Telephone"; etree.SubElement(c, q("ep", "UseCode")).text = "mobile"; etree.SubElement(c, q("ep", "CountryDialing")).text = "91"; etree.SubElement(c, q("oa", "DialNumber")).text = re.sub(r"\D", "", data["phone"])[-12:]; etree.SubElement(c, q("ep", "CountryCode")).text = "in"
    if data.get("address"):
        c = etree.SubElement(person, q("ep", "Communication")); etree.SubElement(c, q("ep", "UseCode")).text = "home"; a = etree.SubElement(c, q("ep", "Address"), {"type":"home"}); etree.SubElement(a, q("oa", "AddressLine")).text = data["address"]; 
        if data.get("city"): etree.SubElement(a, q("oa", "CityName")).text = data["city"]
        if data.get("country"): etree.SubElement(a, q("ep", "CountryCode")).text = data["country"].lower()[:2]
        if data.get("postal_code"): etree.SubElement(a, q("oa", "PostalCode")).text = data["postal_code"]

    for tag in ["NationalityCode", "GenderCode"]:
        old = person.find(q("ep", tag))
        if old is not None: person.remove(old)
    if data.get("nationality"):
        etree.SubElement(person, q("ep", "NationalityCode")).text = data["nationality"].lower()[:2] if len(data["nationality"]) > 2 else data["nationality"].lower()
    if data.get("date_of_birth"):
        etree.SubElement(person, q("hr", "BirthDate")).text = format_date(data["date_of_birth"])
    if data.get("gender"):
        etree.SubElement(person, q("ep", "GenderCode")).text = data["gender"].lower()

    # Do not leak template-specific language data into another person's CV.
    old_lang = person.find(q("ep", "PrimaryLanguageCode"))
    if old_lang is not None:
        person.remove(old_lang)
    native_lang = next((x.get("name") for x in (data.get("languages") or []) if x.get("native") and x.get("name")), "")
    if native_lang:
        etree.SubElement(person, q("ep", "PrimaryLanguageCode"), {"name": "FREE_TEXT"}).text = native_lang

    # Rebuild profile using the exact element vocabulary/order of the known-good template.
    clear_children(profile, {q("hr", "ID")})
    set_text(profile, "ExecutiveSummary", f"<p>{esc_html(data.get('summary',''))}</p>", "hr")
    if data.get("employment"):
        eh = etree.SubElement(profile, q("ep", "EmploymentHistory"))
        for job in data["employment"]:
            e = etree.SubElement(eh, q("ep", "EmployerHistory")); etree.SubElement(e, q("hr", "OrganizationName")).text = job.get("employer", "")
            p = etree.SubElement(e, q("ep", "PositionHistory")); etree.SubElement(p, q("ep", "PositionTitle"), {"typeCode":"FREETEXT"}).text = job.get("title", "")
            period = etree.SubElement(p, q("eures", "EmploymentPeriod")); sd = format_date(job.get("start", "")); ed = format_date(job.get("end", ""))
            if sd: x=etree.SubElement(period,q("eures","StartDate")); etree.SubElement(x,q("hr","FormattedDateTime")).text=sd
            if ed and not job.get("current"): x=etree.SubElement(period,q("eures","EndDate")); etree.SubElement(x,q("hr","FormattedDateTime")).text=ed
            etree.SubElement(period,q("hr","CurrentIndicator")).text="true" if job.get("current") else "false"
            desc = job.get("description", []) or ([job.get("description")] if isinstance(job.get("description"),str) else [])
            if desc: etree.SubElement(p,q("oa","Description")).text = p_html(desc)
            if job.get("city"): etree.SubElement(p,q("ep","City")).text=job["city"]
            if job.get("country"): etree.SubElement(p,q("ep","Country")).text=job["country"].lower()[:2]

    if data.get("education"):
        eh = etree.SubElement(profile, q("ep", "EducationHistory"))
        for ed in data["education"]:
            a=etree.SubElement(eh,q("ep","EducationOrganizationAttendance")); etree.SubElement(a,q("hr","OrganizationName")).text=ed.get("institution","")
            per=etree.SubElement(a,q("ep","AttendancePeriod")); sd=format_date(ed.get("start","")); en=format_date(ed.get("end",""))
            if sd: x=etree.SubElement(per,q("ep","StartDate")); etree.SubElement(x,q("hr","FormattedDateTime")).text=sd
            if en: x=etree.SubElement(per,q("ep","EndDate")); etree.SubElement(x,q("hr","FormattedDateTime")).text=en
            etree.SubElement(per,q("ep","Ongoing")).text="false"
            deg=etree.SubElement(a,q("ep","EducationDegree")); etree.SubElement(deg,q("hr","DegreeName")).text=ed.get("degree","")
            if ed.get("field"): etree.SubElement(deg,q("ep","OccupationalSkillsCovered")).text=f"<p>Field(s) of study: {esc_html(ed['field'])}.</p>"
            if ed.get("level"): etree.SubElement(a,q("ep","EducationLevelCode")).text=str(ed["level"])

    langs=data.get("languages",[])
    if langs:
        pq=etree.SubElement(profile,q("ep","PersonQualifications"))
        for lang in langs:
            if lang.get("native"): continue
            pc=etree.SubElement(pq,q("ep","PersonCompetency")); etree.SubElement(pc,q("ep","CompetencyID"),{"schemeName":"NORMAL"}).text=lang.get("name","")[:3].lower(); etree.SubElement(pc,q("hr","TaxonomyID")).text="language"
            mapping={"listening":"CEF-Understanding-Listening","reading":"CEF-Understanding-Reading","writing":"CEF-Writing-Production","spoken_production":"CEF-Speaking-Production","spoken_interaction":"CEF-Speaking-Interaction"}
            for k,t in mapping.items():
                if lang.get(k): d=etree.SubElement(pc,q("eures","CompetencyDimension")); etree.SubElement(d,q("hr","CompetencyDimensionTypeCode")).text=t; s=etree.SubElement(d,q("eures","Score")); etree.SubElement(s,q("hr","ScoreText")).text=lang[k]

    if data.get("skills"):
        sk=etree.SubElement(profile,q("ep","Skills"))
        for item in data["skills"]:
            if item: pc=etree.SubElement(sk,q("ep","PersonCompetency")); etree.SubElement(pc,q("hr","TaxonomyID")).text="Digital_Skill"; etree.SubElement(pc,q("hr","CompetencyName")).text=str(item)

    for section in data.get("custom_sections",[]) or []:
        if not section.get("title"): continue
        o=etree.SubElement(profile,q("ep","Others")); etree.SubElement(o,q("ep","Title")).text=section["title"]
        for entry in section.get("entries",[]) or []:
            if not entry.get("title") and not entry.get("description"): continue
            x=etree.SubElement(o,q("ep","Other")); etree.SubElement(x,q("ep","Title")).text=entry.get("title","")
            desc=entry.get("description",[]) or []
            if desc: etree.SubElement(x,q("ep","Description")).text=p_html(desc)

    # Keep only sections actually populated, in the same vocabulary as the working template.
    order = root.find(q("ep","RenderingInformation"))
    so = order.find(".//"+q("ep","SectionsOrder"))
    clear_children(so)
    for title in ["work-experience" if data.get("employment") else None, "education-training" if data.get("education") else None, "language" if data.get("languages") else None, "profile-skills" if data.get("skills") else None]:
        if title:
            s=etree.SubElement(so,q("ep","Section")); etree.SubElement(s,q("ep","Title")).text=title
    for section in data.get("custom_sections",[]) or []:
        mapping={"certifications":"certifications","projects":"projects","creative works":"creative-works","honours and awards":"honour-award","networks and memberships":"membership","conferences and seminars":"conference-seminar","volunteering":"volunteering","hobbies and interests":"hobbies-interests"}
        key=mapping.get(section.get("title","").lower())
        if key:
            s=etree.SubElement(so,q("ep","Section")); etree.SubElement(s,q("ep","Title")).text=key

    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)


def validate_xml(xml_bytes: bytes):
    root=etree.fromstring(xml_bytes)
    if etree.QName(root).localname != "Candidate": raise ValueError("Root element must be Candidate")
    did=root.find(q("hr","DocumentID"));
    if did is None or did.get("schemeVersionID") != "4.0": raise ValueError("Missing current Europass 4.0 DocumentID")
    return True


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "max_mb": MAX_MB})


@app.post("/api/convert")
async def convert(file: UploadFile = File(...), validate_importer: bool = Form(False)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF CV.")
    data = await file.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {MAX_MB} MB.")
    try:
        text = parse_pdf(data)
        if len(text.strip()) < 80:
            raise ValueError("Very little text was extracted. This may be a scanned/image-only PDF.")
        structured = openrouter_extract(text)
        xml = make_xml(structured)
        validate_xml(xml)
        return JSONResponse({"filename": Path(file.filename).stem + "_europass.xml", "text_chars": len(text), "data": structured, "xml": xml.decode("utf-8"), "validated": False})
    except requests.RequestException as e:
        raise HTTPException(502, f"AI extraction failed: {e}")
    except Exception as e:
        raise HTTPException(422, str(e))


@app.post("/api/validate-import")
async def validate_import(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {MAX_MB} MB.")
    # Explicit opt-in endpoint. This sends the uploaded XML to the Europass importer.
    s = requests.Session()
    headers = {"User-Agent": "Europass-PDF-XML-Converter/1.0"}
    editor = "https://europa.eu/europass/eportfolio/screen/cv-editor?lang=en"
    importer = "https://europa.eu/europass/eportfolio/api/eprofile/europass-cv"
    r = s.get(editor, headers=headers, timeout=30); r.raise_for_status()
    token = s.cookies.get("XSRF-TOKEN")
    if not token: raise HTTPException(502, "Europass validation session did not provide an XSRF token.")
    r2=s.get("https://europa.eu/europass/eportfolio/api/user-details",headers={**headers,"Cookie":s.cookies.get_dict().__str__()},timeout=30)
    token=s.cookies.get("XSRF-TOKEN", token)
    files={"file":(file.filename,content,"text/xml")}
    r3=s.post(importer,headers={**headers,"x-xsrf-token":token,"Accept":"application/json"},files=files,timeout=60)
    try: body=r3.json()
    except Exception: return JSONResponse({"status":r3.status_code,"raw":r3.text[:1000]})
    return JSONResponse({"status":r3.status_code,"accepted":not bool(body.get("errorCode")),"error":body.get("errorMessage"),"error_code":body.get("errorCode"),"profile_structure":body.get("profile",{}).get("preference",{}).get("profileStructure",[])})
