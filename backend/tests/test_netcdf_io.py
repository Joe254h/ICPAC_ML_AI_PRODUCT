"""Concurrent HTTP readers and background writers must not crash NetCDF-C."""

import subprocess
import sys


def test_concurrent_netcdf_read_write_and_lazy_load(tmp_path):
    # Run native stress in a child: a regression must fail this test, not kill pytest.
    script = r"""
import faulthandler
import resource
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
import xarray as xr
from climate_engine.ncio import open_dataset as open_netcdf, to_netcdf as write_netcdf

faulthandler.enable()
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
root = Path(sys.argv[1])
rain = xr.Dataset({'rain': (('latitude', 'longitude'), np.arange(2000).reshape(40, 50))},
                  attrs={'units': 'mm', 'reference': 'test'})
write_netcdf(rain, root / 'shared.nc')
def exercise(index):
    for _ in range(40):
        # Metadata and lazy values stay under the same lock until the context exits.
        with open_netcdf(root / 'shared.nc') as data:
            assert data.attrs['reference'] == 'test'
            np.testing.assert_array_equal(data.rain.values, rain.rain.values)
        own = root / f'writer-{index}.nc'
        write_netcdf(rain, own)
        with open_netcdf(own) as data:
            np.testing.assert_array_equal(data.rain.values, rain.rain.values)
with ThreadPoolExecutor(max_workers=4) as pool:
    list(pool.map(exercise, range(4)))
# In-memory reference snapshots retain their explicit SciPy format.
import io
payload = bytes(write_netcdf(rain, engine='scipy'))
with open_netcdf(io.BytesIO(payload), engine='scipy') as data:
    np.testing.assert_array_equal(data.rain.values, rain.rain.values)
print('native concurrency and snapshot roundtrip passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "native concurrency and snapshot roundtrip passed" in result.stdout
