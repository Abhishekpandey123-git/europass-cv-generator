# Sending student data from the website

The website sends a student's details to this service once, after the student
submits the form. The service turns them into a Europass CV, stores it for
staff to check and edit, and answers with the CV's id and links.

Interactive documentation with every field is at **`<service address>/docs`**.

## Security: call from the server, never from the browser

Every request needs the header `X-API-Key: <key>` (one of the keys in `API_KEYS`
in the service's `.env`). Send requests from the website's **server code**
(PHP, Node, Python...). If the key is put in browser JavaScript, anyone can
read it and send fake CVs.

## Endpoints

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/v1/cvs` | Send a student. Creates the CV (or updates it, see below). |
| `GET` | `/api/v1/cvs?external_id=STU-1` | Find the CV made for one of your ids. |
| `GET` | `/api/v1/cvs/{id}` | Status (`new`, `in_review`, `ready`) and data. |
| `GET` | `/api/v1/cvs/{id}/pdf` | Download. Also `docx`, `xml`, `json`, `png`, `html`. |

**Sending the same `external_id` again** (the student corrects the form):
if staff have not touched the CV yet it is updated; if they have, a new CV is
created and the old one is kept, so staff work is never overwritten.

**Status** tells the website when the CV is finished: staff set it to `ready`.
Poll `GET /api/v1/cvs/{id}` (for example once an hour) or check before showing
the student a download button.

## Request body

```json
{
  "external_id": "STU-2026-0142",
  "cv": { ...student data... }
}
```

`external_id` is your own id for the student or application (optional, but
recommended). A full example is in `samples/website_payload.json`.

### Student data (`cv`)

Only `personal.first_name` and `personal.last_name` (or `personal.name`) are
required. Everything else is optional, so send what the form collects.

| Field | Example | Notes |
|---|---|---|
| `personal.name` | `"RAHUL KUMAR SHARMA"` | Or `first_name` + `last_name`. Capitals are fixed. |
| `personal.date_of_birth` | `"21/05/2003"` | Any date format below. |
| `personal.gender` | `"M"` / `"Female"` | |
| `personal.nationality` | `"Indian"` or `["Indian","Italian"]` | |
| `personal.phone` | `"+91 98765 43210"` | Country code is detected from `+`. |
| `personal.email` | `"rahul@example.com"` | |
| `personal.address` | `{"street","city","pincode","country"}` | Or one string. |
| `personal.photo` | `"data:image/jpeg;base64,..."` | Base64 only, not a link. Max ~5 MB. |
| `about` | `"Computer science student…"` | Short summary. |
| `education[]` | see below | Most recent is placed first automatically. |
| `work_experience[]` | see below | |
| `languages.mother_tongues` | `"Hindi"` or `["Hindi","Urdu"]` | |
| `languages.other[]` | `{"language":"English","level":"C1"}` | Or separate `listening`, `reading`, `spoken_production`, `spoken_interaction`, `writing`. A1–C2 only. |
| `digital_skills` | `"Python, SQL, Excel"` or a list | |
| `driving_licence` | `"B"` or `["A","B"]` | |
| `additional_sections[]` | `{"title":"Projects","items":[{"heading","text"}]}` | Anything else. |

**Education entry:** `qualification` (or `title`), `university` / `school` /
`organisation`, `city`, `country`, `from`, `to`, `field`, `final_grade`,
`eqf_level` (1–8; if missing, Bachelor/B.Tech → 6, Master → 7, PhD → 8 are
filled in and flagged for staff to confirm).

**Work entry:** `position` (or `title`), `company` (or `employer`), `city`,
`country`, `from`, `to`, `description` (text; lines starting with `•` or `-`
become bullet points).

**Dates** may be `2021`, `2021-05`, `05/2021`, `21/05/2021`, `2021-05-21`,
`May 2021`. Leave `to` empty or send `"Present"` for ongoing.

Anything the service had to guess or could not read is returned in `warnings`
and shown to staff on the CV, so they know what to check.

## Response

```json
{
  "id": "6fdf2b62c32f",
  "external_id": "STU-2026-0142",
  "status": "new",
  "created": true,
  "warnings": ["Education 1: EQF level 6 was assumed from “B.Tech …”. Please confirm."],
  "edit_url": "https://cv.example.com/edit/6fdf2b62c32f",
  "downloads": { "pdf": "https://cv.example.com/api/v1/cvs/6fdf2b62c32f/pdf", "docx": "…", "xml": "…", "json": "…" }
}
```

`201` = created, `200` = updated. Errors come back as `{"error": "message"}`
with `400` (bad JSON), `401` (wrong key), `422` (data problem) or `503` (API
switched off).

The download links need the API key too, so fetch the file on your server and
pass it on to the student; don't link the student to them directly.

## Examples

### curl

```bash
curl -X POST https://cv.example.com/api/v1/cvs \
  -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" \
  --data @samples/website_payload.json
```

### PHP (e.g. WordPress form handler)

```php
$payload = [
  'external_id' => 'STU-' . $application_id,
  'cv' => [
    'personal' => [
      'name' => $_POST['full_name'],
      'date_of_birth' => $_POST['dob'],
      'nationality' => $_POST['nationality'],
      'phone' => $_POST['phone'],
      'email' => $_POST['email'],
    ],
    'education' => $education_rows,        // array of arrays, see fields above
    'languages' => ['mother_tongues' => $_POST['mother_tongue']],
  ],
];
$ch = curl_init('https://cv.example.com/api/v1/cvs');
curl_setopt_array($ch, [
  CURLOPT_POST => true,
  CURLOPT_RETURNTRANSFER => true,
  CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'X-API-Key: ' . getenv('CV_API_KEY')],
  CURLOPT_POSTFIELDS => json_encode($payload),
  CURLOPT_TIMEOUT => 30,
]);
$result = json_decode(curl_exec($ch), true);
$status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);
if ($status === 200 || $status === 201) {
  save_cv_id($application_id, $result['id']);   // keep it to check status / download later
}
```

### Node.js (server side)

```js
const res = await fetch("https://cv.example.com/api/v1/cvs", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-API-Key": process.env.CV_API_KEY },
  body: JSON.stringify({ external_id: `STU-${application.id}`, cv: studentData }),
});
const result = await res.json();
if (!res.ok) throw new Error(result.error);
```
