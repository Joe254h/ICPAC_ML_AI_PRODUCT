"""Run the operational tasks without the web interface (cron, an Azure Container Apps job,
the HPC), with the same database, storage and settings as the API (DATABASE_URL, RUN_ROOT,
FORECAST_INPUT_ROOT, DATA_ROOT, PACKAGE_STORE_CONNECTION).

Weekly cycle: download the newest ECMWF ensemble from ECMWF Open Data, run the Week-2
forecast if it has not been run for that initialization, verify every finished forecast
against CHIRPS and update the CHIRPS rainfall monitoring.

Daily task, as ICPAC's climate monitoring framework schedules its CHIRPS download: update
the rainfall monitoring (nothing is downloaded when no new dekad is published) and verify
the forecasts CHIRPS now covers.

    python -m scripts.operational_cycle --actor "scheduled cycle"
    python -m scripts.operational_cycle --task daily --actor "daily monitoring"
    python -m scripts.operational_cycle --init-date 2026-10-05 --actor Joe254h

Example crontab (UTC): the daily task at 07:00 and the weekly cycle on Mondays at 09:30,
once ECMWF has published the 00 UTC run.

    0 7 * * *  cd /app && python -m scripts.operational_cycle --task daily
    30 9 * * 1 cd /app && python -m scripts.operational_cycle
"""

import argparse
import json
from datetime import date

from backend.app.db import Repository
from backend.app.schemas import OperationRequest
from backend.app.services.operations import OperationService
from backend.app.services.platform import Platform

TASKS = {"cycle": ["cycle"], "daily": ["update_chirps", "verify_due"]}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=sorted(TASKS), default="cycle")
    parser.add_argument("--init-date", type=date.fromisoformat)
    parser.add_argument("--actor", default="scheduled cycle")
    args = parser.parse_args()
    platform = Platform(Repository(), register_descriptors=True)
    service = OperationService(platform)
    failed = False
    for action in TASKS[args.task]:
        record = service.start(
            OperationRequest(action=action, initialization=args.init_date, actor=args.actor),
            background=False,
        )
        print(json.dumps(record, indent=2, default=str))
        failed |= record["status"] != "complete"
    raise SystemExit(1 if failed else 0)
