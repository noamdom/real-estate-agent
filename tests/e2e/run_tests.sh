#!/usr/bin/env bash
# E2E test suite for the AI Property Triage System.
# Tests both services directly and the full n8n pipeline.
# Usage:
#   bash tests/e2e/run_tests.sh                          # run all groups, production webhook
#   bash tests/e2e/run_tests.sh --mode=debug             # run all groups, n8n test-mode webhook
#   bash tests/e2e/run_tests.sh --group=image-analyzer   # run one group only
#
# Groups: guardrails-input | guardrails-output | langgraph | n8n | image-analyzer

set -euo pipefail

MODE="production"
GROUP="all"

for arg in "$@"; do
  case "$arg" in
    --mode=debug)        MODE="debug" ;;
    --group=*)           GROUP="${arg#--group=}" ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

VALID_GROUPS="guardrails-input guardrails-output langgraph n8n image-analyzer all"
if [[ ! " $VALID_GROUPS " =~ " $GROUP " ]]; then
  echo "Unknown group: $GROUP"
  echo "Valid groups: guardrails-input | guardrails-output | langgraph | n8n | image-analyzer"
  exit 1
fi

should_run() { [ "$GROUP" = "all" ] || [ "$GROUP" = "$1" ]; }

if [ "$MODE" = "debug" ]; then
  N8N_WEBHOOK_PATH="webhook-test"
else
  N8N_WEBHOOK_PATH="webhook"
fi

N8N_URL="http://localhost:5678/${N8N_WEBHOOK_PATH}/property-intake"
GUARDRAILS_URL="http://localhost:9001"
LANGGRAPH_URL="http://localhost:9000"

echo "Mode: $MODE  Group: $GROUP  (n8n path: /${N8N_WEBHOOK_PATH}/property-intake)"

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

LG_UP=false; GR_UP=false; N8N_UP=false; IA_UP=false

if should_run langgraph || should_run guardrails-input || should_run guardrails-output; then
  if curl -sf --max-time 5 "$LANGGRAPH_URL/health" | grep -q '"ok"'; then
    pass "LangGraph service healthy (port 9000)"; LG_UP=true
  else
    fail "LangGraph service unreachable (port 9000)"
  fi

  if curl -sf --max-time 5 "$GUARDRAILS_URL/health" | grep -q '"ok"'; then
    pass "Guardrails service healthy (port 9001)"; GR_UP=true
  else
    fail "Guardrails service unreachable (port 9001)"
  fi
fi

if should_run n8n; then
  if curl -sf --max-time 3 "http://localhost:5678/" > /dev/null 2>&1; then
    pass "n8n reachable (port 5678)"; N8N_UP=true
  else
    fail "n8n unreachable (port 5678)"
  fi
fi

if should_run image-analyzer; then
  if curl -sf --max-time 5 "http://localhost:9002/health" | grep -q '"ok"'; then
    pass "Image Analyzer service healthy (port 9002)"; IA_UP=true
  else
    fail "Image Analyzer service unreachable (port 9002)"
  fi
fi

# ── Guardrails: input check ────────────────────────────────────────────────────

if should_run guardrails-input; then
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
fi

# ── Guardrails: output check ───────────────────────────────────────────────────

if should_run guardrails-output; then
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
fi

# ── LangGraph: direct analyze ─────────────────────────────────────────────────

if should_run langgraph; then
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

    # With image_analysis — verifies image scoring path contributes to deal_score
    LG_WITH_IMAGE=$(curl -sf -X POST "$LANGGRAPH_URL/analyze" \
      -H "Content-Type: application/json" \
      --max-time 90 \
      --data-raw '{
        "property_type": "apartment",
        "location": "Tel Aviv, Florentin",
        "description": "Renovated 3-room apartment, bright and quiet.",
        "price_asking": 3000000,
        "size_sqm": 85,
        "num_rooms": 3,
        "condition": "renovated",
        "intent": "sell",
        "image_analysis": [
          { "room_type": "kitchen",  "condition_score": 0.901, "confidence": 0.95 },
          { "room_type": "bedroom",  "condition_score": 0.697, "confidence": 0.46 }
        ]
      }')
    SCORE=$(python3 -c "import json; d=json.loads('''$LG_WITH_IMAGE'''); s=d.get('deal_score',0); print(s)" 2>/dev/null || echo "0")
    IMG_SUMMARY=$(python3 -c "import json; d=json.loads('''$LG_WITH_IMAGE'''); print(d.get('analysis',{}).get('image_summary',''))" 2>/dev/null || echo "")
    if python3 -c "import sys; sys.exit(0 if float('$SCORE') > 0 else 1)" 2>/dev/null && [ -n "$IMG_SUMMARY" ]; then
      pass "LangGraph: image_analysis path — deal_score=$SCORE  image_summary non-empty"
    else
      fail "LangGraph: image_analysis path — deal_score=$SCORE  image_summary='$IMG_SUMMARY'  raw=$LG_WITH_IMAGE"
    fi

    # No price_asking — must still return status=complete and estimated_price
    LG_NO_PRICE=$(curl -sf -X POST "$LANGGRAPH_URL/analyze" \
      -H "Content-Type: application/json" \
      --max-time 90 \
      --data-raw '{
        "property_type": "apartment",
        "location": "Tel Aviv, Florentin",
        "description": "Renovated 3-room apartment, bright and quiet.",
        "size_sqm": 85,
        "num_rooms": 3,
        "condition": "renovated",
        "intent": "sell"
      }')
    NP_STATUS=$(python3 -c "import json; print(json.loads('''$LG_NO_PRICE''').get('status','?'))" 2>/dev/null || echo "?")
    NP_SCORE=$(python3 -c "import json; d=json.loads('''$LG_NO_PRICE'''); print(d.get('deal_score','?'))" 2>/dev/null || echo "?")
    if [ "$NP_STATUS" = "complete" ]; then
      pass "LangGraph: no price_asking — status=complete  deal_score=$NP_SCORE"
    else
      fail "LangGraph: no price_asking — expected status=complete got=$NP_STATUS  raw=$LG_NO_PRICE"
    fi

  else
    skip "LangGraph sell test (service down)"
    skip "LangGraph rent test (service down)"
    skip "LangGraph image_analysis test (service down)"
    skip "LangGraph no-price test (service down)"
  fi
fi

# ── n8n: webhook end-to-end ───────────────────────────────────────────────────

if should_run n8n; then
  echo ""
  info "n8n webhook — end-to-end"

  # All n8n submissions use multipart/form-data (matching the v2 workflow)
  N8N_DATASET_DIR="$(dirname "$0")/../../assets/House_Room_Dataset"

  if [ "$N8N_UP" = "true" ]; then

    # Sell — text-only (no image)
    N8N_SELL=$(curl -sf -X POST "$N8N_URL" \
      --max-time 15 \
      -F "property_type=apartment" \
      -F "location=Tel Aviv, Florentin" \
      -F "description=Renovated 3-room apartment, bright and quiet. New kitchen, renovated bathroom, air conditioning throughout." \
      -F "price_asking=3000000" \
      -F "size_sqm=85" \
      -F "num_rooms=3" \
      -F "condition=renovated" \
      -F "intent=sell" \
      2>&1 || echo '{}')
    if has_key "$N8N_SELL" job_id || has_key "$N8N_SELL" jobId; then
      SELL_JOB=$(python3 -c "import json; d=json.loads('''$N8N_SELL'''); print(d.get('job_id') or d.get('jobId','?'))")
      pass "n8n webhook: sell submission accepted (job_id=$SELL_JOB)"
    else
      fail "n8n webhook: sell submission did not return job_id — $N8N_SELL"
    fi

    # Rent — text-only (no image)
    N8N_RENT=$(curl -sf -X POST "$N8N_URL" \
      --max-time 15 \
      -F "property_type=villa" \
      -F "location=Jerusalem, German Colony" \
      -F "description=Spacious 5-room villa with garden. Recently repainted, updated plumbing. Owner seeking long-term tenants." \
      -F "price_asking=12000" \
      -F "size_sqm=180" \
      -F "num_rooms=5" \
      -F "condition=good" \
      -F "intent=rent" \
      2>&1 || echo '{}')
    if has_key "$N8N_RENT" job_id || has_key "$N8N_RENT" jobId; then
      RENT_JOB=$(python3 -c "import json; d=json.loads('''$N8N_RENT'''); print(d.get('job_id') or d.get('jobId','?'))")
      pass "n8n webhook: rent submission accepted (job_id=$RENT_JOB)"
    else
      fail "n8n webhook: rent submission did not return job_id — $N8N_RENT"
    fi

    # Sell + image (bedroom photo from dataset)
    # Field name is file0 to match the indexed convention Gradio uses (file0, file1, …).
    N8N_IMAGE_FILE="$N8N_DATASET_DIR/Bedroom/$(ls "$N8N_DATASET_DIR/Bedroom/" | sort | tail -1)"
    N8N_WITH_IMAGE=$(curl -sf -X POST "$N8N_URL" \
      --max-time 15 \
      -F "property_type=apartment" \
      -F "location=Tel Aviv, Florentin" \
      -F "description=Renovated 3-room apartment with bright bedroom, new kitchen, renovated bathroom." \
      -F "price_asking=3000000" \
      -F "size_sqm=85" \
      -F "num_rooms=3" \
      -F "condition=renovated" \
      -F "intent=sell" \
      -F "file0=@$N8N_IMAGE_FILE" \
      2>&1 || echo '{}')
    if has_key "$N8N_WITH_IMAGE" job_id || has_key "$N8N_WITH_IMAGE" jobId; then
      IMG_JOB=$(python3 -c "import json; d=json.loads('''$N8N_WITH_IMAGE'''); print(d.get('job_id') or d.get('jobId','?'))")
      pass "n8n webhook: sell + image submission accepted (job_id=$IMG_JOB) — verify result includes Image Analysis section"
    else
      fail "n8n webhook: sell + image submission did not return job_id — $N8N_WITH_IMAGE"
    fi

    # Spam — guardrails should reject (row status → rejected)
    N8N_SPAM=$(curl -sf -X POST "$N8N_URL" \
      --max-time 15 \
      -F "description=Buy cheap Rolex watches now! Limited time offer, click here!" \
      2>&1 || echo '{}')
    if has_key "$N8N_SPAM" job_id || has_key "$N8N_SPAM" jobId; then
      SPAM_JOB=$(python3 -c "import json; d=json.loads('''$N8N_SPAM'''); print(d.get('job_id') or d.get('jobId','?'))")
      pass "n8n webhook: spam submission routed (job_id=$SPAM_JOB) — verify dataTable row shows status=rejected"
    else
      fail "n8n webhook: spam submission failed unexpectedly — $N8N_SPAM"
    fi

  else
    skip "n8n end-to-end tests (n8n not running)"
    skip "n8n end-to-end tests (n8n not running)"
    skip "n8n end-to-end tests (n8n not running)"
    skip "n8n end-to-end tests (n8n not running)"
  fi
fi

# ── Image Analyzer: per-room classification ───────────────────────────────────

if should_run image-analyzer; then
  echo ""
  info "Image Analyzer — room classification"

  DATASET_DIR="$(dirname "$0")/../../assets/House_Room_Dataset"
  IMAGE_ANALYZER_URL="http://localhost:9002"

  if [ "$IA_UP" = "true" ]; then

    room_label() {
      case "$1" in
        Bathroom)   echo "bathroom"   ;;
        Bedroom)    echo "bedroom"    ;;
        Dinning)    echo "dining_room" ;;
        Kitchen)    echo "kitchen"    ;;
        Livingroom) echo "living_room" ;;
      esac
    }

    for dir_name in Bathroom Bedroom Dinning Kitchen Livingroom; do
      expected="$(room_label "$dir_name")"
      image_path="$DATASET_DIR/$dir_name/$(ls "$DATASET_DIR/$dir_name/" | sort | tail -1)"

      IA_RESULT=$(curl -sf -X POST "$IMAGE_ANALYZER_URL/analyse" \
        --max-time 30 \
        -F "file=@$image_path" 2>&1 || echo '{}')

      predicted=$(python3 -c "import json; print(json.loads('''$IA_RESULT''').get('room_type','?'))" 2>/dev/null || echo "?")
      confidence=$(python3 -c "import json; print(json.loads('''$IA_RESULT''').get('confidence','?'))" 2>/dev/null || echo "?")

      if [ "$predicted" = "$expected" ]; then
        pass "Image Analyzer: $dir_name → $predicted (confidence=$confidence)"
      else
        fail "Image Analyzer: $dir_name → expected=$expected got=$predicted (confidence=$confidence)"
      fi
    done

  else
    for dir_name in Bathroom Bedroom Dinning Kitchen Livingroom; do
      skip "Image Analyzer: $dir_name (service down)"
    done
  fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo "  PASS: $PASS   FAIL: $FAIL   SKIP: $SKIP"
echo "============================================"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
