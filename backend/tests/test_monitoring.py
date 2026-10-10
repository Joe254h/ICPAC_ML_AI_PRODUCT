"""CHIRPS preliminary dekads for rainfall monitoring, as ICPAC's climate monitoring
framework downloads them, through the API on the tiny grid."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from backend.tests.test_forecasts import env as env
from backend.tests.test_inputs import chc, wait
from backend.tests.tiny import LAT, LON, MASK
from climate_engine.inputs import chirps, chirps_dekad, tamsat
from climate_engine.inputs.chirps_dekad import Dekad

# A CHIRPS-aligned window around the tiny grid (the real files are global).
FILE_LAT = np.round(np.arange(-0.3, 0.351, 0.05), 3)
FILE_LON = np.round(np.arange(35.8, 36.401, 0.05), 3)
DIR = chirps.settings()["dekad_dir"]


def dekad_file(tmp: Path, dekad: Dekad, mm: float, dry: tuple[int, int] | None = None) -> bytes:
    """A dekadal NetCDF as CHC publishes it: precip(time, latitude, longitude), mm,
    dated by the dekad's first day, -9999 where there is no data."""
    values = np.full((1, FILE_LAT.size, FILE_LON.size), mm, dtype=np.float32)
    values[0, 0, 0] = -9999.0
    if dry:
        lat, lon = LAT[dry[0]], LON[dry[1]]
        values[0, np.argmin(abs(FILE_LAT - lat)), np.argmin(abs(FILE_LON - lon))] = 0.4
    data = xr.Dataset(
        {"precip": (("time", "latitude", "longitude"), values, {"units": "mm/dekad"})},
        coords={
            "time": [np.datetime64(dekad.start.isoformat())],
            "latitude": FILE_LAT,
            "longitude": FILE_LON,
        },
    )
    path = tmp / f"{dekad.name}.bytes.nc"
    data.to_netcdf(path)
    return path.read_bytes()


def climatology(tmp: Path) -> Path:
    """1991-2020 dekads: the first dekad of October has 20 mm every year, the first dekad of
    January 100 mm. A same-month normal for October is 20 mm; averaging the first dekad of
    every month (selecting by day only) would give 60 mm."""
    times = []
    values = []
    for year in range(1991, 2021):
        for month, mm in ((1, 100.0), (10, 20.0)):
            times.append(np.datetime64(f"{year}-{month:02d}-01"))
            values.append(np.full((FILE_LAT.size, FILE_LON.size), mm, dtype=np.float32))
    data = xr.Dataset(
        {"precip": (("time", "latitude", "longitude"), np.stack(values))},
        coords={"time": np.array(times), "latitude": FILE_LAT, "longitude": FILE_LON},
    )
    path = tmp / "chirps-dekads-1991-2020.nc"
    data.to_netcdf(path)
    return path


def test_dekads_follow_chirps_dating():
    assert Dekad.from_name("chirps-v2.0.2026.02.3.nc").end == date(2026, 2, 28)
    assert Dekad.from_name("chirps-v2.0.2026.10.2.nc").start == date(2026, 10, 11)
    assert Dekad(2026, 10, 2).end == date(2026, 10, 20)
    assert Dekad.from_id("2026-10-1").name == "chirps-v2.0.2026.10.1.nc"
    with pytest.raises(ValueError):
        Dekad.from_id("2026-10-4")


def test_the_newest_dekad_is_downloaded_once_and_mapped(env, monkeypatch):
    first, second = Dekad(2026, 9, 3), Dekad(2026, 10, 1)
    dry = (2, 2)
    assert MASK[dry]
    files = {
        DIR + first.name: dekad_file(env.tmp, first, 5.0),
        DIR + second.name: dekad_file(env.tmp, second, 30.0, dry),
    }
    monkeypatch.setattr(chirps, "download", chc(files))
    client = env.client
    assert client.get("/monitoring/dekads/latest").status_code == 404

    done = wait(
        client,
        client.post("/operations", json={"action": "update_chirps", "actor": "Joe N"}).json(),
    )
    assert done["status"] == "complete", done
    assert {k: done["result"][k] for k in ("source", "dekad", "new")} == {
        "source": "chirps",
        "dekad": "2026-10-1",
        "new": True,
    }
    # TAMSAT lists nothing on this server; CHIRPS is updated all the same.
    assert "error" in done["result"]["tamsat"]
    latest = client.get("/monitoring/dekads/latest").json()
    assert latest["start"] == "2026-10-01" and latest["end"] == "2026-10-10"
    assert latest["product"] == "preliminary" and latest["url"] == DIR + second.name
    cells = MASK.sum()
    assert latest["region"]["max_mm"] == 30.0
    assert latest["region"]["dry_fraction"] == pytest.approx(1 / cells, abs=1e-3)
    assert latest["percent_of_normal"]["status"] == "in_progress"
    assert {row["country"] for row in latest["countries"]}
    assert latest["overlays"] == {
        "total": "/monitoring/dekads/2026-10-1/overlay?source=chirps&product=total"
    }
    png = client.get(latest["overlays"]["total"])
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/monitoring/dekads/2026-10-1/overlay?product=percent").status_code == 404
    assert (env.tmp / "observations/chirps/dekad" / second.name).exists()

    # Nothing new on the server: nothing is downloaded again.
    again = wait(
        client,
        client.post("/operations", json={"action": "update_chirps", "actor": "Joe N"}).json(),
    )
    assert again["result"]["dekad"] == "2026-10-1" and again["result"]["new"] is False
    assert [d["dekad"] for d in client.get("/monitoring/dekads").json()] == ["2026-10-1"]


def test_percent_of_normal_uses_the_same_month(env, monkeypatch):
    dekad = Dekad(2026, 10, 1)
    dry = (2, 2)
    monkeypatch.setattr(
        chirps, "download", chc({DIR + dekad.name: dekad_file(env.tmp, dekad, 30.0, dry)})
    )
    monkeypatch.setenv("CHIRPS_DEKAD_CLIMATOLOGY", str(climatology(env.tmp)))
    path = chirps_dekad.climatology_path()
    assert path is not None
    normal = chirps_dekad.long_term_mean(path, dekad, env.grid)
    assert np.allclose(normal[MASK], 20.0)
    client = env.client
    done = wait(
        client,
        client.post("/operations", json={"action": "update_chirps", "actor": "Joe N"}).json(),
    )
    assert done["status"] == "complete", done
    latest = client.get("/monitoring/dekads/latest").json()
    assert latest["percent_of_normal"]["status"] == "available"
    assert latest["region"]["normal_mm"] == pytest.approx(20.0)
    assert 140 <= latest["region"]["percent_of_normal"] <= 150
    assert client.get(latest["overlays"]["percent"]).status_code == 200
    # The dry cell (below 1 mm) has no percentage; the others are 150% (wetter than normal).
    total = chirps_dekad.on_grid(
        chirps_dekad.read(env.tmp / "observations/chirps/dekad" / dekad.name, dekad), env.grid
    )
    percent = chirps_dekad.percent_of_normal(total, normal)
    assert np.isnan(percent[dry])
    assert np.allclose(percent[MASK & np.isfinite(percent)], 150.0)


def test_a_file_for_another_dekad_is_refused(env, tmp_path):
    path = tmp_path / "wrong.nc"
    path.write_bytes(dekad_file(tmp_path, Dekad(2026, 10, 2), 5.0))
    with pytest.raises(ValueError, match="dated 2026-10-11, not 2026-10-01"):
        chirps_dekad.read(path, Dekad(2026, 10, 1))


# A TAMSAT-aligned window (0.0375 degree, latitude north to south as TAMSAT writes it).
TAMSAT_LAT = np.round(np.arange(0.375, -0.376, -0.0375), 4)
TAMSAT_LON = np.round(np.arange(35.7, 36.451, 0.0375), 4)


def tamsat_file(tmp: Path, dekad: Dekad, mm: float, variable: str = "rfe_filled") -> bytes:
    """A TAMSAT v3.1 dekadal NetCDF: rfe_filled(time, lat, lon) in mm, dated in the dekad."""
    values = np.full((1, TAMSAT_LAT.size, TAMSAT_LON.size), mm, dtype=np.float32)
    values[0, 0, 0] = np.nan
    data = xr.Dataset(
        {variable: (("time", "lat", "lon"), values, {"units": "mm"})},
        coords={
            "time": [np.datetime64(dekad.start.isoformat())],
            "lat": TAMSAT_LAT,
            "lon": TAMSAT_LON,
        },
    )
    path = tmp / f"tamsat-{dekad.id}.bytes.nc"
    data.to_netcdf(path)
    return path.read_bytes()


def test_tamsat_dekads_are_monitored_next_to_chirps(env, monkeypatch):
    # TAMSAT is listed by month; the newest dekad of last month is the one published.
    last_month = date.today().replace(day=1) - timedelta(days=1)
    older, newest = (
        Dekad(last_month.year, last_month.month, 2),
        Dekad(last_month.year, last_month.month, 3),
    )
    folder = tamsat.folder(newest.year, newest.month)
    held = newest  # CHIRPS holds the same dekad: the two records must not collide
    files = {
        folder + tamsat.file_name(older): tamsat_file(env.tmp, older, 10.0),
        folder + tamsat.file_name(newest): tamsat_file(env.tmp, newest, 40.0),
        DIR + held.name: dekad_file(env.tmp, held, 30.0),
    }
    monkeypatch.setattr(chirps, "download", chc(files))
    client = env.client
    assert client.get("/monitoring/dekads/latest?source=tamsat").status_code == 404
    done = wait(
        client,
        client.post("/operations", json={"action": "update_chirps", "actor": "Joe N"}).json(),
    )
    assert done["status"] == "complete", done
    assert done["result"]["tamsat"] == {"source": "tamsat", "dekad": newest.id, "new": True}
    latest = client.get("/monitoring/dekads/latest?source=tamsat").json()
    assert latest["source"] == "tamsat" and latest["dekad"] == newest.id
    assert latest["url"] == folder + tamsat.file_name(newest)
    assert latest["region"]["mean_mm"] == pytest.approx(40.0)
    assert latest["percent_of_normal"]["status"] == "in_progress"
    assert "CHIRPS" in latest["percent_of_normal"]["reason"]
    png = client.get(latest["overlays"]["total"])
    assert latest["overlays"]["total"].endswith("source=tamsat&product=total")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    # The two sources keep their own records of the same dekad.
    chirps_latest = client.get("/monitoring/dekads/latest").json()
    assert chirps_latest["dekad"] == held.id and chirps_latest["source"] == "chirps"
    assert chirps_latest["region"]["mean_mm"] == pytest.approx(30.0, abs=0.5)
    assert client.get(f"/monitoring/dekads/{newest.id}?source=tamsat").json()["source"] == (
        "tamsat"
    )
    assert [d["dekad"] for d in client.get("/monitoring/dekads?source=tamsat").json()] == [
        newest.id
    ]
    assert client.get("/monitoring/dekads/latest?source=rfe2").status_code == 422


def test_tamsat_files_are_checked(tmp_path):
    dekad = Dekad(2026, 9, 3)
    path = tmp_path / "rfe.nc"
    path.write_bytes(tamsat_file(tmp_path, dekad, 5.0, variable="rfe"))
    field = tamsat.read(path, dekad)
    assert field.attrs["variable"] == "rfe" and float(np.nanmax(field)) == 5.0
    assert np.all(np.diff(field["latitude"].values) > 0)
    with pytest.raises(ValueError, match="outside dekad"):
        tamsat.read(path, Dekad(2026, 10, 1))
    other = tmp_path / "other.nc"
    other.write_bytes(tamsat_file(tmp_path, dekad, 5.0, variable="precip"))
    with pytest.raises(ValueError, match="none of rfe_filled, rfe"):
        tamsat.read(other, dekad)


def test_tamsat_downloads_the_name_its_server_lists():
    dekad = Dekad(2026, 9, 3)
    folder = tamsat.folder(2026, 9)
    source = tamsat.server(get=chc({folder + "rfe2026_09-dk3.v3.nc": b"x"}))
    assert tamsat.published(source, today=date(2026, 10, 2)) == [dekad]
    assert tamsat.listed_name(dekad, source) == "rfe2026_09-dk3.v3.nc"
    assert tamsat.listed_name(Dekad(2026, 9, 2), source) == "rfe2026_09-dk2.v3.1.nc"
