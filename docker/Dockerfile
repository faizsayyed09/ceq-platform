FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN python -m pip install --upgrade pip==25.1.1 && python -m pip install --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/* && groupadd -r ceq && useradd -r -g ceq ceq
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=ceq:ceq . /app
RUN mkdir -p /app/generated_reports /app/recordings /app/models/whisper /app/cache/huggingface && chown -R ceq:ceq /app/generated_reports /app/recordings /app/models /app/cache
USER ceq
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
