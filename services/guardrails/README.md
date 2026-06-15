# Guardrails Service

Two endpoints that validate property submissions and AI-generated reports using NeMo Guardrails.

## How it works

```
Text in → NeMo reads Colang rail definitions → LLM classifies intent → pass or block
```

- **`/check/input`** — rejects spam, off-topic text, discriminatory content
- **`/check/output`** — flags fabricated prices, false legal claims, invented data

## Run

```bash
cp .env.example .env    # fill in OPENAI_API_KEY
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:server --port 9001 --reload
uvicorn main:server --port 9001 --reload --log-level debug  # debug
```

## Test

```bash
# valid listing → should pass
curl -s -X POST http://localhost:9001/check/input -H "Content-Type: application/json" -d '{"text": "3 bedroom apartment in Tel Aviv Florentin, 85sqm, asking 3M NIS, renovated"}' | jq

# spam → should block
curl -s -X POST http://localhost:9001/check/input \
  -H "Content-Type: application/json" \
  -d '{"text": "Buy cheap Rolex watches, limited offer!"}' | jq

# clean report → should pass
curl -s -X POST http://localhost:9001/check/output \
  -H "Content-Type: application/json" \
  -d '{"text": "Based on 3 comparable listings, we recommend negotiating to 2.85M NIS."}' | jq

# false claim → should flag
curl -s -X POST http://localhost:9001/check/output \
  -H "Content-Type: application/json" \
  -d '{"text": "This property is legally guaranteed to appreciate by 20% per year."}' | jq
```

## Rail files

```
rails/
  config.yml     ← LLM config + which rails are active
  input.co       ← Colang: valid listing vs spam/off-topic/offensive
  output.co      ← Colang: false claims, invented prices, bad legal advice
```

To tune a rail: edit the `.co` file and restart the server — no code changes needed.
