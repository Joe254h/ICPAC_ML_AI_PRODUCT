# The ICPAC Week-2 API on a Hugging Face Docker Space. The image is the one GitHub Actions
# built and tested from main (Publish backend image): change the tag to deploy another commit.
FROM ghcr.io/joe254h/icpac-backend:cba99200d47f268a89e8d39adebce1c13cdd214c

# Everything the service writes goes under /app/data (user 1000, as Spaces require). A Space's
# disk is wiped when it restarts, so records go to Supabase (secret DATABASE_URL) and forecast
# packages to a private dataset (secret HF_TOKEN with write access). Public access: visitors
# use the Copilot and bulletins without a key; the scheduler makes every Sunday's forecast
# and fills every week since AUTOMATION_ARCHIVE_SINCE. Copilot: Groq (secret LLM_API_KEY).
ENV PORT=7860 \
    RUN_ROOT=/app/data/runs \
    DATA_ROOT=/app/data/observations \
    FORECAST_INPUT_ROOT=/app/data/forecasts \
    ARTIFACT_ROOT=/app/artifacts \
    ACCESS_MODE=public \
    RELEASE_MODE=evaluation \
    AUTO_REGISTER_MODELS=true \
    OPERATION_WORKER_ENABLED=true \
    AUTOMATION_SCHEDULER_ENABLED=true \
    AUTOMATION_ARCHIVE_SINCE=2026-08-02 \
    PACKAGE_STORE_CONNECTION=hf://datasets/joe254h/icpac-forecast-packages \
    LLM_PROVIDER=openai_compatible \
    LLM_BASE_URL=https://api.groq.com/openai/v1 \
    LLM_MODEL=openai/gpt-oss-120b \
    LLM_FALLBACK_MODELS=qwen/qwen3.8-27b,openai/gpt-oss-20b \
    LLM_TOOLS=true \
    LLM_TIMEOUT_SECONDS=60

EXPOSE 7860
