import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.staticfiles import StaticFiles

from tg_events.db import SessionLocal, get_session
from tg_events.config import get_settings
from tg_events.ingest.service import ingest_channels
from tg_events.repositories.miniapp_queries import list_recent_messages
from tg_events.ingest.telethon_client import build_client, open_client
from telethon.utils import get_display_name
from telethon.tl.types import Channel as TlChannel, User as TlUser
from tg_events.ai.commenter import comment_message


settings = get_settings()
app = FastAPI(title=settings.app_name)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class IngestRequest(BaseModel):
    """Request to trigger ingestion."""

    channels: List[str]
    limit: Optional[int] = 1000
    force_media: Optional[bool] = False


@app.post("/ingest")
async def ingest(req: IngestRequest, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    return await ingest_channels(
        session,
        req.channels,
        limit=req.limit or 1000,
        update_existing_media=bool(req.force_media),
    )


class MiniappPostsResponse(BaseModel):
    items: List[dict]


@app.get("/miniapp/api/posts", response_model=MiniappPostsResponse)
async def miniapp_posts(
    session: AsyncSession = Depends(get_session),
    limit: int = 500,
    username: Optional[str] = None,
    channel_id: Optional[int] = None,
) -> MiniappPostsResponse:
    items = await list_recent_messages(
        session, limit=limit, channel_username=username, channel_tg_id=channel_id
    )
    return MiniappPostsResponse(items=items)


# Serve media files
media_dir = Path(settings.media_root)
media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_dir), html=False), name="media")


class ChannelItem(BaseModel):
    id: int
    kind: str
    name: str
    username: Optional[str] = None


class ChannelsResponse(BaseModel):
    items: List[ChannelItem]


@app.get("/miniapp/api/channels", response_model=ChannelsResponse)
async def miniapp_channels(limit: int = 300) -> ChannelsResponse:
    items: list[ChannelItem] = []
    async with open_client() as client:
        try:
            async for d in client.iter_dialogs(limit=limit):
                e = d.entity
                if isinstance(e, TlChannel):
                    kind = "channel" if getattr(e, "broadcast", False) else "supergroup"
                    items.append(
                        ChannelItem(
                            id=int(getattr(e, "id", 0)),
                            kind=kind,
                            name=get_display_name(e) or "",
                            username=getattr(e, "username", None),
                        )
                    )
                elif isinstance(e, TlUser):
                    items.append(
                        ChannelItem(
                            id=int(getattr(e, "id", 0)),
                            kind="user",
                            name=get_display_name(e) or "",
                            username=getattr(e, "username", None),
                        )
                    )
        finally:
            pass
    # sort by name
    items.sort(key=lambda x: (x.username is None, (x.username or x.name or "").lower()))
    return ChannelsResponse(items=items)


class MiniIngestRequest(BaseModel):
    channel: str
    limit: Optional[int] = 500
    force_media: Optional[bool] = True


@app.post("/miniapp/api/ingest")
async def miniapp_ingest(
    req: MiniIngestRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    return await ingest_channels(
        session, [req.channel], limit=req.limit or 500, update_existing_media=bool(req.force_media)
    )

class GenerateCommentsRequest(BaseModel):
    message_ids: List[int]
    model: Optional[str] = None


@app.post("/miniapp/api/comments/generate")
async def generate_comments(req: GenerateCommentsRequest, tasks: BackgroundTasks) -> dict[str, int]:
    # Process in background to keep UI responsive
    s = get_settings()
    # cap batch size to avoid overload
    ids = list(dict.fromkeys(req.message_ids))[:50]

    async def _worker(message_id: int) -> None:
        async with SessionLocal() as ses:
            try:
                await comment_message(ses, message_id, model=req.model or s.ai_model)
            except Exception:
                pass

    async def _run() -> None:
        await asyncio.gather(*(_worker(mid) for mid in ids))

    # Schedule the async gather via background tasks
    def _start() -> None:
        asyncio.run(_run())

    tasks.add_task(_start)
    return {"accepted": len(ids)}

# Serve static Mini App (mounted AFTER API routes so it doesn't shadow /miniapp/api/*)
miniapp_dir = Path(__file__).parent / "miniapp_static"
if miniapp_dir.exists():
    app.mount("/miniapp", StaticFiles(directory=str(miniapp_dir), html=True), name="miniapp")
