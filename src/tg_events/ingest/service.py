from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import ChannelInvalidError, UsernameInvalidError
from telethon.tl.types import (
    Channel as TlChannel,
    ChannelForbidden,
    PeerChannel,
    PeerUser,
    User as TlUser,
    DocumentAttributeAnimated,
)
from telethon.utils import get_display_name

from pathlib import Path
from tg_events.ingest.telethon_client import build_client, open_client
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
    async with open_client() as client:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session not authorized. Run tg_events.scripts.tg_auth first.")

        results: dict[str, str] = {}
        forward_cache: dict[tuple[str, int], dict[str, str | int | None]] = {}
        for ch in channels:
            key = ch
            try:
                target = ch
                if isinstance(ch, str) and ch.isdigit():
                    # first try as channel id, then as user id
                    try:
                        target = PeerChannel(int(ch))
                        entity = await client.get_entity(target)
                    except Exception:
                        target = PeerUser(int(ch))
                        entity = await client.get_entity(target)
                else:
                    entity = await client.get_entity(target)
            except (UsernameInvalidError, ChannelInvalidError):
                results[key] = "not_found"
                continue
            if isinstance(entity, ChannelForbidden):
                results[key] = "forbidden"
                continue
            # accept channels and users (private chats)
            if not isinstance(entity, (TlChannel, TlUser)):
                results[key] = "unsupported_peer"
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
            # fetch newest first
            async for msg in client.iter_messages(entity, limit=limit):
                if msg.id is None or msg.date is None:
                    continue
                exists = await get_message(session, channel_id=db_channel.id, msg_id=msg.id)
                attachments: dict | None = None
                features: dict | None = None
                media_items: list[dict] = []
                # Images
                if getattr(msg, "photo", None) is not None:
                    base = f"{getattr(entity, 'username', getattr(entity, 'id', 'chan'))}_{msg.id}"
                    out = await client.download_media(msg, file=str(media_root / base))
                    if out:
                        media_items.append({"path": Path(out).name, "kind": "photo", "mime": "image/jpeg"})
                else:
                    doc = getattr(msg, "document", None)
                    mime = getattr(doc, "mime_type", None) if doc is not None else None
                    if isinstance(mime, str):
                        if mime.startswith("image/"):
                            base = f"{getattr(entity, 'username', getattr(entity, 'id', 'chan'))}_{msg.id}"
                            out = await client.download_media(msg, file=str(media_root / base))
                            if out:
                                media_items.append({"path": Path(out).name, "kind": "photo", "mime": mime})
                        elif mime.startswith("video/"):
                            # detect animated gif-as-video
                            attrs = getattr(doc, "attributes", []) or []
                            is_gif = any(isinstance(a, DocumentAttributeAnimated) for a in attrs)
                            base = f"{getattr(entity, 'username', getattr(entity, 'id', 'chan'))}_{msg.id}"
                            out = await client.download_media(msg, file=str(media_root / base))
                            if out:
                                media_items.append(
                                    {"path": Path(out).name, "kind": "gif" if is_gif else "video", "mime": mime}
                                )
                if media_items:
                    attachments = {"media": media_items}
                # forward metadata
                fwd = getattr(msg, "fwd_from", None)
                if fwd is not None:
                    f_from_name = getattr(fwd, "from_name", None)
                    f_from = getattr(fwd, "from_id", None)
                    f_username: str | None = None
                    f_title: str | None = None
                    f_type: str | None = None
                    f_peer_id: int | None = None
                    if f_from is not None:
                        # PeerChannel / PeerUser
                        f_peer_id = getattr(f_from, "channel_id", None) or getattr(
                            f_from, "user_id", None
                        )
                        if getattr(f_from, "channel_id", None) is not None:
                            f_type = "channel"
                        elif getattr(f_from, "user_id", None) is not None:
                            f_type = "user"
                        # try resolve human-readable title/username via cache
                        if f_type and f_peer_id:
                            cache_key = (f_type, int(f_peer_id))
                            info = forward_cache.get(cache_key)
                            if info is None:
                                try:
                                    entity = (
                                        await client.get_entity(PeerChannel(int(f_peer_id)))
                                        if f_type == "channel"
                                        else await client.get_entity(PeerUser(int(f_peer_id)))
                                    )
                                    info = {
                                        "title": get_display_name(entity) or None,
                                        "username": getattr(entity, "username", None),
                                    }
                                except Exception:
                                    info = {"title": None, "username": None}
                                forward_cache[cache_key] = info
                            f_title = info.get("title") if info else None
                            f_username = info.get("username") if info else None
                    # Telethon не всегда даёт username в fwd header; оставим только name/id/type
                    features = {
                        "forward": {
                            "from_name": f_from_name,
                            "from_title": f_title,
                            "from_username": f_username,
                            "from_type": f_type,
                            "from_peer_id": f_peer_id,
                        }
                    }
                if exists is not None:
                    if update_existing_media:
                        update_values: dict[str, object] = {}
                        if attachments and not exists.attachments:
                            update_values["attachments"] = attachments
                        if features:
                            # update forward info if absent or can be enriched with title/username
                            existing_features = exists.features or {}
                            ef = existing_features.get("forward") if isinstance(existing_features, dict) else None
                            nf = features.get("forward")
                            should_update_forward = False
                            if not ef:
                                should_update_forward = True
                            else:
                                # enrich when missing title/username
                                missing_title = not bool(ef.get("from_title"))
                                missing_username = not bool(ef.get("from_username"))
                                have_new_title = bool(nf and nf.get("from_title"))
                                have_new_username = bool(nf and nf.get("from_username"))
                                if (missing_title and have_new_title) or (missing_username and have_new_username):
                                    should_update_forward = True
                                    # merge existing with new
                                    merged = dict(ef)
                                    merged.update({k: v for k, v in (nf or {}).items() if v is not None})
                                    features = dict(existing_features)
                                    features["forward"] = merged
                            if should_update_forward:
                                update_values["features"] = features
                        if update_values:
                            await session.execute(
                                update(MessageRaw).where(MessageRaw.id == exists.id).values(**update_values)
                            )
                            processed += 1
                    # else skip already stored message
                else:
                    await create_message(
                        session,
                        channel_id=db_channel.id,
                        msg_id=msg.id,
                        date=msg.date,
                        text=msg.message or None,
                        attachments=attachments,
                        features=features,
                    )
                    processed += 1
                if processed % 200 == 0:
                    await session.commit()

            # update last_message_id only for channels that expose it
            if isinstance(entity, TlChannel):
                await session.execute(
                    update(Channel)
                    .where(Channel.id == db_channel.id)
                    .values(last_message_id=getattr(entity, "max_read_msg_id", None))
                )
            await session.commit()
            results[key] = f"ok:{processed}"
        return results

    # unreachable


