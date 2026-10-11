# Europass template geometry, measured from official exports

All figures from official Europass PDFs (confirmed by the `<Template>` element in
each file's embedded `attachment.xml`), Default colour, Medium font size, logo on
first page, page numbers off. A4, 209.9 x 296.69 mm.

Two independent methods, used to cross-check each other:

- **Text geometry** — `pdftotext -bbox-layout`, which reports word boxes in points
  straight from the PDF. Exact, no inference.
- **Fills and rules** — `pdftoppm -r 150` then NumPy colour masking. 1 px = 0.1693 mm.

**Font sizes are derived from box height, not ink height.** Measuring ink
under-reads, because a word's tallest glyph is rarely the font's full ascent. The
body text box is 13.6 pt and the body font is 9.7 pt, giving a constant
`box height = 1.402 x font-size` that converts every other box on the page.

| Box height | Font size | Used for |
|---|---|---|
| 13.6 pt | **9.7 pt** | body text |
| 14.9 pt | **10.6 pt** | section headings, entry titles |
| 21.7 pt | **15.5 pt** | candidate name |
| 11.2 pt | **8.0 pt** | language table |

These hold across Templates 3 and 4, so treat them as the shared type scale.

---

## Template 1 — full-width grey header band

Reference: `template_01__1_.pdf` (official export, 191 KB, carries the photo attachment).

| Element | Measured |
|---|---|
| Header band | `#f5f5f5`, full width, 0 -> **76.88 mm**, full bleed to both edges |
| Photo circle | **29.5 mm** diameter, left edge 5.08 mm, top 16.43 mm |
| Header text column | starts 40.8 mm |
| Name | first baseline 16.05 mm, 15.5 pt |
| Logo | 55.4 mm wide, 5.25 mm from right, 4.91 mm from top |
| Content | text left 10.0 mm, right edge 202.42 mm |
| Section rules | span 9.99 -> 204.89 mm; first section heading at 79.49 mm |
| Frame | none |

The photo diameter was taken from the arc's minimum x (5.08 mm at the equator,
y 31.16 mm), giving radius 14.73 mm. Wider spans in the raw scan are adjacent
text, not the circle.

## Cross-check

Both methods agree where they overlap, which is the reason to trust the numbers.

| Figure | Pixel method | Text-box method |
|---|---|---|
| Template 3 content left | 9.31 mm | 9.2 mm |
| Template 3 header text column | 52.32 mm | 52.5 mm |
| Template 3 first heading | 82.47 mm | 81.35 mm |
| Template 2 sidebar text left | 3.22 mm | 3.3 mm |

## Template 2 — grey left sidebar

Reference: `template.pdf` (byte-identical to `template_01.pdf`, md5 `ae879010`),
plus `official-backgrounds/template2-page{1,2}.png`.

**Template 2 is the only template whose geometry changes between pages**, and the
page-background pair is what made that visible. Page 1 carries the wide sidebar
that holds the photo, the name and the contact block; from page 2 on the sidebar
is a narrow grey stripe and the text column slides left into the space.

| Element | Page 1 | Page 2 onwards |
|---|---|---|
| Sidebar | `#f5f5f5`, **67.39 mm** wide, full 296.69 mm height, flush left | **10.84 mm** wide, same colour and height |
| Text column starts | **70.0 mm** | **13.0 mm** |
| Text column ends | 205.44 mm (right margin 4.56 mm) | same |

Page 1 only:

| Element | Measured |
|---|---|
| Sidebar text | left margin 3.3 mm, runs to 60.62 mm |
| Photo circle | 34.04 mm diameter, left edge 16.26 mm, top 6.77 mm |
| First baseline | 17.61 mm ("ABOUT ME") |
| Top margin | 6.11 mm |
| Frame | none — no coloured banding anywhere on the page |

The photo is centred in the sidebar: 16.26 + 34.04/2 = 33.3 mm, against a sidebar
centre of 33.7 mm.

### How the two states are built

The wide sidebar is a **float**, not a fixed or absolutely-positioned box. That
is the one construction that gives both states from a single rule: a float
occupies page 1, and the text that outlives it reflows to the full column width
on page 2 by itself, exactly as the official export does. It was probed in both
engines before being written, and both place page 1 at 70 mm and page 2 at
13.0 mm.

Three things went wrong on the way there, all of them worth knowing:

- **The float is 70 mm wide, not 57 mm.** A float is positioned inside the page
  area, so its width already excludes the page margin; subtracting the 13 mm
  margin again indented the text to 57 mm.
- **`position: relative; z-index: 1` on `.section` made every section rule span
  the full page width**, straight through the sidebar. Once the text genuinely
  starts at 70 mm the stacking context is unnecessary — removing it fixed the
  rules.
- **A negative `margin-top` on the float destroyed the sidebar's contents
  entirely** — photo, name and contacts all vanished. The 6.11 mm top offset is
  a per-template page margin (`TEMPLATE_TOP`) instead.

Two smaller ones: list markers escaped into the grey sidebar until
`list-style-position: inside`, and the logo was clipped off the right edge
because it was anchored to `--page-margin` (13 mm, the left margin) rather than
`--page-margin-right` (4.56 mm). Template 2 is the only template whose two
horizontal margins differ, so it is the only one where that mistake shows.

Note also that a *plain* block beside a float narrows to fit, but a block with
`overflow: hidden` or `display: flow-root` does not — it establishes a new
block formatting context and ignores the float. Several section styles are one
property away from breaking this layout.

## Template 3 — blue bracket frame

References: `real_cv_will_almost_all_feilds.pdf`, `Aarav_CV_Bari.pdf`,
`Bhavyansh_CV_Perugia_EM__1_.pdf`.

| Element | Measured |
|---|---|
| Frame colour | `#82acd9`, exact RGB (130, 172, 217) |
| Top / bottom bar | 5.93 mm tall, full width, **on every page** |
| Corner arms | 5.93 mm wide x 23.9 mm tall, all four corners |
| Content inset | left 9.2 mm, right edge 200.67 mm |
| Photo circle | 35.4 mm diameter, left edge 9.14 mm, top 22.86 mm |
| Header text column | starts 52.5 mm (photo column = 43 mm) |
| Name | first baseline 22.45 mm, 15.5 pt |
| Logo | 55.4 mm wide, 9.65 mm from right, 10.33 mm from top |
| Header block | ends ~76 mm; first section heading at 81.35 mm |
| Section rule | 1 px `#999`, full content width, 2.2 mm below heading, 5.1 mm above body |

The frame is a **bracket, not two bands**. At 10 mm down the page only two 5.93 mm
runs exist, one at each edge; by 34 mm there is no blue at all.

## Template 4 — right-aligned label column

Reference: `template_3.pdf`, plus `official-backgrounds/template4-page{1,2}.png`.

| Element | Measured |
|---|---|
| Label column | section labels right-aligned, ending at 53.2 mm |
| Body column | starts 57.6 mm, ends 204.97 mm |
| Content left | 6.98 mm (labels extend left as far as needed) |
| First baseline | 16.55 mm |
| Logo | 55.4 mm wide, 5.25 mm from right, 4.91 mm from top |
| Horizontal rules | 73.32, 120.9, 155.45 mm |
| Frame | none |

Example labels: "ABOUT ME" at y 70.79 mm, "EDUCATION AND TRAINING" at y 116.15 mm,
both right-aligned to 53.2 mm.

**Template 4 has no page decoration at all.** Both background pages are blank,
so the blue rules that appear in the exported background file are artefacts of
how it was exported, not part of the design. Nothing is painted behind the text.

### The label column only holds for the *first* child

The labels are grid children placed in column 1 and everything else in column 2.
That was written as `.section > h2 { grid-column: 1 }`-style positional rules,
and **education and work experience wrap their heading in an extra div**, so
their labels fell through to the content column and rendered at 203.02 mm
instead of 53.2 mm. The rule is now structural:

```css
body.template-4 .section > :first-child      { grid-column: 1; }
body.template-4 .section > :not(:first-child) { grid-column: 2; }
```

The old test did not catch it because it filtered candidate labels by width
(`< 60 mm`), which silently excluded the escaped ones. `template_check.py` now
selects labels by name from a fixed `LABEL_WORDS` set, so position can never
hide a label from the measurement. Verified by reintroducing the bug: the check
reports 203.02 mm against the 53.2 mm target.

---

## Build verification

`templates/europass_templates.css` is measured against these numbers on every
test run by `tools/template_check.py`: it renders the same CV in all four
templates with WeasyPrint and measures the output the same two ways the
references were measured. **30 of 30 measurements land within 0.7 mm**, most of
them exact. The 30 cover every band, sidebar, photo and logo position above,
plus a Template 2 page-2 block that asserts the sidebar has narrowed to
10.84 mm and the text column has moved to 13.0 mm.

Three renderer defects were found this way and fixed. None of them would have
been visible by reading the CSS:

- **The header band grew to 125.65 mm** instead of 76.88. `min-height` applies
  to the content box, so the padding stacked on top of it. Fixed with
  `box-sizing: border-box` and an explicit height.
- **The Template 3 frame filled the whole page** - 2.1 million blue pixels.
  WeasyPrint ignores a multi-value `background-size` and paints every gradient
  full-size. Replaced with six positioned bars inside the fixed frame element.
- **A fixed element is positioned from the page area, not the paper edge.**
  The frame and the Template 2 sidebar are pulled back out with negative
  offsets equal to the page margins.

And one renderer quirk worth remembering beyond this project:

- **WeasyPrint 70 stretches a grid item to fill its column even when the item
  has a definite width**, contrary to CSS Grid, where `stretch` applies only to
  `auto` widths. Confirmed with a two-case probe. Every fixed-size grid child
  needs an explicit `justify-self: start`; without it the photo rendered at the
  column width (35.73 mm) instead of its own 29.5 mm.

Each template also carries its own page margin, measured from the official
export: 10 mm, 13 mm, 9.2 mm and 6.98 mm. Template 4's label column only lines
up at 6.98 mm. Template 2 is the exception twice over: its 13 mm is the
*continuation*-page text position (page 1's sidebar and text are placed relative
to it), its right margin is a separate 4.56 mm, and its top margin is 6.11 mm
where the others are 10 mm.

## The Europass logo

Measured on page 1 of all four official exports. It is the same size
everywhere - 55.37 x 10.5mm - and only the offset from the paper's top-right
corner changes. The XML says `<Logo>FirstPage</Logo>`, and none of the
references repeat it on later pages.

| Template | From the right | From the top |
|---|---|---|
| 1 | 5.25 mm | 4.91 mm |
| 2 | 6.10 mm | 6.94 mm |
| 3 | 9.65 mm | 10.33 mm |
| 4 | 5.25 mm | 4.91 mm |

The asset is extracted from `references/official-backgrounds/template3-page1.png`,
which carries the official rendering on white, and un-premultiplied to
transparency so it sits correctly on Template 1 and 2's grey band as well as on
white. Aspect ratio 5.268 against the official 5.273.

Two WeasyPrint behaviours shape how it is placed, both confirmed with probes
rather than assumed:

- **An absolutely-positioned grid child is laid out as a grid item.** Every
  template makes `.header` a grid, so a logo inside it ignored `top`/`right`
  entirely and landed in the second grid row (measured 154.9mm from the right
  instead of 5.1mm).
- **A first child's negative top margin collapses through the body**, moving
  the containing block of any absolutely-positioned element with it. Templates
  1 and 2 pull `.header` up to the paper edge that way, which dragged the logo
  10mm too high and clipped it off the page.

Both are avoided by giving the logo its own zero-height `position: relative`
layer before the header. The CSS offsets are written as
`calc(<measured>mm - var(--page-margin))` so the official number stays visible
and a margin change cannot silently move the logo.

## Screen and print are different engines

The editor preview is drawn by the browser and the PDF by WeasyPrint, from the
same stylesheet. They disagree about `position: fixed`: WeasyPrint repeats a
fixed box on every page, which is how Template 3's frame and Template 2's
sidebar reach every sheet in the PDF, while a browser pins it to the viewport.
In the editor that left the frame hanging in place as the CV scrolled
underneath, with the blue bars cutting through the middle of the content.

On screen the frame is painted on the editor's own per-sheet `.page-frame`
elements instead, using gradients - a browser honours a multi-value
`background-size`, which WeasyPrint does not. `tools/editor_check.py` opens the
real editor in Chromium and fails if the frame colour ever lands outside a
sheet's bands and corner brackets.

Template 2's first sheet gets its own screen rule, because only page 1 carries
the wide column:

```css
body.template-2 .page-frame.first { background-size: 67.39mm 100%; }
```

## Page backgrounds

`official-backgrounds/` holds the eight official page decorations — one pair per
template, with no CV content on them. They are reference material; nothing at
runtime reads them. Their own README lists what each file shows. Two facts came
out of them that no single populated page could have shown: Template 2's change
of shape after page 1, and Template 4 having no decoration whatsoever.

## Known gaps

Geometry matches. Two **styling** differences against the official exports are
deliberate and still open, because either answer is defensible and they change
how every CV looks:

- **Template 1 headings.** The official export uses dark grey section headings
  with bullet dots, and UPPERCASE entry titles with the dates set inline. Ours
  uses the blue headings shared with the other templates.
- **Template 4 dates.** The official export puts dates right-aligned in the
  left label column, beneath the section label. Ours sets them inline with the
  entry title, as Templates 1-3 do.
