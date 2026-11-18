# The image Railway builds and runs. One container: the API and the frontend together.
# Railway always uses a Dockerfile when the repo has one, so the Python version and the start
# command are fixed here instead of in dashboard settings.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # The live site: no interactive API pages, and browsers are told to use HTTPS only.
    APP_ENV=production \
    # This image runs behind Railway's proxy, which puts the visitor's address in X-Real-IP.
    TRUST_PROXY=1 \
    # The SQLite file lives on the volume mounted at /data, so a redeploy doesn't wipe it.
    DATABASE_PATH=/data/spartan.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend

# Railway sets PORT. The shell is here so that $PORT is filled in.
# --no-access-log keeps visitor addresses out of the logs.
CMD ["/bin/sh", "-c", "exec python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
