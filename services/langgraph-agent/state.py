from __future__ import annotations

from typing import TypedDict, Optional, List


class NormalizedFields(TypedDict):
    property_type: Optional[str]
    location: Optional[str]
    size_sqm: Optional[float]
    num_rooms: Optional[int]
    price_asking: Optional[float]
    condition: Optional[str]
    agent_name: Optional[str]


class RagComp(TypedDict):
    id: str
    location: str
    price_sold: float
    size_sqm: float
    days_on_market: int
    similarity_score: float


class Analysis(TypedDict):
    market_context: str
    property_assessment: str
    pricing_opinion: str
    recommendation: str
    expected_timeline: str


class PropertyState(TypedDict):
    # Raw input
    raw_payload: dict

    # After intake_node
    normalized: Optional[NormalizedFields]

    # After classifier_node
    intent: Optional[str]  # "sell" | "rent" | "unknown"

    # After confidence_node
    confidence: Optional[float]
    missing_fields: List[str]

    # After rag_node
    rag_comps: List[RagComp]

    # After clarify_node (low-confidence path)
    clarification_message: Optional[str]

    # After analyst_node
    analysis: Optional[Analysis]

    # Final output status
    status: Optional[str]  # "complete" | "incomplete"
