"""Read-only completeness audit of the predictor datasets on the HPC, before any download.

    python audit_hpc_data.py                         # fast: dates from file names
    python audit_hpc_data.py --deep                  # also open files: time axis, members,
                                                     # steps, levels, variables (slower)
    python audit_hpc_data.py --root /scratch/njoel --start 2005-01-01 --end 2025-12-31

It never writes outside --out and never deletes, moves or downloads anything. For each
dataset it finds the files (by name and folder), reads the dates they cover, compares them
with the dates expected, and writes:

    <out>/SUMMARY.txt          one line per dataset: files, size, span, expected, missing
    <out>/summary.csv          the same as a table
    <out>/missing_<name>.txt   every missing date (or case), one per line
    <out>/folders.csv          which folders each dataset was found in (check the matching)
    <out>/deep_<name>.csv      with --deep: per file variables, time range, members, steps,
                               levels, and whether the file could be opened at all

ECMWF fields are reforecast cases, not calendar days: their expected dates are the case
dates found for total precipitation (tp), the most complete ECMWF variable, unless
--cases points to a file of dates (one YYYY-MM-DD per line).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

#: name -> (frequency, words any of which must appear in the path, words that must also
#: appear (any of), words that exclude the path). Words are matched as whole tokens of the
#: lower-cased path split on anything that is not a letter or digit.
DATASETS: dict[str, tuple[str, set[str], set[str], set[str]]] = {
    "ecmwf_tp": ("cases", {"tp", "tprate", "precip", "precipitation"}, {"ecmwf", "s2s", "ifs", "enfo", "reforecast", "hindcast"}, {"chirps", "imerg", "tamsat", "era5", "merra"}),
    "ecmwf_cape": ("cases", {"cape", "mucape"}, set(), {"era5", "merra"}),
    "ecmwf_skt": ("cases", {"skt", "skin"}, set(), {"era5", "merra", "land"}),
    "ecmwf_tcw": ("cases", {"tcw", "tcwv"}, set(), {"era5", "merra"}),
    "ecmwf_sm20": ("cases", {"sm20", "sm100", "swvl1", "swvl2", "sm"}, {"ecmwf", "s2s", "ifs", "reforecast", "hindcast"}, {"era5", "merra", "land"}),
    "ecmwf_pressure": ("cases", {"gh", "z500", "u", "v", "q", "t", "pressure", "pl", "plev", "pressure_levels"}, {"ecmwf", "s2s", "ifs", "reforecast", "hindcast"}, {"era5", "merra", "chirps"}),
    "oisst": ("daily", {"oisst", "sst"}, set(), {"ecmwf", "s2s", "era5"}),
    "era5_land": ("daily", {"era5land"}, set(), set()),
    "era5_atmos": ("daily", {"era5"}, set(), {"era5land", "land"}),
    "mjo_rmm": ("index", {"rmm", "mjo"}, set(), set()),
    "chirps": ("daily", {"chirps", "chirps3"}, set(), set()),
    "modis_ndvi": ("16day", {"ndvi", "evi", "mod13", "mod13c1", "mod13a2", "myd13"}, set(), set()),
    "modis_landcover": ("yearly", {"mcd12", "mcd12c1", "landcover"}, set(), set()),
    "merra2": ("daily", {"merra", "merra2"}, set(), set()),
    "noaa_olr": ("daily", {"olr"}, set(), set()),
    "ibtracs": ("index", {"ibtracs"}, set(), set()),
    "dmi_roni": ("index", {"dmi", "iod", "roni", "oni", "nino34", "enso"}, set(), set()),
    "tamsat": ("daily", {"tamsat"}, set(), set()),
    "imerg": ("daily", {"imerg", "gpm"}, set(), set()),
    "gefs": ("cases", {"gefs"}, set(), set()),
    "cnrm": ("cases", {"cnrm", "meteofrance"}, set(), set()),
}
#: Folders never searched: environments, code, logs, other projects.
SKIP = {"envs", "pkgs", "__pycache__", "code", "logs", ".git", "node_modules", "rl_thesis",
        "rl_thesis_pre_final_20260819", "gemma-4-africa-reasoning", "organized_root_logs"}
DATA_EXT = (".nc", ".nc4", ".grib", ".grib2", ".grb", ".grb2", ".tif", ".tiff", ".hdf",
            ".h5", ".he5", ".csv", ".txt", ".dat", ".zarr", ".npz", ".npy", ".parquet",
            ".gz", ".zip", ".bz2", ".nc.gz", ".tif.gz")

D8 = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)")
DOY = re.compile(r"(?<!\d)A?((?:19|20)\d{2})(\d{3})(?!\d)")  # MODIS A2005001
YM = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])(?!\d)")
Y = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def tokens(path: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", path.lower()) if t}


def classify(path: str) -> list[str]:
    toks = tokens(path)
    out = []
    for name, (_, words, also, exclude) in DATASETS.items():
        if toks & words and (not also or toks & also) and not toks & exclude:
            out.append(name)
    return out


def dates_in_name(name: str, start: date, end: date) -> tuple[set[date], str]:
    """The days a file's own name says it covers, and how it was read."""
    found = set()
    for m in D8.finditer(name):
        try:
            found.add(date(int(m[1]), int(m[2]), int(m[3])))
        except ValueError:
            pass
    if found:
        return found, "day"
    if (m := DOY.search(name)) and 1 <= int(m[2]) <= 366:
        return {date(int(m[1]), 1, 1) + timedelta(days=int(m[2]) - 1)}, "day-of-year"
    if m := YM.search(name):
        y, mo = int(m[1]), int(m[2])
        first = date(y, mo, 1)
        last = (date(y + (mo == 12), mo % 12 + 1, 1)) - timedelta(days=1)
        return set(days(max(first, start), min(last, end))), "month"
    years = {int(m[1]) for m in Y.finditer(name)}
    if len(years) == 1:
        y = years.pop()
        return set(days(max(date(y, 1, 1), start), min(date(y, 12, 31), end))), "year"
    return set(), "none"


def days(a: date, b: date):
    while a <= b:
        yield a
        a += timedelta(days=1)


def expected(freq: str, start: date, end: date, cases: set[date]) -> set[date]:
    if freq == "daily":
        return set(days(start, end))
    if freq == "16day":  # MODIS composites start on day 1, 17, 33... of each year
        return {d for d in days(start, end) if (d.timetuple().tm_yday - 1) % 16 == 0}
    if freq == "yearly":
        return {date(y, 1, 1) for y in range(start.year, end.year + 1)}
    if freq == "cases":
        return {d for d in cases if start <= d <= end}
    return set()  # index files: checked deep, by their time axis


def walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP and not d.startswith(".")]
        zarrs = [d for d in dirnames if d.endswith(".zarr")]
        dirnames[:] = [d for d in dirnames if not d.endswith(".zarr")]
        for d in zarrs:
            yield Path(dirpath) / d
        for f in filenames:
            if f.lower().endswith(DATA_EXT):
                yield Path(dirpath) / f


def size_of(p: Path) -> int:
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    try:
        return p.stat().st_size
    except OSError:
        return 0


def deep_read(p: Path) -> dict:
    """What the file holds: variables, time span, members, steps, levels."""
    info: dict = {"file": str(p), "opened": False}
    try:
        import xarray as xr

        if p.suffix == ".zarr" or p.is_dir():
            ds = xr.open_zarr(p)
        elif p.suffix in (".grib", ".grib2", ".grb", ".grb2"):
            ds = xr.open_dataset(p, engine="cfgrib", backend_kwargs={"indexpath": ""})
        elif p.suffix in (".nc", ".nc4", ".h5", ".he5"):
            ds = xr.open_dataset(p, decode_times=True)
        else:
            return info
        info["opened"] = True
        info["variables"] = " ".join(sorted(map(str, ds.data_vars)))
        for key in ("time", "valid_time", "date", "forecast_reference_time"):
            if key in ds.coords and ds[key].size:
                t = ds[key].values.ravel()
                info["time_first"], info["time_last"], info["times"] = str(t.min())[:10], str(t.max())[:10], int(t.size)
                break
        for key, label in (("number", "members"), ("member", "members"), ("step", "steps"),
                           ("isobaricInhPa", "levels"), ("level", "levels"), ("pressure_level", "levels")):
            if key in ds.coords:
                info[label] = int(ds[key].size)
        ds.close()
    except Exception as exc:  # a damaged or partial download is exactly what we look for
        info["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
    return info


def ranges(sorted_days: list[date]) -> str:
    """2005-01-01..2005-03-04, 2007-06-01 ... (first 8 runs)."""
    runs, out = [], []
    for d in sorted_days:
        if runs and (d - runs[-1][1]).days <= 1:
            runs[-1][1] = d
        else:
            runs.append([d, d])
    for a, b in runs[:8]:
        out.append(str(a) if a == b else f"{a}..{b}")
    return ", ".join(out) + (f" (+{len(runs) - 8} more gaps)" if len(runs) > 8 else "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", action="append", help="folder to search (repeatable); default /scratch/njoel")
    ap.add_argument("--start", default="2005-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--cases", help="file of ECMWF case dates, one YYYY-MM-DD per line")
    ap.add_argument("--deep", action="store_true", help="open every file (needs xarray, cfgrib)")
    ap.add_argument("--only", nargs="*", help="audit only these datasets")
    ap.add_argument("--out", default=f"results/data_audit_{datetime.now():%Y%m%d_%H%M}")
    args = ap.parse_args()
    roots = [Path(r) for r in (args.root or ["/scratch/njoel"])]
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted = set(args.only or DATASETS)

    files: dict[str, list[Path]] = defaultdict(list)
    folders: dict[tuple[str, str], int] = defaultdict(int)
    for root in roots:
        print(f"Searching {root} ...", flush=True)
        for p in walk(root):
            for name in classify(str(p.relative_to(root))):
                if name in wanted:
                    files[name].append(p)
                    folders[(name, str(p.parent))] += 1

    covered: dict[str, set[date]] = {}
    how: dict[str, dict[str, int]] = {}
    for name, paths in files.items():
        got: set[date] = set()
        kinds: dict[str, int] = defaultdict(int)
        for p in paths:
            d, kind = dates_in_name(p.name, start, end)
            if not d:  # yearly folders: 2005/file.nc
                d, kind = dates_in_name(str(p.parent.name), start, end)
            got |= {x for x in d if start <= x <= end}
            kinds[kind] += 1
        covered[name], how[name] = got, kinds

    if args.cases:
        cases = {date.fromisoformat(s.strip()[:10]) for s in open(args.cases) if s.strip()}
        case_source = args.cases
    else:
        cases, case_source = covered.get("ecmwf_tp", set()), "dates found for ecmwf_tp"

    rows = []
    for name, (freq, *_rest) in DATASETS.items():
        if name not in wanted:
            continue
        paths = files.get(name, [])
        exp = expected(freq, start, end, cases)
        got = covered.get(name, set())
        missing = sorted(exp - got)
        size_gb = sum(size_of(p) for p in paths) / 1e9
        row = {
            "dataset": name, "frequency": freq, "files": len(paths), "size_gb": round(size_gb, 2),
            "first": str(min(got)) if got else "", "last": str(max(got)) if got else "",
            "expected": len(exp), "present": len(exp & got) if exp else len(got),
            "missing": len(missing) if exp else "", "dates_from": " ".join(f"{k}:{v}" for k, v in how.get(name, {}).items()),
            "status": ("NOT FOUND" if not paths else "COMPLETE" if exp and not missing
                       else "CHECK DEEP" if not exp else "MISSING DATES"),
        }
        rows.append(row)
        if missing:
            (out / f"missing_{name}.txt").write_text("\n".join(map(str, missing)) + "\n")
        row["gaps"] = ranges(missing) if missing else ""
        if args.deep and paths:
            print(f"Opening {len(paths)} files of {name} ...", flush=True)
            infos = [deep_read(p) for p in sorted(paths)]
            keys = sorted({k for i in infos for k in i})
            with open(out / f"deep_{name}.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=keys)
                w.writeheader()
                w.writerows(infos)
            row["unreadable"] = sum(1 for i in infos if "error" in i)

    fields = ["dataset", "status", "frequency", "files", "size_gb", "first", "last", "expected",
              "present", "missing", "unreadable", "dates_from", "gaps"]
    with open(out / "summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(out / "folders.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["dataset", "folder", "files"])
        for (name, folder), n in sorted(folders.items()):
            w.writerow([name, folder, n])

    lines = [f"Data audit {datetime.now():%Y-%m-%d %H:%M}  period {start}..{end}  roots {', '.join(map(str, roots))}",
             f"ECMWF case dates: {len(cases)} ({case_source})", ""]
    lines.append(f"{'dataset':16s} {'status':14s} {'files':>7s} {'GB':>8s} {'first':>10s}  {'last':>10s} {'expected':>8s} {'missing':>8s}")
    for r in rows:
        lines.append(f"{r['dataset']:16s} {r['status']:14s} {r['files']:>7d} {r['size_gb']:>8.2f} {r['first']:>10s}  {r['last']:>10s} {r['expected']:>8d} {str(r['missing']):>8s}")
        if r["gaps"]:
            lines.append(f"{'':16s} gaps: {r['gaps']}")
        if r.get("unreadable"):
            lines.append(f"{'':16s} unreadable files: {r['unreadable']} (see deep_{r['dataset']}.csv)")
    lines += ["", "Dates are read from file names (dates_from in summary.csv says how). A file named",
              "by year only counts as the whole year: run with --deep to check its time axis.",
              "Check folders.csv: a folder matched to the wrong dataset changes the counts."]
    text = "\n".join(lines)
    (out / "SUMMARY.txt").write_text(text + "\n")
    print("\n" + text + f"\n\nWritten to {out.resolve()}")


if __name__ == "__main__":
    sys.exit(main())
