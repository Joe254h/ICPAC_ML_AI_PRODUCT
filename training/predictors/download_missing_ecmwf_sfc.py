"""Download the missing ECMWF S2S reforecast surface fields (CAPE, SKT, TCW, SM20) for the
case dates the audit lists, and nothing else.

    # 1. see what it would do (no download)
    python download_missing_ecmwf_sfc.py --dry-run
    # 2. try two dates first
    python download_missing_ecmwf_sfc.py --limit 2
    # 3. everything, in the background on the login node (compute nodes have no internet)
    nohup python download_missing_ecmwf_sfc.py > logs/ecmwf_sfc_download.log 2>&1 &

The case dates are the ECMWF model-version dates of the total-precipitation files already on
disk (the audit's "dates found for ecmwf_tp"), read from <audit>/missing_ecmwf_*.txt. One
request per date and member type (control "cf", perturbed "pf") fetches all four
parameters, every hindcast year and the Week-2 steps, over the ICPAC box at 1.5 degrees, the
grid of the existing S2S files. A file already present and readable is skipped, so the
script can be stopped and restarted at any time. Needs ~/.ecmwfapirc (ECMWF Web API key).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import time
from datetime import date, datetime
from pathlib import Path

#: S2S parameter codes (ECMWF S2S catalogue, surface, instantaneous).
PARAMS = {"cape": "59", "skt": "235", "tcw": "136", "sm20": "228086"}
AREA = "25/19/-15/54"  # N/W/S/E: the 11 ICPAC member states with a margin
GRID = "1.5/1.5"
STEPS = "168/to/336/by/24"  # days 8 to 14, daily, as the Week-2 predictors use them
MEMBERS = "1/to/10"


def hindcast_dates(model_date: date, first: int, last: int) -> str:
    """The same day and month in every hindcast year (29 February falls back to the 28th)."""
    out = []
    for y in range(first, last + 1):
        try:
            out.append(model_date.replace(year=y))
        except ValueError:
            out.append(model_date.replace(year=y, day=28))
    return "/".join(d.isoformat() for d in out)


def readable(path: Path) -> bool:
    """A finished GRIB file: not empty and ends with the GRIB end marker."""
    try:
        if path.stat().st_size < 1000:
            return False
        with open(path, "rb") as fh:
            fh.seek(-4, os.SEEK_END)
            return fh.read(4) == b"7777"
    except OSError:
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--audit", help="audit folder (default: newest results/data_audit_*)")
    ap.add_argument("--out", default="/scratch/njoel/s2s_master_data/raw/ecmwf/predictors_245/sfc_cape_skt_tcw_sm20")
    ap.add_argument("--first-year", type=int, default=2005)
    ap.add_argument("--last-year", type=int, default=2024)
    ap.add_argument("--params", nargs="*", default=list(PARAMS), choices=list(PARAMS))
    ap.add_argument("--limit", type=int, help="only the first N dates (a test)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    audit = Path(args.audit or sorted(glob.glob("/scratch/njoel/results/data_audit_*"))[-1])
    wanted: set[date] = set()
    for name in args.params:
        f = audit / f"missing_ecmwf_{name}.txt"
        if f.is_file():
            wanted |= {date.fromisoformat(s.strip()) for s in f.read_text().split() if s.strip()}
    dates = sorted(wanted)[: args.limit] if args.limit else sorted(wanted)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Audit {audit}: {len(wanted)} dates missing at least one of {', '.join(args.params)}; "
          f"doing {len(dates)}. Output {out}", flush=True)

    server = None
    if not args.dry_run:
        from ecmwfapi import ECMWFDataServer

        server = ECMWFDataServer()
    done = failed = skipped = 0
    for i, d in enumerate(dates, 1):
        for kind in ("cf", "pf"):
            target = out / f"ecmwf_s2s_sfc_{'_'.join(args.params)}_{d:%Y%m%d}_{kind}.grib"
            if readable(target):
                skipped += 1
                continue
            request = {
                "class": "s2", "dataset": "s2s", "expver": "prod", "model": "glob",
                "origin": "ecmf", "stream": "enfh", "levtype": "sfc", "time": "00:00:00",
                "date": d.isoformat(),
                "hdate": hindcast_dates(d, args.first_year, args.last_year),
                "param": "/".join(PARAMS[p] for p in args.params),
                "step": STEPS, "type": kind, "area": AREA, "grid": GRID,
                "target": str(target) + ".part",
            }
            if kind == "pf":
                request["number"] = MEMBERS
            print(f"[{i}/{len(dates)}] {d} {kind} -> {target.name}", flush=True)
            if args.dry_run:
                print(json.dumps(request), flush=True)
                continue
            for attempt in range(1, 4):
                try:
                    server.retrieve(request)
                    Path(request["target"]).rename(target)
                    done += 1
                    break
                except Exception as exc:
                    print(f"  attempt {attempt} failed: {exc}", flush=True)
                    time.sleep(60 * attempt)
            else:
                failed += 1
                with open(out / "FAILED.txt", "a") as fh:
                    fh.write(f"{datetime.now():%Y-%m-%d %H:%M} {d} {kind}\n")
    print(f"Finished: {done} downloaded, {skipped} already present, {failed} failed "
          f"(listed in {out / 'FAILED.txt'}). Rerun the audit to confirm.", flush=True)


if __name__ == "__main__":
    main()
