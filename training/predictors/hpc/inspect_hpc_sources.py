"""Read-only inventory of what the 245-predictor build will read on the ICPAC HPC.

    python inspect_hpc_sources.py > logs/inspect_sources.txt 2>&1

It never changes a file. It prints:
  1. the registry rows (feature id, name, group, kind, dependencies, Stage 3 status);
  2. the Stage 2 archive (columns, one pressure and one rainfall store: dimensions, levels,
     steps, members, latitude/longitude extent);
  3. one file per predictors_245 folder (parameters, levels, steps, members, extent);
  4. the ERA5 / NOAA / index files: time coverage and extent;
  5. where the current model's training cases, splits and results are.
"""

from __future__ import annotations

import csv
import glob
import os
import subprocess
from pathlib import Path

ROOT = Path(os.environ.get("S2S_ROOT", "/scratch/njoel/s2s_master_data"))
EXP = ROOT / "experiments/ICPAC_WEEK2_PHYSICS_245_V1"
AUDIT = EXP / "audit"


def head(title: str) -> None:
    print(f"\n==== {title}")


def sh(cmd: list[str], limit: int = 12) -> None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("   (", cmd[0], "failed:", exc, ")")
        return
    for line in out.splitlines()[:limit]:
        print("  ", line)


def extent(ds) -> str:
    parts = []
    for name in ("latitude", "lat", "longitude", "lon"):
        if name in ds.coords:
            v = ds[name].values
            parts.append(f"{name} {float(v.min()):g}..{float(v.max()):g} ({v.size})")
    return ", ".join(parts)


def describe_store(path: str) -> None:
    import xarray as xr

    try:
        engine = "zarr" if path.rstrip("/").endswith(".zarr") else None
        with xr.open_dataset(path, engine=engine) as ds:
            print("   file:", path)
            print("   dims:", dict(ds.sizes))
            print("   vars:", list(ds.data_vars)[:15])
            print("   extent:", extent(ds))
            for c in (
                "level",
                "isobaricInhPa",
                "pressure_level",
                "step",
                "number",
                "member",
                "time",
                "valid_time",
                "hdate",
                "year",
            ):
                if c in ds.coords:
                    v = ds[c].values
                    shown = v if v.size <= 12 else list(v[:4]) + ["..."] + list(v[-2:])
                    print(f"   {c}: {shown}")
    except Exception as exc:  # noqa: BLE001 - an inventory reports, never stops
        print("   could not open", path, type(exc).__name__, str(exc)[:150])


def describe_grib(path: str) -> None:
    print("   file:", path)
    sh(["grib_ls", "-p", "shortName,typeOfLevel,level,stepRange,number,dataType", path], 0)
    out = subprocess.run(
        ["grib_ls", "-p", "shortName,level,stepRange,number", path],
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    rows = [
        r.split()
        for r in out
        if r and not r.startswith(("shortName", path)) and len(r.split()) == 4
    ]
    for i, label in enumerate(("params", "levels", "steps", "members")):
        print(f"   {label}: {sorted({r[i] for r in rows})[:16]}")
    sh(
        [
            "grib_get",
            "-p",
            "latitudeOfFirstGridPointInDegrees,latitudeOfLastGridPointInDegrees,"
            "longitudeOfFirstGridPointInDegrees,longitudeOfLastGridPointInDegrees,Ni,Nj",
            path,
        ],
        1,
    )


def main() -> None:
    head("1. Registry rows (Stage 3 readiness)")
    readiness = AUDIT / "stage3/feature_readiness_245.csv"
    with readiness.open(newline="") as f:
        for r in csv.DictReader(f):
            print(
                f"{r['feature_id']},{r['feature_name']},{r['feature_group']},{r['feature_kind']},"
                f"{r['stage3_status']},{r['dependency_tokens']}"
            )

    head("2. Stage 2 archive")
    cov = AUDIT / "stage2/dataset_coverage.csv"
    with cov.open(newline="") as f:
        rows = list(csv.DictReader(f))
    print("   columns:", list(rows[0].keys()))
    families: dict[str, list[dict]] = {}
    for r in rows:
        families.setdefault(r["family"], []).append(r)
    for fam, items in families.items():
        print(f"   family {fam}: {len(items)} rows, e.g. {items[0].get('path')}")
    for fam in ("pressure_pf", "tp_pf"):
        if fam in families:
            print(f"  -- {fam}")
            describe_store(families[fam][0]["path"])

    head("3. predictors_245 folders (one file each)")
    for folder in sorted(glob.glob(str(ROOT / "raw/ecmwf/predictors_245/*/"))):
        files = sorted(glob.glob(folder + "*.grib"))
        print(f"  -- {Path(folder).name}: {len(files)} grib files")
        if files:
            describe_grib(files[0])
    ttr = sorted(glob.glob(str(ROOT / "raw/ecmwf/predictors_245/ttr_week2/**/*"), recursive=True))
    print("   ttr_week2 contents:", [p for p in ttr][:8])

    head("4. ERA5 / NOAA / index files")
    for path in sorted(glob.glob(str(ROOT / "raw/era5_cpc_missing12/*/*.nc")))[:1] + [
        str(ROOT / "raw/era5_cpc_missing12/static/era5_vegetation.nc"),
        str(ROOT / "raw/era5_cpc_missing12/noaa_olr/olr.day.mean.nc"),
        str(ROOT / "raw/noaa_oisst_v21/sst.day.mean.2005.nc"),
        str(ROOT / "raw/noaa_oisst_v21/sst.day.mean.2024.nc"),
    ]:
        if Path(path).exists():
            describe_store(path)
    for kind in ("land", "snow"):
        files = sorted(glob.glob(str(ROOT / f"raw/era5_cpc_missing12/{kind}/*.nc")))
        if files:
            print(f"  -- {kind} first file")
            describe_store(files[0])
    for txt in (
        "raw/climate_indices/mjo/bom_rmm_1974_realtime.txt",
        "raw/era5_cpc_missing12/noaa_cpc/soi.txt",
        "raw/era5_cpc_missing12/noaa_cpc/qbo.u50.index.txt",
    ):
        p = ROOT / txt
        if p.exists():
            lines = p.read_text(errors="replace").splitlines()
            print(f"  -- {txt}: {len(lines)} lines")
            for line in lines[:3] + ["..."] + lines[-2:]:
                print("     ", line[:110])
    print("  -- ecmwf_s2s_rmm:")
    sh(["bash", "-c", f"ls -la {ROOT}/raw/climate_indices/ecmwf_s2s_rmm | head -12"])
    print("  -- indices folder:")
    sh(["bash", "-c", f"find {ROOT}/indices -maxdepth 2 -type f | head -20"], 20)
    print("  -- static folder:")
    sh(["bash", "-c", f"find {ROOT}/static {ROOT}/raw/static -maxdepth 2 | head -20"], 20)
    print("  -- CHIRPS stores (Stage 2 family chirps_ea):")
    for r in families.get("chirps_ea", [])[:1]:
        describe_store(r["path"])

    head("5. Current model: cases, splits, results")
    sh(["bash", "-c", f"ls -d {ROOT}/results/*/ 2>/dev/null | head -20"], 20)
    sh(["bash", "-c", f"find {ROOT}/results/ICPAC_RETRAIN_2005_2025_V1 -maxdepth 2 | head -40"], 40)
    sh(
        [
            "bash",
            "-c",
            f"find {ROOT} -maxdepth 6 \\( -name 'cca_month_*.npz' -o -name '*loyo*' -o -name "
            f"'*fold*' -o -name 'cases.csv' -o -name '*training_table*' -o -name '*feature_matrix*' \\) "
            f"2>/dev/null | head -25",
        ],
        25,
    )


if __name__ == "__main__":
    main()
