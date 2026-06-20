# AI Property Triage System

End-to-end pipeline: conversational property intake → guardrails → LangGraph analysis → embassy recommendation.

## Services

| Service         | Port | Purpose                          |
| --------------- | ---- | -------------------------------- |
| LangGraph Agent | 9000 | Reasoning + RAG analysis         |
| Guardrails      | 9001 | Input/output validation          |
| Gradio UI       | 7860 | Conversational intake + admin    |
| n8n             | 5678 | Orchestration (Docker)           |

## Start services

```bash
# Terminal 1 — LangGraph Agent
cd services/langgraph-agent && source .venv/bin/activate
uvicorn main:server --port 9000 --reload

# Terminal 2 — Guardrails
cd services/guardrails && source .venv/bin/activate
uvicorn main:server --port 9001 --reload

# Terminal 3 — Gradio UI
cd services/gradio-ui && source .venv/bin/activate
cp .env.example .env   # fill in values
python app.py

# n8n (Docker)
docker run -it --rm \
  -p 5678:5678 \
  -v n8n_data:/home/node/.n8n \
  n8nio/n8n
```

Import workflow: n8n UI → open workflow → ⋯ → **Import from file** → `n8n-workflows/property-intake-image-analyzer-v2.json`

---

## Submit a property via curl (multipart form)

### Sell listing

```bash
curl -s -X POST http://localhost:5678/webhook-test/property-intake \
  -F "description=4 room apartment on Rothschild Blvd, renovated, 90sqm, asking 3.5M NIS" \
  -F "property_type=apartment" \
  -F "intent=sell" \
  -F "location=Tel Aviv, Rothschild" \
  -F "condition=renovated" \
  -F "price_asking=3500000" \
  -F "size_sqm=90" \
  -F "num_rooms=4" | jq
```

### With image

```bash
curl -s -X POST http://localhost:5678/webhook-test/property-intake \
  -F "description=3 room apartment near the beach" \
  -F "property_type=apartment" \
  -F "intent=rent" \
  -F "location=Tel Aviv, HaYarkon" \
  -F "condition=good" \
  -F "file=@/path/to/image.jpg" | jq
```

### Spam (blocked by guardrails)

```bash
curl -s -X POST http://localhost:5678/webhook-test/property-intake \
  -F "description=Buy cheap Rolex watches, limited offer!" | jq
```

---

## Test services directly (no n8n)

```bash
# Guardrails — valid listing
curl -s -X POST http://localhost:9001/check/input \
  -H "Content-Type: application/json" \
  -d '{"text": "3 bedroom apartment Tel Aviv 85sqm asking 3M NIS renovated"}' | jq

# Guardrails — spam
curl -s -X POST http://localhost:9001/check/input \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy cheap Rolex watches now!"}' | jq

# LangGraph — analyze
curl -s -X POST http://localhost:9000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "location": "Tel Aviv, Dizengoff",
    "size_sqm": 75,
    "num_rooms": 3,
    "price_asking": 2800000,
    "intent": "sell",
    "condition": "good",
    "description": "3 room apartment Dizengoff Tel Aviv 75sqm 2.8M NIS"
  }' | jq
```
