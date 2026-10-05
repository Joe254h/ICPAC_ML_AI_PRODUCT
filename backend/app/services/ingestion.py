"""Explicit registration of canonical local observations, with mandatory QC."""

from backend.app.db import now
from climate_engine.core import config
from climate_engine.observations import LocalNetCDFProvider
from climate_engine.provenance import file_checksum, permitted_file
from climate_engine.qc import check_dataset


class ObservationIngestion:
    def __init__(self, platform):
        self.platform = platform

    def register(self, source: str, path: str, actor: str) -> dict:
        if source not in config("observations")["sources"]:
            raise ValueError("Source must be CHIRPS, TAMSAT or RFE2")
        artifact = permitted_file(path, "DATA_ROOT", "data/observations")
        if artifact.suffix.lower() not in {".nc", ".nc4"}:
            raise ValueError("Observation input must be NetCDF")
        provider = LocalNetCDFProvider(source, str(artifact))
        dates = provider.list_available_dates()
        if not dates:
            raise ValueError("No observation dates available")
        dataset = provider.load(dates[0], dates[-1])
        qc = check_dataset(dataset, dates[0], dates[-1])
        if qc["status"] == "FAIL":
            raise ValueError("Observation QC failed: " + str(qc["errors"]))
        record = self.platform.repo.save(
            "dataset",
            {
                **dataset.attrs,
                **provider.metadata(),
                "version": dataset.attrs["version"],
                "checksum": file_checksum(artifact),
                "qc": qc,
                "qc_status": qc["status"],
                "available_until": dates[-1],
                "registered_at": now(),
                "label": "LOCAL OBSERVATIONS · synthetic forecasts and approximate masks remain",
            },
            source,
        )
        self.platform._calculate.cache_clear()
        self.platform.repo.audit(
            "register_observations", actor, source, {"checksum": record["checksum"]}
        )
        return record
