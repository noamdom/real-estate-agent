# LangGraph Property Analysis Service

```bash
cp .env.example .env        # fill in OPENAI_API_KEY and PINECONE_API_KEY
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:server --port 9000 --reload                   # normal
uvicorn main:server --port 9000 --reload --log-level debug # debug
```

> `.env` is loaded automatically at startup — no need to export variables manually.

Test:

```bash
python test_analyze.py
```

## Observability

**Console logs** — printed automatically on every request:
```
14:03:01  INFO   [intake]      type=apartment    location=Tel Aviv, Florentin   price=3000000.0  size=85.0 sqm  rooms=3
14:03:01  INFO   [classifier]  intent=sell       method=keyword  hits={'sale'}
14:03:01  INFO   [confidence]  score=0.90  missing=none  → rag_node
14:03:02  INFO   [rag]         comps=3  query='apartment in Tel Aviv, Florentin 85.0 sqm 3 rooms'
14:03:04  INFO   [analyst]     calling LLM  comps=3  intent=sell
14:03:06  INFO   [analyst]     recommendation=NEGOTIATE to 2950000 NIS
14:03:06  INFO   [output]      status=complete  intent=sell  confidence=0.9
```

**LangSmith** — full visual trace of every run (inputs, outputs, token usage per node).
Sign up at smith.langchain.com, then add to `.env`:
```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=property-triage
```

## Node Graph

```
POST /analyze
      │
      ▼
 intake_node          normalize & validate raw payload
      │
      ▼
 classifier_node      keyword scan → detect intent: sell | rent | unknown
      │
      ▼
 confidence_node      score 0.0–1.0 based on field completeness
      │
      ├── score >= 0.5 ──────────────────┐
      │                                  ▼
      │                            rag_node        query Pinecone → top-3 comps
      │                                  │
      │                                  ▼
      │                            analyst_node    LLM → full embassy analysis
      │                                  │
      └── score < 0.5 ───┐               │
                         ▼               │
                   clarify_node          │  identify missing fields,
                   (incomplete)          │  generate clarification message
                         │               │
                         └───────────────┘
                                  │
                                  ▼
                            output_node     format final JSON response
                                  │
                                  ▼
                          { intent, confidence, status,
                            normalized, rag_comps,
                            analysis, missing_fields,
                            clarification_message }
```
