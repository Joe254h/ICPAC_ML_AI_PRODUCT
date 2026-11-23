# The ICPAC Week-2 API on a Hugging Face Docker Space. The image is the one GitHub Actions
# built and tested from main (Publish backend image): change the tag to deploy another commit.
FROM ghcr.io/joe254h/icpac-backend:96bc1c24b9abd8d940d46a24b87c1a9493c17bfb

# Everything the service writes goes under /app/data (user 1000, as Spaces require). A Space's
# disk is wiped when it restarts or rebuilds, and Spaces usually cannot reach PostgreSQL or
# SMTP ports, so records and forecasts live on that disk: do not restart before a showcase.
# Public access: visitors use the Copilot and bulletins without a key. The scheduler makes the
# latest Sunday's forecast within a minute of starting and fills the last weeks. An admin key
# (secret STAFF_CREDENTIALS) is still needed once, to confirm the real-time ECMWF input so the
# AI/ML layer is produced. The Copilot's settings (LLM_*) are Space variables and secrets.
ENV PORT=7860 \
    RUN_ROOT=/app/data/runs \
    DATA_ROOT=/app/data/observations \
    FORECAST_INPUT_ROOT=/app/data/forecasts \
    ARTIFACT_ROOT=/app/artifacts \
    ACCESS_MODE=public \
    RELEASE_MODE=evaluation \
    AUTO_REGISTER_MODELS=true \
    OPERATION_WORKER_ENABLED=true \
    AUTOMATION_SCHEDULER_ENABLED=true

EXPOSE 7860
