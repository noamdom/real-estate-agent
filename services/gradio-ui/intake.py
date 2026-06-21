import json
import re
from typing import Generator

import gradio as gr
import ollama as ollama_sdk

from config import OLLAMA_MODEL, OLLAMA_URL

INTAKE_SYSTEM_PROMPT = """You are a property intake assistant for a real estate investment embassy.
Your ONLY job is to collect property details for a sale listing submission. Nothing else.

OFF-TOPIC RULE — absolute, no exceptions:
If the user's message is not directly about submitting or describing a property for sale,
do NOT answer the question at all. Reply with exactly one line:
"I can only help with property sale submissions. Please describe the property you'd like to list."
This applies to: general knowledge, travel, recommendations, opinions, coding, or anything
unrelated to collecting property fields listed below.

RENTAL RULE — highest priority after off-topic:
If the agent mentions renting, rental, or an intent to rent at any point, stop the intake and
reply with exactly: "Rental listings are currently not supported. We only accept properties for sale."
Do not collect any further fields after this response.

REQUIRED FIELDS — collect ALL five before the agent submits:
  1. property_type  — apartment | villa | commercial | land
  2. intent         — sell (only; see rental rule above)
  3. location       — city, street, or neighbourhood
  4. condition      — new | renovated | good | fair | poor
  5. description    — the system drafts this from what the agent tells you (shown on the right)

FIELDS THAT UNLOCK FULL ANALYSIS (aim to collect all three):
  - price_asking    — asking price in NIS
  - size_sqm        — floor area in square metres
  - num_rooms       — number of rooms

OPTIONAL:
  - agent_name      — name of the listing agent
  - images          — uploaded via the button below the chat

How to conduct the intake:
1. Greet the agent and ask them to describe the property they wish to sell.
2. Gather the 5 required fields naturally — type, location, condition, description, and confirm intent is sell.
3. Also ask about price, size, and rooms (needed for a complete embassy analysis).
4. Keep replies short — one or two questions at a time.
5. Once all 5 required fields are filled (shown in the checklist on the right), tell the agent
   they may click "Submit Listing" at any time."""

# Combined extraction + description generation — one non-streaming Ollama call per turn.
EXTRACTION_PROMPT = (
    "You are a data extractor for real estate listings.\n\n"
    "From the conversation below:\n"
    "  1. Extract field values EXPLICITLY AND CLEARLY stated by the user — never infer or guess.\n"
    "  2. Write a concise, professional 2-4 sentence property description based on all known details.\n\n"
    "STRICT RULES:\n"
    '  - Set "intent" to "sell" ONLY if the user explicitly used words like "sell", "sale", or "selling".\n'
    '    Do NOT set it to "sell" just because this is a sale platform or because the user described a property.\n'
    '  - If a field was not explicitly mentioned by the user, set it to null.\n'
    '  - If the conversation is off-topic (travel, general knowledge, etc.), return null for every field.\n\n'
    "Return ONLY a valid JSON object — no explanation, no markdown fences:\n"
    '{{\n'
    '  "property_type": "apartment"|"villa"|"commercial"|"land"|null,\n'
    '  "intent": "sell"|null,\n'
    '  "location": string|null,\n'
    '  "agent_name": string|null,\n'
    '  "price_asking": number|null,\n'
    '  "size_sqm": number|null,\n'
    '  "num_rooms": number|null,\n'
    '  "condition": "new"|"renovated"|"good"|"fair"|"poor"|null,\n'
    '  "generated_description": "2-4 sentence professional description, or empty string if not enough info yet"\n'
    '}}\n\n'
    "Conversation:\n{conversation}\n\n"
    "JSON:"
)

# (key, display label, is_required)
# description is managed separately through the description_box component.
FIELD_META = [
    ("property_type", "Property type",        True),
    ("intent",        "Intent (sell / rent)", True),
    ("location",      "Location",             True),
    ("condition",     "Condition",            True),
    ("agent_name",    "Agent name",           False),
    ("price_asking",  "Asking price (NIS)",   False),
    ("size_sqm",      "Size (sqm)",           False),
    ("num_rooms",     "Rooms",                False),
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _msg_to_dict(msg) -> dict:
    """Normalize a history entry to {role, content: str}.

    Handles plain dicts, Gradio 6 ChatMessage objects, and list content blocks
    (multimodal storage format used internally by Gradio 6).
    """
    if isinstance(msg, dict):
        role = msg.get("role", "")
        content = msg.get("content", "")
    else:
        role = getattr(msg, "role", "")
        content = getattr(msg, "content", "")

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            else:
                parts.append(getattr(block, "text", "") or str(block))
        content = " ".join(p for p in parts if p)

    return {"role": str(role), "content": str(content)}


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


def _get_file_paths(files) -> list[str]:
    """Accept a single file, a list of files, or None; always returns a list of paths."""
    if files is None:
        return []
    if not isinstance(files, list):
        files = [files]
    return [p for f in files if (p := _get_file_path(f))]


# ── Checklist renderer ────────────────────────────────────────────────────────

def render_checklist(
    fields: dict,
    has_images: bool = False,
    description: str = "",
) -> str:
    lines = ["### Listing Checklist", ""]

    lines.append("**Required**")

    # Description row (source is the description_box, not extracted fields)
    if description and description.strip():
        preview = description.strip()[:70] + ("…" if len(description.strip()) > 70 else "")
        lines.append(f"- ✅ **Description**: {preview}")
    else:
        lines.append("- ❌ **Description** — *not yet drafted*")

    for key, label, required in FIELD_META:
        if not required:
            continue
        val = fields.get(key)
        if val is not None:
            lines.append(f"- ✅ **{label}**: {val}")
        else:
            lines.append(f"- ❌ **{label}** — *not yet provided*")

    lines.append("")
    lines.append("**Optional**")
    for key, label, required in FIELD_META:
        if required:
            continue
        val = fields.get(key)
        if val is not None:
            lines.append(f"- ✅ {label}: {val}")
        else:
            lines.append(f"- — {label}")
    lines.append(f"- {'✅' if has_images else '—'} Property images")

    # Ready check
    required_ok = (
        bool(description and description.strip())
        and all(fields.get(k) for k, _, req in FIELD_META if req)
    )
    if required_ok:
        lines += ["", "---", "*All required fields collected — click **Submit Listing** when ready.*"]

    return "\n".join(lines)


# ── Extraction + description generation ──────────────────────────────────────

def extract_fields_and_desc(history: list) -> tuple[dict, str]:
    """Single non-streaming Ollama call: returns (extracted_fields, generated_description)."""
    lines = []
    for raw in history:
        msg = _msg_to_dict(raw)
        role = msg.get("role")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")

    if not lines:
        return {}, ""

    prompt = EXTRACTION_PROMPT.format(conversation="\n".join(lines))
    try:
        client = ollama_sdk.Client(host=OLLAMA_URL)
        resp = client.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        )
        text = resp["message"]["content"]
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            data = json.loads(m.group())
            fields = {k: v for k, v in data.items() if k != "generated_description" and v is not None}
            description = data.get("generated_description", "") or ""
            return fields, description
    except Exception:
        pass
    return {}, ""


def _resolve_description(current: str, last_llm: str, new_llm: str) -> tuple[str, str]:
    """Return (value_for_box, new_last_llm).

    Keeps the user's edit if they have changed the box away from the last LLM draft.
    Always advances last_llm so the detection stays accurate across turns.
    """
    stripped_current = (current or "").strip()
    stripped_last = (last_llm or "").strip()
    if not stripped_current or stripped_current == stripped_last:
        return new_llm, new_llm
    # User has edited — preserve their version, silently track new LLM draft
    return current, new_llm


# ── Main generator ────────────────────────────────────────────────────────────

def intake_respond(
    message: str,
    history: list,
    image_files,
    current_fields: dict,
    current_description: str,
    last_llm_description: str,
) -> Generator:
    """Streams the LLM reply, then extracts fields and updates the description draft.

    Yields 6-tuples:
        (chatbot, checklist_md, fields_state, msg_input, description_box, last_llm_desc_state)
    """
    image_paths = _get_file_paths(image_files)
    has_images = bool(image_paths)

    history = [_msg_to_dict(m) for m in history]
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": ""},
    ]

    # First yield: user message visible, input cleared, rest unchanged
    yield (
        history,
        render_checklist(current_fields, has_images, current_description),
        current_fields,
        "",
        gr.update(),
        gr.update(),
    )

    # Build Ollama messages — skip leading assistant-only entries (initial greeting)
    messages = [{"role": "system", "content": INTAKE_SYSTEM_PROMPT}]
    seen_user = False
    for msg in history[:-1]:
        role = msg.get("role")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "user":
            seen_user = True
            messages.append({"role": "user", "content": content})
        elif role == "assistant" and seen_user:
            messages.append({"role": "assistant", "content": content})

    partial = ""
    try:
        client = ollama_sdk.Client(host=OLLAMA_URL)
        for chunk in client.chat(model=OLLAMA_MODEL, messages=messages, stream=True):
            partial += chunk["message"]["content"]
            history[-1]["content"] = partial
            yield (
                history,
                render_checklist(current_fields, has_images, current_description),
                current_fields,
                "",
                gr.update(),
                gr.update(),
            )
    except ConnectionError as exc:
        history[-1]["content"] = (
            f"Could not connect to Ollama at `{OLLAMA_URL}`.\n\n"
            f"Make sure Ollama is running and **{OLLAMA_MODEL}** is pulled:\n"
            f"```\nollama pull {OLLAMA_MODEL}\n```\n\nDetails: `{exc}`"
        )
        yield (history, render_checklist(current_fields, has_images, current_description),
               current_fields, "", gr.update(), gr.update())
        return
    except Exception as exc:
        history[-1]["content"] = f"Unexpected error while calling the model:\n\n```\n{exc}\n```"
        yield (history, render_checklist(current_fields, has_images, current_description),
               current_fields, "", gr.update(), gr.update())
        return

    # After streaming: extract fields + generate description in one call
    new_fields, new_llm_desc = extract_fields_and_desc(history)
    new_desc_display, new_last_llm = _resolve_description(
        current_description, last_llm_description, new_llm_desc
    )

    yield (
        history,
        render_checklist(new_fields, has_images, new_desc_display),
        new_fields,
        "",
        new_desc_display,
        new_last_llm,
    )
