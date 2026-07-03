FROM python:3.12-slim-bookworm AS requirements-stage
WORKDIR /tmp
RUN pip install uv
COPY ./pyproject.toml ./uv.lock* /tmp/
RUN uv export --no-hashes --format requirements-txt > requirements.txt

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY --from=requirements-stage /tmp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app
WORKDIR /app

CMD ["python3", "main.py"]
