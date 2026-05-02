FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QB_RULES_HOST=0.0.0.0 \
    QB_RULES_PORT=8000 \
    QB_RULES_DATABASE_URL=sqlite:////app/data/qb_rules.db

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN mkdir -p /app/data \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ.get('QB_RULES_PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3).read()"

CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host ${QB_RULES_HOST:-0.0.0.0} --port ${QB_RULES_PORT:-8000}"]
