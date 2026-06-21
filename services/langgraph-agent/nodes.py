from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional, List

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pinecone import Pinecone

from state import PropertyState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("langgraph")

_llm = None
_embeddings = None
_pinecone_index = None

# price_asking intentionally excluded — missing price does not block analysis;
# pricing_node estimates from comps instead.
REQUIRED_FIELDS = ["property_type", "location", "size_sqm", "num_rooms"]

_RESIDENTIAL = {"apartment", "house", "villa", "penthouse", "duplex", "studio", "cottage"}
_COMMERCIAL  = {"office", "retail", "industrial", "warehouse", "commercial", "shop", "co-working"}

_CONDITION_SCORES = {
    "new": 2.0, "renovated": 2.0, "excellent": 2.0,
    "good": 1.5,
    "fair": 1.0,
    "poor": 0.5, "needs renovation": 0.5,
}


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        log.info("_get_llm init — key prefix: %s", (api_key or "")[:8] or "MISSING")
        _llm = ChatOpenAI(model="gpt-4.1-nano", temperature=0, api_key=api_key)
    return _llm


def _get_embeddings() -> OpenAIEmbeddings:
    global _embeddings
    if _embeddings is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        log.info("_get_embeddings init — key prefix: %s", (api_key or "")[:8] or "MISSING")
        _embeddings = OpenAIEmbeddings(model="text-embedding-3-small", dimensions=512, api_key=api_key)
    return _embeddings


def _get_pinecone_index():
    global _pinecone_index
    if _pinecone_index is None:
        pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        _pinecone_index = pc.Index("rag-properties")
    return _pinecone_index


def _call_llm_json(system: str, user: str) -> Any:
    from langchain_core.messages import HumanMessage, SystemMessage
    llm = _get_llm()
    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


# ── Node 1 ────────────────────────────────────────────────────────────────────

def intake_node(state: PropertyState) -> PropertyState:
    """Normalize raw payload and parse image_analysis into typed list."""
    raw = state["raw_payload"]

    normalized = {
        "property_type": raw.get("property_type") or raw.get("propertyType"),
        "location": raw.get("location"),
        "size_sqm": _to_float(raw.get("size_sqm") or raw.get("sizeSqm")),
        "num_rooms": _to_int(raw.get("num_rooms") or raw.get("numRooms")),
        "price_asking": _to_float(raw.get("price_asking") or raw.get("priceAsking")),
        "condition": raw.get("condition"),
        "agent_name": raw.get("agent_name") or raw.get("agentName"),
    }

    raw_images = raw.get("image_analysis") or []
    image_analysis = []
    for img in raw_images:
        if isinstance(img, dict):
            image_analysis.append({
                "room_type": str(img.get("room_type", "other")),
                "condition_score": _to_float(img.get("condition_score")) or 0.0,
                "confidence": _to_float(img.get("confidence")) or 0.0,
            })

    log.info(
        "[intake]      type=%-12s  location=%-20s  price=%s  size=%s sqm  rooms=%s  images=%d",
        normalized.get("property_type") or "?",
        normalized.get("location") or "?",
        normalized.get("price_asking") or "?",
        normalized.get("size_sqm") or "?",
        normalized.get("num_rooms") or "?",
        len(image_analysis),
    )
    return {**state, "normalized": normalized, "image_analysis": image_analysis}


# ── Node 2 ────────────────────────────────────────────────────────────────────

_RENT_KEYWORDS = {
    "rent", "rental", "renting", "tenant", "tenants", "lease", "leasing",
    "monthly", "per month", "pcm",
    "שכירות", "לשכירות", "שוכר", "שכר",
}

_SELL_KEYWORDS = {
    "sell", "sale", "selling", "for sale", "purchase", "buyer",
    "asking price", "list price", "freehold",
    "מכירה", "למכירה", "מוכר",
}


def classifier_node(state: PropertyState) -> PropertyState:
    """Detect intent (sell | rent | unknown) without an LLM call."""
    raw = state["raw_payload"]

    explicit = (raw.get("intent") or "").strip().lower()
    if explicit in ("sell", "rent"):
        log.info("[classifier]  intent=%-8s  method=explicit", explicit)
        return {**state, "intent": explicit}

    haystack = " ".join(filter(None, [
        raw.get("description", ""),
        raw.get("property_type", ""),
    ])).lower()

    words = set(haystack.split())
    rent_hits = words & _RENT_KEYWORDS
    sell_hits = words & _SELL_KEYWORDS

    if rent_hits and not sell_hits:
        intent = "rent"
    elif sell_hits and not rent_hits:
        intent = "sell"
    elif sell_hits and rent_hits:
        intent = "rent" if len(rent_hits) >= len(sell_hits) else "sell"
    else:
        intent = "unknown"

    log.info("[classifier]  intent=%-8s  method=keyword  hits=%s", intent, (rent_hits | sell_hits) or "none")
    return {**state, "intent": intent}


# ── Node 3 ────────────────────────────────────────────────────────────────────

def confidence_node(state: PropertyState) -> PropertyState:
    """Score completeness 0.0–1.0; collect missing required fields."""
    norm = state["normalized"]

    missing = [f for f in REQUIRED_FIELDS if not norm.get(f)]
    present = len(REQUIRED_FIELDS) - len(missing)
    field_score = present / len(REQUIRED_FIELDS)

    intent_penalty = 0.1 if state.get("intent") == "unknown" else 0.0

    price = norm.get("price_asking") or 0
    price_penalty = 0.1 if 0 < price < 100 else 0.0

    score = max(0.0, round(field_score - intent_penalty - price_penalty, 2))

    log.info("[confidence]  score=%.2f  missing=%s  → %s",
             score, missing or "none",
             "rag_node" if score >= 0.4 else "clarify_node")
    return {**state, "confidence": score, "missing_fields": missing}


# ── Node 4a ───────────────────────────────────────────────────────────────────

def rag_node(state: PropertyState) -> PropertyState:
    """Query Pinecone with location + type + size, return top-3 comps."""
    norm = state["normalized"]

    query_text = (
        f"{norm.get('property_type', '')} {norm.get('num_rooms', '')} rooms "
        f"{norm.get('size_sqm', '')}sqm {norm.get('condition', '')} "
        f"{norm.get('location', '')}"
    )

    try:
        embeddings = _get_embeddings()
        vector = embeddings.embed_query(query_text)
        index = _get_pinecone_index()
        results = index.query(vector=vector, top_k=3, include_metadata=True)

        comps = []
        for match in results.get("matches", []):
            meta = match.get("metadata", {})
            price_sold = float(meta.get("price_sold", 0))
            size_sqm   = float(meta.get("size_sqm", 0))
            stored_psm = float(meta.get("price_per_sqm", 0))
            price_per_sqm = stored_psm if stored_psm else (
                round(price_sold / size_sqm) if size_sqm else 0
            )
            comps.append({
                "id":               match["id"],
                "location":         meta.get("location", ""),
                "neighborhood":     meta.get("neighborhood", ""),
                "property_type":    meta.get("property_type", ""),
                "num_rooms":        int(meta.get("num_rooms", 0)),
                "condition":        meta.get("condition", ""),
                "size_sqm":         size_sqm,
                "price_sold":       price_sold,
                "price_listed":     float(meta.get("price_listed", 0)),
                "price_per_sqm":    price_per_sqm,
                "days_on_market":   int(meta.get("days_on_market", 0)),
                "sale_date":        meta.get("sale_date", ""),
                "similarity_score": round(float(match["score"]), 4),
            })
    except Exception as exc:
        log.warning("[rag]         Pinecone query failed: %s — continuing without comps", exc)
        comps = []

    log.info("[rag]         comps=%d  query=%r", len(comps), query_text[:60])
    return {**state, "rag_comps": comps}


# ── Node 4b ───────────────────────────────────────────────────────────────────

def pricing_node(state: PropertyState) -> PropertyState:
    """Compute deal_score, estimated_price, and team — no LLM call."""
    norm     = state["normalized"]
    comps    = state.get("rag_comps", [])
    images   = state.get("image_analysis", [])

    # ── team ──────────────────────────────────────────────────────────────────
    ptype = (norm.get("property_type") or "").lower().strip()
    if ptype in _RESIDENTIAL:
        team = "residential"
    elif ptype in _COMMERCIAL:
        team = "commercial"
    else:
        team = "unknown"

    # ── estimated_price ───────────────────────────────────────────────────────
    valid_comps = [c for c in comps if c.get("price_per_sqm") or (c.get("price_sold") and c.get("size_sqm"))]
    if len(valid_comps) >= 2:
        price_per_sqm_avg = sum(
            c["price_per_sqm"] if c.get("price_per_sqm") else c["price_sold"] / c["size_sqm"]
            for c in valid_comps
        ) / len(valid_comps)
        size = norm.get("size_sqm")
        estimated_price = round(price_per_sqm_avg * size) if size else None
    else:
        price_per_sqm_avg = None
        estimated_price = None

    # ── deal_score (additive, missing signal = 0) ─────────────────────────────
    price_asking = norm.get("price_asking")
    size         = norm.get("size_sqm")

    # price_score (0–4): how well priced vs comp average
    if price_asking and size and price_per_sqm_avg and len(valid_comps) >= 2:
        deviation   = (price_asking / size - price_per_sqm_avg) / price_per_sqm_avg
        price_score = 4.0 * max(0.0, min(1.0, 1 - deviation / 0.30))
    else:
        price_score = 0.0

    # image_score (0–3): average condition across all rooms
    if images:
        avg_condition = sum(img["condition_score"] for img in images) / len(images)
        image_score   = 3.0 * avg_condition
    else:
        image_score = 0.0

    # condition_score (0–2): text condition field
    condition_text  = (norm.get("condition") or "").lower().strip()
    condition_score = _CONDITION_SCORES.get(condition_text, 0.0)

    # velocity_score (0–1): how fast similar properties sell
    dom_comps = [c for c in comps if c.get("days_on_market") is not None]
    if len(dom_comps) >= 2:
        avg_dom        = sum(c["days_on_market"] for c in dom_comps) / len(dom_comps)
        velocity_score = 1.0 - min(1.0, avg_dom / 90)
    else:
        velocity_score = 0.0

    deal_score = round(min(10.0, max(0.0,
        price_score + image_score + condition_score + velocity_score
    )), 2)

    log.info(
        "[pricing]     team=%s  score=%.2f  "
        "(price=%.2f  image=%.2f  condition=%.2f  velocity=%.2f)  est_price=%s",
        team, deal_score,
        price_score, image_score, condition_score, velocity_score,
        estimated_price or "n/a",
    )
    return {**state, "team": team, "estimated_price": estimated_price, "deal_score": deal_score}


# ── Node 4c ───────────────────────────────────────────────────────────────────

def clarify_node(state: PropertyState) -> PropertyState:
    """Low-confidence path: flag status as incomplete, missing_fields already set."""
    log.info("[clarify]     missing=%s", state.get("missing_fields"))
    return {**state, "status": "incomplete"}


# ── Node 5 ────────────────────────────────────────────────────────────────────

def analyst_node(state: PropertyState) -> PropertyState:
    """Full embassy analysis using all available signals."""
    norm           = state["normalized"]
    comps          = state.get("rag_comps", [])
    images         = state.get("image_analysis", [])
    deal_score     = state.get("deal_score", 0.0)
    estimated_price = state.get("estimated_price")

    def _comp_line(c: dict) -> str:
        place    = c.get("neighborhood") or c.get("location", "")
        ptype    = c.get("property_type", "")
        rooms    = c.get("num_rooms", "")
        cond     = c.get("condition", "")
        label    = " | ".join(filter(None, [
            f"{rooms}-room {ptype}".strip() if (rooms or ptype) else "",
            f"{c['size_sqm']}sqm",
            cond,
        ]))
        pricing  = f"sold {c['price_sold']:,.0f} NIS"
        if c.get("price_listed") and c["price_listed"] != c["price_sold"]:
            pricing += f" (listed {c['price_listed']:,.0f} NIS)"
        if c.get("price_per_sqm"):
            pricing += f" | {c['price_per_sqm']:,.0f} NIS/sqm"
        timing   = f"{c['days_on_market']} days on market"
        if c.get("sale_date"):
            timing += f" | sold {c['sale_date']}"
        return f"- {place} | {label} | {pricing} | {timing} (similarity {c['similarity_score']})"

    comps_text = "\n".join(_comp_line(c) for c in comps) or "No comparable listings found."

    image_text = "\n".join(
        f"- {img['room_type']}: condition {img['condition_score']:.2f}/1.0 "
        f"(confidence {img['confidence']:.0%})"
        for img in images
    ) or "No images provided."

    price         = norm.get("price_asking")
    price_str     = f"{price:,.0f} NIS" if price is not None else "Not provided"
    est_price_str = f"{estimated_price:,.0f} NIS" if estimated_price is not None else "Insufficient comp data"

    system = """You are a senior property analyst for a real estate embassy.
Pricing arithmetic has already been computed — use the provided deal_score and estimated_price
as given facts. Do not recalculate or contradict them.
Return a JSON object with exactly these keys:
  market_context, property_assessment, pricing_opinion, recommendation, expected_timeline, image_summary
Guidelines:
- market_context: 1–2 sentences on the sub-market using location, property type, and comp velocity.
- property_assessment: physical condition of the property. Incorporate image condition scores if available.
- pricing_opinion: state the estimated market value and how the asking price compares (% above/below).
  If no asking price was given, state the market estimate only and note that no asking price was supplied.
- recommendation: must start with BUY | NEGOTIATE | RENT | PASS followed by " — " and one line
  explaining why, referencing deal_score or price deviation where relevant.
- expected_timeline: one sentence on likely days-to-close based on comp days_on_market data.
  If no comp data, give a general estimate based on property type and condition.
- image_summary: one sentence per room type summarising the condition score. Use "" if no images provided.
Do not invent prices, legal guarantees, certifications, or market data not present in the input.
If comparable listings are absent, say so explicitly and lower confidence in the pricing opinion."""

    user = (
        f"Property: {norm.get('property_type')} in {norm.get('location')}\n"
        f"Description: {norm.get('description') or (state['raw_payload'].get('description') or 'Not provided')}\n"
        f"Size: {norm.get('size_sqm')} sqm, {norm.get('num_rooms')} rooms\n"
        f"Asking price: {price_str}\n"
        f"Condition: {norm.get('condition') or 'not specified'}\n"
        f"Intent: {state.get('intent')}\n\n"
        f"Pre-computed pricing:\n"
        f"  Estimated market value: {est_price_str}\n"
        f"  Deal score: {deal_score} / 10\n\n"
        f"Comparable listings:\n{comps_text}\n\n"
        f"Image analysis:\n{image_text}"
    )

    log.info("[analyst]     calling LLM  comps=%d  images=%d  deal_score=%.2f  intent=%s",
             len(comps), len(images), deal_score, state.get("intent"))
    try:
        result = _call_llm_json(system, user)
        analysis = {
            "market_context":      result.get("market_context", ""),
            "property_assessment": result.get("property_assessment", ""),
            "pricing_opinion":     result.get("pricing_opinion", ""),
            "recommendation":      result.get("recommendation", ""),
            "expected_timeline":   result.get("expected_timeline", ""),
            "image_summary":       result.get("image_summary", ""),
        }
        log.info("[analyst]     recommendation=%s", analysis["recommendation"][:80])
    except Exception as exc:
        log.warning("[analyst]     LLM failed: %s — falling back to PASS", exc)
        analysis = {
            "market_context":      "Analysis unavailable.",
            "property_assessment": "",
            "pricing_opinion":     "",
            "recommendation":      "PASS",
            "expected_timeline":   "",
            "image_summary":       "",
        }

    return {**state, "analysis": analysis}


# ── Node 6 ────────────────────────────────────────────────────────────────────

def output_node(state: PropertyState) -> PropertyState:
    """Set final status."""
    status = state.get("status") or "complete"
    log.info("[output]      status=%s  intent=%s  confidence=%s  team=%s  deal_score=%s",
             status, state.get("intent"), state.get("confidence"),
             state.get("team"), state.get("deal_score"))
    return {**state, "status": status}


# ── Routing ───────────────────────────────────────────────────────────────────

def route_after_confidence(state: PropertyState) -> str:
    return "rag_node" if (state.get("confidence") or 0) >= 0.4 else "clarify_node"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
