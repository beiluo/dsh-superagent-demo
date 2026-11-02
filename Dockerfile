FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server
COPY assets ./assets
COPY ontology ./ontology
COPY docs ./docs
COPY index.html ./

RUN useradd --create-home --uid 10001 appuser
USER appuser

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
