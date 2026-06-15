## Handoff Summary — AI Property Triage Project

### Project Overview

Building an end-to-end AI pipeline for a property investment embassy that automates real estate listing intake, analysis, and acquisition recommendations. The full stack includes Open WebUI, n8n orchestration, LangGraph reasoning, Pinecone RAG, AWS Bedrock Knowledge Base, and EC2 microservices.

---

### What's Already Built and Working ✅

**Open WebUI (local)**

- Custom Filter function intercepts chat messages
- Guided intake via Ollama system prompt collects: `property_type`, `location`, `description`, `agent_name`, `price_asking`, `size_sqm`, `num_rooms`
- `[SUBMISSION_READY]` token triggers n8n webhook automatically
- Test function supports two trigger codes (`wewewe` = Tel Aviv apartment, `fdsfds` = Jerusalem villa)
- Polls n8n status endpoint every 10s, renders result as chat message

**n8n (local Docker, port 5678)**
Two separate published workflows:

_Workflow 1 — Property Intake:_

```
User Submit (POST /webhook/property-intake)
    ├──→ Respond immediately with { jobId, status: "received" }
    └──→ Insert pending row into dataTable (fp-req-status, id: nrnaFsR7FpzPdNm2)
              ↓
        Format Prompt (Code node)
              ↓
        AI Agent (OpenAI GPT, system prompt: embassy analyst)
              └── property_rag tool → Pinecone (rag-properties index)
                      └── Embeddings OpenAI
              ↓
        Update row → { status: "done", result: agent output, completedAt }
```

_Workflow 2 — Property Status:_

```
Submission Status (GET /webhook/property-status?jobId=XXX)
        ↓
Read row from dataTable by jobId
        ↓
Format Response (Code node)
        ↓
Respond → { status, result, jobId, location, propertyType, completedAt }
```

**n8n dataTable schema** (`fp-req-status`):

```
jobId | status | result | propertyType | location | completedAt
```

**Pinecone**

- Index: `rag-properties`
- 10 mock property listings embedded (Tel Aviv, Jerusalem, Haifa, Herzliya)
- Embeddings: OpenAI (512 dimensions)
- RAG retrieves 2-3 comparable listings by location/type/size

**AI Agent system prompt (embassy framing):**
Returns structured markdown with: Market Context, Property Assessment, Pricing Opinion, Embassy Recommendation (BUY / NEGOTIATE / RENT bills included / PASS), Expected Timeline

---

### What We're Building Next — LangGraph Service

**Purpose:**
Replace the current `Format Prompt + AI Agent` nodes in n8n with a smarter LangGraph service. It receives the raw submission payload from n8n, does multi-step reasoning, and returns a structured JSON that n8n uses to route the job.

**Key additions over current AI Agent:**

- Intent classification: sell vs rent
- Confidence scoring: how complete/reliable is the submission
- Conditional routing: high confidence → full RAG analysis, low confidence → clarification request back to user
- RAG enrichment as a tool call, not hardwired
- Structured JSON output (not markdown) so n8n can route programmatically

---

### LangGraph Node Graph

```
intake_node
    ↓
classifier_node        # detect intent: sell | rent | unknown
    ↓
confidence_node        # score 0.0–1.0 based on field completeness + quality
    ↓
┌───┴────────────────┐
↓ (score >= 0.5)     ↓ (score < 0.5)
rag_node          clarify_node
    ↓                  ↓
analyst_node      output_node
    ↓
output_node
```

**Node responsibilities:**

| Node              | Job                                                                               |
| ----------------- | --------------------------------------------------------------------------------- |
| `intake_node`     | Normalize and validate raw payload, standardize field names                       |
| `classifier_node` | Use LLM to detect intent (sell/rent) from property_type + description             |
| `confidence_node` | Score completeness: required fields present, price reasonable, location parseable |
| `rag_node`        | Query Pinecone with location + type + size, return top 3 comps                    |
| `clarify_node`    | Identify missing fields, generate friendly clarification message                  |
| `analyst_node`    | Full embassy analysis using normalized fields + RAG comps                         |
| `output_node`     | Format final structured JSON response                                             |

---

### Structured Output Schema (returned to n8n)

**Complete submission:**

```json
{
  "intent": "sell",
  "confidence": 0.85,
  "status": "complete",
  "normalized": {
    "property_type": "apartment",
    "location": "Tel Aviv, Florentin",
    "size_sqm": 85,
    "num_rooms": 3,
    "price_asking": 3000000,
    "condition": "renovated",
    "agent_name": "Noam Cohen"
  },
  "rag_comps": [
    {
      "id": "listing_001",
      "location": "Tel Aviv, Florentin",
      "price_sold": 2850000,
      "size_sqm": 82,
      "days_on_market": 18,
      "similarity_score": 0.94
    }
  ],
  "analysis": {
    "market_context": "...",
    "property_assessment": "...",
    "pricing_opinion": "...",
    "recommendation": "NEGOTIATE to 2950000 NIS",
    "expected_timeline": "2-4 weeks for offer, 4-8 weeks to close"
  },
  "missing_fields": [],
  "clarification_message": null
}
```

**Incomplete submission:**

```json
{
  "intent": "unknown",
  "confidence": 0.3,
  "status": "incomplete",
  "normalized": { ... },
  "rag_comps": [],
  "analysis": null,
  "missing_fields": ["location", "price_asking"],
  "clarification_message": "Could you provide the property location and asking price? This will help us find comparable listings."
}
```

---

### Tech Stack for LangGraph Service

| Component    | Choice                                            |
| ------------ | ------------------------------------------------- |
| Framework    | LangGraph `>= 0.2` with `StateGraph` API          |
| LLM          | OpenAI GPT (same credentials as n8n)              |
| RAG          | Pinecone Python client (both sell + rent for now) |
| API wrapper  | FastAPI, `POST /analyze`                          |
| Runtime      | Local Python for now, Docker + EC2 later          |
| State schema | TypedDict with all fields above                   |

---

### How n8n Integrates with LangGraph

Replace `Format Prompt` Code node with an **HTTP Request node** in n8n:

```
User Submit
    ├──→ Respond immediately with jobId
    └──→ Insert pending row
              ↓
        HTTP Request → POST http://localhost:8000/analyze
              ↓
        Code node: route based on response
          if status == "incomplete" → update row with clarification_message
          if intent == "sell"       → update row with full analysis
          if intent == "rent"       → update row with full analysis (AWS KB later)
              ↓
        Update row → status: done
```

---

### Mock Rental Data (to build before AWS KB)

Need ~10 rental listing text files similar to the sales mock data, covering:

- Tel Aviv (Florentin, Old North, Neve Tzedek)
- Jerusalem (Rehavia, German Colony)
- Monthly price in NIS, bills included vs excluded
- Property type, size, condition, lease terms

These get embedded into Pinecone temporarily under a `rental` metadata tag, then migrated to AWS Bedrock Knowledge Base when ready.

---

### What to Ask Claude to Build

> "Build the full LangGraph property analysis service based on this handoff. Use StateGraph >= 0.2 with these nodes: intake_node, classifier_node, confidence_node, rag_node, clarify_node, analyst_node, output_node. Wrap it with FastAPI exposing POST /analyze. LLM is OpenAI GPT. RAG uses Pinecone Python client querying the rag-properties index. State schema uses TypedDict. Return the structured JSON output defined in the handoff. Also write a requirements.txt and a test script that calls /analyze with two mock payloads — one sell (Tel Aviv apartment) and one rent (Jerusalem villa)."
