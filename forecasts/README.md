# ECMWF forecast input (FORECAST_INPUT_ROOT)

The weekly cycle stores the ECMWF Open Data ensemble it downloads here (the default is
`data/forecasts`; point `FORECAST_INPUT_ROOT` elsewhere). Supplied ECMWF files can also be
placed here as `ecmwf_s2s_tp_<YYYY-MM-DD>.nc` and, for Atmos37 models,
`ecmwf_s2s_pl_<YYYY-MM-DD>.nc`, in the format of
[docs/forecast_input_format.md](../docs/forecast_input_format.md). Data files in this
directory are ignored by Git: ECMWF data never belong in the repository.
