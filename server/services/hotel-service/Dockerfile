FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]

# WORKDIR /app : Thư mục làm việc trong container là app
# COPPY . . : Copy tất cả các file trong thư mục hiện tại vào thư mục /app trong container