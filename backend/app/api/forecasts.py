"""Operational forecast endpoints: input data, rainfall monitoring, background operations,
runs, packages, maps, countries and verification."""

from fastapi import Depends, FastAPI, HTTPException, Path, Query
from fastapi.responses import Response

from backend.app.schemas import (
    FORECAST_ID,
    ForecastRunRequest,
    OperationRequest,
    PackageImportRequest,
    VerificationRequest,
)
from backend.app.services.forecasts import ForecastService
from backend.app.services.monitoring import MonitoringService
from backend.app.services.operations import OperationService
from climate_engine.inputs import sources
from climate_engine.products.bulletin import MissingDependency
from climate_engine.products.package import countries_csv

ForecastId = Path(pattern=FORECAST_ID)
DekadId = Path(pattern=r"^\d{4}-\d{2}-[123]$")
MODEL_ID = r"^[a-zA-Z0-9_-]{1,80}$"
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


def install(app: FastAPI, dependency) -> None:
    @app.get("/data/sources")
    def data_sources(platform=Depends(dependency)) -> list[dict]:
        """Observation and forecast sources: active ones with what has been fetched,
        planned ones as listed for later."""
        service = ForecastService(platform)
        fetched = {"ecmwf": service.ecmwf_inputs(), "chirps": service.chirps_inputs()}
        return [
            {
                **source,
                "fetched": len(fetched.get(source["id"], [])),
                "latest": next(iter(fetched.get(source["id"], [])), None),
            }
            for source in sources()
        ]

    @app.get("/data/ecmwf")
    def ecmwf_inputs(platform=Depends(dependency)) -> list[dict]:
        return ForecastService(platform).ecmwf_inputs()

    @app.get("/data/chirps")
    def chirps_inputs(platform=Depends(dependency)) -> list[dict]:
        return ForecastService(platform).chirps_inputs()

    def with_overlays(record: dict) -> dict:
        base = f"/monitoring/dekads/{record['dekad']}/overlay?product="
        overlays = {"total": base + "total"}
        if record["percent_of_normal"]["status"] == "available":
            overlays["percent"] = base + "percent"
        return {**record, "overlays": overlays, "overlay_bounds": MonitoringService.bounds()}

    @app.get("/monitoring/dekads")
    def monitoring_dekads(platform=Depends(dependency)) -> list[dict]:
        """CHIRPS preliminary dekads downloaded for rainfall monitoring, newest first."""
        return MonitoringService(platform).dekads()

    @app.get("/monitoring/dekads/latest")
    def monitoring_latest(platform=Depends(dependency)) -> dict:
        return with_overlays(MonitoringService(platform).latest())

    @app.get("/monitoring/dekads/{dekad}")
    def monitoring_dekad(dekad: str = DekadId, platform=Depends(dependency)) -> dict:
        return with_overlays(MonitoringService(platform).get(dekad))

    @app.get("/monitoring/dekads/{dekad}/overlay")
    def monitoring_overlay(
        dekad: str = DekadId,
        product: str = Query("total", pattern=r"^(total|percent)$"),
        platform=Depends(dependency),
    ):
        """The dekad's total (or percent of normal) as a transparent Web Mercator PNG."""
        return Response(
            MonitoringService(platform).overlay_png(dekad, product),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/operations")
    def operations(platform=Depends(dependency)) -> list[dict]:
        return OperationService(platform).list()

    @app.post("/operations", status_code=202)
    def start_operation(body: OperationRequest, platform=Depends(dependency)) -> dict:
        """Start a background task (download, run, verify or the weekly cycle)."""
        return OperationService(platform).start(body)

    @app.get("/operations/{operation_id}")
    def operation(operation_id: str, platform=Depends(dependency)) -> dict:
        return OperationService(platform).get(operation_id)

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
        # Default: rainfall in the weekly bulletin style, the residual as packaged. Older
        # style names stay valid and give the current bulletin style.
        style: str | None = Query(None, pattern=r"^(package|weekly-v1|weekly-v2)$"),
        country: str | None = Query(None, min_length=4, max_length=40),
        platform=Depends(dependency),
    ):
        png = ForecastService(platform).map_png(forecast_id, layer, style, country)
        return Response(png, media_type="image/png", headers=IMMUTABLE)

    @app.get("/forecasts/{forecast_id}/overlay")
    def forecast_overlay(
        forecast_id: str = ForecastId,
        layer: str = Query("mbc", pattern=r"^(raw|mbc|hybrid)$"),
        platform=Depends(dependency),
    ):
        """A rainfall layer as a transparent Web Mercator PNG on ``overlay_bounds``."""
        return Response(
            ForecastService(platform).overlay_png(forecast_id, layer),
            media_type="image/png",
            headers=IMMUTABLE,
        )

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
        """Reference-format draft sections, maps and generator status."""
        return ForecastService(platform).bulletin(forecast_id)

    @app.get("/forecasts/{forecast_id}/bulletin/export")
    def export_bulletin(forecast_id: str = ForecastId, platform=Depends(dependency)):
        try:
            content = ForecastService(platform).export_bulletin(forecast_id)
        except MissingDependency as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="{forecast_id}-draft-bulletin.docx"',
                "Cache-Control": "no-store",
            },
        )

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
        model_id: str | None = Query(None, pattern=MODEL_ID),
        include_protected: bool = False,
        platform=Depends(dependency),
    ) -> dict:
        """Seasonal metrics of one model (the model in use by default)."""
        return ForecastService(platform).seasonal(model_id, include_protected)

    @app.get("/verification/maps")
    def verification_maps(
        model_id: str | None = Query(None, pattern=MODEL_ID),
        include_protected: bool = False,
        platform=Depends(dependency),
    ) -> dict:
        """Which gridded verification maps the verified forecasts support."""
        return ForecastService(platform).verification_maps(model_id, include_protected)

    @app.get("/verification/maps/{metric}")
    def verification_map(
        metric: str = Path(pattern=r"^[a-z]+$"),
        variant: str | None = Query(None, pattern=r"^[a-z]+$"),
        model_id: str | None = Query(None, pattern=MODEL_ID),
        include_protected: bool = False,
        platform=Depends(dependency),
    ):
        png = ForecastService(platform).verification_map(
            metric, variant, model_id, include_protected
        )
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-cache"})
