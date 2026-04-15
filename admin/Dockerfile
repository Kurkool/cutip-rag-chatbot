FROM python:3.11-slim
WORKDIR /app
COPY shared/ /app/shared/
COPY admin/ /app/admin/
COPY admin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "admin.main:app", "--host", "0.0.0.0", "--port", "8000"]
