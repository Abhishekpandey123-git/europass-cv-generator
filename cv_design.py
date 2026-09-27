"""
Design settings shared by the CLI, the web editor and every exporter.

A CV JSON may carry a "design" object; anything missing falls back to
DEFAULT_DESIGN (the calibrated Europass look).
"""

from __future__ import annotations

import copy
import re

FONTS = {
    "open-sans": {"label": "Open Sans (Europass)", "css": '"Open Sans", "Arial", sans-serif', "docx": "Open Sans"},
    "arial": {"label": "Arial", "css": '"Arial", "Liberation Sans", sans-serif', "docx": "Arial"},
    "calibri": {"label": "Calibri", "css": '"Calibri", "Carlito", "Arial", sans-serif', "docx": "Calibri"},
    "georgia": {"label": "Georgia", "css": '"Georgia", "DejaVu Serif", serif', "docx": "Georgia"},
}

SECTION_LABELS = {
    "about": "About me",
    "work_experience": "Work experience",
    "education": "Education and training",
    "languages": "Language skills",
    "digital_skills": "Digital skills",
    "driving_licence": "Driving licence",
}

DEFAULT_DESIGN = {
    "font": "open-sans",
    "accent": "#0c56a5",
    "text": "#565656",
    "scale": 1.0,            # 0.9 = smaller text, 1.1 = larger
    "margin_mm": 9,          # left / right page margin
    "photo_shape": "square", # square | rounded | circle
    "page_numbers": True,
    "section_order": list(SECTION_LABELS),
    "hidden_sections": [],
}

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalize(cv: dict) -> tuple[dict, list[str]]:
    """Return (design, visible section keys in order)."""
    design = copy.deepcopy(DEFAULT_DESIGN)
    design.update({k: v for k, v in (cv.get("design") or {}).items() if v is not None})

    if design["font"] not in FONTS:
        design["font"] = "open-sans"
    for key in ("accent", "text"):
        if not HEX.match(str(design[key])):
            design[key] = DEFAULT_DESIGN[key]
    design["scale"] = min(max(float(design["scale"]), 0.8), 1.25)
    design["margin_mm"] = min(max(float(design["margin_mm"]), 5), 25)

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
}}
@page {{ margin-left: {design['margin_mm']}mm; margin-right: {design['margin_mm']}mm; }}
"""
    if not design["page_numbers"]:
        css += "@page { @bottom-right { content: none; } }\n"
    return css
