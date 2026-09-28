FROM python:3.12-slim AS base

RUN pip install --no-cache-dir uv==0.11.8
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app

FROM base AS test
RUN uv sync --frozen --no-install-project
COPY tests ./tests
RUN uv run pytest -q

FROM base AS runtime
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
