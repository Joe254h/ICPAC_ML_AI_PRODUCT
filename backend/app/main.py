import csv
import io
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response

from backend.app.db import Repository
from backend.app.schemas import ForecastResponse, Selection
from backend.app.services.health import system_health
from backend.app.services.platform import Platform
from climate_engine.core import DEMO_LABEL, config


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
        for job in app.state.platform.repo.list("job"):
            if job["executor"] == "local" and job["status"] in {"queued", "running"}:
                job.update(
                    status="failed",
                    exit_code=1,
                    log="Local worker interrupted by service restart; resubmit explicitly.",
                )
                app.state.platform.repo.save("job", job, job["id"])
        yield
        app.state.platform.repo.engine.dispose()

    app = FastAPI(title="ICPAC Climate Intelligence Prototype", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def not_found(request: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": f"Resource unavailable: {exc}"})

    @app.exception_handler(FileNotFoundError)
    async def missing_artifact(request: Request, exc: FileNotFoundError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(ImportError)
    async def missing_runtime(request: Request, exc: ImportError):
        return JSONResponse(
            status_code=503, content={"detail": "Optional model runtime is not installed"}
        )

    def platform(request: Request) -> Platform:
        return request.app.state.platform

    @app.get("/health")
    def health(p: Platform = Depends(platform)) -> dict:
        return {**system_health(p), "label": DEMO_LABEL}

    @app.get("/config")
    def settings(p: Platform = Depends(platform)) -> dict:
        return {
            "science": config(),
            "forecasts": config("forecasts"),
            "observations": list(config("observations")["sources"]),
            "models": p.repo.list("model"),
            "label": DEMO_LABEL,
        }

    @app.get("/forecasts")
    def forecasts(p: Platform = Depends(platform)) -> list[dict]:
        return p.repo.list("forecast_cycle")

    @app.get("/analysis", response_model=ForecastResponse)
    def analysis(selection: Selection = Depends(), p: Platform = Depends(platform)):
        return p.calculate(selection)

    @app.get("/forecasts/{cycle}", response_model=ForecastResponse)
    def forecast(cycle: str, selection: Selection = Depends(), p: Platform = Depends(platform)):
        return p.calculate(selection.model_copy(update={"cycle": cycle}))

    @app.get("/observations")
    def observations(p: Platform = Depends(platform)) -> list[dict]:
        return p.repo.list("dataset")

    @app.get("/observations/{source}/availability")
    def availability(source: str, p: Platform = Depends(platform)) -> dict:
        return {"source": source, "dates": p.observation(source).list_available_dates()}

    @app.get("/observations/{source}")
    def observation(source: str, p: Platform = Depends(platform)) -> dict:
        return p.repo.get("dataset", source)

    @app.get("/models")
    def models(p: Platform = Depends(platform)) -> list[dict]:
        return p.repo.list("model")

    @app.get("/models/current")
    def current_model(p: Platform = Depends(platform)) -> dict:
        """The operational model forecasts use: production, else the newest candidate."""
        from backend.app.services.registry import ModelRegistry

        return ModelRegistry(p).current()

    @app.get("/models/{model_id}")
    def model(model_id: str, p: Platform = Depends(platform)) -> dict:
        return p.repo.get("model", model_id)

    @app.get("/verification")
    def verification(p: Platform = Depends(platform)) -> list[dict]:
        return p.repo.list("verification")

    @app.post("/verification/run")
    def run_verification(selection: Selection, p: Platform = Depends(platform)) -> dict:
        return p.run_verification(selection)

    @app.get("/export/{format}")
    def export(format: str, selection: Selection = Depends(), p: Platform = Depends(platform)):
        result = p.calculate(selection)
        if format == "json":
            return Response(
                json.dumps(result),
                media_type="application/json",
                headers={"Content-Disposition": 'attachment; filename="icpac-demo.json"'},
            )
        if format == "png":
            return Response(
                p.png(selection),
                media_type="image/png",
                headers={"Content-Disposition": 'attachment; filename="icpac-demo.png"'},
            )
        if format == "csv":
            stream = io.StringIO()
            columns = [
                "country",
                "mean_rainfall_mm",
                "rmse",
                "mae",
                "bias",
                "correlation",
                "cell_count",
                "mask_status",
            ]
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(result["countries"])
            return Response(
                stream.getvalue(),
                media_type="text/csv",
                headers={
                    "Content-Disposition": 'attachment; filename="icpac-synthetic-countries.csv"'
                },
            )
        raise ValueError("Supported exports: png, csv, json")

    @app.get("/products")
    def products(p: Platform = Depends(platform)) -> list[dict]:
        return [
            {"id": fmt, "name": name, "format": fmt, "label": DEMO_LABEL}
            for fmt, name in [
                ("png", "Week-2 rainfall map"),
                ("csv", "Country verification table"),
                ("json", "Forecast & provenance package"),
            ]
        ]

    @app.get("/products/{id}")
    def product(id: str) -> dict:
        if id not in {"png", "csv", "json"}:
            raise KeyError(id)
        return {"id": id, "download": f"/export/{id}", "label": DEMO_LABEL}

    # Extensions are installed only after Phase 1 passes its local checks.
    try:
        from backend.app.api.extensions import install

        install(app, platform)
    except ModuleNotFoundError as exc:
        if exc.name != "backend.app.api.extensions":
            raise
    return app


app = create_app()
