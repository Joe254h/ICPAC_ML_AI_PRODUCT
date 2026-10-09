# Architecture

Next.js frontend (`frontend/`) → FastAPI (`backend/app/`) → application services →
independent scientific engine (`climate_engine/`). The frontend computes nothing
scientific: every number, map and label comes from the API.

* **Inputs** (`climate_engine/inputs/`): the ECMWF Open Data ensemble download and the
  CHIRPS daily reader, configured in `config/data_sources.yaml`. Planned sources (TAMSAT,
  RFE 2.0, ARC 2.0, GPM IMERG) are listed there without readers.
* **Forecast** (`climate_engine/operational/`): Week-2 processing on the authoritative
  800 × 700, 0.05° grid; MBC; the Atmos37 feature builder and CatBoost residual model,
  used once its pressure-level inputs exist.
* **Products** (`climate_engine/products/`, `climate_engine/cartography/`): the package of
  each forecast (NetCDF, ICPAC maps, map overlays, country statistics, verification,
  provenance) and the weekly bulletin.
* **Operations** (`backend/app/services/operations.py`): the weekly cycle and its steps run
  as background tasks, one at a time, each recorded with who started it.
* **Records**: SQLAlchemy's repository stores typed records by kind (model, forecast,
  ECMWF input, CHIRPS week, operation, bulletin, approval, chat session, audit) in SQLite or
  PostgreSQL (`DATABASE_URL`). Packages live under `RUN_ROOT` and, with
  `PACKAGE_STORE_CONNECTION`, in Blob Storage.
* **Copilot** (`chatbot/`): grounded answers from the forecast's own values, with a
  self-hosted or compatible language model choosing among approved sentences.

See [operations](operations.md), [operational models](operational_models.md) and
[deployment](deployment.md).
