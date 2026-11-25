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
                       content at 850, 700 and 500 hPa (the three mixing ratios)
  NOAA CPC indices     QBO zonal wind at 50 and 30 hPa, SOI (monthly text files)

ERA5 describes the state at each start date (hdate); the features use the day of, or the
days before, initialization. One file per year and month; a file already on disk is skipped,
so the script resumes after a stop.

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
DEFAULT_OUT = "/scratch/njoel/s2s_master_data/raw/era5_cpc_missing12"


def years_from_manifest(path: Path) -> list[int]:
    """Every year that appears as a hindcast date (hdate) in an S2S request manifest."""
    years: set[int] = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        text = json.dumps(record)
        for match in re.finditer(r'"hdate"\s*:\s*"([^"]+)"', text):
            years.update(
                int(y)
                for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?=-?\d{2}-?\d{2})", match.group(1))
            )
    if not years:
        raise SystemExit(f"no hdate found in {path}: pass --years FIRST-LAST instead")
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
    jobs = []
    today = datetime.now(timezone.utc)
    for year in years:
        for month in range(1, 13):
            if (year, month) > (today.year, today.month):
                continue
            base = {
                "product_type": ["reanalysis"],
                "year": [str(year)],
                "month": [f"{month:02d}"],
                "day": [f"{d:02d}" for d in range(1, 32)],
                "time": ["00:00"],
                "area": AREA,
                "grid": GRID,
                "data_format": "netcdf",
                "download_format": "unarchived",
            }
            jobs.append(
                (
                    "reanalysis-era5-single-levels",
                    {**base, "variable": SINGLE},
                    out / "single" / f"era5_single_{year}_{month:02d}.nc",
                )
            )
            jobs.append(
                (
                    "reanalysis-era5-pressure-levels",
                    {**base, "variable": PRESSURE, "pressure_level": LEVELS},
                    out / "pressure" / f"era5_pressure_{year}_{month:02d}.nc",
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
