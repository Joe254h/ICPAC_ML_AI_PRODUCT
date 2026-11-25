"""Teach the Stage 3 readiness audit (audit_features.py) about the predictors fetched by
download_missing_12.py, which live in raw/era5_cpc_missing12/ (a folder the audit does not
search), and fix its gap list.

    python patch_stage3_audit.py /path/to/ICPAC_WEEK2_245_STAGE3_READINESS_20261028/audit_features.py

It keeps a copy as audit_features.py.orig and changes nothing else. Like the rest of the
audit it reads only metadata (variable names and the time coordinate), never field values.

Tokens it resolves (feature):
  SURF:cin (F055)  SURF:pblh (F241)  SURF:cloud_fraction (F243)  SURF:albedo (F244)
  CLOUD:qcloud (F236)  CLOUD:qice (F237)  CLOUD:qrain (F238)  CLOUD:qsnow (F239)
  INDEX:SOI (F167)  INDEX:QBO (F179, F180)
CLOUD:qgraup (F240) stays NOT_LOCATED: neither ERA5 nor the ECMWF model carries graupel.

The ERA5 fields are the reanalysis state at each start date (00 UTC), not forecast
fields, so they are marked SOURCE_FOUND_NEEDS_VALIDATION, never CORE_METADATA_CONFIRMED.
"""

import shutil
import sys
from pathlib import Path

MARK = "# --- ERA5 / NOAA CPC sources fetched by download_missing_12.py ---"

BLOCK = """    # --- ERA5 / NOAA CPC sources fetched by download_missing_12.py ---
    extra = root / 'raw/era5_cpc_missing12'
    needed_years = set(range(min(EXPECTED_YEARS) - 1, max(EXPECTED_YEARS) + 1))  # + lag year

    def era5_coverage(kind, var):
        import glob
        import xarray as xr
        files = sorted(glob.glob(str(extra / kind / '*.nc')))
        years = set()
        for f in files:
            with xr.open_dataset(f) as ds:
                if var not in ds.data_vars:
                    continue
                time = 'valid_time' if 'valid_time' in ds.coords else 'time'
                years |= {int(str(x)[:4]) for x in ds[time].values}
        return [f for f in files], years

    era5 = {
        'SURF:cin': ('single', 'cin'), 'SURF:pblh': ('single', 'blh'),
        'SURF:cloud_fraction': ('single', 'tcc'), 'SURF:albedo': ('single', 'fal'),
        'CLOUD:qcloud': ('pressure', 'clwc'), 'CLOUD:qice': ('pressure', 'ciwc'),
        'CLOUD:qrain': ('pressure', 'crwc'), 'CLOUD:qsnow': ('snow', 'cswc'),
    }
    for tok, (kind, var) in era5.items():
        files, years = era5_coverage(kind, var)
        if files and needed_years <= years:
            setx(tok, 'SOURCE_FOUND_NEEDS_VALIDATION', files[0],
                 f'ERA5 {var}, daily 00 UTC {min(years)}-{max(years)}, 1.5 degree local box: '
                 'reanalysis state at initialization (not a forecast field); numeric QC pending')
        elif files:
            setx(tok, 'PARTIAL_COVERAGE', files[0],
                 f'ERA5 {var}: years {sorted(years)[:1]}..{sorted(years)[-1:]}, '
                 f'missing {sorted(needed_years - years)[:5]}')
    cpc = {'INDEX:SOI': ['soi.txt'], 'INDEX:QBO': ['qbo.u50.index.txt', 'qbo.u30.index.txt']}
    for tok, names in cpc.items():
        paths = [extra / 'noaa_cpc' / n for n in names]
        if all(p.is_file() and p.stat().st_size > 0 for p in paths):
            setx(tok, 'SOURCE_FOUND_NEEDS_VALIDATION', paths[0],
                 'NOAA CPC monthly index text; parsing and publication lag not yet verified')
    setx('CLOUD:qgraup', 'NOT_LOCATED', '',
         'Graupel is in neither ERA5 nor the ECMWF IFS/S2S archive; needs a WRF-type source')
"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.split("\n\n")[1])
        return 2
    path = Path(sys.argv[1])
    text = path.read_text()
    if MARK in text:
        print("Already patched:", path)
        return 0
    anchor = "    discovery=find_local_sources(root)\n"
    if anchor not in text:
        print("Could not find where to insert (", anchor.strip(), "); nothing changed")
        return 1
    shutil.copy2(path, path.with_name(path.name + ".orig"))
    text = text.replace(anchor, BLOCK + anchor)
    # The gap list read e[t] (the last token of an earlier loop) instead of e[tok], so
    # every row of SOURCE_GAPS_FOR_REVIEW.csv showed that one token's status.
    text = text.replace("        r=e[t]\n", "        r=e[tok]\n")
    path.write_text(text)
    print("Patched", path, "(copy kept as", path.name + ".orig)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
