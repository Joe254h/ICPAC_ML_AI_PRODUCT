FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY backend backend
COPY climate_engine climate_engine
COPY chatbot chatbot
COPY hpc hpc
COPY config config
COPY fixtures fixtures
RUN pip install --no-cache-dir . && useradd --create-home climate && mkdir -p /app/data && chown climate /app/data
USER climate
EXPOSE 8000
CMD ["uvicorn","backend.app.main:app","--host","0.0.0.0","--port","8000"]
