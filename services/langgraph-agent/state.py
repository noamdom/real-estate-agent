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


class ImageResult(TypedDict):
    room_type: str        # "kitchen" | "bedroom" | "bathroom" | "living_room" | "exterior" | "other"
    condition_score: float  # 0.0–1.0
    confidence: float       # model classification confidence 0.0–1.0


class RagComp(TypedDict):
    id:               str
    location:         str
    neighborhood:     str
    property_type:    str
    num_rooms:        int
    condition:        str
    size_sqm:         float
    price_sold:       float
    price_listed:     float
    price_per_sqm:    float
    days_on_market:   int
    sale_date:        str
    similarity_score: float


class Analysis(TypedDict):
    market_context: str
    property_assessment: str
    pricing_opinion: str
    recommendation: str   # "NEGOTIATE — 8% above comp avg" | "BUY" | "RENT" | "PASS"
    expected_timeline: str
    image_summary: str    # "" when no images provided


class PropertyState(TypedDict):
    # Raw input
    raw_payload: dict

    # After intake_node
    normalized: Optional[NormalizedFields]
    image_analysis: List[ImageResult]   # empty list when no images submitted

    # After classifier_node
    intent: Optional[str]               # "sell" | "rent" | "unknown"

    # After confidence_node
    confidence: Optional[float]
    missing_fields: List[str]

    # After rag_node (internal — not returned in API response)
    rag_comps: List[RagComp]

    # After pricing_node
    estimated_price: Optional[float]    # market estimate from comps; None if < 2 usable comps
    deal_score: float                   # 0.0–10.0 additive score; 0.0 when no signals present
    team: Optional[str]                 # "residential" | "commercial" | "unknown"

    # After analyst_node
    analysis: Optional[Analysis]

    # Final
    status: Optional[str]               # "complete" | "incomplete"
