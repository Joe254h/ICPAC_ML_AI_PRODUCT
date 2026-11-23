"""Write an ECDS manifest for the missing S2S reforecast fields, in the format of
code/icpac_resume_missing.py (dataset s2s-reforecasts): one request per model date and
member type, with every variable, hindcast year and Week-2 lead time of the set in it.

Sets (--set):
    sfc      CAPE, skin temperature, total column water, soil moisture 0-20 cm (daily means)
    sfc2     mean sea-level pressure, surface pressure, 2 m temperature, 2 m dewpoint
             (daily means)
    cp       convective precipitation (accumulated: lead times 168 and 336)
    pl925    u, v, q, t, geopotential height at 925 hPa (00 UTC each day of Week 2)
    omega    vertical velocity at 925, 850, 700, 500, 300 and 200 hPa (00 UTC each day)

    python add_missing_to_manifest.py --set sfc2 --test-all       # one request per variable
    python add_missing_to_manifest.py --set pl925                  # every date, control
    python add_missing_to_manifest.py --set pl925 --perturbed --member-key number

It writes a NEW manifest and never edits download_manifest.jsonl. The surface request keys
copy the validated pilot line. ECDS names for the new sets are best guesses; --test-all
writes one single-variable request per field so any wrong name fails on its own and the
log says which. Pressure-level request keys can be changed with --level-type and
--level-key if the first test says so.
"""

from __future__ import annotations

import argparse
import glob
import json
from datetime import date
from pathlib import Path

ROOT = Path("/scratch/njoel/s2s_master_data")
DAILY_MEANS = ["168-192", "192-216", "216-240", "240-264", "264-288", "288-312", "312-336"]
DAILY_00UTC = [str(h) for h in range(168, 337, 24)]
#: set -> (level type, levels, lead times, {short name: ECDS variable name})
SETS = {
    "sfc": ("single_level", [], DAILY_MEANS, {
        "cape": "convective_available_potential_energy",
        "skt": "skin_temperature",
        "tcw": "total_column_water",
        "sm20": "soil_moisture_top_20_cm",
    }),
    "sfc2": ("single_level", [], DAILY_MEANS, {
        "msl": "mean_sea_level_pressure",
        "sp": "surface_pressure",
        "t2m": "2m_temperature",
        "d2m": "2m_dewpoint_temperature",
    }),
    "cp": ("single_level", [], ["168", "336"], {
        "cp": "convective_precipitation",
    }),
    "pl925": ("pressure_level", ["925"], DAILY_00UTC, {
        "u": "u_component_of_wind",
        "v": "v_component_of_wind",
        "q": "specific_humidity",
        "t": "temperature",
        "gh": "geopotential_height",
    }),
    "omega": ("pressure_level", ["925", "850", "700", "500", "300", "200"], DAILY_00UTC, {
        "w": "vertical_velocity",
    }),
}


def case_dates(audit: Path) -> list[date]:
    """Every ECMWF model date in the audit (the union of its missing_ecmwf_* lists)."""
    dates: set[date] = set()
    for f in audit.glob("missing_ecmwf_*.txt"):
        dates |= {date.fromisoformat(s) for s in f.read_text().split() if s.strip()}
    return sorted(dates)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", default="sfc", choices=list(SETS))
    ap.add_argument("--audit", help="audit folder (default: newest results/data_audit_*)")
    ap.add_argument("--out", help="manifest to write (default metadata/manifest_<set>.jsonl)")
    ap.add_argument("--variables", nargs="*", help="only these short names of the set")
    ap.add_argument("--first-year", type=int, default=2005)
    ap.add_argument("--last-year", type=int, default=2024)
    ap.add_argument("--perturbed", action="store_true", help="add perturbed-member requests")
    ap.add_argument("--member-key", default="",
                    help="request key listing members 1-10 for perturbed requests (e.g. number)")
    ap.add_argument("--level-type", help="override the level_type value (pressure sets)")
    ap.add_argument("--level-key", default="pressure_level", help="request key for the levels")
    ap.add_argument("--test", action="store_true", help="one date, control, first variable")
    ap.add_argument("--test-all", action="store_true",
                    help="one date, control, one request per variable (checks each ECDS name)")
    ap.add_argument("--test-variable", help="one date, control, this short name only")
    args = ap.parse_args()

    level_type, levels, leadtimes, names = SETS[args.set]
    level_type = args.level_type or level_type
    out = args.out or str(ROOT / "metadata" / f"manifest_{args.set}.jsonl")
    audit = Path(args.audit or sorted(glob.glob("/scratch/njoel/results/data_audit_*"))[-1])
    dates = case_dates(audit)
    chosen = args.variables or list(names)
    unknown = [v for v in chosen + ([args.test_variable] if args.test_variable else [])
               if v not in names]
    if unknown:
        ap.error(f"{unknown} not in set {args.set}: {list(names)}")
    kinds = ["control_forecast"] + (["perturbed_forecast"] if args.perturbed else [])
    groups = [chosen]
    testing = args.test or args.test_all or args.test_variable
    if testing:
        dates = dates[:1]
        kinds = ["perturbed_forecast"] if args.perturbed else ["control_forecast"]
        groups = ([[args.test_variable]] if args.test_variable
                  else [[v] for v in chosen] if args.test_all else [chosen[:1]])

    years = [str(y) for y in range(args.first_year, args.last_year + 1)]
    lines = []
    for d in dates:
        for kind in kinds:
            for group in groups:
                request = {
                    "origin": "ecmwf",
                    "forecast_type": kind,
                    "level_type": level_type,
                    "variable": [names[v] for v in group],
                    "year": f"{d:%Y}", "month": f"{d:%m}", "day": f"{d:%d}",
                    "hyear": years, "hmonth": [f"{d:%m}"],
                    "hday": [f"{min(d.day, 28) if d.month == 2 else d.day:02d}"],
                    "leadtime_hour": leadtimes,
                    "time": "00:00", "grid": "1.5/1.5", "data_format": "grib",
                }
                if levels:
                    request[args.level_key] = levels
                if kind == "perturbed_forecast" and args.member_key:
                    request[args.member_key] = [str(n) for n in range(1, 11)]
                short = "cf" if kind == "control_forecast" else "pf"
                tag = "_".join(group)
                if args.set == "sfc":  # the names of the files already downloaded
                    target = (f"raw/ecmwf/predictors_245/sfc_{tag}/{tag}_{short}_"
                              f"model{d:%Y%m%d}_hdates{args.first_year}-{args.last_year}"
                              "_step168-336.grib")
                else:
                    target = (f"raw/ecmwf/predictors_245/{args.set}_{tag}/{tag}_{short}_"
                              f"model{d:%Y%m%d}_hdates{args.first_year}-{args.last_year}.grib")
                lines.append(json.dumps({"dataset": "s2s-reforecasts", "request": request,
                                         "target": target}))
    Path(out).write_text("\n".join(lines) + "\n")
    print(f"{len(lines)} requests, set {args.set}, {len(dates)} dates, "
          f"{', '.join(kinds)} -> {out}\nFirst request:\n{lines[0] if lines else '-'}")


if __name__ == "__main__":
    main()
