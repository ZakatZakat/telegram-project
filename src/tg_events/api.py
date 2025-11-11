from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.staticfiles import StaticFiles

from tg_events.db import get_session
from tg_events.config import get_settings
from tg_events.ingest.service import ingest_channels
from tg_events.repositories.miniapp_queries import list_recent_messages


settings = get_settings()
app = FastAPI(title=settings.app_name)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class IngestRequest(BaseModel):
    """Request to trigger ingestion."""

    channels: List[str]
    limit: Optional[int] = 1000


@app.post("/ingest")
async def ingest(req: IngestRequest, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    return await ingest_channels(session, req.channels, limit=req.limit or 1000)


class MiniappPostsResponse(BaseModel):
    items: List[dict]


@app.get("/miniapp/api/posts", response_model=MiniappPostsResponse)
async def miniapp_posts(
    session: AsyncSession = Depends(get_session),
    limit: int = 100,
    username: Optional[str] = None,
) -> MiniappPostsResponse:
    items = await list_recent_messages(session, limit=limit, channel_username=username)
    return MiniappPostsResponse(items=items)


# Serve static Mini App
miniapp_dir = Path(__file__).parent / "miniapp_static"
if miniapp_dir.exists():
    app.mount("/miniapp", StaticFiles(directory=str(miniapp_dir), html=True), name="miniapp")


