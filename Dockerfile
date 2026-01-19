# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Lisbon

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
    && if [ -s requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

COPY app ./app
COPY tests ./tests
COPY entrypoint.sh /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
