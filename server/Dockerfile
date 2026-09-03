    FROM python:3.10-slim AS builder

    ENV PYTHONDONTWRITEBYTECODE=1
    ENV PYTHONUNBUFFERED=1
    
    WORKDIR /app
    
    RUN apt-get update && \
        apt-get install -y --no-install-recommends gcc libpq-dev && \
        rm -rf /var/lib/apt/lists/*
    
    COPY requirements.txt .
    RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt
    
    
    FROM python:3.10-slim
    
    WORKDIR /app
    
    ENV PYTHONDONTWRITEBYTECODE=1
    ENV PYTHONUNBUFFERED=1
    ENV PORT=8000
    
    COPY --from=builder /app/wheels /wheels
    COPY --from=builder /app/requirements.txt .
    
    RUN apt-get update && \
        apt-get install -y --no-install-recommends libpq5 && \
        rm -rf /var/lib/apt/lists/* && \
        pip install --no-cache /wheels/*
    
    COPY . .

    RUN mkdir -p /app/output
    
    RUN addgroup --system appgroup && adduser --system --group appuser
    RUN chown -R appuser:0 /app && \
    chmod -R g=rwX /app

    
    USER appuser
    
    EXPOSE 8000
    
    CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]