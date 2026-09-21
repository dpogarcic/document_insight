FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY model_runner.py ./model_runner.py

RUN uv sync --frozen --no-dev

RUN uv run --no-sync python -m spacy download en_core_web_sm \
    && uv run --no-sync python -m spacy download hr_core_news_sm
