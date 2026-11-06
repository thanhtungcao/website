FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 DB_PATH=/data/thukyai.db
WORKDIR /srv

ARG WITH_ASR=0
COPY requirements.txt requirements-asr.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$WITH_ASR" = "1" ]; then pip install --no-cache-dir -r requirements-asr.txt; fi \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /data && chown app /data

COPY app ./app
COPY cli.py .
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz')"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
