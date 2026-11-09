# Single container: the service has no database, queue or cache server to talk
# to, so there is nothing for a compose file to orchestrate.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    QUOTESTACK_SERVER_HOST=0.0.0.0 \
    QUOTESTACK_SERVER_PORT=8000

WORKDIR /app

# Dependencies first: editing source should not reinstall them.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[server]"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/healthz')"

CMD ["quotestack-server"]
