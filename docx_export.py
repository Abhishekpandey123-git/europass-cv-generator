"""
Export a CV to Word (.docx) with the same structure and styling as the PDF.

Word files are meant for further editing, so the layout is close to the PDF
but not pixel-identical. Word uses the font installed on the viewer's computer;
if Open Sans is missing there, Word substitutes a similar font.
"""

from __future__ import annotations

import base64
import io
import re

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from cv_design import FONTS, SECTION_LABELS, ensure_ids, mix_with_white, normalize

GREY_DATE = RGBColor(0x75, 0x75, 0x75)
GREY_ORG = RGBColor(0x6B, 0x6B, 0x6B)
GREY_SEP = RGBColor(0xD3, 0xD3, 0xD3)


def rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color.lstrip("#").upper())


def fmt_date(value) -> str:
    if not value:
        return ""
    parts = str(value).split("-")
    return "/".join(reversed(parts))


def bottom_border(paragraph, hex_color: str, size: int = 6):
    ppr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", str(size)), ("w:space", "1"), ("w:color", hex_color.lstrip("#"))):
        bottom.set(qn(k), v)
    borders.append(bottom)
    ppr.append(borders)


def cell_border_bottom(cell, hex_color="C6C6C6"):
    tcpr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for side in ("top", "left", "right", "bottom"):
        el = OxmlElement(f"w:{side}")
        if side == "bottom":
            el.set(qn("w:val"), "single"); el.set(qn("w:sz"), "4"); el.set(qn("w:color"), hex_color)
        else:
            el.set(qn("w:val"), "nil")
        borders.append(el)
    tcpr.append(borders)


class Writer:
    def __init__(self, cv: dict):
        ensure_ids(cv)
        self.cv = cv
        self.design, self.sections = normalize(cv)
        s = self.design["scale"]
        self.size_body = Pt(9 * s)
        self.size_section = Pt(10 * s)
        self.size_name = Pt(14 * s)
        self.accent = rgb(self.design["accent"])
        self.text = rgb(self.design["text"])
        self.doc = Document()
        self.container = self.doc   # where para() adds paragraphs (the page, or a table cell)
        self._setup()

    # -------------------------------------------------------------- setup ---
    def _setup(self):
        sec = self.doc.sections[0]
        sec.page_width, sec.page_height = Mm(210), Mm(297)
        margin = Mm(self.design["margin_mm"])
        sec.left_margin = sec.right_margin = margin
        sec.top_margin, sec.bottom_margin = Mm(10), Mm(12)

        font_name = FONTS[self.design["font"]]["docx"]
        normal = self.doc.styles["Normal"]
        normal.font.name = font_name
        normal.font.size = self.size_body
        normal.font.color.rgb = self.text
        rpr = normal.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts"); rpr.append(rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rfonts.set(qn(attr), font_name)
        pf = normal.paragraph_format
        pf.space_before, pf.space_after, pf.line_spacing = Pt(0), Pt(1.5), 1.1

        if self.design["page_numbers"]:
            p = sec.footer.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            self._field(p, "PAGE"); r = p.add_run(" / "); r.font.size = Pt(7.5)
            self._field(p, "NUMPAGES")

    def _field(self, paragraph, code):
        run = paragraph.add_run()
        run.font.size = Pt(7.5)
        run.font.color.rgb = GREY_DATE
        for tag, text in (("begin", None), (None, code), ("end", None)):
            if tag:
                el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), tag)
            else:
                el = OxmlElement("w:instrText"); el.set(qn("xml:space"), "preserve"); el.text = text
            run._r.append(el)

    # ------------------------------------------------------------ helpers ---
    def para(self, space_after=1.5):
        p = self.container.add_paragraph()
        p.paragraph_format.space_after = Pt(space_after)
        return p

    def run(self, p, text, bold=False, italic=False, color=None, size=None, semibold=False):
        r = p.add_run(text)
        r.bold = bold or semibold
        r.italic = italic
        if color is not None:
            r.font.color.rgb = color
        if size is not None:
            r.font.size = size
        return r

    def labelled(self, pairs, p=None):
        p = p or self.para()
        for i, (label, value) in enumerate(pairs):
            if i:
                self.run(p, "  |  ", color=GREY_SEP)
            self.run(p, f"{label}: ", bold=True)
            self.run(p, str(value))
        return p

    def section_title(self, title):
        p = self.para(space_after=4)
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.keep_with_next = True
        self.run(p, title.upper(), bold=True, color=self.accent, size=self.size_section)
        bottom_border(p, mix_with_white(self.design["accent"], 0.45), size=6)

    def dates(self, item):
        p = self.para(space_after=0.5)
        p.paragraph_format.keep_with_next = True
        end = fmt_date(item.get("end")) if item.get("end") else "Current"
        self.run(p, f"[ {fmt_date(item.get('start'))} – {end} ]", color=GREY_DATE)

    def entry_head(self, item, title_key, org_key):
        self.dates(item)
        p = self.para(space_after=0.5); p.paragraph_format.keep_with_next = True
        self.run(p, item.get(title_key, ""), bold=True, color=self.accent)
        if item.get(org_key):
            p = self.para(space_after=0.5); p.paragraph_format.keep_with_next = True
            self.run(p, item[org_key], bold=True, italic=True, color=GREY_ORG)
        loc = [(k, item[f]) for k, f in (("City", "city"), ("Country", "country")) if item.get(f)]
        if loc:
            self.labelled(loc)

    def description(self, desc):
        if not desc:
            return
        if isinstance(desc, str):
            for line in desc.split("\n"):
                if line.strip():
                    self.run(self.para(), line.strip())
        else:
            for item in desc:
                p = self.doc.add_paragraph(style="List Bullet")
                p.paragraph_format.space_after = Pt(1)
                self.run(p, item)
        self.para(space_after=3)

    # ----------------------------------------------------------- sections ---
    def header(self):
        p = self.cv.get("personal", {})
        photo = p.get("photo")
        photo_data = None
        if photo and str(photo).startswith("data:image"):
            try:
                photo_data = base64.b64decode(photo.split(",", 1)[1])
            except Exception:
                photo_data = None

        cell = None
        if photo_data:
            # photo beside the details, as in the PDF: a borderless two-column table
            usable = Mm(210 - 2 * self.design["margin_mm"])
            table = self.doc.add_table(rows=1, cols=2)
            table.autofit = False
            widths = (Mm(32), usable - Mm(32))
            for col, w in zip(table.columns, widths):
                col.width = w
            for c, w in zip(table.rows[0].cells, widths):
                c.width = w
            try:
                table.rows[0].cells[0].paragraphs[0].add_run().add_picture(io.BytesIO(photo_data), width=Mm(28))
            except Exception:
                pass
            cell = table.rows[0].cells[1]
            self.container = cell

        name = self.para(space_after=3)
        self.run(name, f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                 bold=True, color=self.accent, size=self.size_name)

        line1 = []
        if p.get("date_of_birth"):
            line1.append(("Date of birth", fmt_date(p["date_of_birth"])))
        if p.get("nationalities"):
            line1.append(("Nationality", ", ".join(n.get("name", "") for n in p["nationalities"])))
        if p.get("gender"):
            line1.append(("Gender", p["gender"]))
        if line1:
            self.labelled(line1)

        line2 = []
        ph = p.get("phone") or {}
        if ph.get("number"):
            num = (f"(+{ph['country_dialing']}) " if ph.get("country_dialing") else "") + ph["number"]
            line2.append(("Phone number", num + (f" ({ph['type']})" if ph.get("type") else "")))
        if p.get("email"):
            line2.append(("Email address", p["email"]))
        if p.get("website"):
            line2.append(("Website", p["website"]))
        if line2:
            self.labelled(line2)

        a = p.get("address") or {}
        if a.get("street") or a.get("city") or a.get("country"):
            city = f"{a.get('postal_code', '')} {a.get('city', '')}".strip()
            value = ", ".join(x for x in (a.get("street"), city, a.get("country")) if x)
            last = self.labelled([("Address", value + (f" ({a['type']})" if a.get("type") else ""))])
        else:
            last = self.para()

        if cell is not None:
            first = cell.paragraphs[0]           # the empty paragraph every new cell starts with
            if not first.text and len(cell.paragraphs) > 1:
                first._element.getparent().remove(first._element)
            self.container = self.doc
            last = self.para(space_after=2)
        bottom_border(last, "C6C6C6", size=4)

    def about(self):
        if self.cv.get("about"):
            self.section_title(SECTION_LABELS["about"])
            self.run(self.para(), self.cv["about"])

    def work_experience(self):
        jobs = self.cv.get("work_experience") or []
        if jobs:
            self.section_title(SECTION_LABELS["work_experience"])
            for job in jobs:
                self.entry_head(job, "title", "employer")
                self.description(job.get("description"))

    def education(self):
        eds = self.cv.get("education") or []
        if eds:
            self.section_title(SECTION_LABELS["education"])
            for ed in eds:
                self.entry_head(ed, "title", "organisation")
                for label, key in (("Field(s) of study", "field"), ("Final grade", "final_grade"), ("Thesis", "thesis")):
                    if ed.get(key):
                        self.labelled([(label, ed[key])])
                if ed.get("eqf_level"):
                    self.labelled([("Level in EQF", f"EQF level {ed['eqf_level']}")])
                if ed.get("description"):
                    self.description(ed["description"])
                else:
                    self.para(space_after=3)

    def languages(self):
        langs = self.cv.get("languages") or {}
        if not (langs.get("mother_tongues") or langs.get("other")):
            return
        self.section_title(SECTION_LABELS["languages"])
        if langs.get("mother_tongues"):
            self.labelled([("Mother tongue(s)", ", ".join(m.get("name", "") for m in langs["mother_tongues"]))])
        other = langs.get("other") or []
        if not other:
            return
        self.labelled([("Other language(s)", "")])
        table = self.doc.add_table(rows=2 + len(other), cols=6)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        widths = [Mm(36)] + [Mm(30.4)] * 5
        heads = [("", 1), ("UNDERSTANDING", 2), ("SPEAKING", 2), ("WRITING", 1)]
        col = 0
        for text, span in heads:
            cell = table.cell(0, col)
            if span > 1:
                cell = cell.merge(table.cell(0, col + span - 1))
            self._cell(cell, text, bold=True, color=self.accent)
            col += span
        for i, text in enumerate(["", "Listening", "Reading", "Spoken production", "Spoken interaction", ""]):
            self._cell(table.cell(1, i), text, bold=bool(text))
        keys = ["listening", "reading", "spoken_production", "spoken_interaction", "writing"]
        for r, lang in enumerate(other, start=2):
            self._cell(table.cell(r, 0), lang.get("name", ""), bold=True, color=self.accent, left=True)
            for c, key in enumerate(keys, start=1):
                self._cell(table.cell(r, c), lang.get(key, ""))
        for row in table.rows:
            for i, cell in enumerate(row.cells):
                cell.width = widths[i]
                cell_border_bottom(cell)
        p = self.para(space_after=3)
        p.paragraph_format.space_before = Pt(3)
        self.run(p, "Levels: A1 and A2: Basic user; B1 and B2: Independent user; C1 and C2: Proficient user",
                 italic=True, color=GREY_DATE, size=Pt(7.5))

    def _cell(self, cell, text, bold=False, color=None, left=False):
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT if left else WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(2)
        if text:
            self.run(p, text, bold=bold, color=color, size=Pt(8 * self.design["scale"]))

    def digital_skills(self):
        skills = self.cv.get("digital_skills") or []
        if skills:
            self.section_title(SECTION_LABELS["digital_skills"])
            p = self.para()
            for i, s in enumerate(skills):
                if i:
                    self.run(p, " | ", color=GREY_SEP)
                self.run(p, s)

    def driving_licence(self):
        lic = self.cv.get("driving_licence") or []
        if lic:
            self.section_title(SECTION_LABELS["driving_licence"])
            self.labelled([("Driving licence", ", ".join(lic))])

    def custom(self, sec_id):
        for sec in self.cv.get("additional_sections") or []:
            if sec.get("id") == sec_id and sec.get("items"):
                self.section_title(sec.get("title", ""))
                for item in sec["items"]:
                    if item.get("heading"):
                        p = self.para(space_after=0.5)
                        self.run(p, item["heading"], bold=True, color=self.accent)
                    self.description(item.get("text"))

    # --------------------------------------------------------------- main ---
    def build(self) -> bytes:
        self.header()
        for key in self.sections:
            if key.startswith("custom:"):
                self.custom(key.split(":", 1)[1])
            else:
                getattr(self, key)()
        out = io.BytesIO()
        self.doc.save(out)
        return out.getvalue()


def build_docx(cv: dict) -> bytes:
    return Writer(cv).build()
