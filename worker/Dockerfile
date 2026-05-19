FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY worker/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY worker/app ./app
COPY renderer ./renderer

EXPOSE 8001
EXPOSE 8002
EXPOSE 8003
EXPOSE 8004