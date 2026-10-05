import numpy as np
import xarray as xr

from climate_engine.core import config


def accumulate_week2(ds: xr.Dataset) -> xr.DataArray:
    cfg = config()
    leads = np.arange(cfg["lead_start"], cfg["lead_end"] + 1)
    if "lead_time" not in ds.coords or not np.isin(leads, ds.lead_time).all():
        raise ValueError("Incomplete Days 8–14 window")
    selected = ds.precipitation.where(ds.lead_time.isin(leads), drop=True)
    result = selected.sum("time", skipna=False)
    result.attrs.update(units="mm", feature_schema=cfg["feature_schema"])
    return result


def align_exact(
    forecast: xr.DataArray, observation: xr.DataArray
) -> tuple[xr.DataArray, xr.DataArray]:
    if forecast.dims != observation.dims:
        raise ValueError("Forecast/observation dimension mismatch")
    return xr.align(forecast, observation, join="exact")
