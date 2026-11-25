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
  and, from files already on the HPC: the predictors_245/ S2S downloads (925 hPa u, v,
  q, t, gh; omega; cape, skt, tcw; msl, sp; cp; t2m, d2m), the Mascarene domain (global
  msl), IVT (derivable), NOAA OISST, BoM RMM, ECMWF S2S RMM forecasts and Natural Earth lakes.
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

MARK2 = "# --- ECMWF S2S downloads in predictors_245/ and other held sources ---"

BLOCK2 = """    # --- ECMWF S2S downloads in predictors_245/ and other held sources ---
    p245 = root / 'raw/ecmwf/predictors_245'
    n_cycles = len(press_cycles)

    def held(tok, status, path, note):
        # Only fills a gap: a source the audit already confirmed is never downgraded.
        if tok not in e or e[tok]['source_status'] == 'NOT_LOCATED':
            setx(tok, status, path, note)

    def s2s(folder, prefix):
        files = sorted((p245 / folder).glob(prefix + '_cf_model*.grib'))
        return files, len({f.name.split('_model')[1][:8] for f in files})

    s2s_sets = {
        'pl925_u_v_q_t_gh': ('u_v_q_t_gh', ['PL:u:925', 'PL:v:925', 'PL:q:925', 'PL:t:925', 'PL:gh:925']),
        'omega_w': ('w', [f'PL:w:{lv}' for lv in (925, 850, 700, 500, 300, 200)]),
        'sfc_cape_skt_tcw_sm20': ('cape_skt_tcw_sm20', ['SURF:cape', 'SURF:tsk', 'SURF:tcwv']),
        'sfc2_msl_sp': ('msl_sp', ['SURF:mslp', 'SURF:sp', 'GEO:MASCARENE_DOMAIN']),
        'cp_cp': ('cp', ['SURF:cp']),
        't2m_d2m': (None, []),
    }
    for folder, (prefix, toks) in s2s_sets.items():
        if prefix is None:
            continue
        files, cycles = s2s(folder, prefix)
        for tok in toks:
            if not files:
                continue
            note = (f'ECMWF S2S control forecast, {cycles} of {n_cycles} model dates in '
                    f'{folder}/ (file names only; levels, steps and values not decoded)')
            if tok == 'GEO:MASCARENE_DOMAIN':
                note += '; mean sea-level pressure is on the global grid, so the SW Indian Ocean is covered'
            held(tok, 'SOURCE_FOUND_NEEDS_VALIDATION' if cycles >= n_cycles else 'PARTIAL_COVERAGE',
                 files[0], note)
    for var, tok in (('t2m', 'SURF:t2m'), ('d2m', 'SURF:d2m')):
        files, cycles = s2s('t2m_d2m', f'{var}_{var}')
        if files:
            held(tok, 'SOURCE_FOUND_NEEDS_VALIDATION' if cycles >= n_cycles else 'PARTIAL_COVERAGE',
                 files[0], f'ECMWF S2S {var}, {cycles} of {n_cycles} model dates in t2m_d2m/')
    # IVT from u, v, q at 925/850/700/500/200 hPa and surface pressure: a five-level
    # approximation of the full column, which the feature notes must say.
    if all(e.get(t, {}).get('source_status') not in (None, 'NOT_LOCATED')
           for t in ('PL:q:925', 'PL:u:925', 'PL:v:925', 'SURF:sp')):
        held('PROFILE:IVT', 'SOURCE_FOUND_NEEDS_VALIDATION', p245,
             'Derivable: vertical integral of q*u and q*v over 925-200 hPa from 5 levels and '
             'surface pressure; a coarse-column approximation, not a full-profile IVT')
    sst = sorted((root / 'raw/noaa_oisst_v21').glob('sst.day.mean.*.nc'))
    sst_years = {int(f.name.split('.')[3]) for f in sst if f.name.split('.')[3].isdigit()}
    if sst:
        held('OCEAN:SST_GRID', 'SOURCE_FOUND_NEEDS_VALIDATION' if needed_years <= sst_years else 'PARTIAL_COVERAGE',
             sst[0], f'NOAA OISST v2.1 daily, years {min(sst_years)}-{max(sst_years)}; '
             'check that no year file is incomplete (a .part file was seen)')
    rmm = root / 'raw/climate_indices/mjo/bom_rmm_1974_realtime.txt'
    if rmm.is_file():
        held('INDEX:MJO_RMM', 'SOURCE_FOUND_NEEDS_VALIDATION', rmm,
             'BoM real-time RMM1/RMM2 since 1974; as-of lag not verified')
    mjo_fc = root / 'raw/climate_indices/ecmwf_s2s_rmm'
    if mjo_fc.is_dir() and any(mjo_fc.iterdir()):
        held('FORECAST:MJO', 'SOURCE_FOUND_NEEDS_VALIDATION', mjo_fc,
             'ECMWF S2S RMM forecasts: check hindcast coverage 2005-2024 and lead days')
    lakes = root / 'raw/static/natural_earth/ne_10m_lakes.zip'
    if lakes.is_file():
        held('GEO:LAKES', 'SOURCE_FOUND_NEEDS_VALIDATION', lakes,
             'Natural Earth 10 m lake polygons; rasterise to the 0.05 degree grid')
"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.split("\n\n")[1])
        return 2
    path = Path(sys.argv[1])
    text = path.read_text()
    anchor = "    discovery=find_local_sources(root)\n"
    if anchor not in text:
        print("Could not find where to insert (", anchor.strip(), "); nothing changed")
        return 1
    added = [b for m, b in ((MARK, BLOCK), (MARK2, BLOCK2)) if m not in text]
    if not added:
        print("Already patched:", path)
        return 0
    backup = path.with_name(path.name + ".orig")
    if not backup.exists():
        shutil.copy2(path, backup)
    text = text.replace(anchor, "".join(added) + anchor)
    # The gap list read e[t] (the last token of an earlier loop) instead of e[tok], so
    # every row of SOURCE_GAPS_FOR_REVIEW.csv showed that one token's status.
    text = text.replace("        r=e[t]\n", "        r=e[tok]\n")
    path.write_text(text)
    print("Patched", path, f"({len(added)} section(s) added; original kept as", backup.name + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
