"""
Design settings shared by the CLI, the web editor and every exporter.

A CV JSON may carry a "design" object; anything missing falls back to
DEFAULT_DESIGN (the calibrated Europass look).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"

# Page geometry in mm, measured from the official exports' continuation pages:
# text starts 10.25mm down on Template 3 and runs to about 286mm. Each template
# sets its own left/right margin (TEMPLATE_MARGINS); the vertical margins are
# the same for all four, and already clear Template 3's 5.93mm frame bars.
PAGE_PLAIN = {"first_top": 10, "top": 10, "bottom": 12}
PAGE_FRAMED = PAGE_PLAIN          # kept so older saved designs still load

FONTS = {
    "open-sans": {"label": "Open Sans (Europass)", "css": '"Open Sans", "Arial", sans-serif', "docx": "Open Sans"},
    "arial": {"label": "Arial", "css": '"Arial", "Liberation Sans", sans-serif', "docx": "Arial"},
    "calibri": {"label": "Calibri", "css": '"Calibri", "Carlito", "Arial", sans-serif', "docx": "Calibri"},
    "georgia": {"label": "Georgia", "css": '"Georgia", "DejaVu Serif", serif', "docx": "Georgia"},
}

# Order and wording follow a genuine Europass export's <SectionsOrder>.
SECTION_LABELS = {
    "about": "About me",
    "education": "Education and training",
    "work_experience": "Work experience",
    "digital_skills": "Skills",
    "languages": "Language skills",
    "certifications": "Certifications",
    "conferences": "Conferences and seminars",
    "creative_works": "Creative works",
    "driving_licence": "Driving licence",
    "hobbies": "Hobbies and interests",
    "honours_awards": "Honours and awards",
    "networks": "Networks and memberships",
    "projects": "Projects",
    "publications": "Publications",
    "recommendations": "Recommendations",
    "social_political": "Social and political activities",
    "volunteering": "Volunteering",
}

# Sections whose entries share one shape, so one template branch renders them.
GENERIC_SECTIONS = ("certifications", "conferences", "creative_works", "hobbies",
                    "honours_awards", "networks", "projects", "social_political",
                    "volunteering")

def with_standard_sections(cv: dict) -> dict:
    """Typed sections are first-class now, so every CV already has each key.

    Kept as a no-op shim because the dashboard and the website importer still
    call it; the empty-section placeholders it used to add are no longer
    needed, and an empty section is never printed.
    """
    for key in SECTION_LABELS:
        if key in ("about", "education", "work_experience", "digital_skills",
                   "languages", "driving_licence"):
            continue
        cv.setdefault(key, [])
    return cv


TEMPLATE_NAMES = ("template1", "template2", "template3", "template4")

# Page margins measured from the official exports. Template 2 sits flush left
# because its sidebar runs to the page edge.
TEMPLATE_MARGINS = {"template1": 10.0, "template2": 13.0, "template3": 9.2, "template4": 6.98}

# Template 2's text column is not centred: measured 13mm on the left and
# 4.56mm on the right. The others are symmetric, so they fall back to
# TEMPLATE_MARGINS.
TEMPLATE_MARGIN_RIGHT = {"template2": 4.56}

DEFAULT_DESIGN = {
    "template": "template1",   # the four official Europass layouts
    "font": "open-sans",
    "accent": "#0c56a5",
    "text": "#565656",
    "scale": 1.0,            # 0.9 = smaller text, 1.1 = larger
    "margin_mm": None,       # left / right page margin; None = the template's own
    "photo_shape": "circle",  # circle | rounded | square
    "page_numbers": True,
    "frame": True,           # show the Europass logo (first page, as the official exports do)
    "section_order": list(SECTION_LABELS),
    "hidden_sections": [],
    # things staff can change while reviewing
    "section_titles": {},      # {"work_experience": "Professional experience"}
    "labels": {},              # {"email": "Email address"} - rename fixed field labels
    "languages_layout": "list",    # list | table  (Europass default is list)
    "line_height": 1.45,
    "section_gap": 4.0,        # mm above each section
    "entry_gap": 3.5,          # mm below each entry
    "block_align": {},         # {"about": "justify", "work_experience.0.description": "center"}
}

ALIGN = ("left", "center", "right", "justify")

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalize(cv: dict) -> tuple[dict, list[str]]:
    """Return (design, visible section keys in order)."""
    design = copy.deepcopy(DEFAULT_DESIGN)
    design.update({k: v for k, v in (cv.get("design") or {}).items() if v is not None})

    if design["font"] not in FONTS:
        design["font"] = "open-sans"
    if design.get("template") not in TEMPLATE_NAMES:
        design["template"] = "template1"
    if design.get("margin_mm") in (None, ""):
        design["margin_mm"] = TEMPLATE_MARGINS[design["template"]]
    for key in ("accent", "text"):
        if not HEX.match(str(design[key])):
            design[key] = DEFAULT_DESIGN[key]
    def number(key, low, high):
        """Keep a numeric option inside its range; fall back if it isn't a number."""
        try:
            design[key] = min(max(float(design[key]), low), high)
        except (TypeError, ValueError):
            design[key] = DEFAULT_DESIGN[key]

    number("scale", 0.8, 1.25)
    number("margin_mm", 5, 25)
    number("line_height", 1.0, 2.2)
    number("section_gap", 0, 15)
    number("entry_gap", 0, 15)
    if design["languages_layout"] not in ("table", "list"):
        design["languages_layout"] = "list"
    titles = design.get("section_titles")
    design["section_titles"] = {str(k): str(v).strip()[:60] for k, v in titles.items()
                                if str(v).strip()} if isinstance(titles, dict) else {}
    labels = design.get("labels")
    design["labels"] = {str(k): str(v).strip()[:40] for k, v in labels.items()
                        if str(v).strip()} if isinstance(labels, dict) else {}
    aligns = design.get("block_align")
    design["block_align"] = {str(k): v for k, v in aligns.items()
                             if v in ALIGN} if isinstance(aligns, dict) else {}

    custom_keys = [f"custom:{s['id']}" for s in cv.get("additional_sections") or [] if s.get("id")]
    valid = list(SECTION_LABELS) + custom_keys
    order = [k for k in design.get("section_order") or [] if k in valid]
    order += [k for k in valid if k not in order]
    design["section_order"] = order

    hidden = set(design.get("hidden_sections") or [])
    return design, [k for k in order if k not in hidden]


def ensure_ids(cv: dict) -> dict:
    """Custom sections need stable ids so their order survives edits."""
    used = {s.get("id") for s in cv.get("additional_sections") or []}
    n = 1
    for sec in cv.get("additional_sections") or []:
        if not sec.get("id"):
            while f"s{n}" in used:
                n += 1
            sec["id"] = f"s{n}"
            used.add(sec["id"])
    return cv


def mix_with_white(hex_color: str, amount: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    mix = lambda c: round(c + (255 - c) * amount)
    return f"#{mix(r):02x}{mix(g):02x}{mix(b):02x}"


# Template 2's text starts higher up the page than the rest: 6.11mm on its
# continuation pages, against ~10mm for the others.
TEMPLATE_TOP = {"template2": 6.11}


def page_geometry(design: dict) -> dict:
    top = TEMPLATE_TOP.get(design.get("template"))
    if top is None:
        return PAGE_PLAIN
    return {**PAGE_PLAIN, "first_top": top, "top": top}


def _margin_right(design: dict) -> float:
    """The right page margin, which only Template 2 sets separately."""
    if design.get("margin_mm") != TEMPLATE_MARGINS.get(design.get("template")):
        return design["margin_mm"]          # the person moved the margin slider
    return TEMPLATE_MARGIN_RIGHT.get(design.get("template"), design["margin_mm"])


def design_css(design: dict) -> str:
    s = design["scale"]
    radius = {"square": "0", "rounded": "3mm", "circle": "50%"}.get(design["photo_shape"], "0")
    css = f"""
:root {{
  --font-family: {FONTS[design['font']]['css']};
  --color-accent: {design['accent']};
  --color-text: {design['text']};
  --color-rule: {mix_with_white(design['accent'], 0.45)};
  --size-name: {14 * s:.2f}pt;
  --size-section: {10 * s:.2f}pt;
  --size-body: {9 * s:.2f}pt;
  --size-small: {8 * s:.2f}pt;
  --photo-radius: {radius};
  --page-margin: {design['margin_mm']}mm;
  --page-margin-right: {_margin_right(design)}mm;
  --page-bottom: {page_geometry(design)['bottom']}mm;
  --page-top: {page_geometry(design)['first_top']}mm;
  --line-height: {design['line_height']};
  --section-gap: {design['section_gap']}mm;
  --entry-gap: {design['entry_gap']}mm;
}}
@page {{ margin-left: {design['margin_mm']}mm; margin-right: {_margin_right(design)}mm; }}
"""
    g = page_geometry(design)
    css += f"@page {{ margin-top: {g['top']}mm; margin-bottom: {g['bottom']}mm; }}\n"
    css += f"@page :first {{ margin-top: {g['first_top']}mm; }}\n"
    # The old page-background PNG is gone. It was Template 3's bracket frame
    # plus the logo baked into one image, so with any template selected it was
    # drawn a second time - over Template 1, 2 and 4 it was simply the wrong
    # frame. Each template now draws its own in europass_templates.css, and the
    # logo is a real element placed at the position measured for that template.
    if not design["page_numbers"]:
        css += "@page { @bottom-right { content: none; } }\n"
    return css