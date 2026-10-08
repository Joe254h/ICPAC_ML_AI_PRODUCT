"""Run the weekly operational cycle without the web interface (cron, Azure Container Apps
job, HPC): download the newest ECMWF ensemble from ECMWF Open Data, run the Week-2 forecast
if it has not been run for that initialization, and verify every finished forecast against
CHIRPS. It uses the same database, storage and settings as the API (DATABASE_URL, RUN_ROOT,
FORECAST_INPUT_ROOT, DATA_ROOT, PACKAGE_STORE_CONNECTION).

    python -m scripts.operational_cycle --actor "scheduled cycle"
    python -m scripts.operational_cycle --init-date 2026-10-05 --actor Joe254h
"""

import argparse
import json
from datetime import date

from backend.app.db import Repository
from backend.app.schemas import OperationRequest
from backend.app.services.operations import OperationService
from backend.app.services.platform import Platform

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init-date", type=date.fromisoformat)
    parser.add_argument("--actor", default="scheduled cycle")
    args = parser.parse_args()
    platform = Platform(Repository(), register_descriptors=True)
    record = OperationService(platform).start(
        OperationRequest(action="cycle", initialization=args.init_date, actor=args.actor),
        background=False,
    )
    print(json.dumps(record, indent=2, default=str))
    raise SystemExit(0 if record["status"] == "complete" else 1)
