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
    channel_tg_id: Optional[int] = None,
) -> List[MiniappPost]:
    settings = get_settings()
    stmt: Select[Any] = (
        select(
            MessageRaw.id,
            MessageRaw.msg_id,
            MessageRaw.date,
            MessageRaw.text,
            MessageRaw.attachments,
            MessageRaw.features,
            Channel.title,
            Channel.username,
        )
        .join(Channel, Channel.id == MessageRaw.channel_id)
        .order_by(desc(MessageRaw.date))
        .limit(limit)
    )
    if channel_username:
        stmt = stmt.where(Channel.username == channel_username)
    if channel_tg_id is not None:
        stmt = stmt.where(Channel.tg_id == channel_tg_id)
    rows = (await session.execute(stmt)).all()
    items: List[MiniappPost] = []
    for rid, msg_id, date, text, attachments, features, title, username in rows:
        source_url: Optional[str] = None
        if username:
            source_url = f"https://t.me/{username}/{msg_id}"
        media_urls: Optional[list[str]] = None
        media_items_fmt: Optional[list[dict]] = None
        if attachments and isinstance(attachments, dict):
            media = attachments.get("media")
            if isinstance(media, list):
                # backward compatibility: list[str]
                if media and isinstance(media[0], str):
                    media_urls = [f"/media/{m}" for m in media]
                else:
                    # list[dict] with path/kind/mime
                    media_items_fmt = []
                    for it in media:
                        if not isinstance(it, dict):
                            continue
                        path = it.get("path")
                        if not path:
                            continue
                        url = f"/media/{path}"
                        kind = it.get("kind") or "photo"
                        mime = it.get("mime")
                        media_items_fmt.append({"url": url, "kind": kind, "mime": mime})
        item: MiniappPost = {
            "id": int(rid),
            "msg_id": int(msg_id),
            "date": date.isoformat(),
            "text": text or "",
            "channel_title": title,
            "channel_username": username,
            "source_url": source_url,
        }
        if features and isinstance(features, dict):
            fwd = features.get("forward")
            if isinstance(fwd, dict):
                item["forward"] = {
                    "from_name": fwd.get("from_name"),
                    "from_title": fwd.get("from_title"),
                    "from_username": fwd.get("from_username"),
                    "from_type": fwd.get("from_type"),
                    "from_peer_id": fwd.get("from_peer_id"),
                }
        if media_urls:
            item["media_urls"] = media_urls
        if media_items_fmt:
            item["media"] = media_items_fmt
        items.append(item)
    return items


