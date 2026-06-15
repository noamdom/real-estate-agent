import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv(override=True)

from nemoguardrails import LLMRails, RailsConfig  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("guardrails")

RAILS_DIR = Path(__file__).parent / "rails"

# Singleton — rails config is expensive to load
_rails: Optional[LLMRails] = None


def _get_rails() -> LLMRails:
    global _rails
    if _rails is None:
        log.info("Loading NeMo rails from %s", RAILS_DIR)
        config = RailsConfig.from_path(str(RAILS_DIR))
        _rails = LLMRails(config)
        log.info("NeMo rails loaded")
    return _rails


server = FastAPI(title="Guardrails Service", version="1.0.0")


class TextInput(BaseModel):
    text: str


@server.on_event("startup")
def _startup() -> None:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        log.warning("OPENAI_API_KEY not set — guardrail LLM calls will fail")
    else:
        log.info("OPENAI_API_KEY loaded: %s...%s", key[:8], key[-4:])
    _get_rails()  # pre-load on startup so first request isn't slow


@server.get("/health")
def health():
    return {"status": "ok"}


@server.post("/check/input")
async def check_input(body: TextInput):
    """
    Validates that the text is a genuine property listing.
    Returns pass=True if valid, pass=False + reason if rejected.
    """
    if not body.text or not body.text.strip():
        return {"pass": False, "reason": "Empty submission."}

    log.info("[input]  checking %d chars", len(body.text))
    try:
        rails = _get_rails()
        response = await rails.generate_async(
            messages=[{"role": "user", "content": body.text}]
        )
        log.info("[input]  rails response: %r", response[:120])

        if response.startswith("BLOCKED:"):
            reason = response.removeprefix("BLOCKED:").strip()
            log.info("[input]  BLOCKED — %s", reason)
            return {"pass": False, "reason": reason}

        log.info("[input]  PASS")
        return {"pass": True}

    except Exception as exc:
        log.error("[input]  rails error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@server.post("/check/output")
async def check_output(body: TextInput):
    """
    Validates that the AI-generated report contains no false claims.
    Returns pass=True if clean, pass=False + reason + safe_text if flagged.
    """
    if not body.text or not body.text.strip():
        return {"pass": False, "reason": "Empty report."}

    log.info("[output] checking %d chars", len(body.text))
    try:
        rails = _get_rails()
        # Send the report as an assistant message — output rails evaluate it
        response = await rails.generate_async(
            messages=[
                {"role": "user", "content": "Review this property report for accuracy."},
                {"role": "assistant", "content": body.text},
            ]
        )
        log.info("[output] rails response: %r", response[:120])

        if response.startswith("FLAGGED:"):
            reason = response.removeprefix("FLAGGED:").strip()
            log.info("[output] FLAGGED — %s", reason)
            return {
                "pass": False,
                "reason": reason,
                "safe_text": None,
            }

        log.info("[output] PASS")
        return {"pass": True, "safe_text": body.text}

    except Exception as exc:
        log.error("[output] rails error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
