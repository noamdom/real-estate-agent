import logging
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Load .env before any LangChain/OpenAI clients are imported or initialized.
# override=True ensures .env always wins over any stale shell export.
load_dotenv(override=True)

from graph import app as langgraph_app  # noqa: E402 — must be after load_dotenv

log = logging.getLogger("langgraph")

server = FastAPI(title="LangGraph Property Analysis Service", version="1.0.0")


@server.on_event("startup")
def _log_key_info() -> None:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        log.warning("OPENAI_API_KEY is NOT set — LLM calls will fail")
    else:
        log.info("OPENAI_API_KEY loaded: %s...%s (len=%d)", key[:8], key[-4:], len(key))

    pinecone_key = os.environ.get("PINECONE_API_KEY", "")
    if not pinecone_key:
        log.warning("PINECONE_API_KEY is NOT set — RAG calls will fail")
    else:
        log.info("PINECONE_API_KEY loaded: %s...%s", pinecone_key[:6], pinecone_key[-4:])


class SubmissionPayload(BaseModel):
    property_type: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    agent_name: Optional[str] = None
    price_asking: Optional[float] = None
    size_sqm: Optional[float] = None
    num_rooms: Optional[int] = None
    condition: Optional[str] = None
    intent: Optional[str] = None  # caller may supply "sell" | "rent" directly


@server.get("/health")
def health():
    return {"status": "ok"}


@server.post("/analyze")
def analyze(payload: SubmissionPayload):
    initial_state = {
        "raw_payload": payload.model_dump(),
        "normalized": None,
        "intent": None,
        "confidence": None,
        "missing_fields": [],
        "rag_comps": [],
        "clarification_message": None,
        "analysis": None,
        "status": None,
    }

    try:
        result = langgraph_app.invoke(initial_state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "intent": result.get("intent"),
        "confidence": result.get("confidence"),
        "status": result.get("status"),
        "normalized": result.get("normalized"),
        "rag_comps": result.get("rag_comps", []),
        "analysis": result.get("analysis"),
        "missing_fields": result.get("missing_fields", []),
        "clarification_message": result.get("clarification_message"),
    }
