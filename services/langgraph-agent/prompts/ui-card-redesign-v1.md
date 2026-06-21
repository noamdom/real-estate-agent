# UI Card Redesign — v1
# Property card field mapping for the new analysis schema

**File:** `services/gradio-ui/properties.py`
**Card built at:** lines 182–227
**Status:** Design spec — not yet implemented

---

## Current card — what it reads and how

| Field from row `r` | Displayed as | Problem |
|---|---|---|
| `image_urls` | image carousel (left panel) | fine — keep |
| `property_type` | card title | fine — keep |
| `location` | card title | fine — keep |
| `price_asking` | 💰 chip | keep, but pair with estimated_price |
| `num_rooms` | 🛏 chip | fine — keep |
| `size_sqm` | 📐 chip | fine — keep |
| `condition` | 🔧 chip | fine — keep |
| `intent` | plain text label | fine — keep |
| `recommendation` | coloured badge (BUY/NEGOTIATE/RENT/PASS) | replace — now embedded in `analysis.recommendation` with justification |
| `result` | parsed with `_parse_sections()` for "Embassy Recommendation" and "Market Context" | fragile markdown parsing — replace with structured fields |

**`_parse_sections()` is the main fragility.** It regex-splits a free-text markdown blob looking
for `**Embassy Recommendation:**` and `**Market Context:**` headings. Any change in LLM phrasing
breaks the display. The new schema eliminates this entirely.

---

## New card — field mapping

### Fields to keep (unchanged source column)
| Field | Display |
|---|---|
| `image_urls` | carousel — unchanged |
| `property_type` | card title |
| `location` | card title |
| `num_rooms` | 🛏 chip |
| `size_sqm` | 📐 chip |
| `condition` | 🔧 chip |
| `intent` | label |

### Fields to replace or add

| Old | New | Display |
|---|---|---|
| `price_asking` alone | `price_asking` + `estimated_price` | 💰 asking price, then `≈ X NIS est.` in muted text below if estimated differs |
| `recommendation` badge | `analysis.recommendation` | coloured badge — read the first word (BUY/NEGOTIATE/RENT/PASS) for colour; show full string as tooltip or sub-line |
| `result` markdown blob | `analysis.market_context` | section block — direct string, no parsing |
| `result` markdown blob | `analysis.pricing_opinion` | section block — direct string, no parsing |
| `result` markdown blob | `analysis.image_summary` | section block — only shown when non-empty |
| *(none)* | `deal_score` | score bar or numeric badge `7.4 / 10` |
| *(none)* | `team` | small pill badge: `Residential` or `Commercial` |

### Fields to drop from the card
| Field | Reason |
|---|---|
| `result` (raw markdown) | replaced by individual `analysis.*` fields |
| `confidence` | internal scoring artifact — not meaningful to a UI user |
| `clarification_message` | dropped from schema entirely |

---

## Suggested card layout (right panel, top → bottom)

```
┌─────────────────────────────────────────────────────────────┐
│  Apartment — Tel Aviv, Florentin          [Residential] pill │
│  🛏 3 rooms  📐 85 sqm  🔧 Renovated  Intent: Sell          │
│  💰 3,000,000 NIS   ≈ 2,780,000 NIS est.                    │
│  [NEGOTIATE — 8% above comp avg]  score: ████████░░ 7.4/10  │
│  ─────────────────────────────────────────────────────────── │
│  Market Context                                              │
│  The Florentin sub-market shows strong demand...             │
│  ─────────────────────────────────────────────────────────── │
│  Pricing Opinion                                             │
│  Asking price is 8% above the comp average of 32,706 NIS/sqm│
│  ─────────────────────────────────────────────────────────── │
│  Image Analysis           (only if image_summary non-empty)  │
│  Kitchen in excellent condition (0.90/1.0).                  │
└─────────────────────────────────────────────────────────────┘
```

---

## `_rec_badge` — update needed

Currently reads `r.get("recommendation")` which is a plain word (`PASS`, `NEGOTIATE`).
After the redesign `analysis.recommendation` is a full string:
`"NEGOTIATE — asking price is 8% above comp average"`

The badge function must:
1. Split on the first space to get the keyword for colour lookup
2. Display the full string as the badge label (or truncate to fit)

```python
# current
rec_raw = r.get("recommendation") or ""

# new
rec_raw = (r.get("analysis") or {}).get("recommendation") or ""
rec_keyword = rec_raw.split()[0] if rec_raw else ""   # "NEGOTIATE", "BUY", etc.
```

---

## `_parse_sections` — remove entirely

Replace every `sections.get(...)` call with direct reads from `r.get("analysis", {})`:

```python
# current (fragile)
sections    = _parse_sections(r.get("result") or "")
embassy_rec = sections.get("Embassy Recommendation", "")
market_ctx  = sections.get("Market Context", "")

# new (direct)
analysis      = r.get("analysis") or {}
market_ctx    = analysis.get("market_context", "")
pricing_op    = analysis.get("pricing_opinion", "")
image_summary = analysis.get("image_summary", "")
rec_raw       = analysis.get("recommendation", "")
```

---

## New Google Sheets columns the UI reads

The Gradio UI reads from the `/properties` endpoint which queries Google Sheets.
These columns must exist in the sheet for the new card to render correctly:

| Column | Type | Source |
|---|---|---|
| `analysis` | JSON string | LangGraph `/analyze` response → `analysis` object |
| `deal_score` | float | LangGraph → `deal_score` |
| `estimated_price` | float | LangGraph → `estimated_price` |
| `team` | string | LangGraph → `team` |

The `result` column (markdown blob) can be kept for backwards compatibility with old rows
but new rows will not use it for display.

---

## Files to change

| File | Change |
|---|---|
| `properties.py` | Replace `_parse_sections` call with direct `analysis` dict reads; update `_rec_badge` call; add `deal_score` bar, `estimated_price`, `team` pill, `image_summary` block |
| `properties_router.py` | Ensure `/properties` endpoint returns `analysis`, `deal_score`, `estimated_price`, `team` from Sheets |
