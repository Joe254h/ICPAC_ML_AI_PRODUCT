"""Write an ECDS manifest for the missing S2S reforecast surface fields, in the format of
code/icpac_resume_missing.py (dataset s2s-reforecasts), one request per model date and
member type with every variable, hindcast year and Week-2 day in it.

    python add_missing_to_manifest.py --test            # 1 date, control, CAPE only
    python add_missing_to_manifest.py                    # every missing date, control
    python add_missing_to_manifest.py --perturbed        # also the 10 perturbed members

It writes a NEW manifest (default s2s_master_data/metadata/manifest_missing_sfc.jsonl) and
never edits download_manifest.jsonl. Request keys copy the validated pilot line:
origin, forecast_type, level_type, variable, year/month/day, hyear/hmonth/hday,
leadtime_hour, time, grid, data_format.
"""

from __future__ import annotations

import argparse
import glob
import json
from datetime import date
from pathlib import Path

ROOT = Path("/scratch/njoel/s2s_master_data")
#: ECDS variable names. CAPE is the pilot's; check the others with --test-variable first.
VARIABLES = {
    "cape": "convective_available_potential_energy",
    "skt": "skin_temperature",
    "tcw": "total_column_water",
    "sm20": "soil_moisture_top_20_cm",
}
LEADTIMES = ["168-192", "192-216", "216-240", "240-264", "264-288", "288-312", "312-336"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--audit", help="audit folder (default: newest results/data_audit_*)")
    ap.add_argument("--out", default=str(ROOT / "metadata" / "manifest_missing_sfc.jsonl"))
    ap.add_argument("--variables", nargs="*", default=list(VARIABLES), choices=list(VARIABLES))
    ap.add_argument("--first-year", type=int, default=2005)
    ap.add_argument("--last-year", type=int, default=2024)
    ap.add_argument("--perturbed", action="store_true", help="add perturbed-member requests")
    ap.add_argument("--member-key", default="",
                    help="request key listing members 1-10 for perturbed requests (e.g. number)")
    ap.add_argument("--test", action="store_true", help="one date, control, CAPE only")
    ap.add_argument("--test-variable", choices=list(VARIABLES),
                    help="one date, control, this variable only (checks its ECDS name)")
    args = ap.parse_args()

    audit = Path(args.audit or sorted(glob.glob("/scratch/njoel/results/data_audit_*"))[-1])
    dates: set[date] = set()
    for name in VARIABLES:
        f = audit / f"missing_ecmwf_{name}.txt"
        if f.is_file():
            dates |= {date.fromisoformat(s) for s in f.read_text().split() if s.strip()}
    dates_sorted = sorted(dates)
    variables = args.variables
    kinds = ["control_forecast"] + (["perturbed_forecast"] if args.perturbed else [])
    if args.test or args.test_variable:
        dates_sorted = dates_sorted[:1]
        kinds = ["perturbed_forecast"] if args.perturbed else ["control_forecast"]
        variables = [args.test_variable or "cape"]

    years = [str(y) for y in range(args.first_year, args.last_year + 1)]
    lines = []
    for d in dates_sorted:
        for kind in kinds:
            request = {
                "origin": "ecmwf",
                "forecast_type": kind,
                "level_type": "single_level",
                "variable": [VARIABLES[v] for v in variables],
                "year": f"{d:%Y}", "month": f"{d:%m}", "day": f"{d:%d}",
                "hyear": years, "hmonth": [f"{d:%m}"],
                "hday": [f"{min(d.day, 28) if d.month == 2 else d.day:02d}"],
                "leadtime_hour": LEADTIMES,
                "time": "00:00", "grid": "1.5/1.5", "data_format": "grib",
            }
            if kind == "perturbed_forecast" and args.member_key:
                request[args.member_key] = [str(n) for n in range(1, 11)]
            short = "cf" if kind == "control_forecast" else "pf"
            target = (f"raw/ecmwf/predictors_245/sfc_{'_'.join(variables)}/"
                      f"{'_'.join(variables)}_{short}_model{d:%Y%m%d}_"
                      f"hdates{args.first_year}-{args.last_year}_step168-336.grib")
            lines.append(json.dumps({"dataset": "s2s-reforecasts", "request": request,
                                     "target": target}))
    Path(args.out).write_text("\n".join(lines) + "\n")
    print(f"{len(lines)} requests for {len(dates_sorted)} dates ({', '.join(variables)}; "
          f"{', '.join(kinds)}) written to {args.out}\nFirst request:\n{lines[0] if lines else '-'}")


if __name__ == "__main__":
    main()
