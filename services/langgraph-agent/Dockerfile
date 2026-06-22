# --platform ensures the image targets linux/amd64 (EC2) even when built on Apple Silicon
FROM --platform=linux/amd64 python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9000

CMD ["uvicorn", "main:server", "--host", "0.0.0.0", "--port", "9000"]
