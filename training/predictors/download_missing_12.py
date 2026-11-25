"""Download the 12 predictors of the 245 that the ECMWF S2S reforecasts do not carry.

    python download_missing_12.py --manifest s2s_master_data/metadata/t2m_d2m_full.jsonl
    python download_missing_12.py --years 2004-2025 --workers 4

What it fetches, all at 00 UTC of each day on the 1.5 degree local box (25.5N-13.5S,
18E-52.5E) so it lines up with the S2S fields:

  ERA5 single levels   convective_inhibition (CIN), boundary_layer_height (PBLH),
                       total_cloud_cover (cloud fraction), forecast_albedo (albedo),
                       total_column_cloud_liquid_water (liquid-water path),
                       total_column_cloud_ice_water (ice-water path)
  ERA5 pressure levels specific cloud liquid water, cloud ice water and rain water
                       content at 850, 700 and 500 hPa (the three mixing ratios), and
                       specific snow water content (qsnow) in its own folder. ERA5 has
                       no graupel (qgraup): neither does the ECMWF model
  NOAA CPC indices     QBO zonal wind at 50 and 30 hPa, SOI (monthly text files)
  ERA5-Land            soil temperature layers 1-2, total evaporation, sensible and latent
                       heat flux (land/), daily 00 UTC
  ERA5 fixed maps      high/low vegetation cover and type (static/era5_vegetation.nc)
  NOAA PSL OLR         interpolated daily OLR, global 2.5 degree (noaa_olr/)

ERA5 describes the state at each start date (hdate); the features use the day of, or the
days before, initialization. One file per year (months held from an earlier monthly run are skipped); a file
already on disk is skipped, so the script resumes after a stop.

ERA5 comes from the Copernicus Climate Data Store (CDS), not ECDS. Put your CDS key in
~/.cdsapirc-era5 (two lines: "url: https://cds.climate.copernicus.eu/api" and
"key: <your key>") and accept the ERA5 licence once on the CDS website. Your ~/.cdsapirc
stays as it is for the S2S downloads.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

AREA = [25.5, 18.0, -13.5, 52.5]  # North, West, South, East (the local box)
GRID = [1.5, 1.5]
SINGLE = [
    "convective_inhibition",
    "boundary_layer_height",
    "total_cloud_cover",
    "forecast_albedo",
    "total_column_cloud_liquid_water",
    "total_column_cloud_ice_water",
]
PRESSURE = [
    "specific_cloud_liquid_water_content",
    "specific_cloud_ice_water_content",
    "specific_rain_water_content",
]
LEVELS = ["500", "700", "850"]
CPC = {
    "qbo.u50.index": "https://www.cpc.ncep.noaa.gov/data/indices/qbo.u50.index",
    "qbo.u30.index": "https://www.cpc.ncep.noaa.gov/data/indices/qbo.u30.index",
    "soi": "https://www.cpc.ncep.noaa.gov/data/indices/soi",
}
LAND = [
    "soil_temperature_level_1",
    "soil_temperature_level_2",
    "total_evaporation",
    "surface_sensible_heat_flux",
    "surface_latent_heat_flux",
]
STATIC = [
    "high_vegetation_cover",
    "low_vegetation_cover",
    "type_of_high_vegetation",
    "type_of_low_vegetation",
]
OLR_URL = "https://downloads.psl.noaa.gov/Datasets/interp_OLR/olr.day.mean.nc"
DEFAULT_OUT = "/scratch/njoel/s2s_master_data/raw/era5_cpc_missing12"


def years_from_manifest(path: Path) -> list[int]:
    """Every hindcast year in an S2S request manifest: the ECDS ``hyear`` lists, or the
    years inside MARS-style ``hdate`` strings."""
    years: set[int] = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        request = record.get("request", record)
        hyear = request.get("hyear")
        if hyear:
            years.update(int(y) for y in (hyear if isinstance(hyear, list) else [hyear]))
        hdate = str(request.get("hdate") or "")
        years.update(
            int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?=-?\d{2}-?\d{2})", hdate)
        )
    if not years:
        raise SystemExit(f"no hyear or hdate found in {path}: pass --years FIRST-LAST instead")
    # Antecedent features reach into the days before a start date in early January.
    return sorted(years | {min(years) - 1})


def client():
    import cdsapi

    rc = Path.home() / ".cdsapirc-era5"
    if not rc.exists():
        raise SystemExit(
            f"{rc} is missing: create it with your CDS url and key (see the top of this script)"
        )
    settings = dict(line.split(":", 1) for line in rc.read_text().splitlines() if ":" in line)
    return cdsapi.Client(
        url=settings["url"].strip(), key=settings["key"].strip(), quiet=True, progress=False
    )


def era5_jobs(years: list[int], out: Path) -> list[tuple[str, dict, Path]]:
    """One request per year and level type: the Copernicus queue, not the data, sets the
    pace, so fewer and larger requests finish sooner. Months already held as monthly files
    (from an earlier run) are left out of that year's request."""
    jobs = []
    today = datetime.now(timezone.utc)
    kinds = [
        ("reanalysis-era5-single-levels", "single", {"variable": SINGLE}),
        (
            "reanalysis-era5-pressure-levels",
            "pressure",
            {"variable": PRESSURE, "pressure_level": LEVELS},
        ),
        # F239 qsnow, added after the first run: its own folder, so the files already
        # held are not fetched again.
        (
            "reanalysis-era5-pressure-levels",
            "snow",
            {"variable": ["specific_snow_water_content"], "pressure_level": LEVELS},
        ),
        # F148-F149 soil temperature, F152-F153 evapotranspiration, F154-F155 sensible and
        # latent heat flux. ERA5-Land accumulations at 00 UTC are the previous day's total.
        ("reanalysis-era5-land", "land", {"variable": LAND}),
    ]
    for year in years:
        for dataset, kind, extra in kinds:
            folder = out / kind
            months = [
                m
                for m in range(1, 13)
                if (year, m) <= (today.year, today.month)
                and not (folder / f"era5_{kind}_{year}_{m:02d}.nc").exists()
            ]
            if not months:
                continue
            name = (
                f"era5_{kind}_{year}.nc"
                if len(months) == 12
                else (f"era5_{kind}_{year}_{months[0]:02d}-{months[-1]:02d}.nc")
            )
            request = {
                **({} if dataset == "reanalysis-era5-land" else {"product_type": ["reanalysis"]}),
                "year": [str(year)],
                "month": [f"{m:02d}" for m in months],
                "day": [f"{d:02d}" for d in range(1, 32)],
                "time": ["00:00"],
                "area": AREA,
                "grid": GRID,
                "data_format": "netcdf",
                "download_format": "unarchived",
                **extra,
            }
            jobs.append((dataset, request, folder / name))
    # F245 vegetation fraction, F212 land-cover class: ERA5's fixed vegetation maps.
    static = out / "static" / "era5_vegetation.nc"
    if not static.exists():
        jobs.append(
            (
                "reanalysis-era5-single-levels",
                {
                    "product_type": ["reanalysis"],
                    "variable": STATIC,
                    "year": ["2024"],
                    "month": ["01"],
                    "day": ["01"],
                    "time": ["00:00"],
                    "area": AREA,
                    "grid": GRID,
                    "data_format": "netcdf",
                    "download_format": "unarchived",
                },
                static,
            )
        )
    return jobs


def retrieve(dataset: str, request: dict, target: Path, retries: int) -> str:
    if target.exists() and target.stat().st_size > 0:
        return f"kept    {target.name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    for attempt in range(1, retries + 2):
        try:
            client().retrieve(dataset, request, str(partial))
            partial.replace(target)
            return f"fetched {target.name}"
        except Exception as exc:  # CDS queue errors, timeouts: wait and try again
            if attempt > retries:
                return f"FAILED  {target.name}: {str(exc)[:200]}"
            time.sleep(60 * attempt)
    return f"FAILED  {target.name}"


def fetch_olr(out: Path) -> None:
    """NOAA interpolated daily OLR (2.5 degree, global, 1974 on) for the Kelvin-wave index
    (F200): one file of about 0.8 GB, streamed to disk and kept once complete."""
    target = out / "noaa_olr" / "olr.day.mean.nc"
    if target.exists() and target.stat().st_size > 0:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    try:
        with urllib.request.urlopen(OLR_URL, timeout=600) as response, open(partial, "wb") as f:
            while chunk := response.read(1 << 20):
                f.write(chunk)
        partial.replace(target)
        print(f"fetched {target.name} ({target.stat().st_size / 1e6:.0f} MB)")
    except OSError as exc:
        print(f"FAILED  olr.day.mean.nc: {exc} (needs internet: run on the login node)")


def fetch_cpc(out: Path) -> None:
    folder = out / "noaa_cpc"
    folder.mkdir(parents=True, exist_ok=True)
    for name, url in CPC.items():
        target = folder / f"{name}.txt"
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                target.write_bytes(response.read())
            print(f"fetched {target.name} ({len(target.read_text().splitlines())} lines)")
        except OSError as exc:
            print(f"FAILED  {name}: {exc} (needs internet: run on the login node)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--manifest", type=Path, help="S2S manifest (.jsonl) to take the years from"
    )
    source.add_argument("--years", help="FIRST-LAST, e.g. 2004-2025")
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUT))
    parser.add_argument("--workers", type=int, default=4, help="requests queued at CDS at once")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true", help="list the requests, fetch nothing")
    parser.add_argument("--skip-era5", action="store_true", help="only the CPC indices")
    args = parser.parse_args(argv)

    if args.manifest:
        years = years_from_manifest(args.manifest)
    else:
        first, last = (int(y) for y in args.years.split("-"))
        years = list(range(first, last + 1))
    jobs = [] if args.skip_era5 else era5_jobs(years, args.out)
    todo = [j for j in jobs if not (j[2].exists() and j[2].stat().st_size > 0)]
    print(
        f"{len(years)} years ({years[0]}-{years[-1]}): {len(jobs)} ERA5 files, {len(todo)} still to fetch"
    )
    print(f"writing to {args.out}")
    if args.dry_run:
        for dataset, request, target in todo[:4]:
            print(
                dataset,
                target.name,
                json.dumps({k: request[k] for k in ("variable", "year", "month")}),
            )
        return 0

    fetch_cpc(args.out)
    fetch_olr(args.out)
    if not todo:
        return 0
    client()  # fail now, not after an hour, if the CDS key is missing
    done = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(retrieve, *job, args.retries) for job in todo]
        for future in as_completed(futures):
            line = future.result()
            done += 1
            failed += line.startswith("FAILED")
            print(f"[{done}/{len(todo)}] {line}", flush=True)
    print(f"finished: {len(todo) - failed} fetched, {failed} failed (run again to retry them)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
