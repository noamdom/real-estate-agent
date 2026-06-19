import io
import logging

import requests as http_client
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from PIL import Image
from pydantic import BaseModel

from model import analyse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("image-analyzer")

server = FastAPI(title="Image Analyzer Service", version="1.0.0")


def _decode(data: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot decode image: {exc}")


@server.get("/health")
def health():
    return {"status": "ok"}


@server.post("/analyse")
async def analyse_endpoint(request: Request):
    """
    Accepts either:
      - multipart/form-data with a 'file' field (image upload)
      - application/json with an 'image_url' field
    Returns {"room_type", "condition_score", "confidence"}.
    """
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        upload: UploadFile = form.get("file")
        if not upload:
            raise HTTPException(status_code=400, detail="Missing 'file' field in multipart form")
        data = await upload.read()
        log.info("Received file upload: %s (%d bytes)", upload.filename, len(data))
        image = _decode(data)

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

    else:
        raise HTTPException(
            status_code=415,
            detail="Content-Type must be multipart/form-data or application/json",
        )

    result = analyse(image)
    log.info("Result: %s", result)
    return result
