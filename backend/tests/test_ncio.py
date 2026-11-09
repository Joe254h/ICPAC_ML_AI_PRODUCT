"""Every NetCDF read and write in the service holds one lock (climate_engine.ncio).

The API crashed with a segmentation fault when a bulletin read a forecast package while
the worker thread ran a forecast: netCDF-C and HDF5 are not thread-safe.
"""

import re
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from climate_engine import ncio

ROOT = Path(__file__).resolve().parents[2]
UNLOCKED = re.compile(
    r"\bxr\.(open_dataset|load_dataset|open_mfdataset|open_dataarray)\(|(?<!ncio)\.to_netcdf\("
)


def test_no_netcdf_file_is_opened_or_written_outside_the_lock():
    found = []
    for folder in ("backend/app", "climate_engine", "chatbot", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            if path.name == "ncio.py" or "tests" in path.parts:
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if UNLOCKED.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert found == [], "use climate_engine.ncio:\n" + "\n".join(found)


def _field(value: float) -> xr.Dataset:
    return xr.Dataset(
        {"rain": (("latitude", "longitude"), np.full((20, 30), value, dtype=np.float32))},
        coords={"latitude": np.arange(20.0), "longitude": np.arange(30.0)},
        attrs={"value": value},
    )


def test_a_read_waits_while_another_thread_holds_the_lock(tmp_path):
    path = tmp_path / "field.nc"
    ncio.to_netcdf(_field(1.0), path)
    held = threading.Event()

    def hold():
        with ncio.LOCK:
            held.set()
            time.sleep(0.3)

    holder = threading.Thread(target=hold)
    holder.start()
    held.wait(5)
    started = time.monotonic()
    data = ncio.load_dataset(path)
    waited = time.monotonic() - started
    holder.join()
    assert waited >= 0.2
    assert float(data["rain"].mean()) == 1.0 and data.attrs["value"] == 1.0


def test_threads_read_and_write_netcdf_at_once(tmp_path):
    errors: list[BaseException] = []

    def work(index: int):
        try:
            for round_ in range(15):
                path = tmp_path / f"field-{index}-{round_ % 3}.nc"
                ncio.to_netcdf(_field(float(index)), path)
                with ncio.open_dataset(path) as data:
                    assert data.attrs["value"] == float(index)
                    assert float(data["rain"].values.mean()) == float(index)
        except BaseException as exc:  # reported by the test, not lost in the thread
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_deferred_write_cannot_escape_the_native_lock(tmp_path):
    with pytest.raises(ValueError, match="Deferred NetCDF"):
        ncio.to_netcdf(_field(1.0), tmp_path / "deferred.nc", compute=False)
