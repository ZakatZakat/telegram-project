FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN adduser --disabled-password --gecos '' appuser

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
COPY README.md /app/README.md

RUN pip install --upgrade pip && pip install -e .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "tg_events.api:app", "--host", "0.0.0.0", "--port", "8000"]


