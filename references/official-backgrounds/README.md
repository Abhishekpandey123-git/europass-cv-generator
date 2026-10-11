# Official Europass page backgrounds

One pair per template: the page decoration with no CV content on it, which is
what each layout draws behind the text. Reference material only - nothing at
runtime reads these. `tools/template_check.py` measures the rendered PDF
against the numbers in `../template-specs.md`, which were taken from these and
from the full official exports in `samples/reference/`.

| File | What it shows |
|---|---|
| `template1-page1.png` | grey band 0 - 76.88mm, full width, logo top right |
| `template1-page2.png` | blank: the band and logo are page 1 only |
| `template2-page1.png` | grey column 67.39mm wide, full page height, logo top right |
| `template2-page2.png` | the column narrows to 10.84mm |
| `template3-page1.png` | blue bracket frame, logo top right |
| `template3-page2.png` | the same frame, no logo |
| `template4-page1.png` | no decoration |
| `template4-page2.png` | no decoration |

Two things these made plain that a single page could not:

- **Template 2 changes shape after page 1.** The sidebar drops from 67.39mm to
  10.84mm and the text column moves from 70mm to 13mm. We were keeping the
  wide column on every page, which cost about 57mm of line length on every
  continuation page.
- **Template 4 has no page decoration at all**, so the blue rules in its
  background file are artefacts of however it was exported, not part of the
  design.

`template3-page1.png` was previously `templates/europass_page1.png` and was
painted as a page background whenever `design.frame` was on. That one image is
Template 3's frame and the Europass logo together, so it drew Template 3's
frame over whichever template was selected. It is kept here for reference, and
`assets/europass-logo.png` was extracted from it.
