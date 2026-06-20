# Handoff — Next Steps

## Current State (as of session end)

### Services built and working

| Service | Port | File | LLM |
|---------|------|------|-----|
| LangGraph Agent | 9000 | `services/langgraph-agent/` | `gpt-4.1-nano` |
| Guardrails | 9001 | `services/guardrails/` | `gpt-4.1-nano` |

### n8n workflow

File: `n8n-workflows/property-intake-guardrails-v1.json`
Pipeline: Webhook → Guardrails input → (reject OR LangGraph → Guardrails output) → update row

Each service has its own `.venv`. Copy `.env.example` → `.env` and fill `OPENAI_API_KEY` (and `PINECONE_API_KEY` for langgraph).

---

## Step 1 — End-to-End Test

### Directory to create

```
tests/
└── e2e/
    ├── README.md         # how to run
    ├── run_tests.sh      # shell script that fires all curl cases
    └── expected/
        ├── sell_pass.json
        ├── rent_pass.json
        └── spam_block.json
```

### Pre-conditions

1. Both services running:
   ```bash
   # Terminal 1
   cd services/langgraph-agent && source .venv/bin/activate
   uvicorn main:server --port 9000 --reload

   # Terminal 2
   cd services/guardrails && source .venv/bin/activate
   uvicorn main:server --port 9001 --reload
   ```

2. n8n Docker running on port 5678:
   ```bash
   docker run -it --rm -p 5678:5678 -v n8n_data:/home/node/.n8n n8nio/n8n
   ```

3. Workflow imported in n8n UI and **listening** (click "Test workflow" to activate `/webhook-test/` path, or publish for `/webhook/`).

### Test cases for `run_tests.sh`

| Case | Payload | Expected |
|------|---------|----------|
| Sell listing (complete) | address, size, rooms, price, `"intent":"sell"` | `status: done`, recommendation in result |
| Rent listing | same fields, `"intent":"rent"` | `status: done`, rent analysis |
| Spam | `"description": "Buy cheap Rolex watches!"` | guardrails blocks, row `status: rejected` |
| False claim in output | inject `"This property is legally guaranteed to appreciate"` into report | output guardrail flags it, `status: flagged` |

### Webhook URLs

- **Test mode** (workflow open in UI, listening): `POST http://localhost:5678/webhook-test/property-intake`
- **Production** (workflow published): `POST http://localhost:5678/webhook/property-intake`

### What to verify

- [ ] Guardrails `/check/input` returns `{"pass": true/false, "reason": ...}`
- [ ] LangGraph `/analyze` returns `{"recommendation": "...", "intent": "sell"|"rent", "confidence": 0.0–1.0, ...}`
- [ ] n8n row in dataTable updates to `status: done` for valid submissions
- [ ] n8n row updates to `status: rejected` for spam
- [ ] Output with false claims gets `status: flagged`

### What to tell Claude

> "Create `tests/e2e/run_tests.sh` — a shell script that fires 4 curl cases against the n8n webhook at `http://localhost:5678/webhook-test/property-intake` and prints PASS/FAIL based on the response. Cases: sell listing (expect `pass`), rent listing (expect `pass`), spam (expect guardrail block), complete output that includes a false legal guarantee (if testable directly against guardrails output endpoint). Also add health checks for ports 9000 and 9001 at the top of the script."

---

## Step 2 — Image Analyzer Service

### Purpose

Analyze a property image and return:
- `room_type`: one of `bedroom | living_room | kitchen | bathroom | exterior | other`
- `condition_score`: float 0.0–1.0 (0 = wreck, 1 = new/renovated)

This feeds into the LangGraph analyst node to enrich the property assessment.

### Spec

| Item | Value |
|------|-------|
| Port | 9002 |
| Endpoint | `POST /analyse` |
| Input | multipart image file OR `{"image_url": "..."}` JSON |
| Output | `{"room_type": "bedroom", "condition_score": 0.82, "confidence": 0.91}` |
| Model | ResNet-50 pretrained, fine-tuned or zero-shot with class mapping |
| Framework | PyTorch + torchvision, FastAPI |

### Directory to create

```
services/
└── image-analyzer/
    ├── main.py          # FastAPI, POST /analyse, GET /health
    ├── model.py         # ResNet-50 load + inference
    ├── labels.py        # class → room_type + condition mapping
    ├── requirements.txt
    ├── Dockerfile
    ├── .env.example
    └── README.md
```

### Model approach

ResNet-50 pretrained on ImageNet. Map top-5 predicted classes to room types using a hand-crafted label mapping (e.g. `"bedroom"` ImageNet classes → `room_type: bedroom`). Condition score derived from predicted class confidence + secondary heuristics (brightness, clutter proxy).

If zero-shot mapping is too noisy: use CLIP (`openai/clip-vit-base-patch32`) — embed image, embed each room label, cosine similarity gives room type + confidence.

**Recommended: start with CLIP** — no fine-tuning needed, works out of the box, better accuracy for room types than ImageNet label mapping.

### n8n integration (after service is built)

Add an HTTP Request node after LangGraph in the workflow:
```
LangGraph Analyze
    ↓
Image Analyzer (POST http://host.docker.internal:9002/analyse)
    ↓
Merge image result into row update
```

Only fires if submission includes an image URL.

### What to tell Claude

> "Build the Image Analyzer microservice at `services/image-analyzer/`. Use CLIP (`openai/clip-vit-base-patch32` via HuggingFace `transformers`) to classify room type and estimate condition. Endpoint: `POST /analyse` accepts either a multipart file upload or `{"image_url": "..."}`. Returns `{"room_type": "...", "condition_score": 0.0–1.0, "confidence": 0.0–1.0}`. Room type labels: `bedroom`, `living_room`, `kitchen`, `bathroom`, `exterior`, `other`. Condition score: use a second CLIP prompt set like `['well-maintained room', 'average condition room', 'rundown room']` to derive a 0–1 score. Wrap in FastAPI on port 9002 with GET /health. Add requirements.txt, Dockerfile, and README with run + test curl commands."

---

## Step 3 — Admin Panel: S3 Storage + Google Sheets + Property Listing View

### Goal

Build a property admin panel that shows all submitted listings with images, basic filters, and status. No chat component in this step.

### Architecture decisions made

- **Images**: stored in a public S3 bucket. URL saved in Google Sheets row.
- **Database**: Google Sheets (POC, max ~30 rows). Replaceable with real DB later.
- **Properties API**: `GET /properties` added to the existing `services/langgraph-agent` FastAPI service (pragmatic POC choice — extract to dedicated service later).
- **n8n**: new workflow version `property-intake-admin-v1.json` forked from `property-intake-image-analyzer-v2.json`.
- **Image analysis for scoring**: image analysis result is stored as descriptive text only — it does NOT feed into the LangGraph score. Score comes from LangGraph only.

---

### Part A — AWS S3 Setup (manual, done once)

1. Create a public S3 bucket (e.g. `fp-property-images`, region `us-east-1` or same as EC2)
2. Bucket policy — allow public read:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::fp-property-images/*"
  }]
}
```
3. Create an IAM user with `s3:PutObject` permission on that bucket only. Save Access Key ID + Secret.
4. Add AWS credentials to n8n: n8n UI → Credentials → AWS → paste Key ID + Secret + region.

Image URL pattern: `https://fp-property-images.s3.amazonaws.com/{jobId}/{filename}`

---

### Part B — Google Sheets Setup (manual, done once)

1. Create a Google Sheet named `Property Submissions`.
2. Row 1 = headers (exact names, case-sensitive — n8n uses these):

| Column | Type | Notes |
|--------|------|-------|
| jobId | string | primary key |
| submittedAt | string | ISO datetime |
| status | string | pending / done / rejected / flagged |
| property_type | string | apartment / villa / commercial / land |
| intent | string | sell / rent |
| location | string | |
| condition | string | new / renovated / good / fair / poor |
| price_asking | number | NIS, may be empty |
| size_sqm | number | may be empty |
| num_rooms | number | may be empty |
| agent_name | string | may be empty |
| image_url | string | S3 public URL, may be empty |
| image_analysis | string | OpenAI Vision description, may be empty |
| recommendation | string | BUY / NEGOTIATE / RENT / PASS |
| confidence | number | 0.0–1.0 from LangGraph |
| result | string | full formatted markdown result |
| completedAt | string | ISO datetime, set when done/rejected/flagged |

3. Share the sheet with a Google service account (create one in Google Cloud Console → IAM → Service Accounts → create key JSON).
4. Add Google Sheets credentials to n8n: n8n UI → Credentials → Google Sheets API → paste service account JSON.
5. Note the **Sheet ID** from the URL: `https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit`

---

### Part C — n8n Workflow v3 (`property-intake-admin-v1.json`)

Fork `property-intake-image-analyzer-v2.json`. Changes:

#### 1. Replace all DataTable nodes with Google Sheets nodes

| Old node | New node | Operation |
|----------|----------|-----------|
| Insert row (DataTable) | Append Row (Google Sheets) | Append new row with jobId, submittedAt=now, status=pending, + all form fields from webhook body |
| Update row(s) (DataTable) | Update Row (Google Sheets) | Match on jobId, set status/result/recommendation/confidence/completedAt |
| Update row (rejected) (DataTable) | Update Row (Google Sheets) | Match on jobId, set status=rejected, result=reason |
| Update row (processing error) (DataTable) | Update Row (Google Sheets) | Match on jobId, set status=rejected, result=error message |

For "Append Row", map these fields from `{{ $('User Submit').first().json.body }}`:
- `jobId`, `submittedAt` = `{{ $now.toISO() }}`, `status` = `pending`
- `property_type`, `intent`, `location`, `condition`, `price_asking`, `size_sqm`, `num_rooms`, `agent_name`, `description`

#### 2. Add S3 Upload node (in the image branch, before Image Analyzer)

Position: after `Has Image File?` (true branch), before Image Analyzer.

Node type: AWS S3 → Upload  
- Bucket: `fp-property-images`  
- Key: `{{ $('Insert Row').item.json.jobId }}/{{ $binary.file.fileName }}`  
- Binary field: `file`  

Output: the node returns the S3 object URL. Store it as `image_url` in the Google Sheets update.

#### 3. Image Analyzer — use S3 URL instead of binary

After S3 upload, pass the URL to the OpenAI Vision node:
- Image source: URL
- URL: `https://fp-property-images.s3.amazonaws.com/{{ $('Insert Row').item.json.jobId }}/{{ $binary.file.fileName }}`

Keep `"onError": "continueRegularOutput"` — if Vision fails, flow continues without image analysis.

#### 4. Merge & format Code node (after image branch rejoins)

Replace "Route Response" code node with one that merges LangGraph output + optional image analysis:

```javascript
const langResult = $('LangGraph Analyze').first().json;
let imageAnalysis = "";
let imageUrl = "";

try {
  imageAnalysis = $('Image Analyzer').first().json.message?.content || "";
} catch(e) {}

try {
  imageUrl = `https://fp-property-images.s3.amazonaws.com/${$('Insert Row').first().json.jobId}/${$('Has Image File?').first().json.body?.file?.originalFilename || ''}`;
} catch(e) {}

const analysis = langResult.analysis || {};
const result = [
  analysis.market_context,
  analysis.property_assessment,
  analysis.pricing_opinion,
  analysis.recommendation,
  analysis.expected_timeline,
  imageAnalysis ? `\n**Image Analysis:** ${imageAnalysis}` : ""
].filter(Boolean).join("\n\n");

return [{
  json: {
    result,
    recommendation: analysis.recommendation || "PASS",
    confidence: langResult.confidence || 0,
    status: langResult.status || "complete",
    image_url: imageUrl,
    image_analysis: imageAnalysis,
  }
}];
```

#### 5. Final Google Sheets "Update Row" (done/flagged)

After Guardrails Output Check, update the row:
- `status`: done or flagged
- `result`: from merge node
- `recommendation`: from merge node
- `confidence`: from merge node
- `image_url`: from merge node
- `image_analysis`: from merge node
- `completedAt`: `{{ $now.toISO() }}`

---

### Part D — `GET /properties` endpoint in langgraph-agent

New file: `services/langgraph-agent/properties_router.py`

```python
from fastapi import APIRouter, Query
from google.oauth2.service_account import Credentials
import gspread, os
from typing import Optional

router = APIRouter()
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "google-credentials.json")

def _get_sheet():
    creds = Credentials.from_service_account_file(
        CREDS_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).sheet1

@router.get("/properties")
def get_properties(
    location: Optional[str] = Query(None),
    property_type: Optional[str] = Query(None),
    min_rooms: Optional[int] = Query(None),
    max_price: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
):
    rows = _get_sheet().get_all_records()
    # apply filters
    if location:
        rows = [r for r in rows if location.lower() in (r.get("location") or "").lower()]
    if property_type:
        rows = [r for r in rows if r.get("property_type") == property_type]
    if min_rooms:
        rows = [r for r in rows if int(r.get("num_rooms") or 0) >= min_rooms]
    if max_price:
        rows = [r for r in rows if int(r.get("price_asking") or 0) <= max_price or not r.get("price_asking")]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return rows
```

Register in `main.py`:
```python
from properties_router import router as properties_router
server.include_router(properties_router)
```

Add to `services/langgraph-agent/.env.example`:
```
GOOGLE_SHEET_ID=your_sheet_id_here
GOOGLE_CREDENTIALS_FILE=google-credentials.json
```

Add to `requirements.txt`:
```
gspread>=6.0.0
google-auth>=2.0.0
```

---

### Part E — Gradio Admin Tab

New Tab 3 in `services/gradio-ui/app.py`: `"🏠 Properties"`.

Layout:
- Top row: filter controls (dropdowns + number inputs + Refresh button)
- Main area: property cards rendered as markdown (image thumbnail + fields + status chip + recommendation)

Fetch from `http://localhost:9000/properties` (or from `config.py` env var `LANGGRAPH_API_URL`).

New file: `services/gradio-ui/properties.py`

```python
import httpx
from config import LANGGRAPH_API_URL  # add this to config.py

def fetch_properties(location="", property_type="", min_rooms=None, max_price=None):
    params = {}
    if location: params["location"] = location
    if property_type: params["property_type"] = property_type
    if min_rooms: params["min_rooms"] = int(min_rooms)
    if max_price: params["max_price"] = int(max_price)
    params["status"] = "done"  # only show completed listings

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{LANGGRAPH_API_URL}/properties", params=params)
            resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return []

def render_properties(rows: list) -> str:
    if not rows:
        return "*No listings found matching the filters.*"
    parts = []
    for r in rows:
        img = f"![property]({r['image_url']})" if r.get("image_url") else "*(no image)*"
        parts.append(
            f"### {r.get('property_type','').title()} — {r.get('location','')}\n"
            f"{img}\n\n"
            f"**Rooms:** {r.get('num_rooms','—')} | "
            f"**Size:** {r.get('size_sqm','—')} sqm | "
            f"**Price:** {int(r['price_asking']):,} NIS\n\n" if r.get('price_asking') else ""
            f"**Condition:** {r.get('condition','—')} | "
            f"**Intent:** {r.get('intent','—')} | "
            f"**Recommendation:** `{r.get('recommendation','—')}`\n\n"
            f"{r.get('result','')[:300]}…\n\n---"
        )
    return "\n\n".join(parts)
```

Tab wiring in `app.py`:
```python
with gr.Tab("🏠 Properties"):
    with gr.Row():
        filter_location    = gr.Textbox(label="Location", scale=2)
        filter_type        = gr.Dropdown(["", "apartment","villa","commercial","land"], label="Type", scale=1)
        filter_min_rooms   = gr.Number(label="Min rooms", scale=1, minimum=0)
        filter_max_price   = gr.Number(label="Max price (NIS)", scale=1, minimum=0)
        refresh_btn        = gr.Button("🔄 Refresh", scale=1)

    properties_display = gr.Markdown("*Click Refresh to load listings.*")

    def _load(location, ptype, rooms, price):
        rows = properties_mod.fetch_properties(location, ptype or "", rooms or None, price or None)
        return properties_mod.render_properties(rows)

    refresh_btn.click(_load, [filter_location, filter_type, filter_min_rooms, filter_max_price], properties_display)
```

---

### Summary of files to create / modify

| File | Action |
|------|--------|
| `n8n-workflows/property-intake-admin-v1.json` | New — fork of v2 with S3 + Google Sheets + merge node |
| `services/langgraph-agent/properties_router.py` | New — GET /properties with gspread |
| `services/langgraph-agent/main.py` | Modify — register properties_router |
| `services/langgraph-agent/requirements.txt` | Modify — add gspread, google-auth |
| `services/langgraph-agent/.env.example` | Modify — add GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_FILE |
| `services/gradio-ui/properties.py` | New — fetch + render helpers |
| `services/gradio-ui/app.py` | Modify — add Tab 3 |
| `services/gradio-ui/config.py` | Modify — add LANGGRAPH_API_URL |

### What to tell Claude

> "We're building Step 3 of the admin panel. Read `assets/handoff-next.md` Step 3 in full before starting. Then implement in this order: (1) add `properties_router.py` to `services/langgraph-agent` and register it in `main.py` — use gspread with service account auth, read GOOGLE_SHEET_ID and GOOGLE_CREDENTIALS_FILE from env; (2) add `services/gradio-ui/properties.py` and wire up a new Tab 3 in `app.py`; (3) create `n8n-workflows/property-intake-admin-v1.json` by modifying the existing `property-intake-image-analyzer-v2.json` — replace all DataTable nodes with Google Sheets nodes, add S3 Upload before Image Analyzer, add a Merge & Score Code node. The n8n workflow JSON must be valid importable JSON. Do not start the n8n workflow from scratch — fork the existing file."
