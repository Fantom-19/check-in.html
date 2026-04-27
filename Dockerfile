FROM python:3.12-alpine

WORKDIR /app
COPY . /app

ENV LEAD_LOG_DIR=/app/data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -qO- http://127.0.0.1:8080/health || exit 1

CMD ["python", "app.py"]
