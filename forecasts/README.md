# ECMWF S2S forecast input (FORECAST_INPUT_ROOT)

Place `ecmwf_s2s_tp_<YYYY-MM-DD>.nc` and, for Atmos37 models, `ecmwf_s2s_pl_<YYYY-MM-DD>.nc`
here (or point `FORECAST_INPUT_ROOT` elsewhere). The format is described in
[docs/forecast_input_format.md](../docs/forecast_input_format.md). Data files in this
directory are ignored by Git: ECMWF archives never belong in the repository.
