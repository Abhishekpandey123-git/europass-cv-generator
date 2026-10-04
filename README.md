# Europass PDF → XML Converter

A FastAPI website that converts CV PDFs into the current Europass Candidate XML structure.

## How it works
1. Extract PDF text with PyMuPDF.
2. Extract structured CV fields with Groq (optional; configured through `.env`).
3. Use the known-good current `Candidate` XML template rather than generating the Europass structure from scratch.
4. Generate and XML-validate the result.
5. Optionally send the generated XML to the official Europass importer for a live compliance check. This is opt-in because the XML contains personal data.

Europass currently supports importing Europass CV PDFs/XML in its online editor, and its current site was redesigned in June 2026. The current importer format is not the old SkillsPassport format; this project therefore preserves a known-good Candidate template.

## Run locally

```powershell
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
copy .env.example .env
# Add GROQ_API_KEY to .env for high-quality extraction
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## Without Groq
The site still runs using heuristic extraction, but complex CVs will be less accurate. For production, keep the AI extractor enabled and show the extracted data for user review before download.

## Security notes
- Do not log uploaded CVs.
- Delete temporary files after processing.
- Keep Groq API keys server-side only.
- Live Europass validation is explicitly opt-in because it sends the generated XML to europa.eu.
- Add authentication/rate limits before public deployment.
