"""Versioned supplementary products, kept outside immutable forecast packages."""

import os
from pathlib import Path

import numpy as np
import xarray as xr

from backend.app.db import now
from backend.app.services.forecasts import ForecastService, Unavailable
from climate_engine.cartography import icpac_maps as maps
from climate_engine.core import ROOT
from climate_engine.products import supplemental
from climate_engine.products.store import package_store
from climate_engine.provenance import file_checksum


def output_root() -> Path:
    return Path(os.getenv("RUN_ROOT", str(ROOT / "data" / "runs"))) / "supplemental"


class SupplementalService:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    def current(self, forecast_id: str) -> dict:
        self.repo.get("forecast_run", forecast_id)
        try:
            pointer = self.repo.get("supplemental_pointer", f"supplemental-pointer-{forecast_id}")
            return self.repo.get("supplemental_product", pointer["record_id"])
        except KeyError:
            return {
                "status": "blocked",
                "available": [],
                "pending": {
                    key: "Reviewed reference data for the exact forecast window"
                    for key in supplemental.NAMES
                },
            }

    def build(self, forecast_id: str, actor: str) -> dict:
        service = ForecastService(self.platform)
        detail = service.get(forecast_id)
        root = output_root() / forecast_id
        metadata = supplemental.build(service.directory(forecast_id), root, detail["primary_layer"])
        if metadata["status"] != "available":
            return metadata
        target = root / metadata["revision"] / "products.nc"
        store = package_store()
        if store is not None:
            store.put(
                f"supplemental/{forecast_id}/{metadata['revision']}/products.nc",
                target.read_bytes(),
            )
        with xr.open_dataset(target) as dataset:
            summary = {}
            for name in metadata["available"]:
                values = dataset[name].values
                finite = values[np.isfinite(values)]
                summary[name] = {
                    "min": float(finite.min()),
                    "max": float(finite.max()),
                    "mean": float(finite.mean()),
                    "units": dataset[name].attrs["units"],
                }
        identifier = f"supplemental-{forecast_id}-{metadata['revision']}"
        record = self.repo.save(
            "supplemental_product",
            {
                **metadata,
                "forecast_id": forecast_id,
                "summary": summary,
                "created_at": now(),
                "created_by": actor,
            },
            identifier,
        )
        self.repo.save(
            "supplemental_pointer",
            {"record_id": record["id"]},
            f"supplemental-pointer-{forecast_id}",
        )
        self.repo.audit(
            "supplemental_products_prepared",
            actor,
            identifier,
            {"manifest_sha256": metadata["manifest_sha256"]},
        )
        return record

    def dataset(self, record: dict) -> xr.Dataset:
        forecast_id = record["forecast_id"]
        target = output_root() / forecast_id / record["revision"] / "products.nc"
        if not target.is_file():
            store = package_store()
            data = (
                store.get(f"supplemental/{forecast_id}/{record['revision']}/products.nc")
                if store
                else None
            )
            if data is None:
                raise Unavailable("The supplemental product is not in durable storage")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if file_checksum(target) != record["data_sha256"]:
            raise ValueError("Supplemental product checksum changed")
        with xr.open_dataset(target) as opened:
            return opened.load()

    def map(self, record: dict, product: str) -> bytes:
        if product not in record.get("available", []) or product not in supplemental.NAMES:
            raise Unavailable("The requested supplementary product needs reviewed inputs")
        dataset = self.dataset(record)
        field = maps.Field(
            product, dataset[product].values, dataset.latitude.values, dataset.longitude.values
        )
        layer = maps.Layer(supplemental.NAMES[product][0], field, f"supplemental_{product}")
        return maps.render_png(
            maps.Figure(
                product,
                [layer],
                note=f"Evaluation product · reference {record['reference_period']} · forecaster review required",
            )
        )

    def appendix(self, forecast_id: str) -> dict | None:
        record = self.current(forecast_id)
        if record["status"] != "available":
            return None
        return {
            "record_id": record["id"],
            "manifest_sha256": record["manifest_sha256"],
            "data_sha256": record["data_sha256"],
            "reference_period": record["reference_period"],
            "reference_source": record["reference_source"],
            "extreme_definition": record.get("extreme_definition"),
            "heat_stress_definition": record.get("heat_stress_definition"),
            "approved_by": record["approved_by"],
            "summary": record["summary"],
            "notes": record["notes"],
        }
