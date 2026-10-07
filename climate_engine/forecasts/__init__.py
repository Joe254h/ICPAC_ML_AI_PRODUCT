"""Forecast providers.

ForecastProvider
    ├── MockForecastProvider      synthetic demonstration grid (CI, demos)
    └── ECMWFS2SForecastProvider  ECMWF S2S ensemble files (operational inference)
"""

from abc import ABC, abstractmethod
from datetime import date, timedelta

import numpy as np
import xarray as xr

from climate_engine.core import config
from climate_engine.observations import synthetic


class ForecastProvider(ABC):
    @abstractmethod
    def load(self, cycle: str) -> xr.Dataset:
        """Rainfall for one forecast initialization (cycle = ISO date)."""

    @abstractmethod
    def metadata(self) -> dict: ...

    def load_pressure(self, cycle: str) -> xr.Dataset | None:
        """Pressure-level fields, when the provider supplies them."""
        return None


class MockForecastProvider(ForecastProvider):
    def __init__(self, source: str = "ECMWF S2S"):
        if source not in config("forecasts")["sources"]:
            raise ValueError("Unknown forecast provider")
        self.source = source

    def load(self, cycle: str) -> xr.Dataset:
        if cycle not in [str(x) for x in config("forecasts")["cycles"]]:
            raise ValueError("Forecast cycle unavailable")
        start = date.fromisoformat(cycle)
        ds = synthetic(
            str(start + timedelta(days=1)), str(start + timedelta(days=14)), 0, self.source
        )
        ds["precipitation"] = ds.precipitation * 1.28 + 0.65
        ds = ds.assign_coords(lead_time=("time", np.arange(1, 15)))
        ds.attrs.update(forecast_cycle=cycle, accumulation="daily_increments")
        return ds

    def metadata(self) -> dict:
        return {"source": self.source, "mode": "synthetic", "lead_days": [1, 14]}


from climate_engine.forecasts.ecmwf_s2s import ECMWFS2SForecastProvider  # noqa: E402

__all__ = ["ECMWFS2SForecastProvider", "ForecastProvider", "MockForecastProvider"]
