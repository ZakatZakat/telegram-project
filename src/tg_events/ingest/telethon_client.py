from __future__ import annotations

from pathlib import Path
from typing import Optional

from telethon import TelegramClient

from tg_events.config import get_settings


def build_client(session_path: Optional[str] = None) -> TelegramClient:
    """Create Telethon client from settings."""
    s = get_settings()
    if s.telegram_api_id is None or s.telegram_api_hash is None:
        raise RuntimeError("TELEGRAM_API_ID/TELEGRAM_API_HASH must be set")
    session_file = Path(session_path or s.telegram_session_path)
    session_file.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(session_file), s.telegram_api_id, s.telegram_api_hash)


