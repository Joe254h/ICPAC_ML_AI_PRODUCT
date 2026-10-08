FROM python:3.12-slim
WORKDIR /app
ARG GIT_COMMIT=unversioned
ARG INSTALL_MODEL_RUNTIMES=false
# Extra dependency groups, e.g. "postgres" for Supabase or another PostgreSQL.
ARG PIP_EXTRAS=""
ENV GIT_COMMIT=${GIT_COMMIT} PYTHONUNBUFFERED=1 MPLBACKEND=Agg
COPY pyproject.toml ./
COPY backend backend
COPY climate_engine climate_engine
COPY chatbot chatbot
COPY hpc hpc
COPY scripts scripts
COPY config config
COPY fixtures fixtures
COPY cartography cartography
COPY templates templates
# The verified inference artifacts (about 25 MB), so an image pins the model it serves.
# Mount another ARTIFACT_ROOT (read-only) to serve newer registered versions.
COPY artifacts artifacts
RUN extras="$PIP_EXTRAS"; \
    if [ "$INSTALL_MODEL_RUNTIMES" = "true" ]; then extras="${extras:+$extras,}models"; fi; \
    if [ -n "$extras" ]; then pip install --no-cache-dir ".[$extras]"; else pip install --no-cache-dir .; fi \
    && useradd --create-home --uid 1000 climate && mkdir -p /app/data && chown climate /app/data
USER climate
EXPOSE 8000
# Cloud Run provides PORT; Compose and local runs use 8000.
CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
