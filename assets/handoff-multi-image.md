# Multi-Image Support — Implementation Handoff

## Goal

Allow users to upload multiple images per property listing. All images are uploaded to S3,
stored as a JSON array in `image_urls`, and displayed as a gallery in the Properties tab.

CLIP analysis runs on the **first image only** (the model accepts one image per call — keep it that way).

---

## Chosen Approach: Option C — Image-Analyzer owns the full image pipeline

The image-analyzer service receives all files directly from n8n, uploads every file to S3,
runs CLIP on the first one, and returns the combined result in a single response.
n8n acts as a pure pass-through for the binary data — no fan-out, no separate S3 Upload node.

```
Gradio  ──multipart (file0, file1, …)──►  n8n webhook
                                               │
                                          [all processing unchanged up to Has Image File?]
                                               │ true
                                    "Forward to Image Analyzer"
                                     (Code node, replaces Prepare Binary
                                      + S3 Upload + Image Analyzer)
                                               │  POST multipart: files[] + job_id
                                               ▼
                                        image-analyzer :9002
                                         upload all → S3
                                         CLIP on files[0]
                                               │
                                    { image_urls: [...], room_type,
                                      condition_score, confidence }
                                               │
                                    "Update row (image data)"
                                    "Route Response"
                                    "Update row(s)"
```

**Why this design is correct:**
- AWS credentials live in the image service — the one component that owns image infrastructure.
  They never touch Gradio (UI) or n8n (orchestrator).
- S3 upload and CLIP are a single atomic operation from n8n's perspective.
- n8n stays as a pure orchestrator with no knowledge of S3 paths or binary handling logic.

---

## Credentials

### What needs to be added, and where

| Credential | Value | Where to add |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | IAM key with `s3:PutObject` on `fp-property-images` | `services/image-analyzer/.env` |
| `AWS_SECRET_ACCESS_KEY` | matching secret | `services/image-analyzer/.env` |
| `AWS_REGION` | `us-east-1` | `services/image-analyzer/.env` |

**Nothing changes in Gradio's `.env`.** n8n already has the AWS credential for the (now-removed)
S3 Upload node — that credential stays in n8n but is no longer used for S3 uploads.

Update `services/image-analyzer/.env.example`:
```
# CLIP runs locally — no OpenAI key needed.

# AWS — required for S3 image uploads
AWS_ACCESS_KEY_ID=your-key-id
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1
```

---

## Current State (single image, for reference)

### Gradio → n8n today

`services/gradio-ui/submission.py` — `submit_from_chat()`:
- Accepts a list of files from `gr.File(file_count="multiple")`
- Sends **only the first** as `{"file": first_image}` in a multipart POST
- The comment in the code explains why: multiple files with the same key cause n8n to rename
  them `file0/file1/…`, breaking the S3 Upload node that looks for `$binary.file`

`submit_and_poll()` in the same file is **not wired in `app.py`** — dead code today.
Update it for consistency but it won't affect runtime behaviour.

### n8n image path today

```
Has Image File? (true)
  → Prepare Binary   (Code: copies $('User Submit').first().binary onto current items)
  → S3 Upload        (uploads $binary.file; key = {job_id}/{fileName})
  → Image Analyzer   (POST JSON {"image_url": "https://.../{job_id}/{fileName}"})
  → Update row (image data)   (writes image_urls, image_analysis)
  → Route Response
```

### Broken references that also need fixing

`Route Response` (Code node) currently reads:
```javascript
$('Image Analyzer').first().json          // for image_analysis string
$('User Submit').first().binary?.file?.fileName   // to build imageUrl
```
Both break with multi-image (`.file` becomes undefined when files are `file0`/`file1`/…).

`Update row (image data)` currently reads:
```javascript
$('User Submit').first().binary.file.fileName    // same breakage
```

---

## What Needs to Change

### 1. `services/gradio-ui/submission.py`

**`submit_from_chat`** — send all images as indexed fields:

```python
# Replace:
first_image = open(image_paths[0], "rb") if image_paths else None
try:
    files = {"file": first_image} if first_image else None
    ...
finally:
    if first_image:
        first_image.close()

# With:
open_files = [open(p, "rb") for p in image_paths]
try:
    files = {f"file{i}": fh for i, fh in enumerate(open_files)} if open_files else None
    ...
finally:
    for fh in open_files:
        fh.close()
```

Also update `img_note` — remove "first analysed" qualifier:
```python
img_note = (
    f" ({len(image_paths)} image{'s' if len(image_paths) != 1 else ''} attached)"
    if image_paths else ""
)
```

**`submit_and_poll`** (dead code, update for consistency only):
```python
# Replace:
open_file = open(image_file, "rb")
files = {"file": open_file}

# With:
open_file = open(image_file, "rb")
files = {"file0": open_file}
```

### 2. `services/image-analyzer/main.py`

Replace the current `analyse_endpoint` with a version that:
- Accepts `files` (list of UploadFile) + `job_id` (Form field) via multipart
- Uploads all files to S3
- Runs CLIP on the first image
- Returns `{ image_urls, room_type, condition_score, confidence }`
- Keeps the JSON path (`image_url`) for local testing without n8n

```python
import io
import logging
import os

import boto3
import requests as http_client
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from PIL import Image

from model import analyse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("image-analyzer")

server = FastAPI(title="Image Analyzer Service", version="2.0.0")

S3_BUCKET = "fp-property-images"
S3_BASE_URL = f"https://{S3_BUCKET}.s3.us-east-1.amazonaws.com"


def _decode(data: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot decode image: {exc}")


def _s3_client():
    return boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


@server.get("/health")
def health():
    return {"status": "ok"}


@server.post("/analyse")
async def analyse_endpoint(request: Request):
    """
    Accepts either:
      - multipart/form-data with 'files' (one or more) + 'job_id' form field
        → uploads all to S3, runs CLIP on first, returns image_urls array + analysis
      - application/json with 'image_url'
        → fetches image from URL, runs CLIP only (no S3 upload — for local testing)
    """
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        job_id = form.get("job_id")  # optional — absent means CLIP-only, no S3 upload

        # Accept 'files' (new multi-file API) or fall back to old single 'file' field
        # so the existing e2e tests (-F "file=@...") keep passing without modification.
        uploads: list[UploadFile] = form.getlist("files")
        if not uploads:
            single = form.get("file")
            if single:
                uploads = [single]
        if not uploads:
            raise HTTPException(status_code=400, detail="Missing 'files' (or 'file') field")

        # Read all payloads upfront before any async S3 call
        file_data: list[tuple[bytes, str, str]] = []
        for upload in uploads:
            data = await upload.read()
            file_data.append((data, upload.filename, upload.content_type or "image/jpeg"))

        # Upload to S3 only when job_id is present (full pipeline path).
        # Without job_id the endpoint runs CLIP only — used by direct e2e tests.
        image_urls: list[str] = []
        if job_id:
            s3 = _s3_client()
            for data, filename, ctype in file_data:
                key = f"{job_id}/{filename}"
                s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType=ctype)
                image_urls.append(f"{S3_BASE_URL}/{key}")
                log.info("Uploaded %s (%d bytes) → s3://%s/%s", filename, len(data), S3_BUCKET, key)

        image = _decode(file_data[0][0])
        result = analyse(image)
        if image_urls:
            result["image_urls"] = image_urls
        log.info("Result: %s", result)
        return result

    elif "application/json" in content_type:
        body = await request.json()
        image_url = body.get("image_url")
        if not image_url:
            raise HTTPException(status_code=400, detail="Missing 'image_url' in JSON body")
        log.info("Fetching image from URL: %s", image_url)
        try:
            resp = http_client.get(image_url, timeout=15)
            resp.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to fetch image: {exc}")
        image = _decode(resp.content)
        result = analyse(image)
        log.info("Result: %s", result)
        return result

    else:
        raise HTTPException(
            status_code=415,
            detail="Content-Type must be multipart/form-data or application/json",
        )
```

### 3. `services/image-analyzer/requirements.txt`

Add `boto3`:
```
fastapi
uvicorn[standard]
torch
transformers
Pillow
requests
python-multipart
python-dotenv
boto3
```

### 4. n8n workflow — replace three nodes with one

**Remove:**
- `Prepare Binary` (Code node)
- `S3 Upload` (AWS S3 node)
- `Image Analyzer` (HTTP Request node)

**Add: "Forward to Image Analyzer" (Code node)**

Wire: `Has Image File?` (true output) → `Forward to Image Analyzer` → `Update row (image data)` → `Route Response`

```javascript
// "Forward to Image Analyzer" Code node
const userItem   = $('User Submit').first();
const binary     = userItem.binary || {};
const jobId      = $('Insert row').first().json.job_id;

const fd = new FormData();
fd.append('job_id', jobId);

for (const key of Object.keys(binary).sort()) {   // sort → file0, file1, … order
  const meta = binary[key];
  const buf  = await $helpers.getBinaryDataBuffer(userItem, key);
  fd.append('files', new Blob([buf], { type: meta.mimeType }), meta.fileName);
}

const resp = await fetch('http://host.docker.internal:9002/analyse', {
  method: 'POST',
  body: fd,
});
if (!resp.ok) throw new Error(`Image analyzer ${resp.status}: ${await resp.text()}`);
const result = await resp.json();

// result = { image_urls: [...], room_type, condition_score, confidence }
const imageAnalysis = result.room_type
  ? `Room: ${result.room_type} | Condition: ${result.condition_score}/1.0 | Confidence: ${Math.round(result.confidence * 100)}%`
  : '';

return [{ json: {
  job_id:         jobId,
  image_urls:     JSON.stringify(result.image_urls || []),   // stringified for Sheets
  image_analysis: imageAnalysis,
} }];
```

**Update: "Update row (image data)"**

Change both expressions to read from the Code node output instead of the binary/Image Analyzer:
```
image_urls      ={{ $json.image_urls }}
image_analysis  ={{ $json.image_analysis }}
```

**Update: "Route Response" (Code node)**

Replace the two broken `try` blocks that reference `$('Image Analyzer')` and `$binary.file.fileName`:

```javascript
// Remove:
let imageAnalysis = '';
let imageUrl = '';

try {
  const img = $('Image Analyzer').first().json;
  if (img && img.room_type) {
    imageAnalysis = '...';
  }
} catch (e) {}

try {
  const imgResult = $('Image Analyzer').first().json;
  const fileName = $('User Submit').first().binary?.file?.fileName || '';
  if (imgResult && fileName) {
    imageUrl = 'https://fp-property-images.s3.us-east-1.amazonaws.com/' + job_id + '/' + fileName;
  }
} catch (e) {}

// Replace with:
let imageAnalysis = '';
let imageUrls = '';

try {
  const fwd = $('Forward to Image Analyzer').first().json;
  imageAnalysis = fwd.image_analysis || '';
  imageUrls     = fwd.image_urls     || '';
} catch (e) {}   // no-image path: node never ran, catch is expected
```

In the `return` at the bottom of Route Response, change:
```javascript
// Remove:
image_urls: imageUrl ? JSON.stringify([imageUrl]) : '',
image_analysis: imageAnalysis,

// Replace with:
image_urls:     imageUrls,
image_analysis: imageAnalysis,
```

### 5. `services/gradio-ui/properties.py` — gallery instead of first image

```python
# Replace:
try:
    first_url = json.loads(raw_urls)[0] if raw_urls else ""
except Exception:
    first_url = raw_urls
img = f"![property]({first_url})" if first_url else "*(no image)*"

# With:
try:
    signed_urls = json.loads(raw_urls) if raw_urls else []
except Exception:
    signed_urls = [raw_urls] if raw_urls else []
img = "\n".join(f"![property]({u})" for u in signed_urls) if signed_urls else "*(no image)*"
```

---

## Files to Modify

| File | Change |
|---|---|
| `services/gradio-ui/submission.py` | Send all images as `file0`, `file1`, … (indexed) |
| `services/image-analyzer/main.py` | New endpoint: accepts N files + job_id, uploads all to S3, returns `image_urls` array |
| `services/image-analyzer/requirements.txt` | Add `boto3` |
| `services/image-analyzer/.env.example` | Add AWS vars |
| `services/image-analyzer/.env` | **Add real AWS credentials** (do not commit) |
| `n8n-workflows/Property Intake + Admin (Google Sheets + S3 + Vision).json` | Remove Prepare Binary + S3 Upload + Image Analyzer; add Forward to Image Analyzer Code node; update Update row (image data) expressions; fix Route Response |
| `services/gradio-ui/properties.py` | Render all images as gallery |

**No changes needed:**
- `services/langgraph-agent/properties_router.py` — already loops the array and signs each URL
- `services/gradio-ui/app.py` — no wiring changes
- `services/gradio-ui/config.py` — no new env vars for Gradio
- `Has Image File?` condition — `Object.keys($('User Submit').first().binary || {}).length > 0` still works with any binary key name

---

## Key Constraints / Gotchas

- **n8n binary field naming**: Gradio sends `file0`, `file1`, … so n8n stores them as
  `$binary.file0`, `$binary.file1`, etc. `Has Image File?` checks `.length > 0` which still passes. ✓
- **`Object.keys(binary).sort()`**: sorting ensures `file0` is always first, so CLIP always analyses
  the first image the user uploaded regardless of JS object key order.
- **`$helpers.getBinaryDataBuffer(userItem, key)`**: `userItem` must be the actual item from
  `$('User Submit').first()`, not `$input.first()` — the current item (from LangGraph) doesn't carry binary.
- **Route Response no-image path**: the `try/catch` around `$('Forward to Image Analyzer')` is
  intentional — when there is no image, that node never ran and the reference throws. The catch leaves
  `imageUrls` and `imageAnalysis` as empty strings, which is correct.
- **S3 public access**: the bucket must allow `s3:PutObject` from the IAM key and
  `s3:GetObject` publicly (or via pre-signed URLs). `properties_router.py` already generates
  pre-signed URLs for display, so the bucket does not need to be fully public for reads.
- **Google Sheets cell limit**: 50,000 chars per cell. A JSON array of 10 S3 URLs ≈ 800 chars. Safe. ✓
- **CLIP memory**: the model is loaded once at startup. Processing extra images only costs the S3 upload
  time, not additional CLIP inference time (only first image goes through the model).
- **`submit_and_poll` in submission.py** is not connected in `app.py` — it is dead code. Update it for
  consistency (`{"file0": open_file}`) but it does not affect runtime.

---

## Verification Steps

1. Add `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` to `services/image-analyzer/.env`
2. Add `boto3` to the venv: `pip install boto3`
3. Restart the image-analyzer service
4. Submit a listing with **3 images** via the Gradio Intake tab
5. Check n8n execution: "Forward to Image Analyzer" should show one output item with `image_urls` (JSON array of 3) and `image_analysis`
6. Check S3 bucket `fp-property-images/{job_id}/` — should contain 3 files
7. Check Google Sheets `image_urls` column — should be a JSON array with 3 URLs
8. Open Properties tab → Refresh — should show 3 images stacked for that listing
9. Submit a listing with **no image** — verify no-image path still works (Route Response catches the missing node, `image_urls` is empty string)
10. Submit a listing with **1 image** — verify single-image path still works end-to-end
