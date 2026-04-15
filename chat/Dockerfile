FROM python:3.11-slim
WORKDIR /app
COPY shared/ /app/shared/
COPY chat/ /app/chat/
COPY chat/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "chat.main:app", "--host", "0.0.0.0", "--port", "8000"]
