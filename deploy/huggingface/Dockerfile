# The ICPAC Week-2 API on a Hugging Face Docker Space. The image is the one GitHub Actions
# built and tested from main (Publish backend image): change the tag to deploy another commit.
FROM ghcr.io/joe254h/icpac-backend:d443e59b140eda092d01eca5e17b65a992e1af80

# Everything the service writes goes under /app/data (user 1000, as Spaces require). A Space's
# disk is wiped when it restarts or rebuilds, and Spaces usually cannot reach PostgreSQL or
# SMTP ports, so records and forecasts live on that disk: do not restart before a showcase.
# Open access (OPEN_ACCESS): every visitor may run forecasts, verify and manage models, no staff
# key. The scheduler makes the latest Sunday's forecast within a minute of starting and fills
# the last weeks. The Space variable REALTIME_REVIEW_CONFIRMED_BY (a reviewer's name) confirms
# the real-time ECMWF input at startup, so the MBC + AI/ML layer is produced. The Copilot's
# settings (LLM_*) are Space variables and secrets.
ENV PORT=7860 \
    RUN_ROOT=/app/data/runs \
    DATA_ROOT=/app/data/observations \
    FORECAST_INPUT_ROOT=/app/data/forecasts \
    ARTIFACT_ROOT=/app/artifacts \
    ACCESS_MODE=public \
    OPEN_ACCESS=true \
    RELEASE_MODE=evaluation \
    AUTO_REGISTER_MODELS=true \
    OPERATION_WORKER_ENABLED=true \
    AUTOMATION_SCHEDULER_ENABLED=true

# Hugging Face Dev Mode (Settings) adds steps that need git: installed here, then back to the
# image's own user (uid 1000, as Spaces require).
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
USER climate

EXPOSE 7860
