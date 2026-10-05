from abc import ABC, abstractmethod
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from climate_engine.core import DEMO_LABEL, config


class ObservationProvider(ABC):
    @abstractmethod
    def load(self, start_date: str, end_date: str, variable: str = "precipitation") -> xr.Dataset:
        """Return daily rainfall in canonical coordinates and mm/day units."""

    @abstractmethod
    def metadata(self) -> dict[str, Any]: ...

    @abstractmethod
    def list_available_dates(self) -> list[str]: ...

    def validate(self) -> bool:
        return bool(self.list_available_dates())


def synthetic(start: str, end: str, seed: int = 0, source: str = "ECMWF S2S") -> xr.Dataset:
    settings = config()
    west, south, east, north = settings["domain"]
    ny, nx = settings["grid_shape"]
    lat, lon = np.linspace(south, north, ny), np.linspace(west, east, nx)
    times = pd.date_range(start, end)
    if not len(times):
        raise ValueError("End date must follow start date")
    yy, xx = np.meshgrid(lat, lon, indexing="ij")
    days = (times - pd.Timestamp("2026-01-01")).days.to_numpy()
    base = 2.0 + 5.5 * np.exp(-(((yy + 1) / 9) ** 2)) + 2.2 * np.sin(xx / 5) ** 2
    rain = np.maximum(0, base[None, :, :] + 1.5 * np.sin(days[:, None, None] / 4 + xx / 6))
    # Seeds define reproducible source-specific measurement perturbations; no random redraws.
    rain += (seed / 40) * (0.7 + np.cos(xx / 3 + yy / 5)[None, :, :] ** 2)
    attrs = {
        "units": "mm/day",
        "source": source,
        "version": "demo-1.0",
        "spatial_resolution": f"{(east - west) / (nx - 1):.3f} degrees",
        "temporal_resolution": "daily",
        "start_date": start,
        "end_date": end,
        "processing_level": "synthetic",
        "qc_status": "pending",
        "provenance": DEMO_LABEL,
        "variable": "precipitation",
    }
    return xr.Dataset(
        {"precipitation": (("time", "latitude", "longitude"), rain)},
        coords={"time": times, "latitude": lat, "longitude": lon},
        attrs=attrs,
    )


class MockObservationProvider(ObservationProvider):
    def __init__(self, source: str):
        self.source = source
        self.settings = config("observations")["sources"][source]

    def load(self, start_date: str, end_date: str, variable: str = "precipitation") -> xr.Dataset:
        if variable != "precipitation":
            raise ValueError("Unsupported variable")
        available = self.list_available_dates()
        if start_date < available[0] or end_date > available[-1]:
            raise ValueError("Observations unavailable for requested dates")
        ds = synthetic(start_date, end_date, self.settings["seed"], self.source)
        ds.attrs["version"] = self.settings["version"]
        return ds

    def metadata(self) -> dict[str, Any]:
        return {
            "source": self.source,
            **self.settings,
            "units": "mm/day",
            "label": DEMO_LABEL,
            "available_until": self.list_available_dates()[-1],
        }

    def list_available_dates(self) -> list[str]:
        return [str(x.date()) for x in pd.date_range("2026-09-01", "2026-10-12")]


class LocalNetCDFProvider(ObservationProvider):
    """Opt-in local ingestion: never silently substitute synthetic observations."""

    def __init__(self, source: str, path: str):
        self.source, self.path = source, Path(path)

    def load(self, start_date: str, end_date: str, variable: str = "precipitation") -> xr.Dataset:
        if not self.path.is_file():
            raise FileNotFoundError(f"Dataset missing: {self.path.name}")
        with xr.open_dataset(self.path) as raw:
            ds = (
                raw.rename(
                    {
                        k: v
                        for k, v in {"lat": "latitude", "lon": "longitude"}.items()
                        if k in raw.coords
                    }
                )
                .sel(time=slice(start_date, end_date))
                .load()
            )
        if variable not in ds:
            raise ValueError(f"Variable {variable} missing")
        units = ds[variable].attrs.get("units", ds.attrs.get("units"))
        if units != "mm/day":
            raise ValueError("Explicit unit conversion required; expected mm/day")
        ds.attrs.update(
            units=units,
            source=self.source,
            version="local",
            variable=variable,
            processing_level="local",
            provenance=str(self.path),
            qc_status="pending",
            spatial_resolution="provided",
            temporal_resolution="daily",
            start_date=start_date,
            end_date=end_date,
        )
        return ds

    def metadata(self) -> dict[str, Any]:
        return {"source": self.source, "path": str(self.path), "mode": "local"}

    def list_available_dates(self) -> list[str]:
        with xr.open_dataset(self.path) as ds:
            return [str(pd.Timestamp(x).date()) for x in ds.time.values]


class ChirpsProvider(MockObservationProvider):
    def __init__(self):
        super().__init__("CHIRPS")


class TamsatProvider(MockObservationProvider):
    def __init__(self):
        super().__init__("TAMSAT")


class RFE2Provider(MockObservationProvider):
    def __init__(self):
        super().__init__("RFE2")


def week2_dates(cycle: str) -> tuple[str, str]:
    c = date.fromisoformat(cycle)
    return str(c + timedelta(days=config()["lead_start"])), str(
        c + timedelta(days=config()["lead_end"])
    )
