# The ICPAC Week-2 API on a Hugging Face Docker Space. The image is the one GitHub Actions
# built and tested from main (Publish backend image): change the tag to deploy another commit.
FROM ghcr.io/joe254h/icpac-backend:cba99200d47f268a89e8d39adebce1c13cdd214c

# Everything the service writes goes under /app/data (user 1000, as Spaces require). A Space's
# disk is wiped when it restarts: set DATABASE_URL (Supabase) as a secret to keep records.
ENV PORT=7860 \
    RUN_ROOT=/app/data/runs \
    DATA_ROOT=/app/data/observations \
    FORECAST_INPUT_ROOT=/app/data/forecasts \
    ARTIFACT_ROOT=/app/artifacts \
    ACCESS_MODE=staff \
    RELEASE_MODE=evaluation \
    AUTO_REGISTER_MODELS=true \
    OPERATION_WORKER_ENABLED=true \
    AUTOMATION_SCHEDULER_ENABLED=false

EXPOSE 7860
