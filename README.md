# Europass CV service

Turns student details sent by the client's website into Europass CVs, lets
staff check and edit them, and exports them in the official Europass layout
(page frame and logo, Open Sans, embedded Europass XML).

```
Client website ──POST /api/v1/cvs──▶ clean the data ──▶ stored CV (status: new)
                                                            │
Staff dashboard ◀── list, search, status ◀──────────────────┘
      │
      └─▶ editor: click-to-edit, sections, design ──▶ PDF · Word · Europass XML · PNG · HTML · JSON
```

Two ways a student's details get in:

1. **The website sends them** — automatic, see INTEGRATION.md.
2. **Staff upload a filled Student Information Form (.docx)** — dashboard →
   *Upload student form*. The blank form is `samples/Student_Information_Form.docx`.

## Setup (Windows, PowerShell)

WeasyPrint needs Pango from MSYS2 (`pacman -S mingw-w64-x86_64-pango` inside MSYS2).

```powershell
$env:WEASYPRINT_DLL_DIRECTORIES = "C:\msys64\mingw64\bin"
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # then edit .env
python app.py                 # opens http://localhost:8000
```

On Linux: `apt install libpango-1.0-0 libpangoft2-1.0-0`, then the same steps
with `source venv/bin/activate` and `cp`.

Putting it on a server: **[DEPLOY.md](DEPLOY.md)** (AWS, one script).
Sending data from the client's website: **[INTEGRATION.md](INTEGRATION.md)**.

## Settings (.env)

| Setting | Purpose |
|---|---|
| `ADMIN_PASSWORD` | Staff login. Empty = no login (only on your own computer). |
| `API_KEYS` | Keys the website sends in `X-API-Key`. Empty = website API off. |
| `PUBLIC_URL` | Address of the service, used in links returned to the website. |
| `HOST`, `PORT` | Where to listen (`HOST=0.0.0.0` on a server). |
| `DATA_DIR` | Where the database is stored (default `data/`). Back this folder up. |

Make an API key: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

## For the website developer

See **INTEGRATION.md** (fields, examples in curl / PHP / Node) and the live
docs at `/docs`. Try it locally:

```powershell
curl.exe -X POST http://localhost:8000/api/v1/cvs -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" --data "@samples/website_payload.json"
```

## For staff

- **Dashboard** (`/`): every CV with status *New from website*, *In review*,
  *Ready*. Search by name, email or website id. New submissions appear by
  themselves. "Things to check" lists what the service guessed.
- **Editor** (`/edit/<id>`): click text on the page to change it; click a block
  for all its fields (dates, CEFR levels, photo…); drag sections; Design tab for
  frame, colours, text size. Saves automatically. Set the status to *Ready*
  when done.
- **Downloads**: PDF (with Europass XML, can be imported into the Europass
  website), Word, PNG, HTML, XML, JSON.

## Files

| File | Purpose |
|---|---|
| `app.py` | Web server: website API, staff login, dashboard, editor, exports |
| `config.py` | Reads `.env` |
| `storage.py` | CV database (SQLite file in `data/`) |
| `normalize.py` | Cleans website data: dates, names, phone, CEFR, EQF |
| `generate.py` | CV rendering + PDF; also a command line tool for JSON files |
| `cv_design.py` | Design options, page frame and margins |
| `docx_export.py` | Word export |
| `europass_xml.py` | Europass XML embedded in each PDF |
| `europass_import.py` | Reads Europass PDF/XML files |
| `form_import.py` | Reads a filled Student Information Form (.docx) |
| `text_import.py` | Reads any other document (PDF, Word, text, sheets, images) |
| `form_import.py` | Reads a filled Student Information Form (.docx) |
| `extract.py` | Pulls the XML out of a Europass PDF |
| `templates/` | CV layout, styles, fonts, Europass page frame images |
| `static/` | Dashboard and editor |
| `tools/` | Calibration: `inspect_reference.py`, `compare.py` |
| `samples/` | `sample_cv.json`, `website_payload.json`, `Student_Information_Form.docx` |

## Command line (no server)

```powershell
python generate.py samples\sample_cv.json          # one CV -> output\
python generate.py folder_of_json\ -o output\      # many
python extract.py some_europass_cv.pdf             # get the XML out
```

## Notes

- The Word export has no page frame (it's meant for further editing).
- The dashed "Page 2" lines in the editor are approximate; *Preview PDF* shows
  the exact pages.
- Europass name and logo belong to the European Union; the frame images in
  `templates/` were supplied by the client.
