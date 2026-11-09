"""NetCDF reads and writes, one at a time in the process.

The netCDF-C and HDF5 libraries in the netCDF4 wheels are not thread-safe, and xarray holds
its own lock only while it opens a file and reads array data, not while it reads a file's
variables and attributes. A page that read a forecast package while the worker thread ran a
forecast crashed the API with a segmentation fault. Every NetCDF file the service opens or
writes goes through ``LOCK`` (backend/tests/test_ncio.py checks that nothing else does).

Keep the work done under the lock short: read what is needed and leave the ``with`` block.
Never wait for another lock (a forecast run, a map rendering) inside it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import xarray as xr

LOCK = threading.RLock()


@contextmanager
def open_dataset(path: Any, **kwargs: Any) -> Iterator[xr.Dataset]:
    """``xr.open_dataset``, with the lock held until the ``with`` block ends."""
    with LOCK, xr.open_dataset(path, **kwargs) as dataset:
        yield dataset


def load_dataset(path: Any, **kwargs: Any) -> xr.Dataset:
    """The whole file in memory, closed before the lock is released."""
    with open_dataset(path, **kwargs) as dataset:
        return dataset.load()


def to_netcdf(
    data: xr.Dataset | xr.DataArray, path: str | Path | None = None, **kwargs: Any
) -> Any:
    """Write eagerly under the lock, including in-memory observation snapshots."""
    if kwargs.get("compute") is False:
        raise ValueError("Deferred NetCDF writes must not escape the native I/O lock")
    with LOCK:
        return data.to_netcdf(path, **kwargs)
