# AI Property Triage System

End-to-end AI pipeline that automates real estate listing intake and analysis for a property investment embassy. A user submits a property via the Gradio UI, n8n orchestrates the flow through guardrails and analysis microservices, and a structured embassy recommendation is returned.

---

## Architecture

```
┌─────────────────────────┐   ┌─────────────────────┐   ┌──────────────────────────────────────────┐   ┌──────────────────────────┐
│   Local (MacBook)        │   │  n8n Orchestration   │   │          AWS EC2 — Microservices          │   │  External APIs & Storage │
│                          │   │  Docker · :5678       │   │                                          │   │                          │
│  ┌──────────────────┐    │   │  ┌───────────────┐   │   │  ┌──────────────────┐  ┌─────────────┐  │   │  OpenAI API              │
│  │   Gradio UI      │────────▶ │ n8n Workflow   │───────▶ │ Guardrails :9001  │  │ LangGraph   │  │   │  gpt-4.1-nano            │
│  │   :7860          │    │   │ │ Intake orchestr│   │   │ │ gpt-4o-mini       │  │ Agent :9000 │──────▶ gpt-4o-mini             │
│  │ Intake · Status  │    │   │ │ Async jobs     │   │   │ │ Input/Image/Output│  │ 7-node graph│  │   │  text-embedding-3-small  │
│  └────────┬─────────┘    │   │  └───────────────┘   │   │ │ validation        │  └──────┬──────┘  │   │                          │
│           │              │   │                       │   │  └──────────────────┘         │         │   │  Pinecone                │
│  ┌────────▼─────────┐    │   │                       │   │  ┌──────────────────┐         │ RAG     │   │  rag-properties-israel   │
│  │   Ollama         │    │   │                       │   │  │ Image Analyzer   │         └────────────▶ 1 000 Israeli comps      │
│  │   llama3.1       │    │   │                       │   │  │ :9002 · CLIP     │                   │   │  512-dim embeddings      │
│  │   :11434         │    │   │                       │   │  │ ViT-B/32 zero-shot│                  │   │                          │
│  └──────────────────┘    │   │                       │   │  └──────────────────┘                   │   │  Google Sheets           │
│                          │   │                       │   │                                          │   │  AWS S3                  │
└─────────────────────────┘   └─────────────────────┘   └──────────────────────────────────────────┘   └──────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Agent framework** | LangGraph (StateGraph, 7-node reasoning graph) |
| **Local LLM** | Ollama + llama3.1 (conversational intake) |
| **LLM inference** | OpenAI gpt-4.1-nano (analyst), gpt-4o-mini (guardrails) |
| **Embeddings** | OpenAI text-embedding-3-small |
| **Vector store / RAG** | Pinecone — `rag-properties-israel`, 1 000 Israeli comps, 512-dim |
| **Image classification** | CLIP ViT-B/32 — zero-shot room type + condition score |
| **Guardrails** | Custom LLM prompts — input spam/discriminatory, image label, output false claims |
| **Orchestration** | n8n (Docker) — webhook trigger, async job processing, Google Sheets logging |
| **UI** | Gradio — Intake Assistant, Properties tab, Submission Status |
| **APIs** | FastAPI — all three EC2 microservices |
| **Storage** | Google Sheets (job tracking), AWS S3 `fp-property-images` (image store) |
| **Infra** | AWS EC2 (3 services), Docker (n8n), macOS local (Gradio + Ollama) |
| **Observability** | LangSmith — traces every LangGraph node run (LLM calls, inputs, outputs, latency) |

---

## Services

| Service | Port | Host | Purpose |
|---------|------|------|---------|
| Gradio UI | 7860 | Local | Conversational intake, submission status, properties tab |
| Ollama | 11434 | Local | Local LLM for intake conversation (llama3.1) |
| n8n | 5678 | Docker | Workflow orchestration — validates, routes, logs every submission |
| Guardrails | 9001 | EC2 | Input · image-label · output content validation (gpt-4o-mini) |
| LangGraph Agent | 9000 | EC2 | 7-node reasoning graph — deal score, pricing, team routing |
| Image Analyzer | 9002 | EC2 | CLIP zero-shot room classification, uploads to S3 |

---

## Run locally

```bash
# Terminal 1 — LangGraph Agent
cd services/langgraph-agent && source .venv/bin/activate
uvicorn main:server --port 9000 --reload

# Terminal 2 — Guardrails
cd services/guardrails && source .venv/bin/activate
uvicorn main:server --port 9001 --reload

# Terminal 3 — Image Analyzer
cd services/image-analyzer && source .venv/bin/activate
uvicorn main:server --port 9002 --reload

# Terminal 4 — Gradio UI
cd services/gradio-ui && source .venv/bin/activate
cp .env.example .env   # fill in values
python app.py

# n8n (Docker)
docker run -it --rm \
  -p 5678:5678 \
  -v n8n_data:/home/node/.n8n \
  n8nio/n8n
```

Import workflow: n8n UI → open workflow → ⋯ → **Import from file** → `n8n-workflows/property-intake.json`

---

## E2E Test Suite

The test suite covers all five services with health checks, happy-path cases, and guardrail rejection scenarios.

```bash
# Run all tests (production webhook — requires n8n published workflow)
bash tests/e2e/run_tests.sh

# Run against n8n test-mode webhook (workflow open in UI)
bash tests/e2e/run_tests.sh --mode=debug

# Run a single group
bash tests/e2e/run_tests.sh --group=guardrails-input
bash tests/e2e/run_tests.sh --group=guardrails-output
bash tests/e2e/run_tests.sh --group=langgraph
bash tests/e2e/run_tests.sh --group=image-analyzer
bash tests/e2e/run_tests.sh --group=n8n
```

**Test groups:**

| Group | What it tests |
|-------|--------------|
| `guardrails-input` | Valid listing accepted · spam blocked |
| `guardrails-output` | False legal claim flagged · safe hedged report accepted |
| `langgraph` | Sell · rent · with image_analysis · no price_asking |
| `image-analyzer` | CLIP classification across 5 room types (Bathroom/Bedroom/Kitchen/Dining/Living) |
| `n8n` | Full webhook — sell · rent · sell+image · spam rejected |

The `image-analyzer` and `n8n` groups expect the dataset at `assets/House_Room_Dataset/`.
Download from Kaggle: https://www.kaggle.com/datasets/robinreni/house-rooms-image-dataset
Extract so the structure is:
```
assets/House_Room_Dataset/
  Bathroom/
  Bedroom/
  Dinning/
  Kitchen/
  Livingroom/
```

---

## Quick curl examples

```bash
# Submit a sell listing
curl -s -X POST http://localhost:5678/webhook/property-intake \
  -F "description=Renovated 4-room apartment on Rothschild Blvd, Tel Aviv. 92sqm, 8th floor." \
  -F "property_type=apartment" \
  -F "intent=sell" \
  -F "location=Tel Aviv, Rothschild" \
  -F "condition=renovated" \
  -F "price_asking=3400000" \
  -F "size_sqm=92" \
  -F "num_rooms=4" \
  -F "agent_name=David Cohen" | jq

# Check job status
curl -s "http://localhost:5678/webhook/property-status?job_id=<JOB_ID>" | jq

# Test guardrails directly — spam (blocked)
curl -s -X POST http://localhost:9001/check/input \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy cheap Rolex watches! Limited time offer."}' | jq

# Test LangGraph directly
curl -s -X POST http://localhost:9000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "property_type": "apartment",
    "location": "Tel Aviv, Florentin",
    "description": "Renovated 3-room apartment, south-facing, new kitchen.",
    "price_asking": 3200000,
    "size_sqm": 85,
    "num_rooms": 3,
    "condition": "renovated",
    "intent": "sell"
  }' | jq
```

---

## Service health checks

```bash
curl -s http://localhost:9000/health && echo " LangGraph"
curl -s http://localhost:9001/health && echo " Guardrails"
curl -s http://localhost:9002/health && echo " Image Analyzer"
```
