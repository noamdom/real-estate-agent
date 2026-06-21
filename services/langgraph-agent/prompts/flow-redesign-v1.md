# Flow Redesign — v1
# "Give the analyst everything it needs"

**Status:** Implemented
**Covers:** n8n sequence changes, new `/analyze` API contract, new LangGraph state fields, new graph nodes

---

## What the current data reveals

From `assets/properties - Sheet1.csv`:

| Signal | Current state |
|---|---|
| `image_analysis` | Plain string: `"Room: kitchen \| Condition: 0.901/1.0 \| Confidence: 95%"` — unparsed |
| Jobs without images | Always `PASS`, reasoning: "comparable data is lacking" |
| Jobs with images | Sometimes `NEGOTIATE` — image data demonstrably changes the outcome |
| `confidence` | Binary in practice: always `0.8` or `1.0` — not actually graduated |
| `result` free text | Every single entry says "comparable data is lacking" — Pinecone comps not reaching LLM meaningfully |
| `recommendation` | Only `PASS` or `NEGOTIATE` seen — `BUY` and `RENT` never produced |

**Root cause:** LangGraph runs before images. The analyst gets no image data, no parsed comp prices,
and no description. It is generating recommendations with almost no real signal.

---

## New n8n Flow Sequence

### Current (broken) order
```
Guardrails Input → LangGraph Analyze → Update Sheets → Image Analyser → Route Response → Guardrails Output → Update Sheets
```

### New order
```
Guardrails Input
      │
      ▼
Image Analyser  (if images present — run BEFORE LangGraph)
      │
      ▼
Parse Image JSON  (Code node: string → structured array)
      │
      ▼
LangGraph Analyze  (receives image data + all structured fields)
      │
      ▼
Guardrails Output
      │
      ▼
Router  (residential vs commercial, from result.team)
      │
      ▼
Update Sheets  (single write, full result)
```

### Why this order
- LangGraph must receive image condition scores **before** writing its analysis
- The image analyser output is small and fast — no reason to defer it
- A single Sheets write at the end is cleaner than two partial writes

---

## New `/analyze` API — Input Schema

The n8n HTTP node calling `POST :9000/analyze` must send:

```json
{
  "property_type": "apartment",
  "location": "Tel Aviv, Florentin",
  "description": "Renovated 3-room apartment, bright and quiet. New kitchen...",
  "agent_name": "John Doe",
  "price_asking": 3000000,
  "size_sqm": 85,
  "num_rooms": 3,
  "condition": "renovated",
  "intent": "sell",
  "image_analysis": [
    { "room_type": "kitchen", "condition_score": 0.901, "confidence": 0.95 },
    { "room_type": "bedroom", "condition_score": 0.697, "confidence": 0.46 }
  ]
}
```

### `image_analysis` field notes
- Array of objects, one per analysed image. Pass `[]` if no images.
- `condition_score`: float 0.0–1.0 from the image analyser service
- `confidence`: float 0.0–1.0 model classification confidence
- The n8n **Parse Image JSON** Code node must convert the current string format
  `"Room: kitchen | Condition: 0.901/1.0 | Confidence: 95%"` into this structure before calling `/analyze`
- `price_asking` may be null — LangGraph will estimate from comps; no separate flag needed

---

## New LangGraph State Fields

### New TypedDict

```python
class ImageResult(TypedDict):
    room_type:       str    # "kitchen" | "bedroom" | "bathroom" | "living_room" | "exterior" | "other"
    condition_score: float  # 0.0–1.0
    confidence:      float  # model confidence 0.0–1.0
```

### Updated `PropertyState` — 4 new fields only

```python
class PropertyState(TypedDict):
    # --- unchanged ---
    raw_payload:           dict
    normalized:            Optional[NormalizedFields]
    intent:                Optional[str]
    confidence:            Optional[float]
    missing_fields:        List[str]
    rag_comps:             List[RagComp]
    analysis:              Optional[Analysis]
    status:                Optional[str]

    # --- new ---
    image_analysis:  List[ImageResult]  # empty list when no images submitted
    estimated_price: Optional[float]    # market estimate from comps; null if < 2 usable comps
    deal_score:      float              # 0.0–10.0 additive score; 0.0 when no signals present
    team:            Optional[str]      # "residential" | "commercial" | "unknown"

    # rag_comps stays in state (used by pricing_node and analyst_node internally)
    # but is NOT returned in the /analyze HTTP response — its value is already
    # encoded in deal_score, estimated_price, and analysis.pricing_opinion
```

**Removed vs earlier draft:** `price_supplied`, `price_per_sqm_avg`, `market_position`, `score_confidence`
— all four eliminated by the "missing = 0 contribution" scoring model below.

### Updated `Analysis` TypedDict — one field added

```python
class Analysis(TypedDict):
    market_context:      str
    property_assessment: str
    pricing_opinion:     str  # states estimated market price when asking price not given
    recommendation:      str  # "NEGOTIATE — 8% above comp avg" | "BUY" | "RENT" | "PASS"
    expected_timeline:   str
    image_summary:       str  # "" when no images
```

---

## New Graph — Node Sequence

```
intake_node
    │
classifier_node
    │
confidence_node      ← price removed from REQUIRED_FIELDS
    │
    ├── score >= 0.4 ──► rag_node ──► pricing_node ──► analyst_node ──► output_node
    │
    └── score < 0.4 ──► clarify_node ────────────────────────────────► output_node
```

### Confidence threshold
Changed from `>= 0.5` to `>= 0.4`.
`price_asking` demoted from `REQUIRED_FIELDS` to `IMPORTANT_FIELDS` (penalises score but does not
block analysis — pricing_node will estimate from comps instead).

---

## New node: `pricing_node`

Inserted between `rag_node` and `analyst_node`. **No LLM call — pure arithmetic.**

### deal_score — additive, missing signal = 0 contribution

```
deal_score = price_score + image_score + condition_score + velocity_score

price_score  (0–4 pts)
  requires: price_asking is not None AND >= 2 comps with price_sold + size_sqm
  comp_avg_per_sqm = avg(price_sold / size_sqm) across valid comps
  deviation    = (price_asking / size_sqm - comp_avg_per_sqm) / comp_avg_per_sqm
  price_score  = 4 × clamp(1 - deviation / 0.30, 0, 1)
  missing any input → 0

image_score  (0–3 pts)
  requires: len(image_analysis) > 0
  image_score = 3 × mean(r.condition_score for r in image_analysis)
  no images → 0

condition_score  (0–2 pts)
  requires: normalized.condition is not None
  "new" | "renovated" | "excellent"  → 2.0
  "good"                             → 1.5
  "fair"                             → 1.0
  "poor" | "needs renovation"        → 0.5
  None or unrecognised               → 0

velocity_score  (0–1 pt)
  requires: >= 2 comps with days_on_market
  avg_dom    = mean(c.days_on_market for c in rag_comps)
  vel_score  = 1 - clamp(avg_dom / 90, 0, 1)
  missing → 0

deal_score = clamp(sum of above, 0.0, 10.0)
```

### estimated_price

```
if >= 2 comps have both price_sold and size_sqm:
    estimated_price = comp_avg_per_sqm × normalized.size_sqm
else:
    estimated_price = None
```

No other derived fields — `market_position`, `price_per_sqm_avg`, `price_supplied` are not stored in state.
The analyst prompt receives `estimated_price` and `deal_score` and derives its own narrative from them.

### team routing

```
RESIDENTIAL = {"apartment", "house", "villa", "penthouse", "duplex", "studio", "cottage"}
COMMERCIAL  = {"office", "retail", "industrial", "warehouse", "commercial", "shop", "co-working"}

team = "residential" if property_type in RESIDENTIAL
     | "commercial"  if property_type in COMMERCIAL
     | "unknown"     otherwise
```

---

## Deal score in practice

| Scenario | price | image | condition | velocity | total |
|---|---|---|---|---|---|
| Below-market price, great images, renovated, fast sub-market | 3.8 | 2.7 | 2.0 | 0.9 | **9.4** |
| Above-market, poor images, fair condition | 0.4 | 0.8 | 1.0 | 0.7 | **2.9** |
| No price, has images, good condition | 0 | 2.1 | 1.5 | 0.7 | **4.3** |
| No price, no images, text condition only | 0 | 0 | 2.0 | 0 | **2.0** |
| No signals at all | 0 | 0 | 0 | 0 | **0.0** |

A score of 2.0 honestly reflects "we only have a text condition field."
A score of 0.0 tells the analyst and downstream n8n nodes there is nothing to work with.

---

## New `/analyze` API — Output Schema

```json
{
  "intent": "sell",
  "confidence": 0.9,
  "status": "complete",
  "estimated_price": 2780000,
  "deal_score": 7.4,
  "team": "residential",
  "normalized": {
    "property_type": "apartment",
    "location": "Tel Aviv, Florentin",
    "size_sqm": 85,
    "num_rooms": 3,
    "price_asking": 3000000,
    "condition": "renovated",
    "agent_name": null
  },
  "image_analysis": [
    { "room_type": "kitchen", "condition_score": 0.901, "confidence": 0.95 }
  ],
  "analysis": {
    "market_context": "...",
    "property_assessment": "...",
    "pricing_opinion": "Asking price of 3,000,000 NIS is 8% above comp average of 32,706 NIS/sqm. Estimated market value: 2,780,000 NIS.",
    "recommendation": "NEGOTIATE — priced 8% above comp average",
    "expected_timeline": "...",
    "image_summary": "Kitchen in excellent condition (0.90/1.0)."
  },
  "missing_fields": []
}
```

---

## n8n Changes Required

### 1. Move Image Analyser before LangGraph
Reorder nodes. Image Analyser must complete before the LangGraph HTTP call.

### 2. Handle the no-image branch explicitly
The existing `Has Image File?` IF node must be kept. On the **false** branch, set
`image_analysis` to an empty array `[]` so the LangGraph HTTP body always includes the field.

```js
// Code node — no-image path
return [{ json: { image_analysis: [] } }];
```

### 3. Add Parse Image JSON Code node (image path only)
The image analyser at `:9002/analyse` returns a JSON object per call:
```json
{ "room_type": "kitchen", "condition_score": 0.901, "confidence": 0.95 }
```
The Code node must collect all per-image results into one array for LangGraph:
```js
// Code node — after image analyser, before LangGraph
const results = items.map(item => ({
  room_type:       item.json.room_type,
  condition_score: item.json.condition_score,
  confidence:      item.json.confidence,
}));
return [{ json: { image_analysis: results } }];
```
If the service returns a single aggregated string (`"Room: kitchen | Condition: 0.901/1.0 | Confidence: 95%"`)
parse it with a regex instead:
```js
const raw = item.json.image_analysis || "";
const m = raw.match(/Room:\s*(\w+)\s*\|\s*Condition:\s*([\d.]+)\/1\.0\s*\|\s*Confidence:\s*([\d]+)%/i);
return m ? [{ json: { image_analysis: [{ room_type: m[1].toLowerCase(), condition_score: parseFloat(m[2]), confidence: parseFloat(m[3]) / 100 }] } }] : [{ json: { image_analysis: [] } }];
```

### 4. Include `image_analysis` in the LangGraph request body
The HTTP node calling `POST :9000/analyze` must merge all form fields + `image_analysis` array:
```json
{
  "property_type":  "{{ $('Webhook').item.json.property_type }}",
  "location":       "{{ $('Webhook').item.json.location }}",
  "description":    "{{ $('Webhook').item.json.description }}",
  "price_asking":   "{{ $('Webhook').item.json.price_asking }}",
  "size_sqm":       "{{ $('Webhook').item.json.size_sqm }}",
  "num_rooms":      "{{ $('Webhook').item.json.num_rooms }}",
  "condition":      "{{ $('Webhook').item.json.condition }}",
  "intent":         "{{ $('Webhook').item.json.intent }}",
  "image_analysis": "{{ $('Parse Image JSON').item.json.image_analysis }}"
}
```

### 5. Add Router node after LangGraph
Read `team` from response. Route:
- `residential` → residential team path
- `commercial` → commercial team path
- `unknown` → manual review

Condition expression: `{{ $json.team === 'residential' }}`

### 6. Update Google Sheets write node — columns

**New columns to add:**
| Column | Value expression |
|---|---|
| `team` | `{{ $json.team }}` |
| `deal_score` | `{{ $json.deal_score }}` |
| `estimated_price` | `{{ $json.estimated_price }}` |
| `analysis` | `{{ JSON.stringify($json.analysis) }}` — serialize the full object |

**Existing columns to update:**
| Column | Old value | New value |
|---|---|---|
| `recommendation` | `$json.recommendation` (bare word) | `{{ $json.analysis.recommendation }}` |
| `image_analysis` | plain string from image service | `{{ JSON.stringify($json.image_analysis) }}` |
| `result` | markdown blob | leave empty for new rows — `analysis` column replaces it |

Removed vs earlier draft: `market_position`, `price_supplied`, `price_per_sqm_avg` — not stored or surfaced.

---

## New LangGraph tests recommended

Two tests to add to the `langgraph` group in `tests/e2e/run_tests.sh`:

### Test 1 — with `image_analysis` populated
Verifies the image scoring path contributes to `deal_score` and that `image_summary` is non-empty.

```bash
LG_WITH_IMAGE=$(curl -sf -X POST "$LANGGRAPH_URL/analyze" \
  -H "Content-Type: application/json" \
  --max-time 90 \
  --data-raw '{
    "property_type": "apartment",
    "location": "Tel Aviv, Florentin",
    "description": "Renovated 3-room apartment, bright and quiet.",
    "price_asking": 3000000,
    "size_sqm": 85,
    "num_rooms": 3,
    "condition": "renovated",
    "intent": "sell",
    "image_analysis": [
      { "room_type": "kitchen",  "condition_score": 0.901, "confidence": 0.95 },
      { "room_type": "bedroom",  "condition_score": 0.697, "confidence": 0.46 }
    ]
  }')
# assert: deal_score > 0 (image component fired)
# assert: analysis.image_summary is non-empty string
# assert: team == "residential"
```

**Why:** Without this test, the image scoring path (`image_score` component of `deal_score`)
has no coverage. A regression that drops image data from the prompt would go undetected.

### Test 2 — no `price_asking` supplied
Verifies the system still produces a complete analysis (not routed to clarify), `estimated_price`
is populated from comps, and `deal_score` reflects the missing price component (price_score = 0).

```bash
LG_NO_PRICE=$(curl -sf -X POST "$LANGGRAPH_URL/analyze" \
  -H "Content-Type: application/json" \
  --max-time 90 \
  --data-raw '{
    "property_type": "apartment",
    "location": "Tel Aviv, Florentin",
    "description": "Renovated 3-room apartment, bright and quiet.",
    "size_sqm": 85,
    "num_rooms": 3,
    "condition": "renovated",
    "intent": "sell"
  }')
# assert: status == "complete"  (not "incomplete" — price alone must not block analysis)
# assert: estimated_price is present and > 0  (derived from comps)
# assert: deal_score >= 0 and deal_score <= 10
# assert: analysis.pricing_opinion mentions estimated price
```

**Why:** Before the redesign, missing price could drop confidence below threshold and route
to clarify. This test guards that the threshold relaxation and price estimation path work together.

---

## Files to change (LangGraph service)

| File | Change |
|---|---|
| `state.py` | Add `ImageResult`; add 4 new state fields; add `image_summary` to `Analysis` |
| `nodes.py` | `intake_node`: parse `image_analysis` from payload; add `pricing_node`; update `analyst_node` prompt |
| `graph.py` | Wire `pricing_node` between `rag_node` and `analyst_node`; lower threshold to 0.4; remove `price_asking` from `REQUIRED_FIELDS` |
| `main.py` | Add `image_analysis: List[dict]` to `SubmissionPayload`; surface `deal_score`, `estimated_price`, `team` in response; drop `clarification_message` from response |
| `prompts/analyst/v2.md` | New analyst prompt using pre-computed `deal_score`, `estimated_price`, and structured image data |
