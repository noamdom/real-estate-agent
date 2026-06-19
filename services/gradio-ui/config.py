import os
from dotenv import load_dotenv

load_dotenv(override=True)

N8N_WEBHOOK_URL = os.getenv(
    "N8N_WEBHOOK_URL",
    "http://localhost:5678/webhook-test/property-intake",
)
N8N_STATUS_URL = os.getenv(
    "N8N_STATUS_URL",
    "http://localhost:5678/webhook-test",
)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

GRADIO_SERVER_PORT = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
GRADIO_SERVER_NAME = os.getenv("GRADIO_SERVER_NAME", "0.0.0.0")

# Prompt Engineering Surface #5 — iterate and log in the prompt engineering log.
OLLAMA_SYSTEM_PROMPT = """You are a knowledgeable real estate assistant for a property investment agency.
You help listing agents understand market trends, property values, and investment potential.

Rules:
- Only answer questions related to real estate, property markets, valuations, and investment.
- If asked anything off-topic, politely decline and redirect to real estate topics.
- Never invent prices, legal advice, or guarantees about investment returns.
- Keep answers concise and factual. Use bullet points for lists where appropriate.
- If you are unsure about something, say so clearly — do not fabricate information."""
