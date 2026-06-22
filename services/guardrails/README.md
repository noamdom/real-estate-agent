# Guardrails Service

Validates property submissions and AI-generated reports using LLM-based classification (gpt-4o-mini).

## Endpoints

- **`POST /check/input`** — rejects spam, off-topic text, discriminatory content
- **`POST /check/image-label`** — validates computer-vision labels are property-related
- **`POST /check/output`** — flags fabricated prices, false legal claims, invented data
- **`GET /health`** — liveness check

All endpoints accept `{"text": "..."}` and return `{"pass": true/false, "reason": "..."}`.

## Run

```bash
cp .env.example .env    # fill in OPENAI_API_KEY
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:server --port 9001 --reload
```

## Test

```bash
# valid listing → should pass
curl -s -X POST http://localhost:9001/check/input \
  -H "Content-Type: application/json" \
  -d '{"text": "3 bedroom apartment in Tel Aviv Florentin, 85sqm, asking 3M NIS, renovated"}' | jq

# spam → should block
curl -s -X POST http://localhost:9001/check/input \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy cheap Rolex watches, limited offer!"}' | jq

# clean report → should pass
curl -s -X POST http://localhost:9001/check/output \
  -H "Content-Type: application/json" \
  -d '{"text": "Based on 3 comparable listings, we recommend negotiating to 2.85M NIS."}' | jq

# false claim → should flag
curl -s -X POST http://localhost:9001/check/output \
  -H "Content-Type: application/json" \
  -d '{"text": "This property is legally guaranteed to appreciate by 20% per year."}' | jq
```

## Docker

```bash
docker build -t guardrails-service:latest .
docker run -d --name guardrails --restart unless-stopped \
  -p 9001:9001 \
  -e OPENAI_API_KEY=sk-... \
  guardrails-service:latest
```
