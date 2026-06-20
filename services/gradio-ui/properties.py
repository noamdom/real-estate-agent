import json

import httpx

from config import LANGGRAPH_API_URL


def fetch_properties(
    location: str = "",
    property_type: str = "",
    min_rooms=None,
    max_price=None,
    status: str = "done",
) -> list:
    params: dict = {}
    if location:
        params["location"] = location
    if property_type:
        params["property_type"] = property_type
    if min_rooms:
        params["min_rooms"] = int(min_rooms)
    if max_price:
        params["max_price"] = int(max_price)
    params["status"] = status

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{LANGGRAPH_API_URL}/properties", params=params)
            resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return f"__error__: {e.response.status_code} — {e.response.text}"
    except Exception as e:
        return f"__error__: {e}"


def render_properties(rows) -> str:
    if isinstance(rows, str) and rows.startswith("__error__"):
        detail = rows[len("__error__: "):]
        return f"**Could not load properties:** `{detail}`"
    if not rows:
        return "*No listings found matching the filters.*"

    parts = []
    for r in rows:
        raw_urls = r.get("image_urls") or ""
        try:
            first_url = json.loads(raw_urls)[0] if raw_urls else ""
        except Exception:
            first_url = raw_urls
        img = f"![property]({first_url})" if first_url else "*(no image)*"
        price_str = f"**Price:** {int(r['price_asking']):,} NIS | " if r.get("price_asking") else ""
        snippet = (r.get("result") or "")[:300]
        ellipsis = "…" if len(r.get("result") or "") > 300 else ""

        parts.append(
            f"### {r.get('property_type', '').title()} — {r.get('location', '')}\n\n"
            f"{img}\n\n"
            f"**Rooms:** {r.get('num_rooms', '—')} | "
            f"**Size:** {r.get('size_sqm', '—')} sqm | "
            f"{price_str}"
            f"**Condition:** {r.get('condition', '—')}\n\n"
            f"**Intent:** {r.get('intent', '—')} | "
            f"**Recommendation:** `{r.get('recommendation', '—')}`\n\n"
            f"{snippet}{ellipsis}\n\n---"
        )

    return "\n\n".join(parts)
