from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_events.models import MessageRaw


async def get_message(
    session: AsyncSession, *, channel_id: int, msg_id: int
) -> Optional[MessageRaw]:
    stmt = select(MessageRaw).where(
        MessageRaw.channel_id == channel_id, MessageRaw.msg_id == msg_id
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def create_message(
    session: AsyncSession,
    *,
    channel_id: int,
    msg_id: int,
    date: datetime,
    text: Optional[str],
) -> MessageRaw:
    msg = MessageRaw(
        channel_id=channel_id,
        msg_id=msg_id,
        date=date,
        text=text,
        attachments=None,
        features=None,
        hash=None,
    )
    session.add(msg)
    await session.flush()
    return msg


