FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --upgrade pip && pip install .

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn member_event_stream_agent.main:app --host 0.0.0.0 --port ${PORT}"]
