import time
from typing import Generator, Optional, Tuple

import httpx

from config import N8N_STATUS_URL, N8N_WEBHOOK_URL


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_file_path(f) -> str | None:
    if f is None:
        return None
    if isinstance(f, str):
        return f
    if isinstance(f, dict):
        return f.get("name")
    if hasattr(f, "name"):
        return f.name
    return None


def _format_status(row: dict, job_id: str) -> str:
    status = row.get("status", "unknown")
    result = row.get("result") or ""
    if status == "done":
        return f"✅ **Complete** — job `{job_id}`\n\n{result}"
    if status == "rejected":
        return f"❌ **Rejected** — job `{job_id}`\n\n> {result}"
    if status == "flagged":
        banner = f"> ⚠️ **Flagged for review** — job `{job_id}`\n\n"
        return banner + result
    if status == "pending":
        return f"⏳ **Still processing…** — job `{job_id}`\n\nCheck again in a moment."
    return f"Status: **{status}** — job `{job_id}`\n\n{result}"


# ── Conversational intake submission ──────────────────────────────────────────

def submit_from_chat(fields: dict, description: str, image_files) -> str:
    """Submit to n8n; returns a result string for the UI.

    description   — value from the dedicated description_box (overrides fields['description'])
    image_files   — single file, list of files, or None (all are uploaded; n8n uses the first)
    """
    REQUIRED = {
        "description":   description,
        "property_type": fields.get("property_type"),
        "intent":        fields.get("intent"),
        "location":      fields.get("location"),
        "condition":     fields.get("condition"),
    }
    missing = [k for k, v in REQUIRED.items() if not v or not str(v).strip()]
    if missing:
        labels = {
            "description": "Description (draft shown on the right)",
            "property_type": "Property type",
            "intent": "Intent (sell / rent)",
            "location": "Location",
            "condition": "Condition",
        }
        names = ", ".join(labels[k] for k in missing)
        return f"❌ **Missing required fields:** {names}"

    form_fields: dict[str, str] = {"description": description.strip()}
    numeric_keys = {"price_asking", "size_sqm", "num_rooms"}
    for key, val in fields.items():
        if val is None or key == "description":
            continue
        form_fields[key] = str(int(val)) if key in numeric_keys else str(val)

    # Resolve image paths (single file or list)
    raw = image_files if isinstance(image_files, list) else ([image_files] if image_files else [])
    image_paths = [p for f in raw if (p := _get_file_path(f))]

    # Send all images as indexed fields (file0, file1, …) so n8n stores each under
    # its own binary key. The "Forward to Image Analyzer" Code node in n8n iterates
    # all keys and forwards them to the image-analyzer service.
    open_files = [open(p, "rb") for p in image_paths]
    try:
        files = {f"file{i}": fh for i, fh in enumerate(open_files)} if open_files else None

        with httpx.Client(timeout=30) as client:
            resp = client.post(N8N_WEBHOOK_URL, data=form_fields, files=files)
            resp.raise_for_status()

        job = resp.json()
        job_id = job.get("job_id") or job.get("jobId", "unknown")
        img_note = (
            f" ({len(image_paths)} image{'s' if len(image_paths) != 1 else ''} attached)"
            if image_paths else ""
        )
        return (
            f"✅ **Submitted!**{img_note} Job ID: `{job_id}`\n\n"
            "Switch to the **Submissions** tab to check status."
        )
    except Exception as exc:
        return f"❌ Submission failed: `{exc}`"
    finally:
        for fh in open_files:
            fh.close()


# ── One-shot status check (for Submissions tab) ───────────────────────────────

def check_status_once(job_id: str) -> str:
    """Single GET to the status endpoint; returns formatted markdown."""
    job_id = (job_id or "").strip()
    if not job_id:
        return "*Enter a job ID to check its status.*"

    status_url = f"{N8N_STATUS_URL}/property-status"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(status_url, params={"job_id": job_id})

        if resp.status_code == 404:
            return (
                f"Job `{job_id}` not found.\n\n"
                "> ℹ️ The status endpoint may not be active yet. "
                "Check the n8n dataTable **fp-req-status** directly."
            )
        resp.raise_for_status()
        return _format_status(resp.json(), job_id)

    except httpx.HTTPStatusError as exc:
        return f"❌ HTTP {exc.response.status_code} from the status endpoint."
    except Exception as exc:
        return f"❌ Could not reach the status endpoint: `{exc}`"

POLL_INTERVAL = 3   # seconds between status checks
POLL_TIMEOUT = 180  # stop polling after 3 minutes

_STATUS_LABELS = {
    "pending":  "⏳ Analysing…",
    "done":     "✅ Complete",
    "rejected": "❌ Rejected",
    "flagged":  "⚠️ Flagged for review",
}


def submit_and_poll(
    description: str,
    property_type: Optional[str],
    intent: Optional[str],
    location: Optional[str],
    agent_name: Optional[str],
    price_asking: Optional[float],
    size_sqm: Optional[float],
    num_rooms: Optional[float],
    condition: Optional[str],
    image_file: Optional[str],
) -> Generator[Tuple[str, str], None, None]:
    """
    Submits a property listing to n8n and polls for the result.
    Yields (status_text, result_markdown) tuples so Gradio can stream updates.
    """
    if not description or not description.strip():
        yield "❌ Description is required.", ""
        return

    # ── Build multipart form data ──────────────────────────────────────────────
    fields: dict[str, str] = {"description": description.strip()}
    if property_type:          fields["property_type"] = property_type
    if intent:                 fields["intent"] = intent
    if location and location.strip():   fields["location"] = location.strip()
    if agent_name and agent_name.strip(): fields["agent_name"] = agent_name.strip()
    if price_asking is not None: fields["price_asking"] = str(int(price_asking))
    if size_sqm is not None:    fields["size_sqm"] = str(size_sqm)
    if num_rooms is not None:   fields["num_rooms"] = str(int(num_rooms))
    if condition:              fields["condition"] = condition

    # ── Submit to n8n ──────────────────────────────────────────────────────────
    yield "⏳ Submitting…", ""
    try:
        files = None
        open_file = None
        if image_file:
            open_file = open(image_file, "rb")
            files = {"file0": open_file}

        with httpx.Client(timeout=30) as client:
            resp = client.post(N8N_WEBHOOK_URL, data=fields, files=files)
            resp.raise_for_status()

        if open_file:
            open_file.close()

        job = resp.json()
        job_id = job.get("job_id") or job.get("jobId")

        if not job_id:
            yield "❌ Submission failed — no job_id in response.", ""
            return

    except Exception as exc:
        yield f"❌ Submission error: `{exc}`", ""
        return

    yield f"⏳ Received — job `{job_id}`. Polling for result…", ""

    # ── Poll for status ────────────────────────────────────────────────────────
    status_url = f"{N8N_STATUS_URL}/property-status"
    deadline = time.time() + POLL_TIMEOUT

    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)

        try:
            with httpx.Client(timeout=10) as client:
                poll_resp = client.get(status_url, params={"job_id": job_id})
                poll_resp.raise_for_status()
            row = poll_resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                # Status endpoint not yet implemented — show instructions
                yield (
                    f"⏳ Job submitted (ID: `{job_id}`)\n\n"
                    "> ℹ️ The status endpoint is not yet active. "
                    "Check the n8n dataTable **fp-req-status** for your result.",
                    "",
                )
                return
            yield f"⏳ Polling… (job `{job_id}`)", ""
            continue
        except Exception:
            yield f"⏳ Polling… (job `{job_id}`)", ""
            continue

        status = row.get("status", "pending")
        result = row.get("result") or ""
        label = _STATUS_LABELS.get(status, status)

        if status == "done":
            yield f"{label} — job `{job_id}`", result
            return
        elif status == "rejected":
            yield f"{label} — job `{job_id}`", f"> {result}"
            return
        elif status == "flagged":
            banner = (
                "> ⚠️ **This report was flagged by the output guardrails** "
                "and requires human review.\n\n"
            )
            yield f"{label} — job `{job_id}`", banner + result
            return
        else:
            yield f"{label} — job `{job_id}`", ""

    yield (
        f"⏰ Timed out — job `{job_id}`\n\n"
        "Processing took longer than 3 minutes. "
        "Check back later using your job ID.",
        "",
    )
