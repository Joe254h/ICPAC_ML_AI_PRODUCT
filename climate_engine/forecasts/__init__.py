"""Forecast providers.

ForecastProvider
    └── ECMWFS2SForecastProvider  ECMWF ensemble files (ECMWF Open Data downloads, or files
                                  placed by the HPC), validated before use
"""

from abc import ABC, abstractmethod

import xarray as xr


class ForecastProvider(ABC):
    @abstractmethod
    def load(self, cycle: str) -> xr.Dataset:
        """Rainfall for one forecast initialization (cycle = ISO date)."""

    @abstractmethod
    def metadata(self) -> dict: ...

    def load_pressure(self, cycle: str) -> xr.Dataset | None:
        """Pressure-level fields, when the provider supplies them."""
        return None


from climate_engine.forecasts.ecmwf_s2s import ECMWFS2SForecastProvider  # noqa: E402

__all__ = ["ECMWFS2SForecastProvider", "ForecastProvider"]
