import json
import re

import httpx
import ollama as ollama_sdk

from config import LANGGRAPH_API_URL, OLLAMA_MODEL, OLLAMA_URL

_FILTER_PROMPT = (
    "You are a property search assistant. Extract search filters from the user's request "
    "and write a short one-sentence confirmation reply.\n\n"
    "Available filters:\n"
    "  location       — city or neighbourhood name (string)\n"
    "  property_type  — apartment | villa | commercial | land\n"
    "  min_rooms      — minimum number of rooms (integer)\n"
    "  max_price      — maximum asking price in NIS (integer)\n\n"
    "Return ONLY a valid JSON object — no markdown, no explanation:\n"
    '{{\n'
    '  "location": string or null,\n'
    '  "property_type": "apartment"|"villa"|"commercial"|"land" or null,\n'
    '  "min_rooms": integer or null,\n'
    '  "max_price": integer or null,\n'
    '  "reply": "One sentence confirming the active filters, or noting that all filters are cleared"\n'
    '}}\n\n'
    "If the user wants to reset / show all / clear filters, set every filter field to null.\n\n"
    "User request: {message}\nJSON:"
)

_REC_PALETTE = {
    "BUY":       ("#dcfce7", "#166534", "#16a34a"),
    "NEGOTIATE": ("#fef9c3", "#713f12", "#ca8a04"),
    "RENT":      ("#dbeafe", "#1e3a8a", "#2563eb"),
    "PASS":      ("#fee2e2", "#7f1d1d", "#dc2626"),
}


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


def _rec_badge(recommendation: str) -> str:
    parts = (recommendation or "").split()
    word = parts[0].upper() if parts else ""
    bg, text, border = _REC_PALETTE.get(word, ("#f3f4f6", "#374151", "#d1d5db"))
    label = recommendation or "—"
    return (
        f'<span style="background:{bg};color:{text};border:1px solid {border};'
        f'padding:2px 12px;border-radius:20px;font-size:12px;font-weight:700;'
        f'white-space:normal;word-break:break-word;">'
        f'{label}</span>'
    )


def _team_pill(team: str) -> str:
    if not team:
        return ""
    return (
        f'<span style="background:#e0e7ff;color:#3730a3;border:1px solid #818cf8;'
        f'padding:2px 10px;border-radius:20px;font-size:11px;font-weight:600;">'
        f'{team.title()}</span>'
    )


def _deal_score_bar(score) -> str:
    if score is None or score == "":
        return ""
    try:
        val = float(score)
    except (ValueError, TypeError):
        return ""
    pct = val / 10 * 100
    return (
        f'<div style="display:flex;align-items:center;gap:8px;font-size:12px;">'
        f'<span style="color:var(--body-text-color-subdued,#94a3b8);">Score</span>'
        f'<div style="flex:1;max-width:100px;height:6px;background:#334155;border-radius:3px;">'
        f'<div style="width:{pct:.0f}%;height:100%;background:#22c55e;border-radius:3px;"></div>'
        f'</div>'
        f'<span style="font-weight:700;color:var(--body-text-color,#f1f5f9);">{val:.1f}/10</span>'
        f'</div>'
    )


def _section_block(label: str, text: str) -> str:
    if not text:
        return ""
    return (
        f'<div style="margin-top:8px;">'
        f'<div style="font-size:11px;font-weight:700;color:var(--body-text-color-subdued,#94a3b8);'
        f'text-transform:uppercase;letter-spacing:0.6px;margin-bottom:3px;">{label}</div>'
        f'<div style="font-size:13px;color:var(--body-text-color,inherit);line-height:1.5;">{text}</div>'
        f'</div>'
    )


_PREV_JS = (
    "(function(b){"
    "var p=b.closest('[data-carousel]');"
    "var ss=p.querySelectorAll('[data-slide]');"
    "var c=Array.from(ss).findIndex(function(s){return s.style.display!=='none';});"
    "ss[c].style.display='none';"
    "ss[(c-1+ss.length)%ss.length].style.display='block';"
    "})(this)"
)
_NEXT_JS = (
    "(function(b){"
    "var p=b.closest('[data-carousel]');"
    "var ss=p.querySelectorAll('[data-slide]');"
    "var c=Array.from(ss).findIndex(function(s){return s.style.display!=='none';});"
    "ss[c].style.display='none';"
    "ss[(c+1)%ss.length].style.display='block';"
    "})(this)"
)
_BTN_BASE = (
    "position:absolute;top:50%;transform:translateY(-50%);"
    "background:rgba(0,0,0,0.55);color:#fff;border:none;border-radius:50%;"
    "width:34px;height:34px;font-size:22px;line-height:1;cursor:pointer;"
    "display:flex;align-items:center;justify-content:center;pointer-events:auto;"
    "transition:background 0.15s;"
)


def _carousel(urls: list) -> str:
    if not urls:
        return (
            '<div style="display:flex;align-items:center;justify-content:center;'
            'height:100%;color:var(--body-text-color-subdued,#64748b);font-size:13px;">No image</div>'
        )
    if len(urls) == 1:
        return (
            f'<img src="{urls[0]}" alt="property" '
            f'style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;" />'
        )

    slides = "".join(
        f'<img src="{u}" alt="property {i+1}" data-slide '
        f'style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;'
        f'display:{"block" if i == 0 else "none"};" />'
        for i, u in enumerate(urls)
    )
    return (
        f'<div data-carousel style="position:absolute;inset:0;" '
        f'onmouseenter="this.querySelector(\'[data-arrows]\').style.opacity=\'1\'" '
        f'onmouseleave="this.querySelector(\'[data-arrows]\').style.opacity=\'0\'">'
        f'{slides}'
        f'<div data-arrows style="opacity:0;transition:opacity 0.2s;'
        f'pointer-events:none;position:absolute;inset:0;">'
        f'<button onclick="{_PREV_JS}" style="{_BTN_BASE}left:8px;">&#8249;</button>'
        f'<button onclick="{_NEXT_JS}" style="{_BTN_BASE}right:8px;">&#8250;</button>'
        f'</div>'
        f'</div>'
    )


def render_properties(rows) -> str:
    if isinstance(rows, str) and rows.startswith("__error__"):
        detail = rows[len("__error__: "):]
        return f"**Could not load properties:** `{detail}`"
    if not rows:
        return "*No listings found matching the filters.*"

    cards = []
    for r in rows:
        raw_urls = r.get("image_urls") or ""
        try:
            signed_urls = json.loads(raw_urls) if raw_urls else []
        except Exception:
            signed_urls = [raw_urls] if raw_urls else []

        title = f"{r.get('property_type', '').title()} — {r.get('location', '—')}"
        price_str = f"{int(float(r['price_asking'])):,} NIS" if r.get("price_asking") else "—"

        est_str = ""
        if r.get("estimated_price"):
            try:
                est_str = f"≈ {int(float(r['estimated_price'])):,} NIS est."
            except (ValueError, TypeError):
                pass

        analysis = {}
        raw_analysis = r.get("analysis") or ""
        if raw_analysis:
            try:
                analysis = json.loads(raw_analysis) if isinstance(raw_analysis, str) else raw_analysis
            except Exception:
                pass

        rec_raw       = analysis.get("recommendation", "")
        market_ctx    = analysis.get("market_context", "")
        pricing_op    = analysis.get("pricing_opinion", "")
        image_summary = analysis.get("image_summary", "")

        card = (
            f'<div style="border:1px solid var(--border-color-primary,#334155);border-radius:12px;'
            f'overflow:hidden;margin-bottom:24px;display:flex;min-height:220px;'
            f'box-shadow:0 2px 8px rgba(0,0,0,0.3);background:var(--background-fill-secondary,#1e293b);'
            f'font-family:system-ui,-apple-system,sans-serif;">'
            # left panel
            f'<div style="width:240px;min-width:240px;flex-shrink:0;position:relative;'
            f'background:var(--background-fill-primary,#0f172a);">'
            f'{_carousel(signed_urls)}'
            f'</div>'
            # right panel
            f'<div style="flex:1;padding:16px 20px;display:flex;flex-direction:column;gap:6px;overflow:hidden;">'
            # title + team pill
            f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">'
            f'<span style="font-size:17px;font-weight:700;color:var(--body-text-color,#f1f5f9);">{title}</span>'
            f'{_team_pill(r.get("team", ""))}'
            f'</div>'
            # chips row
            f'<div style="display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--body-text-color-subdued,#94a3b8);">'
            f'<span>🛏&nbsp;<strong>{r.get("num_rooms", "—")}</strong> rooms</span>'
            f'<span>📐&nbsp;<strong>{r.get("size_sqm", "—")}</strong> sqm</span>'
            f'<span>🔧&nbsp;<strong>{(r.get("condition") or "—").title()}</strong></span>'
            f'<span>Intent:&nbsp;<strong style="color:var(--body-text-color,#f1f5f9);">{(r.get("intent") or "—").title()}</strong></span>'
            f'</div>'
            # price row
            f'<div style="display:flex;gap:16px;align-items:baseline;flex-wrap:wrap;font-size:13px;">'
            f'<span>💰&nbsp;<strong style="color:var(--body-text-color,#f1f5f9);">{price_str}</strong></span>'
            + (f'<span style="color:var(--body-text-color-subdued,#94a3b8);">{est_str}</span>' if est_str else '')
            + f'</div>'
            # badge + score row
            f'<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">'
            f'{_rec_badge(rec_raw)}'
            f'{_deal_score_bar(r.get("deal_score"))}'
            f'</div>'
            f'<hr style="border:none;border-top:1px solid var(--border-color-primary,#334155);margin:4px 0;" />'
            f'{_section_block("Market Context", market_ctx)}'
            f'{_section_block("Pricing Opinion", pricing_op)}'
            f'{_section_block("Image Analysis", image_summary)}'
            f'</div>'
            f'</div>'
        )
        cards.append(card)

    return "\n".join(cards)


# ── Filter chatbot ─────────────────────────────────────────────────────────────

def chat_filter(
    message: str,
    history: list,
) -> tuple[list, str, str, int | None, int | None, str]:
    """Parse a natural-language filter request via Ollama.

    Returns:
        (new_history, location, property_type, min_rooms, max_price, rendered_properties)
    """
    history = list(history) + [{"role": "user", "content": message}]

    location = ""
    property_type = ""
    min_rooms = None
    max_price = None
    reply = "Searching…"

    try:
        client = ollama_sdk.Client(host=OLLAMA_URL)
        resp = client.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": _FILTER_PROMPT.format(message=message)}],
            stream=False,
        )
        text = resp["message"]["content"]
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            data = json.loads(m.group())
            location = data.get("location") or ""
            property_type = data.get("property_type") or ""
            min_rooms = data.get("min_rooms")
            max_price = data.get("max_price")
            reply = data.get("reply") or reply
    except Exception as exc:
        reply = f"Sorry, I couldn't process that. ({exc})"

    history.append({"role": "assistant", "content": reply})

    rows = fetch_properties(
        location=location,
        property_type=property_type,
        min_rooms=min_rooms,
        max_price=max_price,
    )
    rendered = render_properties(rows)

    return history, location, property_type, min_rooms, max_price, rendered
