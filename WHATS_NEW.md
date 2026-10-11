# What changed, and why

The complaint this release answers, in your staff's words: *"most of them fail
in Europass partially — Europass loads half of the data fields but some get
missed and some are filled in wrong question."*

That was reproducible, and it is now fixed and guarded by tests.

## The cause

A structural diff against the European Commission's own exports (the
`attachment.xml` embedded in every Europass PDF) showed that on a fully
populated CV we reproduced **124 of 234 element paths**. Just over half.

Two separate faults:

1. **The importer modelled only ten top-level keys.** Certifications,
   conferences, creative works, projects, publications, recommendations,
   social and political activities, volunteering, networks, hobbies, honours,
   driving licences and the profile photo had nowhere to go. They were
   flattened into one generic `additional_sections` list of
   `{heading, text}` pairs — a shape that cannot hold a date, a location, a
   link, or a publication's journal and volume.

2. **The writer matched those pairs back to Europass containers by title
   prefix** and wrote only `<Title>` and `<Description>`. Everything else was
   dropped on export. Europass then showed a half-filled CV with values under
   the wrong headings, exactly as reported.

## The fix

`sections.py` defines each optional section as its own type, with the fields
Europass actually stores, and reads and writes them in the element order a
genuine export uses. Every field name came out of your real CVs, not from
guesswork.

Two containers are easy to confuse, and were:

- `Certifications` is **honours and awards** (`CertificationName`,
  `IssuingAuthority`, `FirstIssuedDate`).
- `CourseCertifications` is what the editor calls **Certifications** (`Title`,
  `IssuingOrganisation`, `FirstIssuedDate`, `ModeOfLearning`, `Link`).

Also restored, all of which were being lost:

- the **profile photo**, as `eures:Attachment` — so our own PDF is
  re-importable and the picture survives
- **driving licences**, as `eures:Licenses`
- the **work permit**, as `Visa/IssuingCountryCode`
- **social-media usernames** (`MediaUsername`), and the channel codes Europass
  actually expects: `Social Media` with a space, `InstantMessage` singular
- **every** phone, email and website, not just the first of each
- **skill group titles** ("social skill", "other skills")
- the full **section order**, sixteen entries rather than four
- employer **department, link, industry code, email and website**; education
  **website, credits, credit type and field of study**
- gender as `ep:GenderCode`, not `hr:GenderCode`

Europass writes some things two ways, and both are now reproduced faithfully:
newer exports use `FieldOfStudy/MainFieldOfStudy/ProgramConcentration` with an
ISCED code, older ones use `OccupationalSkillsCovered` with free text. It also
emits deliberately empty placeholder elements, and an address `Communication`
for an employer even when the address is blank. Omitting either loses an
element path on re-import.

One pre-existing bug surfaced on the way: Europass tags a three-letter
language code with `name="NORMAL"`, and only `FREE_TEXT` was handled, so the
mother tongue was being imported as the literal string "NORMAL".

## The four templates

All four official layouts are now reproduced from measurements taken off real
Europass exports, in one stylesheet shared by the editor preview and the PDF
renderer — so the preview cannot drift from the output. See
`references/template-specs.md` for every number and its source.

### What the blank page backgrounds showed

The eight official page decorations — each template's page 1 and page 2 with no
CV content on them — are now in `references/official-backgrounds/`. Comparing
against them found two layout faults that a populated page had hidden:

- **Template 2 changes shape after page 1.** The grey sidebar drops from
  67.39 mm to 10.84 mm and the text column moves from 70 mm to 13 mm. We were
  keeping the wide column on every page, so every continuation page lost about
  57 mm of line length — on a long CV that is pages of wasted paper. The
  sidebar is now a float, which gives both states from one rule, and its
  contents (photo, name, ID block, contacts) sit inside it as the official does.
- **Template 4's section labels were escaping into the content column.**
  Education and work experience wrap their heading in an extra div, so the
  positional CSS rule missed them and they rendered at 203 mm instead of
  53.2 mm, right-aligned against the wrong edge. The rule is now structural
  (first child to column 1, everything else to column 2).

The second one had been passing the test suite: the check filtered candidate
labels by width, which silently excluded exactly the broken ones.
`tools/template_check.py` now picks labels by name, and the suite is up from 28
to **30 measurements** — the two new ones assert Template 2's page-2 geometry.

### Two styling choices still open

Geometry matches the official exports. Two **styling** differences remain, and
both need a decision because they change how every CV in that template looks:

- **Template 1** officially uses dark grey headings with bullet dots and
  UPPERCASE entry titles with inline dates; ours uses the blue headings shared
  with the other templates.
- **Template 4** officially puts dates right-aligned in the left label column;
  ours sets them inline with the entry title.

## Extraction stays deterministic

No AI, anywhere. Three tiers, chosen by what the file actually is:

1. **Official Europass PDF** — the embedded `attachment.xml` is read directly.
   Exact; the data was written by Europass itself. This is also the revision
   path: version two of a student's CV re-enters here with nothing lost.
2. **Your Student Information Form** — a fixed mapping, since the questionnaire's
   structure is known.
3. **Any other CV** — labelled fields, date ranges and recognised headings.

## The legacy page frame is gone

`design.frame` used to paint `europass_page1.png` as a page background. That
image is Template 3's bracket frame and the Europass logo baked into one
picture, and it was on by default - so choosing Template 3 drew the frame
twice, slightly offset, and choosing Template 1, 2 or 4 stamped Template 3's
frame over a layout that should not have one. It also forced page margins
(25/17/16mm) that match no official export.

Each template now draws its own frame, the logo is a real element positioned
per template, and `design.frame` means "show the Europass logo" - which is what
the official `<Logo>FirstPage</Logo>` setting controls.

## The preview matches the PDF

The editor preview and the PDF come from different engines, and they disagree
about `position: fixed`. The frame reached every page correctly in the PDF
while, on screen, it stayed pinned to the viewport and the blue bars cut
through the middle of the CV as it scrolled. Every PDF measurement passed while
the preview was visibly wrong, so there is now a fifth check that opens the
real editor in a browser.

## Tests

`./run_tests.sh` runs all five and gates a deploy:

| Check | What it proves |
|---|---|
| `tools/xml_diff.py` | our XML reproduces **6/6** official files' element paths |
| `fidelity.py` | **6/6** CVs survive import → export → import, 53 fields each |
| `tools/template_check.py` | **30/30** page and logo measurements within 0.7 mm of the real thing |
| `tools/e2e.py` | upload, edit, save, export all four formats, re-import |
| `tools/editor_check.py` | the on-screen preview: frame colour never lands on content |

The reference CVs live in `samples/reference/`. They are real student records:
keep them out of version control.
