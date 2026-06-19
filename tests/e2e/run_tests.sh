#!/usr/bin/env bash
# E2E test suite for the AI Property Triage System.
# Tests both services directly and the full n8n pipeline.
# Usage:
#   bash tests/e2e/run_tests.sh              # production webhook (/webhook/)
#   bash tests/e2e/run_tests.sh --mode=debug # n8n test-mode webhook (/webhook-test/)

set -euo pipefail

MODE="production"
for arg in "$@"; do
  case "$arg" in
    --mode=debug) MODE="debug" ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

if [ "$MODE" = "debug" ]; then
  N8N_WEBHOOK_PATH="webhook-test"
else
  N8N_WEBHOOK_PATH="webhook"
fi

N8N_URL="http://localhost:5678/${N8N_WEBHOOK_PATH}/property-intake"
GUARDRAILS_URL="http://localhost:9001"
LANGGRAPH_URL="http://localhost:9000"

echo "Mode: $MODE  (n8n path: /${N8N_WEBHOOK_PATH}/property-intake)"

PASS=0
FAIL=0
SKIP=0

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass()  { echo -e "${GREEN}[PASS]${NC} $1"; ((PASS++))  || true; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; ((FAIL++))   || true; }
skip()  { echo -e "${YELLOW}[SKIP]${NC} $1"; ((SKIP++)) || true; }
info()  { echo -e "${YELLOW}---${NC} $1"; }

json_bool() {
  # json_bool <json_string> <key> <expected: true|false>
  python3 -c "
import sys, json
d = json.loads('''$1''')
got = bool(d.get('$2'))
sys.exit(0 if (got == ('$3' == 'true')) else 1)
"
}

has_key() {
  python3 -c "import sys,json; d=json.loads('''$1'''); sys.exit(0 if '$2' in d else 1)"
}

# ── Health checks ──────────────────────────────────────────────────────────────

info "Health checks"

if curl -sf --max-time 5 "$LANGGRAPH_URL/health" | grep -q '"ok"'; then
  pass "LangGraph service healthy (port 9000)"
  LG_UP=true
else
  fail "LangGraph service unreachable (port 9000)"
  LG_UP=false
fi

if curl -sf --max-time 5 "$GUARDRAILS_URL/health" | grep -q '"ok"'; then
  pass "Guardrails service healthy (port 9001)"
  GR_UP=true
else
  fail "Guardrails service unreachable (port 9001)"
  GR_UP=false
fi

N8N_UP=false
if curl -sf --max-time 3 "http://localhost:5678/" > /dev/null 2>&1; then
  pass "n8n reachable (port 5678)"
  N8N_UP=true
else
  fail "n8n unreachable (port 5678)"
fi

# ── Guardrails: input check ────────────────────────────────────────────────────

echo ""
info "Guardrails — input check"

if [ "$GR_UP" = "true" ]; then

  VALID_TEXT="3 bedroom apartment in Tel Aviv Florentin, 85sqm, asking 3,000,000 NIS, renovated kitchen and bathroom, bright and quiet"
  GR_VALID=$(curl -sf -X POST "$GUARDRAILS_URL/check/input" \
    -H "Content-Type: application/json" \
    --data-raw "{\"text\": \"$VALID_TEXT\"}")
  if json_bool "$GR_VALID" pass true; then
    pass "Guardrails input: valid property listing accepted"
  else
    fail "Guardrails input: valid listing incorrectly blocked — $GR_VALID"
  fi

  SPAM_TEXT="Buy cheap Rolex watches now! Limited time offer, click here to make money fast!"
  GR_SPAM=$(curl -sf -X POST "$GUARDRAILS_URL/check/input" \
    -H "Content-Type: application/json" \
    --data-raw "{\"text\": \"$SPAM_TEXT\"}")
  if json_bool "$GR_SPAM" pass false; then
    pass "Guardrails input: spam correctly blocked"
  else
    fail "Guardrails input: spam was not blocked — $GR_SPAM"
  fi

else
  skip "Guardrails input tests (service down)"
  skip "Guardrails input tests (service down)"
fi

# ── Guardrails: output check ───────────────────────────────────────────────────

echo ""
info "Guardrails — output check"

if [ "$GR_UP" = "true" ]; then

  FALSE_CLAIM="Based on our analysis, this property is legally guaranteed to appreciate by 20% annually. Sign the contract immediately — there is no legal risk."
  GR_FALSE=$(curl -sf -X POST "$GUARDRAILS_URL/check/output" \
    -H "Content-Type: application/json" \
    --data-raw "{\"text\": \"$FALSE_CLAIM\"}")
  if json_bool "$GR_FALSE" pass false; then
    pass "Guardrails output: false legal guarantee correctly flagged"
  else
    fail "Guardrails output: false claim was not flagged — $GR_FALSE"
  fi

  SAFE_REPORT="Based on comparable sales in Tel Aviv Florentin, similar 3-room apartments sold for 2.8M-3.2M NIS in Q1 2024. This property appears fairly priced. Market conditions may change; consult a licensed appraiser before proceeding."
  GR_SAFE=$(curl -sf -X POST "$GUARDRAILS_URL/check/output" \
    -H "Content-Type: application/json" \
    --data-raw "{\"text\": \"$SAFE_REPORT\"}")
  if json_bool "$GR_SAFE" pass true; then
    pass "Guardrails output: safe hedged report accepted"
  else
    fail "Guardrails output: safe report incorrectly flagged — $GR_SAFE"
  fi

else
  skip "Guardrails output tests (service down)"
  skip "Guardrails output tests (service down)"
fi

# ── LangGraph: direct analyze ─────────────────────────────────────────────────

echo ""
info "LangGraph — direct analyze"

if [ "$LG_UP" = "true" ]; then

  LG_SELL=$(curl -sf -X POST "$LANGGRAPH_URL/analyze" \
    -H "Content-Type: application/json" \
    --max-time 90 \
    --data-raw '{
      "property_type": "apartment",
      "location": "Tel Aviv, Florentin",
      "description": "Renovated 3-room apartment, bright and quiet. New kitchen, renovated bathroom, air conditioning throughout. Close to Carmel Market and public transport.",
      "agent_name": "Test Agent",
      "price_asking": 3000000,
      "size_sqm": 85,
      "num_rooms": 3,
      "condition": "renovated",
      "intent": "sell"
    }')
  if has_key "$LG_SELL" analysis; then
    LG_SELL_INTENT=$(python3 -c "import json; print(json.loads('''$LG_SELL''').get('intent','?'))")
    pass "LangGraph: sell listing analyzed — intent=$LG_SELL_INTENT"
  else
    fail "LangGraph: sell listing analysis failed — $LG_SELL"
  fi

  LG_RENT=$(curl -sf -X POST "$LANGGRAPH_URL/analyze" \
    -H "Content-Type: application/json" \
    --max-time 90 \
    --data-raw '{
      "property_type": "villa",
      "location": "Jerusalem, German Colony",
      "description": "Spacious 5-room villa with garden in the prestigious German Colony. Recently repainted, updated plumbing. Walking distance to Emek Refaim. Owner seeking long-term tenants.",
      "agent_name": "Test Agent",
      "price_asking": 12000,
      "size_sqm": 180,
      "num_rooms": 5,
      "condition": "good",
      "intent": "rent"
    }')
  if has_key "$LG_RENT" analysis; then
    LG_RENT_INTENT=$(python3 -c "import json; print(json.loads('''$LG_RENT''').get('intent','?'))")
    pass "LangGraph: rent listing analyzed — intent=$LG_RENT_INTENT"
  else
    fail "LangGraph: rent listing analysis failed — $LG_RENT"
  fi

else
  skip "LangGraph sell test (service down)"
  skip "LangGraph rent test (service down)"
fi

# ── n8n: webhook end-to-end ───────────────────────────────────────────────────

echo ""
info "n8n webhook — end-to-end"

if [ "$N8N_UP" = "true" ]; then

  # Sell submission: should get a job_id back immediately
  N8N_SELL=$(curl -sf -X POST "$N8N_URL" \
    -H "Content-Type: application/json" \
    --max-time 15 \
    --data-raw '{
      "property_type": "apartment",
      "location": "Tel Aviv, Florentin",
      "description": "Renovated 3-room apartment, bright and quiet. New kitchen, renovated bathroom, air conditioning throughout.",
      "price_asking": 3000000,
      "size_sqm": 85,
      "num_rooms": 3,
      "condition": "renovated",
      "intent": "sell"
    }' 2>&1 || echo '{}')
  if has_key "$N8N_SELL" job_id || has_key "$N8N_SELL" jobId; then
    SELL_JOB=$(python3 -c "import json; d=json.loads('''$N8N_SELL'''); print(d.get('job_id') or d.get('jobId','?'))")
    pass "n8n webhook: sell submission accepted (job_id=$SELL_JOB)"
  else
    fail "n8n webhook: sell submission did not return job_id — $N8N_SELL"
  fi

  # Rent submission
  N8N_RENT=$(curl -sf -X POST "$N8N_URL" \
    -H "Content-Type: application/json" \
    --max-time 15 \
    --data-raw '{
      "property_type": "villa",
      "location": "Jerusalem, German Colony",
      "description": "Spacious 5-room villa with garden. Recently repainted, updated plumbing. Owner seeking long-term tenants.",
      "price_asking": 12000,
      "size_sqm": 180,
      "num_rooms": 5,
      "condition": "good",
      "intent": "rent"
    }' 2>&1 || echo '{}')
  if has_key "$N8N_RENT" job_id || has_key "$N8N_RENT" jobId; then
    RENT_JOB=$(python3 -c "import json; d=json.loads('''$N8N_RENT'''); print(d.get('job_id') or d.get('jobId','?'))")
    pass "n8n webhook: rent submission accepted (job_id=$RENT_JOB)"
  else
    fail "n8n webhook: rent submission did not return job_id — $N8N_RENT"
  fi

  # Spam submission: n8n still returns job_id (processing is async),
  # but guardrails will reject it and set row status → rejected in dataTable.
  N8N_SPAM=$(curl -sf -X POST "$N8N_URL" \
    -H "Content-Type: application/json" \
    --max-time 15 \
    --data-raw '{
      "description": "Buy cheap Rolex watches now! Limited time offer, click here!"
    }' 2>&1 || echo '{}')
  if has_key "$N8N_SPAM" job_id || has_key "$N8N_SPAM" jobId; then
    SPAM_JOB=$(python3 -c "import json; d=json.loads('''$N8N_SPAM'''); print(d.get('job_id') or d.get('jobId','?'))")
    pass "n8n webhook: spam submission routed to pipeline (job_id=$SPAM_JOB) — verify dataTable row shows status=rejected"
  else
    fail "n8n webhook: spam submission failed unexpectedly — $N8N_SPAM"
  fi

else
  skip "n8n end-to-end tests (n8n not running)"
  skip "n8n end-to-end tests (n8n not running)"
  skip "n8n end-to-end tests (n8n not running)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo "  PASS: $PASS   FAIL: $FAIL   SKIP: $SKIP"
echo "============================================"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
