import logging

import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from labels import CONDITION_PROMPTS, CONDITION_WEIGHTS, OPEN_LABELS

log = logging.getLogger("image-analyzer")

MODEL_ID = "openai/clip-vit-base-patch32"

_model: CLIPModel | None = None
_processor: CLIPProcessor | None = None


def _load() -> None:
    global _model, _processor
    if _model is not None:
        return
    log.info("Loading CLIP model %s ...", MODEL_ID)
    _model = CLIPModel.from_pretrained(MODEL_ID)
    _processor = CLIPProcessor.from_pretrained(MODEL_ID)
    _model.eval()
    log.info("CLIP model ready")


def analyse(image: Image.Image) -> dict:
    _load()

    # ── Scene classification ───────────────────────────────────────────────────
    inputs = _processor(
        text=OPEN_LABELS,
        images=image,
        return_tensors="pt",
        padding=True,
    )
    with torch.no_grad():
        logits = _model(**inputs).logits_per_image  # shape: (1, num_labels)

    room_probs = logits.softmax(dim=1)[0]
    room_idx = int(room_probs.argmax())
    confidence = round(float(room_probs[room_idx]), 3)

    # ── Condition score ────────────────────────────────────────────────────────
    cond_inputs = _processor(
        text=CONDITION_PROMPTS,
        images=image,
        return_tensors="pt",
        padding=True,
    )
    with torch.no_grad():
        cond_logits = _model(**cond_inputs).logits_per_image

    cond_probs = cond_logits.softmax(dim=1)[0]
    condition_score = round(
        float(sum(cond_probs[i] * CONDITION_WEIGHTS[i] for i in range(len(CONDITION_PROMPTS)))),
        3,
    )

    return {
        "room_type": OPEN_LABELS[room_idx],
        "condition_score": condition_score,
        "confidence": confidence,
    }
