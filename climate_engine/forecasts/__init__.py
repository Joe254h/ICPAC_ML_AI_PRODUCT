from abc import ABC, abstractmethod
from datetime import date, timedelta

import numpy as np
import xarray as xr

from climate_engine.core import config
from climate_engine.observations import synthetic


class ForecastProvider(ABC):
    @abstractmethod
    def load(self, cycle: str) -> xr.Dataset: ...

    @abstractmethod
    def metadata(self) -> dict: ...


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
