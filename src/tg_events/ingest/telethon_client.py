from __future__ import annotations

from pathlib import Path
from typing import Optional
import asyncio
from contextlib import asynccontextmanager

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


_TELETHON_SESSION_LOCK: asyncio.Lock = asyncio.Lock()


@asynccontextmanager
async def open_client(session_path: Optional[str] = None):
    """Serialize access to the Telethon SQLite session to avoid 'database is locked'."""
    client = build_client(session_path)
    await _TELETHON_SESSION_LOCK.acquire()
    try:
        await client.connect()
        try:
            yield client
        finally:
            await client.disconnect()
    finally:
        _TELETHON_SESSION_LOCK.release()


