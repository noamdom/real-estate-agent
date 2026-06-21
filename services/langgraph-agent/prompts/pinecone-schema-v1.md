# Pinecone RAG — Data Enrichment Spec v1

**Index:** `rag-properties`
**Embedding model:** `text-embedding-3-small`, 512 dimensions
**Status:** Current schema is minimal — retrieval works but metadata is too thin for meaningful analysis

---

## Current state (what's actually stored today)

### Metadata fields in Pinecone
| Field | Type | Used by |
|---|---|---|
| `location` | str | `analyst_node` comps_text |
| `price_sold` | float | `pricing_node` → `price_per_sqm_avg`, `estimated_price` |
| `size_sqm` | float | `pricing_node` → `price_per_sqm_avg` |
| `days_on_market` | int | `pricing_node` → `velocity_score` |

### Query text (what gets embedded at retrieval time)
```
"{property_type} in {location} {size_sqm} sqm {num_rooms} rooms"
```
Example: `"apartment in Tel Aviv, Florentin 85.0 sqm 3 rooms"`

### The gap
`property_type` and `num_rooms` drive the **retrieval** query but are not stored as metadata —
so comps come back with no type or room count for the analyst to compare against.
`location` is the only descriptive field. Every result looks like:
```
- Tel Aviv, 82sqm, sold 2,750,000 NIS, 18 days on market (similarity 0.88)
```
The analyst cannot tell if the comp was an apartment or a villa, renovated or poor, or how long ago it sold.

---

## Required fields — must have for the current logic to work properly

These fields are directly consumed by `pricing_node` or `analyst_node`.
Without them, deal_score components silently zero out or the analyst narrates without data.

| Field | Type | Used by | Why it's needed |
|---|---|---|---|
| `property_type` | str | `analyst_node` comps_text | Analyst says "similar apartments" not just "similar listings" |
| `num_rooms` | int | `analyst_node` comps_text | Enables room-count comparison — a 3-room vs 5-room comp is not equivalent |
| `condition` | str | `analyst_node` comps_text | Analyst can weight a "poor condition" comp differently from "renovated" |
| `sale_date` | str (ISO date) | `analyst_node` comps_text | Recency — a 2022 sale is far less relevant than a 2025 sale in a rising market |
| `price_listed` | float | `pricing_node`, `analyst_node` | Negotiation delta: `(price_listed - price_sold) / price_listed` shows typical discount in sub-market |
| `neighborhood` | str | retrieval query + `analyst_node` | Finer granularity than city — Florentin and Dizengoff are both "Tel Aviv" but different markets |

---

## Recommended fields — high value, low cost to source

| Field | Type | Benefit |
|---|---|---|
| `price_per_sqm` | float | Pre-computed at upsert (`price_sold / size_sqm`). Avoids division edge cases at query time and makes `pricing_node` simpler |
| `floor_number` | int | Floor significantly affects price (penthouse premium, ground floor discount). Helps analyst contextualise outlier comps |
| `has_parking` | bool | Common value driver. If subject has parking and comp doesn't, price comparison needs adjustment |
| `has_balcony` | bool | Same rationale as parking |
| `building_year` | int | Proxy for structural condition. A 1970s building vs 2020 new construction affects valuation |
| `city` | str | Separate from `neighborhood` — needed for city-level fallback when neighborhood-level comps are sparse |

---

## Full target schema

```json
{
  "id": "comp-00123",

  "metadata": {
    "property_type":  "apartment",
    "city":           "Tel Aviv",
    "neighborhood":   "Florentin",
    "location":       "Tel Aviv, Florentin",

    "size_sqm":       82.0,
    "num_rooms":      3,
    "floor_number":   3,
    "has_parking":    false,
    "has_balcony":    true,
    "building_year":  1985,
    "condition":      "renovated",

    "price_listed":   2900000,
    "price_sold":     2750000,
    "price_per_sqm":  33537,
    "days_on_market": 18,
    "sale_date":      "2025-03-14"
  }
}
```

---

## Embedding text — what to embed at upsert time

The embedded text must match the query format used at retrieval time.
Currently both use the same short string. Enriching it improves semantic matching.

### Current (too sparse)
```
"apartment in Tel Aviv, Florentin 82 sqm 3 rooms"
```

### Recommended
```
"{property_type}, {num_rooms} rooms, {size_sqm}sqm, {condition}, {neighborhood}, {city}"
```
Example:
```
"apartment, 3 rooms, 82sqm, renovated, Florentin, Tel Aviv"
```

**Also update `rag_node` query text to match:**
```python
query_text = (
    f"{norm.get('property_type', '')} {norm.get('num_rooms', '')} rooms "
    f"{norm.get('size_sqm', '')}sqm {norm.get('condition', '')} "
    f"{norm.get('location', '')}"
)
```

---

## Fields to add to `RagComp` TypedDict in `state.py`

```python
class RagComp(TypedDict):
    # existing
    id:               str
    location:         str
    price_sold:       float
    size_sqm:         float
    days_on_market:   int
    similarity_score: float

    # new
    property_type:  str
    num_rooms:      int
    condition:      str
    sale_date:      str
    price_listed:   float
    price_per_sqm:  float
    neighborhood:   str
```

And update `rag_node` metadata reads to pull all new fields.

---

## Updated comps_text for `analyst_node`

Once fields are available, the comp line the analyst sees becomes:

```
- Florentin, Tel Aviv | 3-room apartment, 82sqm, renovated | sold 2,750,000 NIS (listed 2,900,000 NIS) | 18 days on market | sold 2025-03-14 (similarity 0.88)
```

vs the current:
```
- Tel Aviv, 82sqm, sold 2,750,000 NIS, 18 days on market (similarity 0.88)
```

The analyst can now make statements like:
- "Comps show a typical negotiation discount of 5–6% from asking price in this sub-market"
- "All comparable renovated apartments sold within 3 weeks — strong demand signal"
- "The most recent comp sold in March 2025 at 33,537 NIS/sqm"

---

## Data sourcing options

| Source | Notes |
|---|---|
| Israeli real estate portals (Yad2, Madlan, WinWin) | Public listing and sold-price data. Scraping or manual export. |
| Israel Land Authority (רשות מקרקעי ישראל) | Official transaction registry. Published as CSV quarterly. Most reliable for `price_sold` and `sale_date`. |
| Manual synthetic dataset | Fastest for dev/demo. Generate 50–100 realistic records with a script. Sufficient for POC. |

**Minimum for a useful Pinecone index:** 30+ records covering at least 3 cities and 3 property types.
Fewer records = high chance of low similarity scores on every query, making comps meaningless.

---

## Upsert script changes needed

The existing population script must be updated to:
1. Include all new metadata fields
2. Compute `price_per_sqm` at upsert: `round(price_sold / size_sqm)`
3. Use the new embedding text format
4. Set `sale_date` in ISO format (`YYYY-MM-DD`)
