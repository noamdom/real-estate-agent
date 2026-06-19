# Image Analyzer Service

Classifies a property image into a room type and estimates its condition using CLIP (`openai/clip-vit-base-patch32`). Runs fully locally — no API keys required.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/analyse` | Analyse an image |

### POST /analyse

Accepts either a file upload or a JSON image URL.

**File upload:**
```bash
curl -X POST http://localhost:9002/analyse \
  -F "file=@/path/to/image.jpg"
```

**Image URL:**
```bash
curl -X POST http://localhost:9002/analyse \
  -H "Content-Type: application/json" \
  -d '{"image_url": "https://source.unsplash.com/800x600/?bedroom"}'
```

**Response:**
```json
{
  "room_type": "bedroom",
  "condition_score": 0.82,
  "confidence": 0.91
}
```

| Field | Type | Description |
|-------|------|-------------|
| `room_type` | string | `bedroom`, `living_room`, `kitchen`, `bathroom`, `exterior`, `other` |
| `condition_score` | float 0–1 | 1.0 = excellent, 0.5 = average, 0.0 = poor |
| `confidence` | float 0–1 | CLIP softmax confidence for the room type prediction |

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn main:server --port 9002 --reload
```

The CLIP model (~350MB) is downloaded from HuggingFace on first startup and cached locally.

## Docker

```bash
docker build -t image-analyzer .
docker run -p 9002:9002 image-analyzer
```
