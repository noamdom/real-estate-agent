# AI Property Triage System — Project Guide

## Project Overview

An end-to-end AI pipeline that automates real estate listing intake and analysis for a property investment embassy. A user submits a property via Open WebUI, n8n orchestrates the flow, microservices analyse it, and a structured embassy recommendation is returned.

**Stack:** Open WebUI · Ollama · n8n · LangGraph · Pinecone · NeMo Guardrails · PyTorch · FastAPI · AWS EC2

---

## Folder Structure

```
final-project/
├── services/
│   ├── langgraph-agent/     # LangGraph reasoning service  — port 9000
│   │   ├── main.py          # FastAPI app, POST /analyze
│   │   ├── graph.py         # StateGraph wiring
│   │   ├── nodes.py         # 7 node functions + keyword classifier
│   │   ├── state.py         # TypedDict state schema
│   │   ├── test_analyze.py  # local test script
│   │   ├── .env.example
│   │   ├── requirements.txt
│   │   ├── Dockerfile
│   │   └── README.md
│   │
│   └── guardrails/          # NeMo Guardrails service      — port 9001
│       ├── main.py          # FastAPI app, POST /check/input + /check/output
│       ├── rails/
│       │   ├── config.yml   # NeMo config — LLM + active flows
│       │   ├── input.co     # Colang — property vs spam/off-topic/offensive
│       │   └── output.co    # Colang — false claims / fabricated data
│       ├── .env.example
│       ├── requirements.txt
│       ├── Dockerfile
│       └── README.md
│
├── n8n-workflows/
│   └── property-intake-guardrails-v1.json   # importable n8n workflow
│
├── open-webui/
│   └── test-n8n-submit.py   # Open WebUI Filter function (paste into UI)
│
└── CLAUDE.md                # this file
```

---

## Services

| Service | Port | Key endpoint |
|---------|------|-------------|
| LangGraph Agent | 9000 | `POST /analyze` |
| Guardrails | 9001 | `POST /check/input`, `POST /check/output` |

### Running locally

```bash
# LangGraph Agent
cd services/langgraph-agent
source .venv/bin/activate
uvicorn main:server --port 9000 --reload

# Guardrails
cd services/guardrails
source .venv/bin/activate
uvicorn main:server --port 9001 --reload
```

Each service has its own `.venv` and `.env` (copy from `.env.example`).

### n8n (Docker)

n8n runs in Docker on port 5678. It reaches the local services via `host.docker.internal`:
- `http://host.docker.internal:9000/analyze`
- `http://host.docker.internal:9001/check/input`
- `http://host.docker.internal:9001/check/output`

Import a workflow: n8n UI → open workflow → ⋯ menu → Import from file → select from `n8n-workflows/`.

---

## n8n Workflow — Property Intake Flow

```
Webhook → Respond(jobId) + Insert row (pending)
               ↓
         Guardrails Input Check   (reject spam / off-topic)
               ↓
         Input Valid? (IF node)
          true ──────────────────────── false
           ↓                               ↓
     LangGraph Analyze            Update row (rejected)
           ↓
     Route Response (Code node)
           ↓
     Guardrails Output Check   (flag false claims)
           ↓
     Update row(s) — status: done / flagged
           ↓
     No Operation
```

### Workflow versioning

Workflow JSON files live in `n8n-workflows/` and follow the naming convention:
```
property-intake-<feature>-v<N>.json
```

---

## Commit Convention

Use **Conventional Commits**:

```
<type>(<scope>): <short summary>
```

| Type | When to use |
|------|------------|
| `feat` | new feature or service |
| `fix` | bug fix |
| `chore` | rename, move, config, deps |
| `docs` | documentation only |
| `refactor` | code change with no behaviour change |
| `test` | adding or fixing tests |

**Rules:**
- Summary in imperative mood, lowercase, no period
- Under 72 characters
- No `Co-Authored-By: Claude` or AI attribution
- Never `--no-verify`

**Examples:**
```
feat(guardrails): add NeMo guardrails service with input and output validation
fix(langgraph): load .env before LLMRails initialization
chore(n8n): move workflow files into n8n-workflows directory
```

---

## Environment Variables

Each service reads from its own `.env` file (loaded automatically via `python-dotenv`).

| Variable | Used by |
|----------|---------|
| `OPENAI_API_KEY` | langgraph-agent, guardrails |
| `PINECONE_API_KEY` | langgraph-agent |
| `LANGCHAIN_TRACING_V2` | langgraph-agent (optional, LangSmith) |
| `LANGCHAIN_API_KEY` | langgraph-agent (optional, LangSmith) |
| `LANGCHAIN_PROJECT` | langgraph-agent (optional, LangSmith) |
