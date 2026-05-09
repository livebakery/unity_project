"""Detect when a Google Drive file has been modified."""
from __future__ import annotations

import json
import os

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]


def _drive_service():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not set.")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_modified_time(file_id: str) -> str:
    """Return RFC 3339 timestamp of the file's last modification."""
    svc = _drive_service()
    meta = svc.files().get(fileId=file_id, fields="modifiedTime,name").execute()
    return meta["modifiedTime"]
