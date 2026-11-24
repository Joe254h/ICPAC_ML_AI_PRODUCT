"""Relay CHIRPS v2.0 for a service that CHC's servers refuse.

CHC answers Hugging Face's shared addresses with "429 Too Many Requests", and Spaces cannot
open FTP connections. A scheduled GitHub Actions job (.github/workflows/chirps-relay.yml)
runs this script instead: it reads the recent days (final product when published, else the
preliminary one) and dekads from CHC over HTTPS or FTP, exactly as the service would, cuts
them to the region and writes them to ``--store``. The job publishes that folder on the
``chirps-relay`` branch, which the service reads over HTTPS (CHIRPS_RELAY_URL; config
``chirps.relay``).

    python -m scripts.chirps_relay --store relay --days 120 --dekads 18

Layout of the store: ``daily/chirps-v2.0.YYYY-MM-DD.nc`` (the service's own store format,
with the product, CHC address and checksum of CHC's file), ``dekad/chirps-v2.0.YYYY.MM.D.nc``
(cropped dekadal NetCDF with its time axis) and ``index.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import xarray as xr

from climate_engine import ncio
from climate_engine.inputs import chirps, chirps_dekad

#: Seconds between days asked of CHC.
PAUSE_SECONDS = float(os.getenv("CHIRPS_RELAY_PAUSE", "2"))


def relay_days(store: Path, days: int, today: date) -> dict[str, dict[str, str]]:
    from backend.app.services.operational import authoritative_grid

    grid = authoritative_grid()
    server = chirps.Server()
    held: dict[str, dict[str, str]] = {}
    for offset in range(days, 1, -1):  # CHC publishes a day about two days later
        day = today - timedelta(days=offset)
        kept = chirps._held_day(store, day)
        if not kept or kept[1].get("product") != "final":
            time.sleep(PAUSE_SECONDS)  # a polite pace: CHC refuses addresses that hurry
        try:
            _, info = chirps.fetch_day(day, grid, server, store)
        except (chirps.CHIRPSUnavailable, ValueError, KeyError, OSError) as exc:
            print(f"{day}: not relayed: {str(exc)[:200]}")
            continue
        held[day.isoformat()] = {"product": info.product, "sha256": info.sha256}
    return held


def relay_dekads(store: Path, count: int) -> list[str]:
    server = chirps.Server()
    folder = store / "dekad"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        listed = chirps_dekad.published(server)[-count:]
    except chirps.CHIRPSUnavailable as exc:
        print(f"dekads: not listed: {str(exc)[:200]}")
        listed = []
    for dekad in listed:
        path = folder / dekad.name
        if path.exists():
            continue
        try:
            field, origin = chirps_dekad.fetch(dekad, server)
        except (chirps.CHIRPSUnavailable, ValueError) as exc:
            print(f"{dekad.id}: not relayed: {str(exc)[:200]}")
            continue
        variable = chirps_dekad.settings()["variable"]
        data = field.expand_dims(time=[np.datetime64(dekad.start, "ns")]).rename(variable)
        dataset = xr.Dataset(
            {variable: data}, attrs={"url": origin["url"], "sha256": origin["sha256"]}
        )
        partial = path.with_suffix(".part")
        ncio.to_netcdf(dataset, partial)
        partial.replace(path)
    return sorted(p.name for p in folder.glob("chirps-v2.0.*.nc"))


def prune(store: Path, days: int, dekads: int, today: date) -> None:
    """Drop days and dekads older than the window, so the branch stays small."""
    oldest = today - timedelta(days=days)
    for path in (store / "daily").glob("chirps-v2.0.*.nc"):
        if date.fromisoformat(path.name[len("chirps-v2.0.") : -len(".nc")]) < oldest:
            path.unlink()
    held = sorted((store / "dekad").glob("chirps-v2.0.*.nc"))
    for path in held[:-dekads] if len(held) > dekads else []:
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--dekads", type=int, default=18)
    args = parser.parse_args(argv)
    # The relay reads CHC itself, never another relay.
    os.environ["CHIRPS_RELAY_URL"] = "off"
    today = datetime.now(timezone.utc).date()
    args.store.mkdir(parents=True, exist_ok=True)
    days = relay_days(args.store, args.days, today)
    dekads = relay_dekads(args.store, args.dekads)
    prune(args.store, args.days, args.dekads, today)
    # The index lists every day held, also those kept from earlier runs (here or on
    # another machine running this script).
    held: dict[str, dict[str, str]] = {}
    for path in sorted((args.store / "daily").glob("chirps-v2.0.*.nc")):
        day = date.fromisoformat(path.name[len("chirps-v2.0.") : -len(".nc")])
        kept = chirps._held_day(args.store, day)
        if kept:
            held[day.isoformat()] = {
                "product": str(kept[1].get("product")),
                "sha256": str(kept[1].get("sha256")),
            }
    index = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "days": held,
        "dekads": dekads,
    }
    (args.store / chirps_dekad.RELAY_INDEX).write_text(json.dumps(index, indent=1) + "\n")
    finals = sum(1 for d in held.values() if d["product"] == "final")
    print(
        f"read {len(days)} days this run; holding {len(held)} days ({finals} final, "
        f"{len(held) - finals} preliminary) and {len(dekads)} dekads"
    )
    return 0  # CHC refusing this machine today is not an error: the next run tries again


if __name__ == "__main__":
    sys.exit(main())
