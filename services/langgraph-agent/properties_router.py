import logging
import os
from typing import Optional

import gspread
from fastapi import APIRouter, HTTPException
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)
router = APIRouter()

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
_HERE = os.path.dirname(os.path.abspath(__file__))
_creds_env = os.getenv("GOOGLE_CREDENTIALS_FILE", "google-credentials.json")
CREDS_FILE = _creds_env if os.path.isabs(_creds_env) else os.path.join(_HERE, _creds_env)


def _get_sheet():
    logger.info("_get_sheet: loading creds from %s (exists=%s)", CREDS_FILE, os.path.isfile(CREDS_FILE))
    creds = Credentials.from_service_account_file(
        CREDS_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    logger.info("_get_sheet: creds loaded, opening sheet %s", SHEET_ID)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(SHEET_ID).sheet1
    logger.info("_get_sheet: sheet opened OK")
    return sheet


@router.get("/properties")
def get_properties(
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    min_rooms: Optional[int] = None,
    max_price: Optional[int] = None,
    status: Optional[str] = None,
):
    logger.info("GET /properties location=%s type=%s min_rooms=%s max_price=%s status=%s",
                location, property_type, min_rooms, max_price, status)
    try:
        rows = _get_sheet().get_all_records()
        logger.info("fetched %d rows from sheet", len(rows))
    except Exception as e:
        logger.exception("Sheet read failed")
        raise HTTPException(status_code=500, detail=f"Sheet read failed: {e}")

    if location:
        rows = [r for r in rows if location.lower() in (r.get("location") or "").lower()]
    if property_type:
        rows = [r for r in rows if r.get("property_type") == property_type]
    if min_rooms is not None:
        rows = [r for r in rows if int(r.get("num_rooms") or 0) >= min_rooms]
    if max_price is not None:
        rows = [
            r for r in rows
            if not r.get("price_asking") or int(r.get("price_asking") or 0) <= max_price
        ]
    if status:
        rows = [r for r in rows if r.get("status") == status]

    return rows
