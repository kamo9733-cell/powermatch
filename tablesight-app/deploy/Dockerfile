FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY tablesight ./tablesight
RUN pip install --no-cache-dir . fastapi uvicorn cryptography httpx
RUN useradd -r app && mkdir /data && chown app /data
USER app
ENV TABLESIGHT_DB=/data/tablesight.db
EXPOSE 8080
CMD ["python", "-m", "tablesight.platform"]
