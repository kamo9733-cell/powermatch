FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY tablesight ./tablesight
RUN pip install --no-cache-dir . fastapi==0.149.0 uvicorn==0.54.0 cryptography==50.0.1 httpx==0.28.1 pydantic==2.13.5
RUN useradd -r app && mkdir /data && chown app /data
USER app
ENV TABLESIGHT_DB=/data/tablesight.db
EXPOSE 8080
CMD ["python", "-m", "tablesight.platform"]
