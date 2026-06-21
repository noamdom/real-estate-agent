# n8n Workflows

## property-intake.json

**Property Intake + Admin (Google Sheets + S3 + Vision)**

Receives a property submission via webhook, validates it through guardrails, runs AI analysis, optionally analyses uploaded images, and writes the full result back to Google Sheets.

---

## Node Tree

```
User Submit  (Webhook POST /property-intake)
  ├─► Respond to user submission trigger   → 200 {job_id, status: "received"}
  └─► Insert row                           → Google Sheets: append row (status: pending)
         │
         ▼
  Guardrails Input Check                   → POST :9001/check/input
         │
         ▼
  Input Valid?  ──── false ──────────────► Update row (rejected)
         │ true
         ▼
  LangGraph Analyze                        → POST :9000/analyze  (60 s timeout)
  ├─ error ──────────────────────────────► Update row (processing error)
  └─ main
         ▼
  Update row (LangGraph)                   → Google Sheets: intent, confidence, recommendation
         │
         ▼
  Has Image File?
  ├─ false ──────────────────────────────► Route Response
  └─ true
         ▼
  Prepare Image JSON                       → normalise binary slots (up to 5 files)
         │
         ▼
  Call Image Analyser                      → POST :9002/analyse  (multipart, up to 5 images)
         │
         ▼
  Update row (image data)                  → Google Sheets: image_urls, image_analysis
         │
         ▼
  Route Response                           → Code: merge LangGraph + image results
         │
         ▼
  Guardrails Output Check                  → POST :9001/check/output  (30 s timeout)
  ├─ error ──────────────────────────────► Update row (processing error)
  └─ main
         ▼
  Update row(s)                            → Google Sheets: status (done / flagged / rejected),
         │                                   full result, recommendation, confidence
         ▼
  No Operation, do nothing
```

---

## Prerequisites

### Google Sheets

- A Google Sheet must exist with the following columns (in order):

  | Column | Description |
  |--------|-------------|
  | `job_id` | Execution ID (match key for all updates) |
  | `submitted_at` | ISO timestamp of submission |
  | `status` | `pending` → `done` / `rejected` / `flagged` |
  | `property_type` | e.g. apartment, house |
  | `intent` | buy / sell / rent |
  | `location` | free text |
  | `condition` | property condition |
  | `price_asking` | asking price |
  | `size_sqm` | size in m² |
  | `num_rooms` | number of rooms |
  | `agent_name` | submitting agent |
  | `description` | free-text description |
  | `image_urls` | JSON array of S3 URLs |
  | `image_analysis` | Vision summary string |
  | `recommendation` | PASS / REJECT / REVIEW |
  | `confidence` | float 0–1 |
  | `result` | full formatted embassy recommendation |
  | `completed_at` | ISO timestamp of completion |

- The workflow targets document ID `1MTmu5zOxU9FkOcH9jWvM2-KfPcI3OzDmsIAjPZszX9o`, sheet ID `1408573048`. Update both values in every Google Sheets node after import if using a different sheet.

### n8n Credentials

- **Google Sheets OAuth2** — create a credential named `Google Sheets account` (or re-link the existing one after import). All five Google Sheets nodes use the same credential.

### Running Services

All three microservices must be reachable from the n8n Docker container via `host.docker.internal`:

| Service | Port | Endpoint |
|---------|------|----------|
| LangGraph Agent | 9000 | `POST /analyze` |
| Guardrails | 9001 | `POST /check/input`, `POST /check/output` |
| Image Analyser | 9002 | `POST /analyse` (multipart, up to 5 files) |

See the root `CLAUDE.md` for how to start the LangGraph and Guardrails services.

### AWS S3

- The Image Analyser service (`port 9002`) uploads files to S3 and returns pre-signed URLs. The S3 bucket and credentials are configured inside that service's `.env`, not inside n8n.

---

## Import

1. n8n UI → open any workflow → **⋯ menu** → **Import from file**
2. Select `property-intake.json`
3. Re-link the **Google Sheets account** credential in all Google Sheets nodes
4. Update the **Document ID** and **Sheet ID** if you are using a different spreadsheet
5. Activate the workflow
