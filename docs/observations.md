# Observation providers and local NetCDF ingestion

CHIRPS, TAMSAT and RFE2 initially supply reproducible synthetic daily fields. Their adapters share ObservationProvider.load, metadata, list_available_dates and validate. IMERG, ARC2 and stations remain integration placeholders. No operational feed is contacted.

## Canonical input
NetCDF must contain precipitation(time, latitude, longitude), daily mm/day, with the versioned configured grid/domain. The local adapter renames lat/lon, sorts ascending spatial coordinates, slices valid dates and records canonical metadata. It rejects unsupported units; it does not assume conversions or silently regrid. Configuration must match the intended grid before ingesting a real source. Source-specific readers should supply documented units, calendar, deaccumulation, variable mapping, product version and latency.

## Register a local file
Place files within DATA_ROOT (default data/observations for native Python). In Docker, use the observations/ directory, mounted read-only at /app/observations:

```bash
curl -X POST http://localhost:8000/observations/register \
  -H 'Content-Type: application/json' \
  -d '{"source":"CHIRPS","path":"/app/observations/chirps_daily.nc","actor":"Forecaster"}'
```

Registration opens the file, performs canonical QC, stores its SHA256 and availability, and invalidates cached analysis. The selected source now uses this file across monitoring and verification. Other sources retain their configured synthetic fixtures. Registrations survive restarts. A missing or changed file causes an explicit error; re-register a changed file after QC. Forecasts and country masks remain demonstration inputs even when observations are local.

GET /observations/{source} returns the active source metadata; /availability returns its dates. If another comparison source is missing, its comparison is marked unavailable. A failure in the selected verification source blocks that calculation.

Forecast arrival and observation arrival are separate events. Run `python -m scripts.run_pipeline --trigger observation --observation CHIRPS` once the matching Days 8–14 period exists. Forecast and observation state files are independent. State advances only after successful processing; an exclusive pipeline lock protects native event execution.
