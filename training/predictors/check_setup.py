"""Check that this HPC account can run the predictor kit, before any long job.

    python check_setup.py            # packages, credentials, network, disk
    python check_setup.py --no-net   # on a compute node without internet

Prints one line per check (OK / MISSING / WARN) and exits with 1 if a required one fails.
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

REQUIRED = [
    "numpy",
    "pandas",
    "xarray",
    "yaml",
    "netCDF4",
    "cfgrib",
    "eccodes",
    "scipy",
    "shapefile",
    "matplotlib",
    "dask",
]
DOWNLOAD = ["ecmwfapi", "ecmwf.opendata"]
OPTIONAL = {
    "cdsapi": "ORAS5, ERA5 lake/soil, CAMS dust",
    "earthaccess": "MODIS NDVI",
    "windspharm": "velocity potential at 200 hPa (else divergence is used)",
}
CREDENTIALS = {
    "~/.ecmwfapirc": "ECMWF Web API key: S2S reforecasts (required for download.py s2s)",
    "~/.cdsapirc": "Copernicus CDS key: optional sources",
    "~/.netrc": "NASA Earthdata login: optional NDVI",
}
HOSTS = [
    "https://api.ecmwf.int",
    "https://data.ecmwf.int",
    "https://data.chc.ucsb.edu",
    "https://downloads.psl.noaa.gov",
    "http://www.bom.gov.au",
    "https://www.cpc.ncep.noaa.gov",
    "https://ftp.cpc.ncep.noaa.gov",
    "https://www.ncei.noaa.gov",
    "https://www.ngdc.noaa.gov",
    "https://naciscdn.org",
]


def line(status: str, what: str, note: str = "") -> None:
    print(f"{status:8s}{what}{(' - ' + note) if note else ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-net", action="store_true")
    parser.add_argument("--root", default=os.environ.get("ICPAC_PREDICTORS_ROOT", "predictor_data"))
    args = parser.parse_args()
    failed = False
    line(
        "OK" if sys.version_info >= (3, 10) else "MISSING",
        f"Python {sys.version.split()[0]}",
        "3.10 or newer",
    )
    failed |= sys.version_info < (3, 10)
    for name in REQUIRED + DOWNLOAD:
        try:
            importlib.import_module(name)
            line("OK", name)
        except Exception as exc:
            required = name in REQUIRED or not args.no_net
            line("MISSING" if required else "WARN", name, str(exc).splitlines()[0])
            failed |= required
    for name, use in OPTIONAL.items():
        try:
            importlib.import_module(name)
            line("OK", name, use)
        except Exception:
            line("WARN", name, f"not installed: {use}")
    try:  # cfgrib needs the ecCodes library itself, not only the Python package
        import eccodes

        line("OK", f"ecCodes library {eccodes.codes_get_api_version()}")
    except Exception as exc:
        line("MISSING", "ecCodes library", str(exc).splitlines()[0])
        failed = True
    for path, use in CREDENTIALS.items():
        exists = Path(path).expanduser().exists()
        required = path == "~/.ecmwfapirc" and not args.no_net
        line("OK" if exists else ("MISSING" if required else "WARN"), path, use)
        failed |= required and not exists
    if not args.no_net:
        for host in HOSTS:
            try:
                request = urllib.request.Request(
                    host, method="HEAD", headers={"User-Agent": "icpac-predictors/1.0"}
                )
                urllib.request.urlopen(request, timeout=20)
                line("OK", host)
            except urllib.error.HTTPError as exc:  # the host answered: reachable
                line("OK", host, f"answered {exc.code}")
            except Exception as exc:
                line("WARN", host, f"not reachable from here: {exc}")
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(root).free / 1e9
    status = "OK" if free_gb > 300 else "WARN"
    line(
        status,
        f"{free_gb:.0f} GB free in {root.resolve()}",
        "the S2S reforecasts need about 150-250 GB; derived files about 20 GB",
    )
    print("\nAll required checks passed." if not failed else "\nSome required checks failed.")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
