import io
import logging
import os

import boto3
from dotenv import load_dotenv
import requests as http_client
from fastapi import FastAPI, HTTPException, Request, UploadFile
from PIL import Image

from model import analyse

load_dotenv()

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
      - multipart/form-data with 'files' (one or more UploadFile) + optional 'job_id' form field
        With job_id   → uploads all files to S3, runs CLIP on first, returns image_urls + analysis.
        Without job_id → CLIP only, no S3 upload (used by direct e2e tests).
        Backward compat: also accepts old single 'file' field in place of 'files'.
      - application/json with 'image_url'
        → fetches image from URL, runs CLIP only (no S3 upload, for local testing).
    """
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        job_id: str | None = form.get("job_id")

        # Accept 'files' list, indexed 'file0'/'file1'/... (n8n multipart), or legacy 'file'
        # file_count caps how many indexed slots to read (n8n pads extras with the last file)
        file_count_raw = form.get("file_count")
        file_limit = int(file_count_raw) if file_count_raw and file_count_raw.isdigit() else None

        uploads: list[UploadFile] = form.getlist("files")
        if not uploads:
            i = 0
            while (f := form.get(f"file{i}")) is not None:
                uploads.append(f)
                i += 1
                if file_limit and i >= file_limit:
                    break
        if not uploads:
            single = form.get("file")
            if single:
                uploads = [single]
        if not uploads:
            raise HTTPException(status_code=400, detail="Missing 'files' (or 'file') field")

        # Read all payloads upfront
        file_data: list[tuple[bytes, str, str]] = []
        for upload in uploads:
            data = await upload.read()
            file_data.append((data, upload.filename, upload.content_type or "image/jpeg"))
            log.info("Received %s (%d bytes)", upload.filename, len(data))

        # Upload to S3 when job_id is present; skip for direct test calls
        image_urls: list[str] = []
        if job_id:
            s3 = _s3_client()
            for data, filename, ctype in file_data:
                key = f"{job_id}/{filename}"
                s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType=ctype)
                image_urls.append(f"{S3_BASE_URL}/{key}")
                log.info("Uploaded → s3://%s/%s", S3_BUCKET, key)

        image = _decode(file_data[0][0])
        result = analyse(image)
        if image_urls:
            result["image_urls"] = image_urls
        log.info("Result: %s", result)
        return result

    elif "application/json" in content_type:
        import base64
        body = await request.json()

        # Path 1: base64 files array — sent by n8n Code node
        # {"job_id": "...", "files": [{"data": "<base64>", "filename": "...", "mimetype": "..."}]}
        if "files" in body:
            job_id = body.get("job_id")
            files_payload = body["files"]
            if not files_payload:
                raise HTTPException(status_code=400, detail="Empty 'files' array")

            file_data: list[tuple[bytes, str, str]] = []
            for f in files_payload:
                b64 = f["data"]
                # Strip data-URL prefix if present (data:image/jpeg;base64,...)
                if isinstance(b64, str) and b64.startswith("data:"):
                    b64 = b64.split(",", 1)[-1]
                raw = base64.b64decode(b64)
                file_data.append((raw, f["filename"], f.get("mimetype", "image/jpeg")))
                log.info("Decoded %s (%d bytes)", f["filename"], len(raw))

            image_urls: list[str] = []
            if job_id:
                s3 = _s3_client()
                for raw, filename, ctype in file_data:
                    key = f"{job_id}/{filename}"
                    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=raw, ContentType=ctype)
                    image_urls.append(f"{S3_BASE_URL}/{key}")
                    log.info("Uploaded → s3://%s/%s", S3_BUCKET, key)

            image = _decode(file_data[0][0])
            result = analyse(image)
            if image_urls:
                result["image_urls"] = image_urls
            log.info("Result: %s", result)
            return result

        # Path 2: single image_url — for local testing / direct calls
        image_url = body.get("image_url")
        if not image_url:
            raise HTTPException(status_code=400, detail="Missing 'image_url' or 'files' in JSON body")
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
