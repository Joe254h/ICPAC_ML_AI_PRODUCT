"""Operational forecast endpoints: runs, packages, maps, countries and verification."""

from fastapi import Depends, FastAPI, Path, Query
from fastapi.responses import Response

from backend.app.schemas import (
    FORECAST_ID,
    ForecastRunRequest,
    PackageImportRequest,
    VerificationRequest,
)
from backend.app.services.forecasts import ForecastService
from climate_engine.products.package import countries_csv

ForecastId = Path(pattern=FORECAST_ID)
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


def install(app: FastAPI, dependency) -> None:
    @app.get("/forecasts")
    def forecasts(platform=Depends(dependency)) -> list[dict]:
        """Operational forecast runs, newest initialization first."""
        return ForecastService(platform).runs()

    @app.get("/forecasts/latest")
    def latest(platform=Depends(dependency)) -> dict:
        """The newest forecast from real input (synthetic runs only if nothing else exists)."""
        return ForecastService(platform).latest()

    @app.post("/forecasts/run", status_code=201)
    def run(body: ForecastRunRequest, platform=Depends(dependency)) -> dict:
        return ForecastService(platform).run(body)

    @app.post("/forecasts/import", status_code=201)
    def import_package(body: PackageImportRequest, platform=Depends(dependency)) -> dict:
        return ForecastService(platform).import_package(body)

    @app.get("/forecasts/{forecast_id}")
    def forecast(forecast_id: str = ForecastId, platform=Depends(dependency)) -> dict:
        return ForecastService(platform).get(forecast_id)

    @app.get("/forecasts/{forecast_id}/map")
    def forecast_map(
        forecast_id: str = ForecastId,
        layer: str = Query("hybrid", pattern=r"^[a-z]+$"),
        platform=Depends(dependency),
    ):
        png = ForecastService(platform).map_png(forecast_id, layer)
        return Response(png, media_type="image/png", headers=IMMUTABLE)

    @app.get("/forecasts/{forecast_id}/countries")
    def forecast_countries(
        forecast_id: str = ForecastId,
        format: str = Query("json", pattern=r"^(json|csv)$"),
        platform=Depends(dependency),
    ):
        rows = ForecastService(platform).countries(forecast_id)
        if format == "csv":
            return Response(
                countries_csv(rows),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="{forecast_id}-countries.csv"'
                },
            )
        return rows

    @app.get("/forecasts/{forecast_id}/verification")
    def forecast_verification(forecast_id: str = ForecastId, platform=Depends(dependency)) -> dict:
        return ForecastService(platform).verification(forecast_id)

    @app.post("/forecasts/{forecast_id}/verification")
    def verify_forecast(
        body: VerificationRequest, forecast_id: str = ForecastId, platform=Depends(dependency)
    ) -> dict:
        return ForecastService(platform).verify(forecast_id, body)

    @app.get("/forecasts/{forecast_id}/bulletin")
    def forecast_bulletin(forecast_id: str = ForecastId, platform=Depends(dependency)) -> dict:
        """Bulletin inputs and the generator's status (the Word template is not supplied)."""
        return ForecastService(platform).bulletin(forecast_id)

    @app.get("/forecasts/{forecast_id}/package/{name:path}")
    def package_file(name: str, forecast_id: str = ForecastId, platform=Depends(dependency)):
        content, media_type = ForecastService(platform).file(forecast_id, name)
        filename = f"{forecast_id}-{name.replace('/', '-')}"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        if name not in {"manifest.json", "verification.json"}:  # the only files that change
            headers.update(IMMUTABLE)
        return Response(content, media_type=media_type, headers=headers)

    @app.get("/verification/seasonal")
    def seasonal_verification(
        include_protected: bool = False, platform=Depends(dependency)
    ) -> dict:
        return ForecastService(platform).seasonal(include_protected)
