import json
import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv(override=True)

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("guardrails")

_llm: Optional[ChatOpenAI] = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=api_key)
    return _llm


def _classify(system_prompt: str, text: str) -> dict:
    """Call the LLM and return parsed JSON result."""
    llm = _get_llm()
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=text),
    ])
    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(raw)


# ── Prompts ───────────────────────────────────────────────────────────────────

INPUT_SYSTEM = """You are a guardrail for a real estate property submission system.
Classify the incoming text and return a JSON object with exactly these keys:
  "pass": true or false
  "reason": a short explanation if pass is false, otherwise null

Return pass=true only if the text is a genuine property listing (description, location, price, size, rooms).
Return pass=false for:
  - Spam or advertisements ("buy cheap watches", "make money fast")
  - Off-topic content ("what's the weather", "tell me a joke")
  - Discriminatory or harmful content — including ANY restriction on buyers or tenants based on
    religion, ethnicity, nationality, gender, age, or any other protected characteristic,
    whether stated directly or indirectly (e.g. "specific religious background", "preferred community",
    "suitable for families of a certain background", "only for [group]")
  - Empty or nonsensical text

Examples of VALID listings:
  "3 bedroom apartment in Tel Aviv Florentin, 85sqm, asking 3M NIS, renovated kitchen"
  "Villa in Jerusalem Rehavia, 290sqm, private garden, asking 10M NIS"
  "Commercial office 500sqm Herzliya, monthly rental"

Examples of INVALID listings (discriminatory — even when property details are otherwise valid):
  "4-room apartment Rehavia 120sqm. Seller will only consider buyers of a specific religious background."
  "Beautiful villa, only selling to buyers from our community. Others need not apply."
  "Apartment for rent, suitable for families of the preferred background only."
  "3 rooms Tel Aviv, will not rent to certain nationalities."

Respond ONLY with the JSON object. No explanation outside JSON."""

IMAGE_LABEL_SYSTEM = """You are a guardrail for a real estate image submission system.
You receive one or more image labels returned by a computer vision model, as a comma-separated string.
Classify the labels and return a JSON object with exactly these keys:
  "pass": true or false
  "reason": a short explanation if pass is false, otherwise null

Return pass=true if ALL labels describe real estate or property-related content:
  - Interior spaces: bedroom, living room, kitchen, bathroom, dining room, hallway, corridor, staircase
  - Exterior spaces: building exterior, garden, yard, balcony, terrace, parking, garage, driveway
  - Commercial spaces: office, workspace, meeting room, retail space

Return pass=false if ANY label describes content unrelated to property:
  - Animals (cat, dog, bird, any pet or wildlife)
  - People or portraits
  - Food or beverages
  - Vehicles (car, motorcycle, truck)
  - Natural landscapes without buildings
  - Documents, screens or phones
  - Random or unidentifiable objects

Respond ONLY with the JSON object. No explanation outside JSON."""

OUTPUT_SYSTEM = """You are a guardrail that checks AI-generated real estate reports for problematic content.
Classify the report and return a JSON object with exactly these keys:
  "pass": true or false
  "reason": a short explanation if pass is false, otherwise null

Return pass=false if the report contains ANY of:
  - False legal guarantees ("legally guaranteed to appreciate", "certified by Land Registry")
  - Fabricated or invented price data presented as fact
  - Unauthorized legal advice ("sign the contract immediately", "no legal risk")
  - Price guarantees or investment return guarantees

Return pass=true if the report is factual, based on comparables, and uses hedged language.

Respond ONLY with the JSON object. No explanation outside JSON."""

# ── FastAPI ───────────────────────────────────────────────────────────────────

server = FastAPI(title="Guardrails Service", version="1.0.0")


class TextInput(BaseModel):
    text: str


@server.on_event("startup")
def _startup() -> None:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        log.warning("OPENAI_API_KEY not set — guardrail LLM calls will fail")
    else:
        log.info("OPENAI_API_KEY loaded: %s...%s (len=%d)", key[:8], key[-4:], len(key))
    _get_llm()
    log.info("LLM ready")


@server.get("/health")
def health():
    return {"status": "ok"}


@server.post("/check/input")
def check_input(body: TextInput):
    """Validate that the text is a genuine property listing."""
    if not body.text or not body.text.strip():
        return {"pass": False, "reason": "Empty submission."}

    log.info("[input]  checking %d chars", len(body.text))
    try:
        result = _classify(INPUT_SYSTEM, body.text)
        log.info("[input]  pass=%s  reason=%s", result.get("pass"), result.get("reason"))
        return result
    except Exception as exc:
        log.error("[input]  error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@server.post("/check/image-label")
def check_image_label(body: TextInput):
    """Validate that image labels are property-related."""
    if not body.text or not body.text.strip():
        return {"pass": False, "reason": "Empty label."}

    log.info("[image-label] checking labels: %s", body.text)
    try:
        result = _classify(IMAGE_LABEL_SYSTEM, body.text)
        log.info("[image-label] pass=%s  reason=%s", result.get("pass"), result.get("reason"))
        return result
    except Exception as exc:
        log.error("[image-label] error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@server.post("/check/output")
def check_output(body: TextInput):
    """Validate that the AI-generated report contains no false claims."""
    if not body.text or not body.text.strip():
        return {"pass": False, "reason": "Empty report."}

    log.info("[output] checking %d chars", len(body.text))
    try:
        result = _classify(OUTPUT_SYSTEM, body.text)
        log.info("[output] pass=%s  reason=%s", result.get("pass"), result.get("reason"))
        if result.get("pass"):
            result["safe_text"] = body.text
        return result
    except Exception as exc:
        log.error("[output] error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
