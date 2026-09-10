FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl ca-certificates libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
       libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
       libxfixes3 libxrandr2 libgbm1 libgtk-3-0 libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install pytest

COPY . .

RUN python -m compileall -q app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
