# Gradio Web UI

Two-tab Gradio application for the AI Property Triage System.

| Tab | Purpose |
|-----|---------|
| 💬 Assistant | Conversational real-estate chat via local Ollama |
| 📋 Submit Listing | Property submission form → n8n pipeline → live result |

## Prerequisites

- Ollama running locally with a model pulled:
  ```bash
  ollama pull llama3.1
  ```
- Backend services running on their default ports (9000, 9001, 9002)
- n8n running on port 5678 with the workflow active

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit if your ports differ
python app.py
# → open http://localhost:7860
```

## Docker

```bash
# Build
docker build -t gradio-ui .

# Run (local — reaches host services via host.docker.internal)
docker run -p 7860:7860 \
  --env-file .env \
  --add-host=host.docker.internal:host-gateway \
  gradio-ui
```

Uncomment the `host.docker.internal` lines in `.env` when running inside Docker.

## Environment variables

| Variable | Default | Notes |
|----------|---------|-------|
| `N8N_WEBHOOK_URL` | `http://localhost:5678/webhook-test/property-intake` | Use `/webhook/` for published workflow |
| `N8N_STATUS_URL` | `http://localhost:5678/webhook-test` | Base URL for status polling |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `OLLAMA_MODEL` | `llama3.1` | Any model available in Ollama |
| `GRADIO_SERVER_PORT` | `7860` | |
| `GRADIO_SERVER_NAME` | `0.0.0.0` | Bind address |
