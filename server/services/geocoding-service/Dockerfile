FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY packages/agent_runtime/requirements.txt /tmp/agent_runtime-requirements.txt
COPY services/geocoding-service/requirements.txt /tmp/service-requirements.txt
RUN pip install --no-cache-dir \
    -r /tmp/agent_runtime-requirements.txt \
    -r /tmp/service-requirements.txt

COPY packages /app/packages
COPY services/geocoding-service /app/services/geocoding-service

WORKDIR /app/services/geocoding-service

EXPOSE 8003

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
