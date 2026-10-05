# Observation providers

CHIRPS, TAMSAT and RFE2 currently use deterministic synthetic daily grids. They share ObservationProvider and canonical precipitation(time,latitude,longitude), mm/day units and source/version/QC/provenance metadata. The local NetCDF interface rejects missing files and unexpected units; it does not silently substitute demo data.

All scientific input files must match the versioned domain/grid and expected period. A real source adapter must declare file variable mappings, rainfall units, calendar, coordinate normalization, accumulation convention, version and latency. Source changes require adapter and QC tests. Forecast arrival and observation arrival are separate events; observations trigger verification only when the matching seven-day period is available.

IMERG, ARC2 and station adapters remain explicit integration placeholders. No operational feeds are contacted by the shipped demonstration.
