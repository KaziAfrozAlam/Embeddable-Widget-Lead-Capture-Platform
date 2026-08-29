FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=postgresql+psycopg://app:app@db:5432/app

WORKDIR /srv/app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p data

EXPOSE 8000

# Migrate, seed demo data, then serve. (The compose `worker` service runs the
# background job loop separately.)
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed --wipe && uvicorn app.main:app --host 0.0.0.0 --port 8000"]