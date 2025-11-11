## tg-events (MVP)

Run API locally:

```bash
pip install -e .
uvicorn tg_events.api:app --reload --host 0.0.0.0 --port 8000
```

Docker:

```bash
cp config/.env.example .env
docker compose up --build
```

API:
- GET `/health` → `{ "status": "ok" }`


