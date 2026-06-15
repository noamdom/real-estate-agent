import requests
import json
import time
from pydantic import BaseModel
from typing import Optional

# ── Config ───────────────────────────────────────────────────────
N8N_WEBHOOK_URL = "http://host.docker.internal:5678/webhook-test/property-intake"
N8N_STATUS_URL = "http://host.docker.internal:5678/webhook/property-status"

TRIGGER_PHRASE_1 = "wewewe"
TRIGGER_PHRASE_2 = "fdsfds"

MOCK_PAYLOADS = {
    TRIGGER_PHRASE_1: {
        "property_type": "apartment",
        "location": "Tel Aviv, Florentin",
        "description": "3 room apartment, second floor, renovated kitchen, balcony facing west, quiet street.",
        "agent_name": "Noam Cohen",
        "price_asking": 3000000,
        "size_sqm": 85,
        "num_rooms": 3,
        "condition": "renovated",
        "intent": "sell",
    },
    TRIGGER_PHRASE_2: {
        "property_type": "villa",
        "location": "Jerusalem, Rehavia",
        "description": "7 room stone villa, renovated, private garden, 2 parking spots, original architectural details.",
        "agent_name": "Noam Cohen",
        "price_asking": 10000000,
        "size_sqm": 290,
        "num_rooms": 7,
        "condition": "renovated",
        "intent": "sell",
    },
}

POLL_INTERVAL = 10  # seconds between polls
POLL_MAX = 10  # max attempts (30 seconds total)


# ── Helpers ──────────────────────────────────────────────────────
def submit_to_n8n(payload: dict) -> Optional[str]:
    r = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data.get("job_id")


def poll_n8n(job_id: str) -> Optional[str]:
    """
    Polls the status endpoint until done or max attempts reached.
    Returns the result string or None on timeout.
    """
    for attempt in range(1, POLL_MAX + 1):
        time.sleep(POLL_INTERVAL)
        try:
            r = requests.get(f"{N8N_STATUS_URL}", params={"job_id": job_id}, timeout=10)
            data = r.json()
            print(f"Poll attempt {attempt}: {data}")

            if data.get("status") == "done":
                return data.get("result", "Analysis complete.")

            if data.get("status") == "error":
                return f"Processing failed: {data.get('reason', 'unknown error')}"

        except Exception as e:
            print(f"Poll attempt {attempt} failed: {e}")

    return None  # timeout


# ── Filter ───────────────────────────────────────────────────────
class Filter:

    class Valves(BaseModel):
        pass

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        return body

    def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        messages = body.get("messages", [])

        user_messages = [m for m in messages if m["role"] == "user"]
        if not user_messages:
            return body

        last_user_msg = user_messages[-1].get("content", "").lower().strip()
        matched_trigger = None
        for trigger in MOCK_PAYLOADS:
            if trigger in last_user_msg:
                matched_trigger = trigger
                break

        if not matched_trigger:
            return body
        # ── Step 1: Submit ────────────────────────────────────────
        result_text = ""
        try:
            print("=== SUBMITTING TO N8N ===")
            job_id = submit_to_n8n(MOCK_PAYLOADS[matched_trigger])
            print(f"Got job_id: {job_id}")

            if not job_id:
                result_text = "❌ Submission failed — no job_id returned."
            else:
                # ── Step 2: Poll ──────────────────────────────────
                print(f"Polling for result (job_id: {job_id})...")
                result = poll_n8n(job_id)

                if result:
                    result_text = (
                        f"✅ **Submission accepted** (job `{job_id}`)\n\n"
                        f"🏡 **Property Analysis:**\n\n{result}"
                    )
                else:
                    result_text = (
                        f"⏳ **Submission accepted** (job `{job_id}`)\n\n"
                        f"Analysis is taking longer than expected. "
                        f"We'll follow up with you shortly."
                    )

        except requests.exceptions.ConnectionError:
            result_text = "❌ Could not reach n8n. Check `host.docker.internal:5678`."
        except requests.exceptions.Timeout:
            result_text = "❌ n8n did not respond in time."
        except Exception as e:
            result_text = f"❌ Error: `{str(e)}`"

        # ── Append result to last assistant message ───────────────
        assistant_messages = [m for m in messages if m["role"] == "assistant"]
        if assistant_messages:
            assistant_messages[-1]["content"] = (
                f"{assistant_messages[-1]['content']}\n\n---\n"
                f"🧪 **Test Submission**\n{result_text}"
            )
            body["messages"] = messages

        return body
