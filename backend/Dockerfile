# Build context: repository root (the backend depends on the Python SDK's evaluation engine).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY sdks/python /srv/sdks/python
RUN pip install --no-cache-dir /srv/sdks/python
COPY backend/pyproject.toml /srv/backend/pyproject.toml
COPY backend/app /srv/backend/app
COPY backend/migrations /srv/backend/migrations
COPY backend/alembic.ini /srv/backend/alembic.ini
RUN pip install --no-cache-dir /srv/backend
WORKDIR /srv/backend
RUN useradd --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
