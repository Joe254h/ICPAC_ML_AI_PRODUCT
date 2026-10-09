"""Rainfall monitoring: the latest CHIRPS preliminary dekad, as ICPAC's climate monitoring
framework produces it (total rainfall and, with the 1991-2020 normal, percent of normal).

Each update lists the server, downloads the newest dekad only if it is not held yet, checks
and crops it, and records its regional and country figures. The cropped file is kept under
DATA_ROOT/chirps/dekad (and in Blob Storage when configured, so a restarted server finds it
again).
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from backend.app.services import operational
from climate_engine.core import ROOT
from climate_engine.inputs import chirps, chirps_dekad
from climate_engine.inputs.chirps_dekad import Dekad
from climate_engine.operational.grid import DomainGrid, country_selections
from climate_engine.products.store import package_store

KIND = "chirps_dekad"
PRODUCTS = ("total", "percent")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def figures(
    total: np.ndarray, normal: np.ndarray | None, grid: DomainGrid
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Regional and per-country area means (cos-latitude weighted) of the dekad."""
    weights = np.cos(np.deg2rad(grid.cell_latitude))
    cells = grid.to_cells(total)
    normal_cells = grid.to_cells(normal) if normal is not None else None

    def summary(selected: np.ndarray) -> dict[str, Any] | None:
        valid = selected & np.isfinite(cells)
        if not valid.any():
            return None
        row: dict[str, Any] = {
            "mean_mm": round(float(np.average(cells[valid], weights=weights[valid])), 2),
            "max_mm": round(float(cells[valid].max()), 1),
            "dry_fraction": round(float(np.mean(cells[valid] < chirps_dekad.DRY_MM)), 3),
        }
        if normal_cells is not None:
            both = valid & np.isfinite(normal_cells)
            mean_normal = float(np.average(normal_cells[both], weights=weights[both]))
            mean_total = float(np.average(cells[both], weights=weights[both]))
            row["normal_mm"] = round(mean_normal, 2)
            row["percent_of_normal"] = (
                round(100.0 * mean_total / mean_normal) if mean_normal > 0 else None
            )
        return row

    region = summary(np.ones(cells.shape, dtype=bool)) or {}
    countries = []
    for name, selected in country_selections(grid).items():
        row = summary(selected)
        if row is not None:
            countries.append({"country": name, **row})
    return region, countries


class MonitoringService:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    @staticmethod
    def root() -> Path:
        data_root = Path(os.getenv("DATA_ROOT", str(ROOT / "data" / "observations")))
        return data_root / "chirps" / "dekad"

    def dekads(self) -> list[dict[str, Any]]:
        return sorted(self.repo.list(KIND), key=lambda r: r["dekad"], reverse=True)

    def latest(self) -> dict[str, Any]:
        records = self.dekads()
        if not records:
            raise KeyError("no CHIRPS dekad downloaded yet")
        return records[0]

    def get(self, identifier: str) -> dict[str, Any]:
        return self.repo.get(KIND, Dekad.from_id(identifier).id)

    def update(self, actor: str, server: chirps.Server | None = None) -> dict[str, Any]:
        """Download the newest published dekad if it is not held yet."""
        server = server or chirps.Server()
        listed = chirps_dekad.published(server)
        if not listed:
            raise chirps.CHIRPSUnavailable("The CHIRPS server lists no preliminary dekad")
        dekad = listed[-1]
        if any(r["dekad"] == dekad.id for r in self.repo.list(KIND)):
            return {"dekad": dekad.id, "new": False}
        field, source = chirps_dekad.fetch(dekad, server)
        path = self.root() / dekad.name
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f".{path.name}.partial")
        field.to_dataset().to_netcdf(partial)
        partial.replace(path)
        store = package_store()
        if store is not None:
            store.put(f"inputs/chirps/dekad/{dekad.name}", path.read_bytes())
        record = self._record(dekad, field, source, actor)
        self.repo.save(KIND, record, dekad.id)
        return {"dekad": dekad.id, "new": True}

    def _record(
        self, dekad: Dekad, field: xr.DataArray, source: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        grid = operational.authoritative_grid()
        total = chirps_dekad.on_grid(field, grid)
        normal, reason = self._normal(dekad, grid)
        region, countries = figures(total, normal, grid)
        return {
            "dekad": dekad.id,
            "year": dekad.year,
            "month": dekad.month,
            "number": dekad.number,
            "start": dekad.start.isoformat(),
            "end": dekad.end.isoformat(),
            "product": "preliminary",
            "file": dekad.name,
            **source,
            "region": region,
            "countries": countries,
            "percent_of_normal": {
                "status": "available" if normal is not None else "in_progress",
                "reason": reason,
            },
            "fetched_at": now(),
            "fetched_by": actor,
        }

    @staticmethod
    def _normal(dekad: Dekad, grid: DomainGrid) -> tuple[np.ndarray | None, str | None]:
        path = chirps_dekad.climatology_path()
        if path is None:
            return None, (
                "Percent of normal needs the 1991–2020 long-term mean of each dekad, which "
                "ICPAC keeps for its monitoring products; it has not been added yet."
            )
        if not path.exists():
            return None, "The 1991–2020 long-term mean file was not found on the server."
        return chirps_dekad.long_term_mean(path, dekad, grid), None

    def field(self, identifier: str) -> xr.DataArray:
        record = self.get(identifier)
        path = self.root() / record["file"]
        if not path.exists():
            store = package_store()
            saved = store.get(f"inputs/chirps/dekad/{record['file']}") if store else None
            if saved is None:
                raise FileNotFoundError(f"The CHIRPS dekad {identifier} file is not available")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(saved)
        with xr.open_dataset(path) as data:
            return data["precip"].load()

    def overlay_png(self, identifier: str, product: str) -> bytes:
        """The dekad as a transparent Web Mercator overlay for the interactive map."""
        from climate_engine.cartography import overlay

        if product not in PRODUCTS:
            raise ValueError("Monitoring products: total, percent")
        record = self.get(identifier)
        if product == "percent" and record["percent_of_normal"]["status"] != "available":
            raise KeyError(f"no percent of normal for dekad {identifier}")
        cache = self.root() / "overlays" / f"{record['dekad']}-{product}-v1.png"
        if not cache.exists():
            grid = operational.authoritative_grid()
            total = chirps_dekad.on_grid(self.field(identifier), grid)
            if product == "total":
                values, scale = total, chirps_dekad.TOTAL
            else:
                normal, _ = self._normal(Dekad.from_id(identifier), grid)
                assert normal is not None
                values = chirps_dekad.percent_of_normal(total, normal)
                scale = chirps_dekad.PERCENT
            cache.parent.mkdir(parents=True, exist_ok=True)
            partial = cache.with_name(f".{cache.name}.partial")
            partial.write_bytes(overlay.mercator_png(values, grid.latitude, grid.longitude, scale))
            partial.replace(cache)
        return cache.read_bytes()

    @staticmethod
    def bounds() -> list[float]:
        from climate_engine.cartography import overlay

        grid = operational.authoritative_grid()
        return overlay.bounds(grid.latitude, grid.longitude)
