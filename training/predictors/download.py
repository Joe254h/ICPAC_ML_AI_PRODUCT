"""Download every source the predictor catalogue needs, for the ICPAC region.

Run on the HPC (on a login or data-transfer node if compute nodes have no internet):

    python download.py cases --from-cca /scratch/.../CCA_DIAGNOSTIC_2005_2021
    python download.py probe-s2s            # which ECMWF parameters/levels the archive has
    python download.py probe-opendata       # which of them ECMWF Open Data has live
    python download.py s2s --workers 3      # the reforecasts (the big one; resumable)
    python download.py observed             # CHIRPS, OISST, OLR, indices, IBTrACS
    python download.py static               # ETOPO elevation, Natural Earth coast and lakes
    python download.py optional --what oras5 cams era5-lake era5-soil ndvi

Every command skips files already complete, writes to a .part file first and logs what it
did to <root>/logs/download.log. Downloads that need an account read their usual
credential file: ~/.ecmwfapirc (S2S), ~/.cdsapirc (CDS), ~/.adsapirc or the ADS key
(CAMS), and Earthdata (NDVI) through the earthaccess login.

The S2S cases default to the existing refit's: model-version dates of 2025 with hindcast
years 2005-2024, 10 perturbed members, 1.5 degrees (the files the current model was
trained on are ecmwf_s2s_mv2025MMDD_h2005-2024_pf_pressure.nc).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common import (
    Box,
    Case,
    catalogue,
    data_root,
    hindcast_date,
    log,
    read_cases,
    setup_logging,
    write_cases,
)

# ---------------------------------------------------------------- sources
# Fix a URL here if a provider moves a file; each is used by one command only.
URLS = {
    "chirps_daily": "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/"
    "chirps-v2.0.{year}.days_p25.nc",
    "oisst_daily": "https://downloads.psl.noaa.gov/Datasets/noaa.oisst.v2.highres/"
    "sst.day.mean.{year}.nc",
    "olr_daily": "https://downloads.psl.noaa.gov/Datasets/interp_OLR/olr.day.mean.nc",
    "rmm": "http://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt",
    "aao_daily": "https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.aao.cdas.z700.19790101_current.csv",
    "nao_daily": "https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.nao.cdas.z500.19500101_current.csv",
    "qbo_u30": "https://www.cpc.ncep.noaa.gov/data/indices/qbo.u30.index",
    "soi": "https://www.cpc.ncep.noaa.gov/data/indices/soi",
    "ibtracs": "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-"
    "stewardship-ibtracs/v04r01/access/csv/ibtracs.{basin}.list.v04r01.csv",
    "etopo": "https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/60s/"
    "60s_surface_elev_netcdf/ETOPO_2022_v1_60s_N90W180_surface.nc",
    "ne_coastline": "https://naciscdn.org/naturalearth/10m/physical/ne_10m_coastline.zip",
    "ne_lakes": "https://naciscdn.org/naturalearth/10m/physical/ne_10m_lakes.zip",
}

# ECMWF parameter ids in the S2S archive. The "verify" ones are checked by probe-s2s before
# any bulk download asks for them.
S2S_PARAMS = {
    "gh": 156,
    "t": 130,
    "u": 131,
    "v": 132,
    "q": 133,
    "w": 135,
    "tp": 228228,
    "ttr": 179,
    "msl": 151,
    "sp": 134,
    "tcw": 136,
    "sm20": 228086,  # verify: top 20 cm soil moisture
}
SFC_INSTANT_STEPS = [192, 216, 240, 264, 288, 312, 336]
SFC_ACCUMULATED_STEPS = [168, 336]  # tp, ttr: day 14 minus day 7


# ---------------------------------------------------------------- http helpers


def fetch(url: str, target: Path, attempts: int = 4, timeout: int = 600) -> Path:
    """One file over HTTP(S), resumable at the file level: a complete file is kept, a
    partial one is fetched again; retried with a growing wait."""
    if target.exists() and target.stat().st_size > 0:
        log.info("have %s", target.name)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "icpac-predictors/1.0"})
    for attempt in range(1, attempts + 1):
        try:
            log.info("fetch %s", url)
            with (
                urllib.request.urlopen(request, timeout=timeout) as response,
                open(part, "wb") as out,
            ):
                shutil.copyfileobj(response, out, length=1 << 20)
            part.replace(target)
            return target
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.warning("attempt %d/%d failed for %s: %s", attempt, attempts, url, exc)
            if attempt == attempts:
                raise
            time.sleep(30 * attempt)
    return target


def crop_netcdf(source: Path, target: Path, box: Box, lat: str = "lat", lon: str = "lon") -> None:
    """Keep only the box of a global NetCDF file (and delete the global one)."""
    import xarray as xr
    from common import select_box

    with xr.open_dataset(source) as data:
        cropped = select_box(data, box, lat, lon).load()
    part = target.with_name(target.name + ".part")
    cropped.to_netcdf(part)
    part.replace(target)
    source.unlink()


# ---------------------------------------------------------------- cases


def cases_command(args: argparse.Namespace, cat: dict[str, Any], root: Path) -> None:
    """cases.csv: the (model-version date, hindcast date) pairs to download.

    --from-cca: exactly the refit's 3,148 cases (its CCA inventory files list them).
    --from-dir: every hindcast year of each model-version file in a directory.
    --model-year: Mondays and Thursdays of that year with --years hindcast years.
    """
    cases: list[Case] = []
    if args.from_cca:
        import numpy as np

        for path in sorted(Path(args.from_cca).glob("cca_month_*.npz")):
            with np.load(path) as z:
                inits, years = z["inits"].astype(str), z["years"].astype(int)
            for init_text, year in zip(inits, years, strict=True):
                init = datetime.strptime(init_text.replace("-", "")[:8], "%Y%m%d").date()
                hdate = hindcast_date(init, int(year))
                if hdate:
                    cases.append(Case(init, hdate))
    else:
        first, last = (int(x) for x in args.years.split("-"))
        inits: list[date] = []
        if args.from_dir:
            for path in sorted(Path(args.from_dir).glob("*mv*_h*")):
                stamp = path.name.split("mv", 1)[1][:8]
                inits.append(datetime.strptime(stamp, "%Y%m%d").date())
        else:
            day = date(args.model_year, 1, 1)
            while day.year == args.model_year:
                if day.weekday() in (0, 3):  # Monday, Thursday
                    inits.append(day)
                day += timedelta(days=1)
        for init in sorted(set(inits)):
            for year in range(first, last + 1):
                hdate = hindcast_date(init, year)
                if hdate:
                    cases.append(Case(init, hdate))
    path = root / "cases.csv"
    write_cases(path, cases)
    log.info(
        "%d cases (%d model-version dates) written to %s",
        len(set(cases)),
        len({c.init for c in cases}),
        path,
    )


# ---------------------------------------------------------------- ECMWF S2S


def s2s_request(
    init: date,
    hdates: list[date],
    levtype: str,
    params: list[str],
    steps: list[int],
    area: str,
    levels: list[int] | None = None,
    members: int = 10,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "class": "s2",
        "dataset": "s2s",
        "expver": "prod",
        "model": "glob",
        "origin": "ecmf",
        "stream": "enfh",
        "type": "pf",
        "number": "/".join(str(n) for n in range(1, members + 1)),
        "date": init.isoformat(),
        "hdate": "/".join(h.isoformat() for h in sorted(hdates)),
        "time": "00:00:00",
        "levtype": levtype,
        "param": "/".join(str(S2S_PARAMS[p]) for p in params),
        "step": "/".join(str(s) for s in steps),
        "area": area,
        "grid": "1.5/1.5",
    }
    if levels:
        request["levelist"] = "/".join(str(level) for level in levels)
    return request


def retrieve(request: dict[str, Any], target: Path, client: str) -> None:
    """One S2S retrieval through the ECMWF Web API, or the MARS client on an ECMWF HPC."""
    part = target.with_name(target.name + ".part")
    if client == "mars":
        lines = ["retrieve,"] + [f"  {k}={v}," for k, v in request.items() if k != "dataset"]
        lines.append(f'  target="{part}"')
        script = target.with_suffix(".req")
        script.write_text("\n".join(lines) + "\n")
        subprocess.run(["mars", str(script)], check=True)
    else:
        from ecmwfapi import ECMWFDataServer

        ECMWFDataServer().retrieve({**request, "target": str(part)})
    part.replace(target)


def s2s_plan(cat: dict[str, Any], availability: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The S2S requests for one model-version date: pressure levels, surface and global,
    leaving out what probe-s2s found missing."""
    raw = cat["ens_raw"]
    missing = set((availability or {}).get("missing", []))
    large = Box.of(cat["domain"]["large_box"])
    plan = []
    by_levels: dict[tuple[int, ...], list[str]] = defaultdict(list)
    for name, levels in raw["pressure_levels"].items():
        kept = tuple(lvl for lvl in levels if f"{name}@{lvl}" not in missing)
        if kept:
            by_levels[kept].append(name)
    for levels, names in by_levels.items():
        plan.append(
            {
                "kind": "pl_" + "_".join(names),
                "params": names,
                "levels": list(levels),
                "steps": SFC_INSTANT_STEPS,
                "area": large.area(),
            }
        )
    surface = [p for p in raw["surface"] if p not in missing]
    instant = [p for p in surface if p in ("msl", "sp", "tcw")]
    accumulated = [p for p in surface if p in ("tp", "ttr")]
    if instant:
        plan.append(
            {
                "kind": "sfc_instant",
                "params": instant,
                "steps": SFC_INSTANT_STEPS,
                "area": large.area(),
            }
        )
    if accumulated:
        plan.append(
            {
                "kind": "sfc_accumulated",
                "params": accumulated,
                "steps": SFC_ACCUMULATED_STEPS,
                "area": large.area(),
            }
        )
    if "sm20" in surface:
        local = Box.of(cat["domain"]["local_box"])
        plan.append({"kind": "sfc_initial", "params": ["sm20"], "steps": [0], "area": local.area()})
    for name, levels in raw["global_levels"].items():
        kept = [lvl for lvl in levels if f"{name}@{lvl}" not in missing]
        if kept:
            plan.append(
                {
                    "kind": f"global_{name}",
                    "params": [name],
                    "levels": kept,
                    "steps": SFC_INSTANT_STEPS,
                    "area": "90/-180/-90/180",
                }
            )
    return plan


def s2s_command(args: argparse.Namespace, cat: dict[str, Any], root: Path) -> None:
    cases = read_cases(root / "cases.csv")
    by_init: dict[date, list[date]] = defaultdict(list)
    for case in cases:
        by_init[case.init].append(case.hdate)
    probe = root / "availability_s2s.json"
    availability = json.loads(probe.read_text()) if probe.exists() else None
    if availability is None:
        log.warning(
            "No availability_s2s.json: run probe-s2s first, or every parameter is asked for"
        )
    plan = s2s_plan(cat, availability)
    members = int(cat["training"]["members"])
    jobs = []
    for init, hdates in sorted(by_init.items()):
        if args.inits and init.isoformat() not in args.inits:
            continue
        for item in plan:
            target = root / "raw" / "s2s" / f"{init:%Y%m%d}" / f"{item['kind']}.grib"
            if target.exists() and target.stat().st_size > 0:
                continue
            levtype = "pl" if item.get("levels") else "sfc"  # global_* carry levels too
            request = s2s_request(
                init,
                hdates,
                levtype,
                item["params"],
                item["steps"],
                item["area"],
                item.get("levels"),
                members,
            )
            jobs.append((request, target))
    log.info("%d S2S requests to make (%d model-version dates)", len(jobs), len(by_init))
    if args.dry_run:
        for request, target in jobs[:5]:
            log.info("%s <- %s", target, json.dumps(request))
        return
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for request, target in jobs:
            target.parent.mkdir(parents=True, exist_ok=True)
            futures[pool.submit(retrieve, request, target, args.client)] = target
        for future in as_completed(futures):
            try:
                future.result()
                log.info("done %s", futures[future])
            except Exception as exc:  # keep going; the next run retries what is missing
                log.error("failed %s: %s", futures[future], exc)
                failed.append(str(futures[future]))
    if failed:
        log.error("%d requests failed; run the same command again to retry them", len(failed))
        raise SystemExit(1)


def probe_s2s_command(args: argparse.Namespace, cat: dict[str, Any], root: Path) -> None:
    """Ask the archive for one step of each parameter and level, for one case, and record
    what exists: availability_s2s.json, read by the s2s command and by derive.py."""
    cases = read_cases(root / "cases.csv")
    case = cases[0]
    local = Box.of(cat["domain"]["local_box"])
    checks: list[tuple[str, str, list[int] | None, int]] = []
    for name, levels in cat["ens_raw"]["pressure_levels"].items():
        checks += [(f"{name}@{lvl}", name, [lvl], 192) for lvl in levels]
    for name in cat["ens_raw"]["surface"]:
        checks.append((name, name, None, 0 if name == "sm20" else 336))
    for name, levels in cat["ens_raw"]["global_levels"].items():
        checks += [(f"{name}@{lvl}", name, [lvl], 192) for lvl in levels]
    found, missing = [], []
    folder = root / "raw" / "probe"
    folder.mkdir(parents=True, exist_ok=True)
    for label, name, levels, step in dict.fromkeys(checks):
        target = folder / f"{label.replace('@', '_')}.grib"
        request = s2s_request(
            case.init,
            [case.hdate],
            "pl" if levels else "sfc",
            [name],
            [step],
            local.area(),
            levels,
            members=1,
        )
        try:
            if not target.exists():
                retrieve(request, target, args.client)
            found.append(label)
            log.info("available: %s", label)
        except Exception as exc:
            missing.append(label)
            log.warning("missing: %s (%s)", label, exc)
    result = {
        "checked": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case": case.key,
        "found": found,
        "missing": missing,
    }
    (root / "availability_s2s.json").write_text(json.dumps(result, indent=2))
    log.info("S2S: %d available, %d missing -> availability_s2s.json", len(found), len(missing))


def probe_opendata_command(args: argparse.Namespace, cat: dict[str, Any], root: Path) -> None:
    """Which of the same parameters ECMWF Open Data publishes for the live ENS: a predictor
    that is in the reforecasts but not live cannot be used operationally."""
    from ecmwf.opendata import Client

    client = Client(source=args.opendata_source)
    folder = root / "raw" / "probe_opendata"
    folder.mkdir(parents=True, exist_ok=True)
    found, missing = [], []
    checks = []
    for name, levels in cat["ens_raw"]["pressure_levels"].items():
        checks += [(f"{name}@{lvl}", {"param": name, "levelist": lvl}) for lvl in levels]
    for name in cat["ens_raw"]["surface"]:
        checks.append((name, {"param": name}))
    for name, levels in cat["ens_raw"]["global_levels"].items():
        checks += [(f"{name}@{lvl}", {"param": name, "levelist": lvl}) for lvl in levels]
    for label, extra in dict.fromkeys((c[0], json.dumps(c[1])) for c in checks):
        params = json.loads(extra)
        target = folder / f"{label.replace('@', '_')}.grib2"
        try:
            client.retrieve(
                type="pf", stream="enfo", step=192, number=1, target=str(target), **params
            )
            found.append(label)
            log.info("live: %s", label)
        except Exception as exc:
            missing.append(label)
            log.warning("not live: %s (%s)", label, exc)
    result = {
        "checked": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "found": found,
        "missing": missing,
    }
    (root / "availability_opendata.json").write_text(json.dumps(result, indent=2))
    log.info(
        "Open Data: %d live, %d missing -> availability_opendata.json", len(found), len(missing)
    )


# ---------------------------------------------------------------- observed


def observed_years(cat: dict[str, Any], cases: list[Case]) -> range:
    first = min(c.hdate for c in cases).year - 1  # lags reach into the year before
    last = max(c.hdate for c in cases).year
    del cat
    return range(first, last + 1)


def observed_command(args: argparse.Namespace, cat: dict[str, Any], root: Path) -> None:
    cases = read_cases(root / "cases.csv")
    years = observed_years(cat, cases)
    local = Box.of(cat["domain"]["local_box"])
    # CHIRPS 0.25 degree daily, cropped to the local box (lagged rainfall, L3).
    for year in years:
        target = root / "raw" / "chirps" / f"chirps_{year}_icpac.nc"
        if target.exists():
            continue
        whole = fetch(URLS["chirps_daily"].format(year=year), target.with_name(f"global_{year}.nc"))
        crop_netcdf(
            whole,
            target,
            Box(local.north + 1, local.south - 1, local.west - 1, local.east + 1),
            "latitude",
            "longitude",
        )
    # NOAA OISST v2.1 daily, 30S-30N (ocean indices N6 and the E7 field).
    tropics = Box(30.5, -30.5, 0, 360, 0.25)
    for year in years:
        target = root / "raw" / "oisst" / f"sst_{year}_tropics.nc"
        if target.exists():
            continue
        whole = fetch(URLS["oisst_daily"].format(year=year), target.with_name(f"global_{year}.nc"))
        crop_netcdf(whole, target, tropics, "lat", "lon")
    # NOAA interpolated daily OLR (Kelvin and Rossby filtering, N2).
    fetch(URLS["olr_daily"], root / "raw" / "olr" / "olr.day.mean.nc")
    # Indices (N2, N3, P2).
    for key, name in [
        ("rmm", "rmm.txt"),
        ("aao_daily", "aao_daily.csv"),
        ("nao_daily", "nao_daily.csv"),
        ("qbo_u30", "qbo_u30.txt"),
        ("soi", "soi.txt"),
    ]:
        target = root / "raw" / "indices" / name
        if target.exists() and not args.refresh:
            continue
        if target.exists():
            target.unlink()
        fetch(URLS[key], target)
    # IBTrACS for the South and North Indian Ocean (N5).
    for basin in ("SI", "NI"):
        target = root / "raw" / "ibtracs" / f"ibtracs_{basin}.csv"
        if target.exists() and args.refresh:
            target.unlink()
        fetch(URLS["ibtracs"].format(basin=basin), target)
    log.info(
        "Observed data complete. BSISO (N2, 89-90) is not downloaded: put a daily CSV "
        "(date,bsiso1,bsiso2) at raw/indices/bsiso.csv if you have one."
    )


# ---------------------------------------------------------------- static


def static_command(args: argparse.Namespace, cat: dict[str, Any], root: Path) -> None:
    folder = root / "raw" / "static"
    etopo = folder / "etopo_icpac.nc"
    if not etopo.exists():
        whole = fetch(URLS["etopo"], folder / "etopo_global.nc", timeout=3600)
        local = Box.of(cat["domain"]["local_box"])
        crop_netcdf(
            whole,
            etopo,
            Box(local.north + 1, local.south - 1, local.west - 1, local.east + 1),
            "lat",
            "lon",
        )
    for key in ("ne_coastline", "ne_lakes"):
        archive = fetch(URLS[key], folder / f"{key}.zip")
        out = folder / key
        if not out.exists():
            with zipfile.ZipFile(archive) as z:
                z.extractall(out)
    log.info("Static data complete in %s", folder)


# ---------------------------------------------------------------- optional


def optional_command(args: argparse.Namespace, cat: dict[str, Any], root: Path) -> None:
    """Optional sources; each needs its own account. Variable names follow the Copernicus
    catalogues at the time of writing: check them on the dataset page if a request fails."""
    cases = read_cases(root / "cases.csv")
    years = [str(y) for y in observed_years(cat, cases)]
    local = Box.of(cat["domain"]["local_box"])
    folder = root / "raw" / "optional"
    folder.mkdir(parents=True, exist_ok=True)
    months = [f"{m:02d}" for m in range(1, 13)]
    days = [f"{d:02d}" for d in range(1, 32)]
    for what in args.what:
        if what == "oras5":  # N3 96: Indian Ocean heat content, monthly
            import cdsapi

            target = folder / "oras5_heat_content.zip"
            if not target.exists():
                cdsapi.Client().retrieve(
                    "reanalysis-oras5",
                    {
                        "product_type": ["consolidated"],
                        "vertical_resolution": "single_level",
                        "variable": ["ocean_heat_content_for_the_upper_300m"],
                        "year": years,
                        "month": months,
                    },
                    str(target),
                )
        elif what == "era5-lake":  # N6 116: Lake Victoria temperature
            import cdsapi

            for year in years:
                target = folder / f"era5_lake_{year}.nc"
                if not target.exists():
                    cdsapi.Client().retrieve(
                        "reanalysis-era5-single-levels",
                        {
                            "product_type": ["reanalysis"],
                            "variable": ["lake_mix_layer_temperature"],
                            "year": [year],
                            "month": months,
                            "day": days,
                            "time": ["00:00"],
                            "area": [1.5, 31, -3.5, 35],
                            "data_format": "netcdf",
                        },
                        str(target),
                    )
        elif what == "era5-soil":  # L3 46 fallback when sm20 is not in S2S
            import cdsapi

            for year in years:
                target = folder / f"era5land_swvl1_{year}.nc"
                if not target.exists():
                    cdsapi.Client().retrieve(
                        "reanalysis-era5-land",
                        {
                            "variable": ["volumetric_soil_water_layer_1"],
                            "year": [year],
                            "month": months,
                            "day": days,
                            "time": ["00:00"],
                            "area": [local.north, local.west, local.south, local.east],
                            "data_format": "netcdf",
                        },
                        str(target),
                    )
        elif what == "cams":  # N3 98: dust AOD (CAMS EAC4 starts in 2003)
            import cdsapi

            url = "https://ads.atmosphere.copernicus.eu/api"
            for year in years:
                target = folder / f"cams_dust_{year}.nc"
                if not target.exists():
                    cdsapi.Client(url=url).retrieve(
                        "cams-global-reanalysis-eac4",
                        {
                            "variable": ["dust_aerosol_optical_depth_550nm"],
                            "date": [f"{year}-01-01/{year}-12-31"],
                            "time": ["12:00"],
                            "area": [local.north, local.west, local.south, local.east],
                            "data_format": "netcdf",
                        },
                        str(target),
                    )
        elif what == "ndvi":  # L3 47: MODIS 0.05 degree 16-day NDVI
            import earthaccess

            earthaccess.login(strategy="netrc")
            results = earthaccess.search_data(
                short_name="MOD13C1", temporal=(f"{years[0]}-01-01", f"{years[-1]}-12-31")
            )
            earthaccess.download(results, str(folder / "ndvi"))
        else:
            raise SystemExit(f"Unknown optional source {what}")
    log.info("Optional data complete in %s", folder)


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", help="output folder (default $ICPAC_PREDICTORS_ROOT)")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    cases = sub.add_parser("cases", help="write cases.csv")
    cases.add_argument("--from-cca", help="the refit's CCA_DIAGNOSTIC folder (exact cases)")
    cases.add_argument("--from-dir", help="folder of ecmwf_s2s_mvYYYYMMDD_* files")
    cases.add_argument("--model-year", type=int, default=2025)
    cases.add_argument("--years", default="2005-2024", help="hindcast years, e.g. 2005-2024")

    for name in ("probe-s2s", "s2s"):
        p = sub.add_parser(name)
        p.add_argument("--client", choices=["ecmwfapi", "mars"], default="ecmwfapi")
        if name == "s2s":
            p.add_argument(
                "--workers", type=int, default=3, help="parallel requests (ECMWF allows few)"
            )
            p.add_argument("--inits", nargs="*", help="only these model-version dates (YYYY-MM-DD)")
            p.add_argument("--dry-run", action="store_true")

    od = sub.add_parser("probe-opendata")
    od.add_argument("--opendata-source", default="ecmwf", help="ecmwf, azure or aws")

    ob = sub.add_parser("observed")
    ob.add_argument("--refresh", action="store_true", help="fetch the index files again")

    sub.add_parser("static")

    op = sub.add_parser("optional")
    op.add_argument(
        "--what",
        nargs="+",
        required=True,
        choices=["oras5", "era5-lake", "era5-soil", "cams", "ndvi"],
    )

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    root = data_root(args.root)
    (root / "logs").mkdir(exist_ok=True)
    import logging

    handler = logging.FileHandler(root / "logs" / "download.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    cat = catalogue()
    commands = {
        "cases": cases_command,
        "probe-s2s": probe_s2s_command,
        "probe-opendata": probe_opendata_command,
        "s2s": s2s_command,
        "observed": observed_command,
        "static": static_command,
        "optional": optional_command,
    }
    commands[args.command](args, cat, root)


if __name__ == "__main__":
    main()
