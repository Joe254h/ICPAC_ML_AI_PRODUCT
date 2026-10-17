"""Operator-side external adapters. Never invoked from public HTTP requests.

python -m scripts.integration_bridge --task status
python -m scripts.integration_bridge --task acquire --source era5 --date YYYY-MM-DD
python -m scripts.integration_bridge --task hpc-submit --date YYYY-MM-DD --request-id UUID
python -m scripts.integration_bridge --task hpc-poll --request-id UUID

Use the same persistent database and package storage as the website. Credentials
stay in the provider's server configuration. The HPC bridge runs on its SLURM host.
"""

import argparse
import json
from datetime import date

from backend.app.db import Repository
from backend.app.services.external_feeds import ExternalFeeds
from backend.app.services.hpc import HPCService
from backend.app.services.platform import Platform


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task",
        choices=("status", "acquire", "hpc-submit", "hpc-poll", "hpc-collect", "hpc-daily"),
        default="status",
    )
    parser.add_argument("--source", choices=("ifs", "aifs", "s2s", "era5"))
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--request-id")
    parser.add_argument("--actor", default="integration operator")
    args = parser.parse_args()
    platform = Platform(Repository(), register_descriptors=False)
    try:
        if args.task == "status":
            result = {
                "feeds": ExternalFeeds(platform).status(),
                "hpc": HPCService(platform).status(),
            }
        elif args.task == "acquire":
            if not args.source or not args.date:
                parser.error("acquire requires --source and --date")
            result = ExternalFeeds(platform).acquire(args.source, args.date, args.actor)
        elif args.task == "hpc-daily":
            result = HPCService(platform).daily(args.actor)
        elif args.task == "hpc-submit":
            if not args.date or not args.request_id:
                parser.error("hpc-submit requires --date and --request-id")
            result = HPCService(platform).submit(args.request_id, args.date, args.actor)
        elif args.task == "hpc-collect":
            if not args.request_id:
                parser.error("hpc-collect requires --request-id")
            result = HPCService(platform).collect(args.request_id, args.actor)
        else:
            if not args.request_id:
                parser.error("hpc-poll requires --request-id")
            result = HPCService(platform).poll(args.request_id)
        print(json.dumps(result, indent=2))
    finally:
        platform.repo.engine.dispose()


if __name__ == "__main__":
    main()
