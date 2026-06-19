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

REQUIRED_FIELDS = ["property_type", "location", "price_asking", "size_sqm", "num_rooms"]


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
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


# ── Node 1 ────────────────────────────────────────────────────────────────────

def intake_node(state: PropertyState) -> PropertyState:
    """Normalize and validate the raw payload, standardize field names."""
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

    log.info(
        "[intake]      type=%-12s  location=%-20s  price=%s  size=%s sqm  rooms=%s",
        normalized.get("property_type") or "?",
        normalized.get("location") or "?",
        normalized.get("price_asking") or "?",
        normalized.get("size_sqm") or "?",
        normalized.get("num_rooms") or "?",
    )
    return {**state, "normalized": normalized}


# ── Node 2 ────────────────────────────────────────────────────────────────────

_RENT_KEYWORDS = {
    "rent", "rental", "renting", "tenant", "tenants", "lease", "leasing",
    "monthly", "per month", "pcm",
    # Hebrew
    "שכירות", "לשכירות", "שוכר", "שכר",
}

_SELL_KEYWORDS = {
    "sell", "sale", "selling", "for sale", "purchase", "buyer",
    "asking price", "list price", "freehold",
    # Hebrew
    "מכירה", "למכירה", "מוכר",
}


def classifier_node(state: PropertyState) -> PropertyState:
    """Detect intent (sell | rent | unknown) without an LLM call.

    Priority:
      1. Explicit `intent` field on the raw payload (set by the caller).
      2. Keyword scan across description + property_type.
      3. Falls back to "unknown".
    """
    raw = state["raw_payload"]

    # 1 — caller-supplied intent
    explicit = (raw.get("intent") or "").strip().lower()
    if explicit in ("sell", "rent"):
        log.info("[classifier]  intent=%-8s  method=explicit", explicit)
        return {**state, "intent": explicit}

    # 2 — keyword scan
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
        # both found — whichever has more keyword hits wins
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

    # Penalise unknown intent
    intent_penalty = 0.1 if state.get("intent") == "unknown" else 0.0

    # Penalise suspiciously low prices (below 100 NIS/month makes no sense)
    price = norm.get("price_asking") or 0
    price_penalty = 0.1 if 0 < price < 100 else 0.0

    score = max(0.0, round(field_score - intent_penalty - price_penalty, 2))

    log.info("[confidence]  score=%.2f  missing=%s  → %s",
             score, missing or "none",
             "rag_node" if score >= 0.5 else "clarify_node")
    return {**state, "confidence": score, "missing_fields": missing}


# ── Node 4a ───────────────────────────────────────────────────────────────────

def rag_node(state: PropertyState) -> PropertyState:
    """Query Pinecone with location + type + size, return top-3 comps."""
    norm = state["normalized"]

    query_text = (
        f"{norm.get('property_type', '')} in {norm.get('location', '')} "
        f"{norm.get('size_sqm', '')} sqm {norm.get('num_rooms', '')} rooms"
    )

    try:
        embeddings = _get_embeddings()
        vector = embeddings.embed_query(query_text)
        index = _get_pinecone_index()
        results = index.query(vector=vector, top_k=3, include_metadata=True)

        comps = []
        for match in results.get("matches", []):
            meta = match.get("metadata", {})
            comps.append({
                "id": match["id"],
                "location": meta.get("location", ""),
                "price_sold": float(meta.get("price_sold", 0)),
                "size_sqm": float(meta.get("size_sqm", 0)),
                "days_on_market": int(meta.get("days_on_market", 0)),
                "similarity_score": round(float(match["score"]), 4),
            })
    except Exception as exc:
        log.warning("[rag]         Pinecone query failed: %s — continuing without comps", exc)
        comps = []

    log.info("[rag]         comps=%d  query=%r", len(comps), query_text[:60])
    return {**state, "rag_comps": comps}


# ── Node 4b ───────────────────────────────────────────────────────────────────

def clarify_node(state: PropertyState) -> PropertyState:
    """Low-confidence path: generate a friendly clarification message."""
    missing = state.get("missing_fields", [])
    field_labels = {
        "property_type": "property type (apartment / house / villa / office)",
        "location": "property location (city and neighbourhood)",
        "price_asking": "asking price in NIS",
        "size_sqm": "property size in square metres",
        "num_rooms": "number of rooms",
    }
    readable = [field_labels.get(f, f) for f in missing]
    items = ", ".join(readable) if readable else "more details"

    message = (
        f"Thank you for your submission. To proceed with a full analysis, "
        f"we need a bit more information: {items}. "
        "Please reply with these details and we will complete the evaluation."
    )

    log.info("[clarify]     missing=%s", missing)
    return {**state, "clarification_message": message, "status": "incomplete"}


# ── Node 5 ────────────────────────────────────────────────────────────────────

def analyst_node(state: PropertyState) -> PropertyState:
    """Full embassy analysis using normalized fields + RAG comps."""
    norm = state["normalized"]
    comps = state.get("rag_comps", [])

    comps_text = "\n".join(
        f"- {c['location']}, {c['size_sqm']}sqm, sold {c['price_sold']:,.0f} NIS, "
        f"{c['days_on_market']} days on market (similarity {c['similarity_score']})"
        for c in comps
    ) or "No comparable listings found."

    system = """You are a senior property analyst for a real estate embassy.
Your job is to evaluate property listings and provide acquisition recommendations.
Reply with a JSON object containing exactly these keys:
  market_context, property_assessment, pricing_opinion, recommendation, expected_timeline
Keep each value to 1–3 sentences. Be factual. Do not invent prices or legal claims.
recommendation must start with one of: BUY | NEGOTIATE | RENT | PASS."""

    price = norm.get('price_asking')
    price_str = f"{price:,} NIS" if price is not None else "not specified"
    user = (
        f"Property: {norm.get('property_type')} in {norm.get('location')}\n"
        f"Size: {norm.get('size_sqm')} sqm, {norm.get('num_rooms')} rooms\n"
        f"Asking price: {price_str}\n"
        f"Condition: {norm.get('condition', 'not specified')}\n"
        f"Intent: {state.get('intent')}\n\n"
        f"Comparable listings:\n{comps_text}"
    )

    log.info("[analyst]     calling LLM  comps=%d  intent=%s", len(comps), state.get("intent"))
    try:
        result = _call_llm_json(system, user)
        analysis = {
            "market_context": result.get("market_context", ""),
            "property_assessment": result.get("property_assessment", ""),
            "pricing_opinion": result.get("pricing_opinion", ""),
            "recommendation": result.get("recommendation", ""),
            "expected_timeline": result.get("expected_timeline", ""),
        }
        log.info("[analyst]     recommendation=%s", analysis["recommendation"][:60])
    except Exception as exc:
        log.warning("[analyst]     LLM failed: %s — falling back to PASS", exc)
        analysis = {
            "market_context": "Analysis unavailable.",
            "property_assessment": "",
            "pricing_opinion": "",
            "recommendation": "PASS",
            "expected_timeline": "",
        }

    return {**state, "analysis": analysis}


# ── Node 6 ────────────────────────────────────────────────────────────────────

def output_node(state: PropertyState) -> PropertyState:
    """Set final status and clean up state for serialization."""
    status = state.get("status") or "complete"
    log.info("[output]      status=%s  intent=%s  confidence=%s",
             status, state.get("intent"), state.get("confidence"))
    return {**state, "status": status}


# ── Routing ───────────────────────────────────────────────────────────────────

def route_after_confidence(state: PropertyState) -> str:
    return "rag_node" if (state.get("confidence") or 0) >= 0.5 else "clarify_node"


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
