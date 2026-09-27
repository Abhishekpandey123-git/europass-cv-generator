# Europass CV Generator

Generates Europass-style CV PDFs from structured JSON, in bulk, without using the
Europass website. Each PDF carries the Europass XML as an embedded attachment
(`attachment.xml`), the same mechanism the official editor uses, so the files
can be re-imported into europass.europa.eu.

## Setup

```bash
pip install -r requirements.txt
```

WeasyPrint needs Pango on the system (`apt install libpango-1.0-0 libpangoft2-1.0-0`
on Debian/Ubuntu; see WeasyPrint docs for Windows/macOS). Docker is the easiest
way to deploy it on a server.

## Web editor

```bash
python app.py        # opens http://localhost:8000 in your browser
```

- **Open:** File → Open, or drag a file onto the window. Accepts JSON backups,
  Europass PDFs (official or from this tool) and Europass XML.
- **Edit on the page:** click any text and type. In a bullet list, Enter adds a
  bullet and Backspace on an empty bullet removes it.
- **Edit details:** click a block (a job, the language table, the header) and the
  right panel shows every field: dates, locations, CEFR levels, photo.
- **Sections:** drag to reorder, eye icon to hide, + to add an entry, or add a
  custom section.
- **Design:** font, accent colour, text size, margins, photo shape, page
  numbers. "Reset to the Europass look" restores the calibrated defaults.
- **Undo/redo:** Ctrl+Z / Ctrl+Y. Work is saved automatically in the browser.
- **Download:** PDF (with Europass XML inside), Word, PNG image, HTML page,
  Europass XML, or a JSON backup (Ctrl+S).

The dashed "Page 2" lines on the canvas are approximate; use Preview PDF to see
the exact page breaks. For the Word file to look right, Open Sans should be
installed on the computer that opens it (the fonts are in `templates/fonts`).

## Command line

```bash
python generate.py samples/sample_cv.json            # one CV -> output/
python generate.py candidates/ -o output/            # batch: every .json in a folder
python generate.py cv.json --logo assets/logo.png    # optional logo, top-right
python generate.py cv.json --html                    # also save HTML (for CSS work)
python extract.py some_europass_cv.pdf               # pull embedded XML out of a PDF
```

## Project layout

| File | Purpose |
|---|---|
| `app.py` | Web editor server (FastAPI): import, live preview, exports |
| `static/` | Editor page, styles and logic (`index.html`, `editor.css`, `editor.js`) |
| `cv_design.py` | Design options (font, colours, size, section order) shared by all outputs |
| `docx_export.py` | Word (.docx) export |
| `europass_import.py` | Europass XML / PDF → JSON import |
| `generate.py` | CLI: JSON → HTML → PDF → embed XML. Validates input, batch-safe |
| `europass_xml.py` | JSON → Europass Candidate XML. All tag mapping in one place |
| `templates/europass_cv.html` | Jinja2 layout (sections in Europass order) |
| `templates/europass_cv.css` | All visual tokens: font, colours, sizes, margins |
| `extract.py` | Extract the XML from any Europass PDF |
| `tools/inspect_reference.py` | Read fonts/sizes/colours/margins from a real Europass PDF |
| `tools/compare.py` | Pixel diff between an official Europass PDF and ours |
| `samples/sample_cv.json` | Reference input showing every supported field |

## Input format

See `samples/sample_cv.json`. Notes:
- Dates: `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. `"end": null` means *Current*.
- `description` can be a string or a list (rendered as bullets).
- Country codes: ISO 3166 alpha-2 (`it`); language codes: ISO 639-2 (`eng`).
- CEFR levels are validated (A1–C2).
- `personal.photo` is a path relative to the JSON file.

## Calibrating to match your Europass template exactly (do this once)

The template is built to the Europass layout, but Europass offers several
designs and changes them occasionally, so lock it to the one your client uses:

1. On europass.europa.eu, create a CV with the **same data** as
   `samples/sample_cv.json`, pick the client's template, download the PDF as
   `reference.pdf`.
2. `python tools/inspect_reference.py reference.pdf` and copy the font name,
   sizes, colours and margins into the tokens at the top of
   `templates/europass_cv.css` (install that font on the server if needed).
3. `python generate.py samples/sample_cv.json`
4. `python tools/compare.py reference.pdf output/Europass_CV_Marco_Rossi.pdf`
   and adjust CSS until the red areas in `diff/` disappear.
5. `python extract.py reference.pdf -o reference.xml`, compare it with the XML
   in our PDF, and adjust tag names in `europass_xml.py` if they differ.
6. Import our generated PDF into the Europass editor and confirm every field
   lands in the right place. Keep that PDF as a regression test.

## Branding note

The Europass name and logo belong to the European Union. No logo is bundled;
`--logo` accepts any image. Check the Europass brand usage rules before placing
the official logo on generated documents.

## Next steps

- **Web form / API:** wrap `generate()` in a FastAPI endpoint.
- **Old CVs in Word/PDF:** use an LLM (e.g. the Claude API) to extract them
  into this JSON format, with a human review step before generating.
- **Existing Europass CVs:** `extract.py` gives the XML; add an XML → JSON
  mapper to update and re-render them.
