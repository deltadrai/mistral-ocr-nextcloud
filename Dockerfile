# syntax=docker/dockerfile:1
#
# ExApp image for the Nextcloud AppAPI. Built and published by
# .github/workflows/ci.yml; the tag must match <image-tag> in appinfo/info.xml.
FROM python:3.12-alpine

# Set by CI so the image can be traced back to a commit and a release.
ARG VERSION=0.0.0-dev
ARG REVISION=unknown

LABEL org.opencontainers.image.title="Mistral OCR for Nextcloud" \
      org.opencontainers.image.description="Nextcloud ExApp that turns PDFs and images into Markdown with the Mistral OCR API" \
      org.opencontainers.image.source="https://github.com/deltadrai/mistral-ocr-nextcloud" \
      org.opencontainers.image.url="https://github.com/deltadrai/mistral-ocr-nextcloud" \
      org.opencontainers.image.documentation="https://github.com/deltadrai/mistral-ocr-nextcloud#readme" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer only rebuilds when requirements.txt changes.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src/ /app/src/
COPY js/ /app/js/
COPY img/ /app/img/
COPY appinfo/ /app/appinfo/
COPY LICENSE /app/LICENSE

EXPOSE 9000

# AppAPI assigns APP_PORT; the health endpoint does not need Nextcloud credentials,
# so it also works while the ExApp is still being registered.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,sys,urllib.request; url='http://127.0.0.1:%s/api/v1/health' % os.environ.get('APP_PORT','9000'); sys.exit(0 if urllib.request.urlopen(url, timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port \"${APP_PORT:-9000}\""]
