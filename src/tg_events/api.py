from typing import List, Optional

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tg_events.db import get_session
from tg_events.config import get_settings
from tg_events.ingest.service import ingest_channels


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


