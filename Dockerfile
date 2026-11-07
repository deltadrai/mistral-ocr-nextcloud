FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src/ /app/src/
COPY js/ /app/js/
COPY appinfo/ /app/appinfo/

EXPOSE 9000

CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port \"${APP_PORT:-9000}\""]
