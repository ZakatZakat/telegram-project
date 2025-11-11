from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tg_events.models import Channel


async def get_by_username(session: AsyncSession, username: str) -> Optional[Channel]:
    stmt = select(Channel).where(Channel.username == username)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def get_by_tg_id(session: AsyncSession, tg_id: int) -> Optional[Channel]:
    stmt = select(Channel).where(Channel.tg_id == tg_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def upsert_channel(
    session: AsyncSession,
    *,
    tg_id: Optional[int],
    username: Optional[str],
    title: Optional[str],
    is_private: bool,
) -> Channel:
    existing: Optional[Channel] = None
    if tg_id is not None:
        existing = await get_by_tg_id(session, tg_id)
    if existing is None and username:
        existing = await get_by_username(session, username)

    if existing is None:
        channel = Channel(
            tg_id=tg_id,
            username=username,
            title=title,
            is_private=is_private,
        )
        session.add(channel)
        await session.flush()
        return channel
    else:
        await session.execute(
            update(Channel)
            .where(Channel.id == existing.id)
            .values(
                tg_id=tg_id if tg_id is not None else existing.tg_id,
                username=username or existing.username,
                title=title or existing.title,
                is_private=is_private,
            )
        )
        await session.flush()
        return existing


