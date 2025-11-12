from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import ChannelInvalidError, UsernameInvalidError
from telethon.tl.types import Channel as TlChannel, ChannelForbidden, PeerChannel

from pathlib import Path
from tg_events.ingest.telethon_client import build_client
from tg_events.config import get_settings
from tg_events.models import MessageRaw
from tg_events.models import Channel
from tg_events.repositories.channels import upsert_channel
from tg_events.repositories.messages import create_message, get_message


async def ingest_channels(
    session: AsyncSession,
    channels: Iterable[str],
    *,
    limit: int = 1000,
    update_existing_media: bool = False,
) -> dict[str, str]:
    """Fetch recent history for provided channels/usernames and store messages."""
    client = build_client()
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError("Telegram session not authorized. Run tg_events.scripts.tg_auth first.")

    results: dict[str, str] = {}
    try:
        for ch in channels:
            key = ch
            try:
                target = ch
                if isinstance(ch, str) and ch.isdigit():
                    target = PeerChannel(int(ch))
                entity = await client.get_entity(target)
            except (UsernameInvalidError, ChannelInvalidError):
                results[key] = "not_found"
                continue
            if isinstance(entity, ChannelForbidden):
                results[key] = "forbidden"
                continue
            if not isinstance(entity, TlChannel):
                results[key] = "not_a_channel"
                continue

            db_channel: Channel = await upsert_channel(
                session,
                tg_id=entity.id,
                username=getattr(entity, "username", None),
                title=getattr(entity, "title", None),
                is_private=bool(getattr(entity, "broadcast", False) is False),
            )
            await session.commit()

            processed = 0
            s = get_settings()
            media_root = Path(s.media_root)
            media_root.mkdir(parents=True, exist_ok=True)
            async for msg in client.iter_messages(entity, limit=limit, reverse=True):
                if msg.id is None or msg.date is None:
                    continue
                exists = await get_message(session, channel_id=db_channel.id, msg_id=msg.id)
                attachments: dict | None = None
                saved_paths: list[str] = []
                # download photos or image-documents
                is_image = False
                if getattr(msg, "photo", None) is not None:
                    is_image = True
                else:
                    doc = getattr(msg, "document", None)
                    mime = getattr(doc, "mime_type", None) if doc is not None else None
                    if isinstance(mime, str) and mime.startswith("image/"):
                        is_image = True
                if is_image:
                    base = f"{getattr(entity, 'username', getattr(entity, 'id', 'chan'))}_{msg.id}"
                    out = await client.download_media(msg, file=str(media_root / base))
                    if out:
                        # store relative path under media root
                        rel = Path(out).name
                        saved_paths.append(rel)
                if saved_paths:
                    attachments = {"media": saved_paths}
                if exists is not None:
                    if update_existing_media and attachments and not exists.attachments:
                        await session.execute(
                            update(MessageRaw)
                            .where(MessageRaw.id == exists.id)
                            .values(attachments=attachments)
                        )
                        processed += 1
                    else:
                        # skip already stored message
                        pass
                else:
                    await create_message(
                        session,
                        channel_id=db_channel.id,
                        msg_id=msg.id,
                        date=msg.date,
                        text=msg.message or None,
                        attachments=attachments,
                    )
                    processed += 1
                if processed % 200 == 0:
                    await session.commit()

            await session.execute(
                update(Channel)
                .where(Channel.id == db_channel.id)
                .values(last_message_id=getattr(entity, "max_read_msg_id", None))
            )
            await session.commit()
            results[key] = f"ok:{processed}"
    finally:
        await client.disconnect()

    return results


