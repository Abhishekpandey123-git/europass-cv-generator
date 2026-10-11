# Samples

| File | What it is |
|---|---|
| `sample_cv.json` | a synthetic CV in our JSON shape — safe to share, used in docs and demos |
| `website_payload.json` | an example POST body for the website ingest endpoint |
| `Student_Information_Form.docx` | the questionnaire the form importer maps from |
| `reference/` | **real student CVs — not in this package, and not in version control** |

## About `reference/`

Three of the five test harnesses read official Europass PDFs from
`samples/reference/`: `tools/xml_diff.py`, `fidelity.py` and
`tools/editor_check.py`, and `tools/template_check.py` renders against the
numbers taken from them.

Those PDFs are real students' records — names, dates of birth, addresses, phone
numbers. They are excluded from this package and from git on purpose. The tests
will report missing files until you put them back:

```
mkdir -p samples/reference
# copy the official Europass PDFs in, then:
./run_tests.sh
```

`xml_diff.py` and `fidelity.py` take whatever `*.pdf` they find in the folder,
so any official Europass exports work — each one carries its own
`attachment.xml`, which is what the tests diff against.

Three harnesses do name one file, `real_cv_will_almost_all_feilds.pdf`, because
they need a CV that fills every optional section: `template_check.py`,
`editor_check.py` and `e2e.py`. Substitute your own by editing the `REFERENCE`
line at the top of each.

These six are the set every number in `references/template-specs.md` came from:

```
real_cv_will_almost_all_feilds.pdf     Template 3, the most complete CV we have
template.pdf                           Template 2
template_01__1_.pdf                    Template 1
template_3.pdf                         Template 4
Aarav_CV_Bari.pdf                      Template 3
Bhavyansh_CV_Perugia_EM__1_.pdf        Template 3
```

The application itself does not need any of this. It is test material only.
