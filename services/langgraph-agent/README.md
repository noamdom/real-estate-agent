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
 intake_node          normalize payload; parse image_analysis array
      │
      ▼
 classifier_node      keyword scan → detect intent: sell | rent | unknown
      │
      ▼
 confidence_node      score 0.0–1.0 (price_asking not required)
      │
      ├── score >= 0.4 ──────────────────┐
      │                                  ▼
      │                            rag_node        query Pinecone → top-3 comps
      │                                  │
      │                                  ▼
      │                            pricing_node    arithmetic: deal_score, estimated_price, team
      │                                  │
      │                                  ▼
      │                            analyst_node    LLM → full embassy analysis
      │                                  │
      └── score < 0.4 ───┐               │
                         ▼               │
                   clarify_node          │  status=incomplete, missing_fields set
                   (incomplete)          │
                         │               │
                         └───────────────┘
                                  │
                                  ▼
                            output_node     finalize status
                                  │
                                  ▼
                          { intent, confidence, status,
                            team, deal_score, estimated_price,
                            normalized, image_analysis,
                            analysis, missing_fields }
```
