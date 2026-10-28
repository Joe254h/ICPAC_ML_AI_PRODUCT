"""Operational forecast endpoints: input data, rainfall monitoring, background operations,
runs, packages, maps, countries and verification."""

import asyncio
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import Response

from backend.app.api.access import Principal, acting_name, require_operator
from backend.app.schemas import (
    FORECAST_ID,
    ForecastRunRequest,
    OperationRequest,
    PackageImportRequest,
    StopRequest,
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


def pdf_of(png: bytes) -> bytes:
    """The same map as a one-page PDF (the picture is not redrawn)."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        out = io.BytesIO()
        image.convert("RGB").save(out, format="PDF", resolution=200.0)
    return out.getvalue()


def install(app: FastAPI, dependency) -> None:
    @app.post("/external-forecasts", status_code=201)
    async def upload_external_forecast(
        request: Request,
        name: str = Query(min_length=2, max_length=80),
        valid_start: date | None = None,
        file_name: str = Query("", max_length=200),
        platform=Depends(dependency),
        user: Principal = Depends(require_operator),
    ) -> dict:
        """Another model's Week-2 forecast as a NetCDF file (the request body), compared with
        ICPAC's forecast of the same week and, once observed, verified with it."""
        from backend.app.services.external import ExternalForecasts
        from climate_engine.inputs.external_forecast import MAX_BYTES

        limit = f"The file is larger than {MAX_BYTES // 1024**2} MB: upload the Week-2 total only."
        if int(request.headers.get("content-length") or 0) > MAX_BYTES:
            raise HTTPException(413, limit)
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > MAX_BYTES:
                raise HTTPException(413, limit)
        return await asyncio.to_thread(
            ExternalForecasts(platform).upload,
            bytes(data),
            name,
            acting_name(user),
            valid_start,
            file_name,
        )

    @app.get("/external-forecasts")
    def external_forecasts(platform=Depends(dependency)) -> list[dict]:
        """Uploaded forecasts of other models, newest first, with their comparisons."""
        from backend.app.services.external import ExternalForecasts, card

        return [card(record) for record in ExternalForecasts(platform).list()]

    @app.get("/external-forecasts/{identifier}")
    def external_forecast(
        identifier: str = Path(pattern=r"^[0-9a-f-]{36}$"), platform=Depends(dependency)
    ) -> dict:
        from backend.app.services.external import ExternalForecasts

        return ExternalForecasts(platform).get(identifier)

    @app.delete("/external-forecasts/{identifier}", status_code=204)
    def delete_external_forecast(
        identifier: str = Path(pattern=r"^[0-9a-f-]{36}$"),
        platform=Depends(dependency),
        user: Principal = Depends(require_operator),
    ) -> Response:
        from backend.app.services.external import ExternalForecasts

        service = ExternalForecasts(platform)
        service.get(identifier)
        platform.repo.delete("external_forecast", identifier)
        service.root().joinpath(f"{identifier}.nc").unlink(missing_ok=True)
        platform.repo.audit("external_forecast_deleted", acting_name(user), identifier, {})
        return Response(status_code=204)

    @app.get("/automations")
    def automations(platform=Depends(dependency)) -> dict:
        from backend.app.services.automation import AutomationService

        return AutomationService(platform).status()

    @app.get("/automations/integrations")
    def integrations(platform=Depends(dependency)) -> dict:
        from backend.app.services.external_feeds import ExternalFeeds
        from backend.app.services.hpc import HPCService

        return {"feeds": ExternalFeeds(platform).status(), "hpc": HPCService(platform).status()}

    @app.get("/forecasts/{forecast_id}/supplemental")
    def supplemental_products(forecast_id: str = ForecastId, platform=Depends(dependency)) -> dict:
        from backend.app.services.supplemental import SupplementalService

        return SupplementalService(platform).current(forecast_id)

    @app.get("/forecasts/{forecast_id}/supplemental/{product}/map")
    def supplemental_map(product: str, forecast_id: str = ForecastId, platform=Depends(dependency)):
        from backend.app.services.supplemental import SupplementalService

        service = SupplementalService(platform)
        return Response(
            service.map(service.current(forecast_id), product),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/data/sources")
    def data_sources(platform=Depends(dependency)) -> list[dict]:
        """Observation and forecast sources: active ones with what has been fetched,
        planned ones as listed for later."""
        service = ForecastService(platform)
        monitored = {
            source: MonitoringService(platform, source)
            for source in ("tamsat", "arc2", "rfe2", "imerg")
        }
        fetched = {
            "ecmwf": service.ecmwf_inputs(),
            "chirps": service.chirps_inputs(),
            **{source: monitor.dekads() for source, monitor in monitored.items()},
        }
        return [
            {
                **source,
                "fetched": len(fetched.get(source["id"], [])),
                "latest": next(iter(fetched.get(source["id"], [])), None),
                "last_check": monitored[source["id"]].last_check()
                if source["id"] in monitored
                else None,
            }
            for source in sources()
        ]

    @app.get("/data/ecmwf")
    def ecmwf_inputs(platform=Depends(dependency)) -> list[dict]:
        return ForecastService(platform).ecmwf_inputs()

    @app.get("/data/ecmwf/readiness")
    def ecmwf_readiness(platform=Depends(dependency)) -> dict:
        """Recorded ECMWF input states for the model in use (no network call)."""
        from backend.app.services.readiness import readiness

        return readiness(platform)

    @app.get("/data/chirps")
    def chirps_inputs(platform=Depends(dependency)) -> list[dict]:
        return ForecastService(platform).chirps_inputs()

    Source = Query("chirps", pattern=r"^(chirps|tamsat|arc2|rfe2|imerg)$")

    def with_overlays(record: dict, source: str) -> dict:
        base = f"/monitoring/dekads/{record['dekad']}/overlay?source={source}&product="
        overlays = {"total": base + "total"}
        if record["percent_of_normal"]["status"] == "available":
            overlays["percent"] = base + "percent"
        return {**record, "overlays": overlays, "overlay_bounds": MonitoringService.bounds()}

    @app.get("/monitoring/estimates")
    def monitoring_estimates(platform=Depends(dependency)) -> list[dict]:
        """Each rainfall estimate's latest dekad (or none) and its last server check."""
        return MonitoringService.estimates(platform)

    @app.get("/monitoring/dekads")
    def monitoring_dekads(source: str = Source, platform=Depends(dependency)) -> list[dict]:
        """Dekads of observed rainfall held for monitoring (CHIRPS, TAMSAT, ARC 2.0, RFE 2.0
        or GPM IMERG), newest first."""
        return MonitoringService(platform, source).dekads()

    @app.get("/monitoring/dekads/latest")
    def monitoring_latest(source: str = Source, platform=Depends(dependency)) -> dict:
        return with_overlays(MonitoringService(platform, source).latest(), source)

    @app.get("/monitoring/dekads/{dekad}")
    def monitoring_dekad(
        dekad: str = DekadId, source: str = Source, platform=Depends(dependency)
    ) -> dict:
        return with_overlays(MonitoringService(platform, source).get(dekad), source)

    @app.get("/monitoring/dekads/{dekad}/overlay")
    def monitoring_overlay(
        dekad: str = DekadId,
        product: str = Query("total", pattern=r"^(total|percent)$"),
        source: str = Source,
        platform=Depends(dependency),
    ):
        """The dekad's total (or percent of normal) as a transparent Web Mercator PNG."""
        return Response(
            MonitoringService(platform, source).overlay_png(dekad, product),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/operations", dependencies=[Depends(require_operator)])
    def operations(platform=Depends(dependency)) -> list[dict]:
        return OperationService(platform).list()

    @app.post("/operations", status_code=202)
    def start_operation(
        body: OperationRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_operator),
    ) -> dict:
        """Start a background task (download, run, verify or the weekly cycle)."""
        return OperationService(platform).start(
            body.model_copy(update={"actor": acting_name(user, body.actor)})
        )

    @app.get("/operations/{operation_id}", dependencies=[Depends(require_operator)])
    def operation(operation_id: str, platform=Depends(dependency)) -> dict:
        return OperationService(platform).read(operation_id)

    @app.post("/operations/{operation_id}/stop")
    def stop_operation(
        operation_id: str,
        body: StopRequest | None = None,
        platform=Depends(dependency),
        user: Principal = Depends(require_operator),
    ) -> dict:
        """Stop a queued task now, or a running one at its next step."""
        try:
            return OperationService(platform).stop(
                operation_id, acting_name(user, body.actor if body else None)
            )
        except KeyError:
            raise HTTPException(404, "No such task") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/forecasts")
    def forecasts(platform=Depends(dependency)) -> list[dict]:
        """Operational forecast runs, newest initialization first."""
        return ForecastService(platform).runs()

    @app.get("/forecasts/latest")
    def latest(platform=Depends(dependency)) -> dict:
        """The newest forecast from real input (synthetic runs only if nothing else exists)."""
        return ForecastService(platform).latest()

    @app.post("/forecasts/run", status_code=201)
    def run(
        body: ForecastRunRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_operator),
    ) -> dict:
        return ForecastService(platform).run(
            body.model_copy(update={"actor": acting_name(user, body.actor)})
        )

    @app.post("/forecasts/import", status_code=201)
    def import_package(
        body: PackageImportRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_operator),
    ) -> dict:
        return ForecastService(platform).import_package(
            body.model_copy(update={"actor": acting_name(user, body.actor)})
        )

    @app.get("/forecasts/{forecast_id}")
    def forecast(forecast_id: str = ForecastId, platform=Depends(dependency)) -> dict:
        return ForecastService(platform).get(forecast_id)

    @app.get("/forecasts/{forecast_id}/map")
    def forecast_map(
        forecast_id: str = ForecastId,
        layer: str = Query("hybrid", pattern=r"^[a-z]+$"),
        # Default: rainfall in the weekly bulletin style, the residual as packaged. Older
        # style names stay valid and give the current bulletin style.
        style: str | None = Query(None, pattern=r"^(package|weekly-v1|weekly-v2|weekly-v3)$"),
        country: str | None = Query(None, min_length=4, max_length=40),
        format: str = Query("png", pattern=r"^(png|pdf)$"),
        platform=Depends(dependency),
    ):
        png = ForecastService(platform).map_png(forecast_id, layer, style, country)
        if format == "pdf":
            name = (
                f"icpac-week2-{layer}{'-' + country.lower().replace(' ', '-') if country else ''}"
            )
            return Response(
                pdf_of(png),
                media_type="application/pdf",
                headers={**IMMUTABLE, "Content-Disposition": f'attachment; filename="{name}.pdf"'},
            )
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

    @app.get("/forecasts/{forecast_id}/references")
    def forecast_references(
        forecast_id: str = ForecastId, platform=Depends(dependency)
    ) -> list[dict]:
        """The verified forecast scored against the further references (ARC 2.0, RFE 2.0,
        GPM IMERG), as recorded by the verification passes."""
        return ForecastService(platform).references(forecast_id)

    @app.post("/forecasts/{forecast_id}/verification")
    def verify_forecast(
        body: VerificationRequest,
        forecast_id: str = ForecastId,
        platform=Depends(dependency),
        user: Principal = Depends(require_operator),
    ) -> dict:
        return ForecastService(platform).verify(
            forecast_id, body.model_copy(update={"actor": acting_name(user, body.actor)})
        )

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

    EVIDENCE_SET = Query(None, alias="set", pattern=r"^[a-z]{1,20}$")

    @app.get("/verification/experimental")
    def experimental_verification(which: str | None = EVIDENCE_SET, platform=Depends(dependency)):
        """Frozen verification on the 2022-2024 reforecasts: the final refit's retrospective
        comparison or the pre-refit model's independent test. Without a set: the one that
        describes the model in use."""
        from backend.app.services import evidence
        from backend.app.services.registry import ModelRegistry

        try:
            in_use = ModelRegistry(platform).current()["model"]["model_id"]
        except KeyError:
            in_use = None
        body = evidence.summary(which or evidence.set_for_model(in_use))
        return {**body, "describes_model_in_use": in_use in evidence.SETS[body["set"]].model_ids}

    @app.get("/verification/experimental/maps/{name}")
    def experimental_map(
        name: str = Path(pattern=r"^[a-z][a-z_-]{1,40}$"), which: str | None = EVIDENCE_SET
    ):
        from backend.app.services import evidence

        png = evidence.map_file(name, which).read_bytes()
        return Response(png, media_type="image/png", headers=IMMUTABLE)

    @app.get("/verification/experimental/figures/{name}")
    def experimental_figure(
        name: str = Path(pattern=r"^[a-z0-9][a-z0-9-]{1,60}$"), which: str | None = EVIDENCE_SET
    ):
        from backend.app.services import evidence

        png = evidence.figure_file(name, which).read_bytes()
        return Response(png, media_type="image/png", headers=IMMUTABLE)
