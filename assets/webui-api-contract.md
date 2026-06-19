# Web UI — API Contract

This document defines the full interface between the web frontend and the AI Property Triage backend. Any web UI (custom form, Open WebUI replacement, etc.) must conform to this contract to work with the n8n pipeline.

---

## Base URLs

| Environment | Base URL |
|-------------|----------|
| n8n test mode (workflow open in UI) | `http://localhost:5678/webhook-test` |
| n8n production (workflow published) | `http://localhost:5678/webhook` |

---

## 1 — Submit Property

**Endpoint:** `POST /property-intake`  
**Content-Type:** `multipart/form-data`

The main submission form. All text fields are sent as form fields; the image is optional.

### Form fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `property_type` | string | No | `apartment` \| `villa` \| `commercial` \| `land` |
| `location` | string | No | Free text — city, neighbourhood |
| `description` | string | **Yes** | Used by guardrails input check — must describe the property |
| `agent_name` | string | No | Submitting agent's name |
| `price_asking` | number | No | Asking price in NIS |
| `size_sqm` | number | No | Property size in sqm |
| `num_rooms` | integer | No | Number of rooms |
| `condition` | string | No | `new` \| `renovated` \| `good` \| `fair` \| `poor` |
| `intent` | string | No | `sell` \| `rent` — if omitted the pipeline infers it |
| `file` | file | No | Property image — JPEG or PNG, max 10 MB. Field name must be **`file`** |

### Immediate response (200)

```json
{
  "job_id": "string",
  "status": "received"
}
```

The submission is always acknowledged immediately. Processing continues asynchronously — poll endpoint 2 to track progress.

### Rejection flow

If the guardrails input check fails (spam, off-topic, empty), the pipeline marks the row as `rejected` with a reason. The immediate response is still `received` — poll to discover the rejection.

---

## 2 — Poll Submission Status

**Endpoint:** `GET /property-status?job_id=<job_id>`  
**Content-Type:** `application/json`

> ⚠️ **Status:** This endpoint is defined but not yet implemented. It requires a dedicated n8n status workflow (or a lightweight status microservice) that reads from the `fp-req-status` dataTable.

### Query parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `job_id` | Yes | The `job_id` returned by the submit endpoint |

### Response (200)

```json
{
  "job_id": "string",
  "status": "pending | done | rejected | flagged",
  "result": "string (markdown) | null",
  "propertyType": "string | null",
  "location": "string | null",
  "completedAt": "ISO 8601 datetime | null"
}
```

### Status values and UI behaviour

| Status | Meaning | Suggested UI |
|--------|---------|-------------|
| `pending` | Pipeline still running | Spinner / progress bar |
| `done` | Analysis complete, output passed guardrails | Render `result` as markdown |
| `rejected` | Guardrails input check failed | Show rejection message from `result` |
| `flagged` | Output guardrails detected a false claim | Show `result` with a warning banner |

### Recommended polling strategy

- Poll every **3 seconds** after submission
- Stop polling when status is `done`, `rejected`, or `flagged`
- Time out after **3 minutes** — show a "taking longer than expected" message
- On timeout, let the user check back with their `job_id`

---

## 3 — Submission payload flow (internal)

```
User (web UI)
  │  POST /property-intake   multipart/form-data
  │  fields: description, location, price_asking, ...
  │  file:   property image (optional)
  ▼
n8n Webhook
  │  Responds immediately → { job_id, status: "received" }
  │
  ├─ Guardrails input check  (POST :9001/check/input)
  │   pass=false ──→ row status = rejected
  │   pass=true  ──→ continue
  │
  ├─ LangGraph Analyze  (POST :9000/analyze)
  │
  ├─ Has Image File?
  │   yes ──→ Image Analyzer (POST :9002/analyse, multipart)
  │             └──→ result appended to recommendation
  │   no  ──→ skip
  │
  ├─ Guardrails output check  (POST :9001/check/output)
  │   pass=false ──→ row status = flagged
  │   pass=true  ──→ row status = done
  │
  └─ Row updated in fp-req-status dataTable

User (web UI) polls GET /property-status?job_id=xxx
  └─ reads final status + result
```

---

## 4 — Result format (`result` field)

When status is `done`, the `result` field is a markdown string with this structure:

```markdown
**Embassy Recommendation:** <buy / sell / hold / rent — with rationale>

**Market Context:** <comparable sales, market trend>

**Property Assessment:** <condition, size, location quality>

**Pricing Opinion:** <over / under / fairly priced, suggested range>

**Expected Timeline:** <estimated sell/rent duration>

**Image Analysis:** Room: <room_type> | Condition: <0.0–1.0>/1.0 | Confidence: <0–100>%
```

The `**Image Analysis:**` line is only present if an image was submitted.

---

## 5 — Error responses

| HTTP code | Cause | Action |
|-----------|-------|--------|
| 400 | Malformed request | Check field names and content-type |
| 404 | Webhook path wrong | Verify URL and n8n workflow is active |
| 500 | Service crashed | Check service logs on :9000 / :9001 / :9002 |
| Timeout | n8n not running | Ensure Docker n8n is running on port 5678 |

---

## 6 — Web UI checklist

Before building or integrating a web UI, verify:

- [ ] Form submits `multipart/form-data` (not `application/json`)
- [ ] Image file field is named exactly **`file`**
- [ ] `description` field is always populated (required by guardrails)
- [ ] UI stores the returned `job_id` for status polling
- [ ] UI polls `/property-status` and renders `result` as markdown
- [ ] UI handles all four status values (`pending`, `done`, `rejected`, `flagged`)
- [ ] UI shows a timeout fallback after 3 minutes

---

## 7 — Open items

| Item | Priority | Notes |
|------|----------|-------|
| Implement `GET /property-status` endpoint | High | Needs n8n status workflow or status microservice reading from `fp-req-status` dataTable |
| Decide web UI framework | High | Open WebUI can't submit multipart or poll — needs a custom form or replacement |
| Auth / API key on webhook | Medium | Currently the webhook is open — no authentication |
| File size validation | Medium | Validate on frontend before upload; n8n does not enforce size limits |
| Support multiple images per submission | Low | Currently one file per submission |
