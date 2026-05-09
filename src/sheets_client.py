"""Read raw rows from a Google Sheet via service account."""
from __future__ import annotations

import json
import os
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _credentials() -> Credentials:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON env var is not set. "
            "Paste the service account JSON content into this variable."
        )
    info = json.loads(raw)
    return Credentials.from_service_account_info(info, scopes=SCOPES)


def read_sheet(sheet_id: str, worksheet_name: Optional[str] = None) -> list[list[str]]:
    """Return all values as a list of rows (each row = list of cell strings)."""
    client = gspread.authorize(_credentials())
    spreadsheet = client.open_by_key(sheet_id)
    ws = (
        spreadsheet.worksheet(worksheet_name)
        if worksheet_name
        else spreadsheet.sheet1
    )
    return ws.get_all_values()
