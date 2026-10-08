import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.api.forecasts import install as install_forecasts
from backend.app.db import Repository
from backend.app.services import operational
from backend.app.services.forecasts import RunInProgress, Unavailable, capabilities
from backend.app.services.health import system_health
from backend.app.services.operations import OperationService
from backend.app.services.platform import Platform
from climate_engine.inputs import sources


class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "run_id": getattr(record, "run_id", None),
                "cycle": getattr(record, "cycle", None),
                "model": getattr(record, "model", None),
                "dataset": getattr(record, "dataset", None),
                "job": getattr(record, "job", None),
                "stage": getattr(record, "stage", None),
            }
        )


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.getLogger("icpac").addHandler(handler)
logging.getLogger("icpac").setLevel(logging.INFO)


def create_app(database_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.platform = Platform(
            Repository(database_url),
            register_descriptors=os.getenv("AUTO_REGISTER_MODELS", "true") == "true",
        )
        OperationService(app.state.platform).recover()
        yield
        app.state.platform.repo.engine.dispose()

    app = FastAPI(title="ICPAC Week-2 Forecast Service", version="0.2.0", lifespan=lifespan)

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def not_found(request: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": f"Resource unavailable: {exc}"})

    @app.exception_handler(FileNotFoundError)
    async def missing_artifact(request: Request, exc: FileNotFoundError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(Unavailable)
    async def unavailable(request: Request, exc: Unavailable):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(RunInProgress)
    async def busy(request: Request, exc: RunInProgress):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ImportError)
    async def missing_runtime(request: Request, exc: ImportError):
        return JSONResponse(
            status_code=503, content={"detail": "Optional model runtime is not installed"}
        )

    def platform(request: Request) -> Platform:
        return request.app.state.platform

    @app.get("/health")
    def health(p: Platform = Depends(platform)) -> dict:
        return system_health(p)

    @app.get("/config")
    def settings(p: Platform = Depends(platform)) -> dict:
        return {
            "operational": capabilities(),
            "models": [m for m in p.repo.list("model") if operational.is_operational(m)],
            "data_sources": sources(),
        }

    install_forecasts(app, platform)

    @app.get("/models")
    def models(p: Platform = Depends(platform)) -> list[dict]:
        return [m for m in p.repo.list("model") if operational.is_operational(m)]

    @app.get("/models/current")
    def current_model(p: Platform = Depends(platform)) -> dict:
        """The operational model forecasts use: production, else the newest candidate."""
        from backend.app.services.registry import ModelRegistry

        return ModelRegistry(p).current()

    @app.get("/models/{model_id}")
    def model(model_id: str, p: Platform = Depends(platform)) -> dict:
        record = p.repo.get("model", model_id)
        if not operational.is_operational(record):
            raise KeyError(model_id)
        return record

    # Extensions are installed only after Phase 1 passes its local checks.
    try:
        from backend.app.api.extensions import install

        install(app, platform)
    except ModuleNotFoundError as exc:
        if exc.name != "backend.app.api.extensions":
            raise
    return app


app = create_app()
