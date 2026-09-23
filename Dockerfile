# syntax=docker/dockerfile:1

# Pinned by digest so the base image can't silently change between builds and
# force a full rebuild. Digest last resolved from a successful build of the
# python3.13-bookworm-slim tag; bump deliberately when you want a newer base:
#   docker buildx imagetools inspect ghcr.io/astral-sh/uv:python3.13-bookworm-slim
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

RUN uv run --no-sync python -m spacy download en_core_web_sm \
    && uv run --no-sync python -m spacy download hr_core_news_sm
