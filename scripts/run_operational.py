"""Run one operational Week-2 forecast and write its product package (HPC or local).

python -m scripts.run_operational --init-date 2026-10-05 \\
    --descriptor config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml \\
    --rainfall /data/ecmwf_s2s_tp_2026-10-05.nc --pressure /data/ecmwf_s2s_pl_2026-10-05.nc \\
    --output /scratch/products/week2

The descriptor's artifacts are verified (checksums, metadata, MBC, schema, smoke test)
before the run; ARTIFACT_ROOT locates them. No database is needed. The package lands in
<output>/<forecast_id>; with --output on the storage the web platform reads as
RUN_ROOT/forecasts, register it there with POST /forecasts/import.

--model-status is the model's registry status (default: the descriptor's declared status).
The platform imports a package only if its label is the status the registry held for the
model when the package was generated (a production label needs a promotion in force then).
"""

import argparse
import json
from datetime import date
from pathlib import Path

from climate_engine.forecasts import ECMWFS2SForecastProvider
from climate_engine.models.descriptor import load_descriptor
from climate_engine.operational.pipeline import grid_from_config, run_forecast
from climate_engine.operational.settings import settings
from climate_engine.products.package import write_package

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init-date", required=True, type=date.fromisoformat)
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--rainfall", required=True)
    parser.add_argument("--pressure")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-status", choices=["experimental", "candidate", "production"])
    args = parser.parse_args()
    cfg = settings()
    grid = grid_from_config(cfg)
    descriptor = load_descriptor(args.descriptor)
    fields, model = descriptor.verified(grid, cfg)
    record = {**fields, "status": args.model_status or descriptor.data["declared_status"]}
    provider = ECMWFS2SForecastProvider(args.rainfall, args.pressure, cfg)
    run = run_forecast(provider, args.init_date.isoformat(), model, grid, cfg, record)
    package = write_package(run, args.output, grid, record)
    print(json.dumps({"forecast_id": run.forecast_id, "package": str(package)}, indent=2))
