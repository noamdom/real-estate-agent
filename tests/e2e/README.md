# E2E Tests

End-to-end test suite for the AI Property Triage System.

## Pre-conditions

Start both services before running:

```bash
# Terminal 1 — LangGraph Agent (port 9000)
cd services/langgraph-agent
source .venv/bin/activate
uvicorn main:server --port 9000 --reload

# Terminal 2 — Guardrails (port 9001)
cd services/guardrails
source .venv/bin/activate
uvicorn main:server --port 9001 --reload

# Terminal 3 — n8n (port 5678)
docker run -it --rm -p 5678:5678 -v n8n_data:/home/node/.n8n n8nio/n8n
```

Then import `n8n-workflows/property-intake-guardrails-v1.json` in the n8n UI and click **"Test workflow"** to activate the `/webhook-test/` path.

## Running

```bash
# Run all groups, production webhook (/webhook/) — default
bash tests/e2e/run_tests.sh

# Run all groups, n8n test-mode webhook (/webhook-test/)
bash tests/e2e/run_tests.sh --mode=debug

# Run a single group only
bash tests/e2e/run_tests.sh --group=image-analyzer
bash tests/e2e/run_tests.sh --group=guardrails-input
bash tests/e2e/run_tests.sh --group=guardrails-output
bash tests/e2e/run_tests.sh --group=langgraph
bash tests/e2e/run_tests.sh --group=n8n

# Combine flags
bash tests/e2e/run_tests.sh --group=n8n --mode=debug
```

### Groups

| Group | Services needed | What it tests |
|-------|----------------|---------------|
| `guardrails-input` | port 9001 | Valid listing accepted, spam blocked |
| `guardrails-output` | port 9001 | False legal claim flagged, safe report accepted |
| `langgraph` | port 9000 | Sell and rent listing analysis |
| `n8n` | port 5678 | Full webhook pipeline (sell, rent, spam) |
| `image-analyzer` | port 9002 | Room classification for each room in the dataset |

## Test cases

| # | Target | Case | Expected |
|---|--------|------|----------|
| 1 | Guardrails `/check/input` | Valid sell listing | `pass: true` |
| 2 | Guardrails `/check/input` | Spam text | `pass: false` |
| 3 | Guardrails `/check/output` | False legal guarantee | `pass: false` |
| 4 | Guardrails `/check/output` | Hedged factual report | `pass: true` |
| 5 | LangGraph `/analyze` | Full sell payload | `analysis` field present |
| 6 | LangGraph `/analyze` | Full rent payload | `analysis` field present |
| 7 | n8n webhook | Sell submission (text-only, multipart) | `job_id` returned |
| 8 | n8n webhook | Rent submission (text-only, multipart) | `job_id` returned |
| 9 | n8n webhook | Sell + image file (multipart) | `job_id` returned; verify result includes `Image Analysis` |
| 10 | n8n webhook | Spam submission | `job_id` returned; verify dataTable row shows `status: rejected` |

> **Note on n8n async tests (cases 7–9):** The webhook responds immediately with a `job_id`. The pipeline continues asynchronously — open the n8n execution log or the `fp-req-status` dataTable to confirm the final row status (`done`, `rejected`, or `flagged`).

## Expected response shapes

See `expected/` for reference JSON shapes:

- `sell_pass.json` — LangGraph sell response
- `rent_pass.json` — LangGraph rent response
- `spam_block.json` — Guardrails blocked input response
