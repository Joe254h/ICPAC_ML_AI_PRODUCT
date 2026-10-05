FROM python:3.12-slim
WORKDIR /app
ARG GIT_COMMIT=unversioned
ARG INSTALL_MODEL_RUNTIMES=false
ENV GIT_COMMIT=${GIT_COMMIT}
COPY pyproject.toml ./
COPY backend backend
COPY climate_engine climate_engine
COPY chatbot chatbot
COPY hpc hpc
COPY scripts scripts
COPY config config
COPY fixtures fixtures
RUN if [ "$INSTALL_MODEL_RUNTIMES" = "true" ]; then pip install --no-cache-dir ".[models]"; else pip install --no-cache-dir .; fi && useradd --create-home climate && mkdir -p /app/data && chown climate /app/data
USER climate
EXPOSE 8000
CMD ["uvicorn","backend.app.main:app","--host","0.0.0.0","--port","8000"]
