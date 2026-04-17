FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY shared/ /app/shared/
COPY ingest/ /app/ingest/
COPY ingest/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "ingest.main:app", "--host", "0.0.0.0", "--port", "8000"]
