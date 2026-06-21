import json
import time

import httpx

from config import LANGGRAPH_API_URL
from properties import render_properties

POLL_INTERVAL = 3
POLL_TIMEOUT = 180


def fetch_job(job_id: str) -> dict | str:
    """Fetch a single job row from the langgraph-agent. Returns dict or '__error__: …' string."""
    job_id = (job_id or "").strip()
    if not job_id:
        return "__error__: Enter a job ID"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{LANGGRAPH_API_URL}/job/{job_id}")
        if resp.status_code == 404:
            return f"__error__: Job `{job_id}` not found"
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return f"__error__: HTTP {e.response.status_code}"
    except Exception as e:
        return f"__error__: {e}"


def render_status(result) -> str:
    """Render a job row (dict) or error string to displayable HTML/markdown."""
    if result is None:
        return "*Enter a job ID and click Check Status.*"

    if isinstance(result, str) and result.startswith("__error__:"):
        detail = result[len("__error__: "):]
        return f"**Error:** {detail}"

    if isinstance(result, str):
        return result

    status = result.get("status", "unknown")
    job_id = str(result.get("job_id", ""))

    if status == "pending":
        return (
            f'<div style="padding:16px;border-radius:8px;background:#dbeafe;color:#1e3a8a;font-size:14px;">'
            f'⏳ <strong>Still analysing…</strong> — job <code>{job_id}</code>'
            f'<br/><span style="font-size:12px;opacity:0.8;">Checking again automatically every {POLL_INTERVAL}s.</span>'
            f'</div>'
        )

    if status == "rejected":
        # Parse analysis early so we can fall back to analysis["error"] for the reason
        analysis = {}
        raw_analysis = result.get("analysis") or ""
        if raw_analysis:
            try:
                analysis = json.loads(raw_analysis) if isinstance(raw_analysis, str) else raw_analysis
            except Exception:
                pass

        reason = result.get("result") or analysis.get("error") or ""
        ptype   = (result.get("property_type") or "—").title()
        loc     = result.get("location") or "—"
        rooms   = result.get("num_rooms") or "—"
        sqm     = result.get("size_sqm") or "—"
        cond    = (result.get("condition") or "—").title()
        price   = result.get("price_asking")
        price_str = f"{int(float(price)):,} NIS" if price else "—"
        desc    = result.get("description") or ""
        submitted = (result.get("submitted_at") or "")[:10]

        chips = (
            f'<div style="display:flex;gap:16px;flex-wrap:wrap;font-size:13px;'
            f'color:var(--body-text-color-subdued,#94a3b8);margin:10px 0;">'
            f'<span>🏠&nbsp;<strong>{ptype}</strong></span>'
            f'<span>📍&nbsp;<strong>{loc}</strong></span>'
            f'<span>🛏&nbsp;<strong>{rooms}</strong> rooms</span>'
            f'<span>📐&nbsp;<strong>{sqm}</strong> sqm</span>'
            f'<span>💰&nbsp;<strong>{price_str}</strong></span>'
            f'<span>🔧&nbsp;<strong>{cond}</strong></span>'
            + (f'<span style="margin-left:auto;font-size:11px;">Submitted: {submitted}</span>' if submitted else "")
            + f'</div>'
        )
        desc_block = (
            f'<div style="font-size:13px;color:var(--body-text-color,inherit);'
            f'line-height:1.5;margin-bottom:10px;">{desc}</div>'
            if desc else ""
        )
        reason_block = (
            f'<div style="font-size:11px;font-weight:700;color:#991b1b;text-transform:uppercase;'
            f'letter-spacing:0.6px;margin-bottom:4px;">Rejection reason</div>'
            f'<div style="padding:10px 14px;border-left:4px solid #dc2626;'
            f'font-size:13px;color:#7f1d1d;line-height:1.5;">{reason}</div>'
            if reason else ""
        )

        def _sec(label, text):
            if not text:
                return ""
            return (
                f'<div style="margin-top:10px;">'
                f'<div style="font-size:11px;font-weight:700;color:var(--body-text-color-subdued,#94a3b8);'
                f'text-transform:uppercase;letter-spacing:0.6px;margin-bottom:3px;">{label}</div>'
                f'<div style="font-size:13px;color:var(--body-text-color,inherit);line-height:1.5;">{text}</div>'
                f'</div>'
            )

        analysis_blocks = (
            _sec("Market Context",  analysis.get("market_context", ""))
            + _sec("Pricing Opinion", analysis.get("pricing_opinion", ""))
            + _sec("Image Analysis",  analysis.get("image_summary", ""))
        )
        hr = '<hr style="border:none;border-top:1px solid #fca5a5;margin:12px 0;" />' if analysis_blocks else ""

        return (
            f'<div style="border:1px solid #fca5a5;border-radius:12px;overflow:hidden;'
            f'margin-bottom:24px;font-family:system-ui,-apple-system,sans-serif;">'
            f'<div style="background:#fee2e2;color:#7f1d1d;padding:12px 16px;font-size:14px;font-weight:700;">'
            f'❌ Rejected — job <code style="font-size:12px;">{job_id}</code></div>'
            f'<div style="padding:16px 20px;">'
            f'{chips}'
            f'{desc_block}'
            f'{reason_block}'
            f'{hr}'
            f'{analysis_blocks}'
            f'</div>'
            f'</div>'
        )

    if status in ("done", "flagged"):
        bg    = "#dcfce7" if status == "done" else "#fef9c3"
        color = "#052e16" if status == "done" else "#713f12"
        icon  = "✅" if status == "done" else "⚠️"
        label = "Complete" if status == "done" else "Flagged for review"
        banner = (
            f'<div style="background:{bg};color:{color};padding:12px 16px;'
            f'font-size:14px;font-weight:700;margin-bottom:12px;">'
            f'{icon} {label} — job <code style="font-size:12px;">{job_id}</code></div>'
        )
        return banner + render_properties([result])

    return f"**Status:** {status} — job `{job_id}`"


def poll_job(job_id: str):
    """Generator — yields (rendered_html, is_terminal) until a terminal status or timeout."""
    job_id = (job_id or "").strip()
    if not job_id:
        yield render_status("__error__: Enter a job ID"), True
        return

    deadline = time.time() + POLL_TIMEOUT

    while time.time() < deadline:
        row = fetch_job(job_id)

        if isinstance(row, str):
            yield render_status(row), True
            return

        status = row.get("status", "pending")
        rendered = render_status(row)

        if status in ("done", "rejected", "flagged"):
            yield rendered, True
            return

        yield rendered, False
        time.sleep(POLL_INTERVAL)

    timeout_html = (
        f'<div style="padding:16px;border-radius:8px;background:#dbeafe;color:#1e3a8a;font-size:14px;">'
        f'⏰ <strong>Timed out</strong> — job <code>{job_id}</code>'
        f'<br/><span style="font-size:12px;opacity:0.8;">Processing took longer than 3 minutes. Try again later.</span>'
        f'</div>'
    )
    yield timeout_html, True
