from __future__ import annotations

from typing import Any, List, Optional, TypedDict

from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_events.models import Channel, MessageRaw
from tg_events.config import get_settings


class MiniappPost(TypedDict, total=False):
    id: int
    msg_id: int
    date: str
    text: str
    channel_title: str | None
    channel_username: str | None
    source_url: str | None


async def list_recent_messages(
    session: AsyncSession,
    *,
    limit: int = 100,
    channel_username: Optional[str] = None,
) -> List[MiniappPost]:
    settings = get_settings()
    stmt: Select[Any] = (
        select(
            MessageRaw.id,
            MessageRaw.msg_id,
            MessageRaw.date,
            MessageRaw.text,
            MessageRaw.attachments,
            Channel.title,
            Channel.username,
        )
        .join(Channel, Channel.id == MessageRaw.channel_id)
        .order_by(desc(MessageRaw.date))
        .limit(limit)
    )
    if channel_username:
        stmt = stmt.where(Channel.username == channel_username)
    rows = (await session.execute(stmt)).all()
    items: List[MiniappPost] = []
    for rid, msg_id, date, text, attachments, title, username in rows:
        source_url: Optional[str] = None
        if username:
            source_url = f"https://t.me/{username}/{msg_id}"
        media_urls: Optional[list[str]] = None
        if attachments and isinstance(attachments, dict):
            media = attachments.get("media")
            if isinstance(media, list):
                media_urls = [f"/media/{m}" for m in media]
        item: MiniappPost = {
            "id": int(rid),
            "msg_id": int(msg_id),
            "date": date.isoformat(),
            "text": text or "",
            "channel_title": title,
            "channel_username": username,
            "source_url": source_url,
        }
        if media_urls:
            item["media_urls"] = media_urls
        items.append(item)
    return items


