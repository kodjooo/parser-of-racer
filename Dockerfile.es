FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Lisbon
WORKDIR /app
COPY requirements-es.txt ./
RUN pip install --no-cache-dir -r requirements-es.txt
COPY app ./app
COPY tests ./tests
COPY entrypoint.sh /app/entrypoint.sh
CMD ["bash", "/app/entrypoint.sh"]
