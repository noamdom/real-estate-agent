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
        reason = result.get("result") or ""
        return (
            f'<div style="padding:16px;border-radius:8px;background:#fee2e2;color:#7f1d1d;'
            f'font-size:14px;margin-bottom:12px;">'
            f'❌ <strong>Rejected</strong> — job <code>{job_id}</code></div>'
            + (
                f'<blockquote style="margin:0;padding:12px 16px;border-left:4px solid #dc2626;'
                f'font-size:13px;">{reason}</blockquote>'
                if reason else ""
            )
        )

    if status in ("done", "flagged"):
        bg    = "#dcfce7" if status == "done" else "#fef9c3"
        color = "#166534" if status == "done" else "#713f12"
        icon  = "✅" if status == "done" else "⚠️"
        label = "Complete" if status == "done" else "Flagged for review"
        banner = (
            f'<div style="padding:12px 16px;border-radius:8px;background:{bg};color:{color};'
            f'font-size:14px;margin-bottom:12px;">'
            f'{icon} <strong>{label}</strong> — job <code>{job_id}</code></div>'
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
