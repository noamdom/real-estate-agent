"""
Run against a locally running service:
    uvicorn main:server --reload
    python test_analyze.py
"""

import json
import sys
import requests

BASE_URL = "http://localhost:9000"

SELL_PAYLOAD = {
    "property_type": "apartment",
    "location": "Tel Aviv, Florentin",
    "description": "Renovated 3-room apartment on the 4th floor, bright and quiet. "
                   "New kitchen, renovated bathroom, air conditioning throughout. "
                   "Close to Carmel Market and public transport.",
    "agent_name": "Noam Cohen",
    "price_asking": 3_000_000,
    "size_sqm": 85,
    "num_rooms": 3,
    "condition": "renovated",
}

RENT_PAYLOAD = {
    "property_type": "villa",
    "location": "Jerusalem, German Colony",
    "description": "Spacious 5-room villa with garden in the prestigious German Colony. "
                   "Recently repainted, updated plumbing. Walking distance to Emek Refaim. "
                   "Owner seeking long-term tenants.",
    "agent_name": "Rivka Levi",
    "price_asking": 12_000,
    "size_sqm": 180,
    "num_rooms": 5,
    "condition": "good",
}

INCOMPLETE_PAYLOAD = {
    "property_type": "apartment",
    "description": "Nice flat somewhere in the center, asking a fair price.",
    "agent_name": "Unknown Agent",
}


def print_result(label: str, response: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  intent:     {response.get('intent')}")
    print(f"  confidence: {response.get('confidence')}")
    print(f"  status:     {response.get('status')}")
    print(f"  missing:    {response.get('missing_fields')}")
    if response.get("clarification_message"):
        print(f"  clarify:    {response['clarification_message']}")
    if response.get("analysis"):
        a = response["analysis"]
        print(f"  recommendation: {a.get('recommendation')}")
        print(f"  timeline:   {a.get('expected_timeline')}")
    comps = response.get("rag_comps", [])
    if comps:
        print(f"  comps ({len(comps)}):")
        for c in comps:
            print(f"    - {c['location']} {c['size_sqm']}sqm @ {c['price_sold']:,.0f} NIS "
                  f"(sim={c['similarity_score']})")
    print()


def run_test(label: str, payload: dict) -> bool:
    try:
        r = requests.post(f"{BASE_URL}/analyze", json=payload, timeout=60)
        r.raise_for_status()
        print_result(label, r.json())
        return True
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Could not connect to {BASE_URL} — is the service running?")
        return False
    except Exception as exc:
        print(f"ERROR [{label}]: {exc}")
        return False


if __name__ == "__main__":
    health = requests.get(f"{BASE_URL}/health", timeout=5)
    assert health.json() == {"status": "ok"}, "Health check failed"
    print("Health check passed.")

    ok1 = run_test("SELL — Tel Aviv Florentin apartment", SELL_PAYLOAD)
    # ok2 = run_test("RENT — Jerusalem German Colony villa", RENT_PAYLOAD)
    # ok3 = run_test("INCOMPLETE — missing location + price", INCOMPLETE_PAYLOAD)

    # sys.exit(0 if (ok1 and ok2 and ok3) else 1)
    sys.exit(0 if ok1 else 1)
