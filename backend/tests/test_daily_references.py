"""ARC 2.0, RFE 2.0 and GPM IMERG: daily files read, checked, summed into dekads for the
rainfall monitoring and into Week-2 totals to compare verified forecasts with."""

import io
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from backend.app.services import forecasts
from backend.app.services.monitoring import MonitoringService
from backend.tests.test_forecasts import env as env
from backend.tests.test_forecasts import fast_maps as fast_maps
from backend.tests.test_forecasts import run
from backend.tests.test_inputs import chc, seen_from, week
from chatbot import agent
from climate_engine.inputs import chirps, daily_references

# CPC files cover Africa at 0.1 degree, north first; a part of it is enough here.
CPC_LAT = np.round(np.arange(27.95, -20.0, -0.1), 2)
CPC_LON = np.round(np.arange(15.05, 56.0, 0.1), 2)
GEOKEYS = (1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326)


def cpc_zip(mm: float, world_file: bool = False) -> bytes:
    """A zipped CPC daily GeoTIFF (mm), georeferenced by its tags or by a world file."""
    import tifffile

    values = np.full((CPC_LAT.size, CPC_LON.size), mm, dtype=np.float32)
    values[0, 0] = -999.0
    tif = io.BytesIO()
    tags = (
        []
        if world_file
        else [
            (33550, 12, 3, (0.1, 0.1, 0.0), False),
            (33922, 12, 6, (0.0, 0.0, 0.0, 15.0, 28.0, 0.0), False),
            (34735, 3, len(GEOKEYS), GEOKEYS, False),
            (42113, 2, 0, "-999", False),
        ]
    )
    tifffile.imwrite(tif, values, extratags=tags)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("africa_arc.tif", tif.getvalue())
        if world_file:
            out.writestr("africa_arc.tfw", "0.1\n0\n0\n-0.1\n15.05\n27.95\n")
    return archive.getvalue()


def imerg_file(tmp: Path, day: date, mm: float) -> bytes:
    """An IMERG daily NetCDF4: precipitation(time, lon, lat) in mm/day, south first."""
    lat = np.round(np.arange(-19.95, 28.0, 0.1), 2)
    lon = CPC_LON
    data = xr.Dataset(
        {
            "precipitation": (
                ("time", "lon", "lat"),
                np.full((1, lon.size, lat.size), mm, dtype=np.float32),
                {"units": "mm/day"},
            )
        },
        coords={"time": [np.datetime64(day.isoformat())], "lon": lon, "lat": lat},
    )
    path = tmp / f"imerg-{day}.nc4"
    data.to_netcdf(path)
    return path.read_bytes()


def cpc_files(source: str, days: list[date], mm: float) -> dict[str, bytes]:
    cfg = daily_references.settings(source)
    return {f"{cfg['base_url']}/{cfg['day_file'].format(day=d)}": cpc_zip(mm) for d in days}


def imerg_files(tmp: Path, days: list[date], mm: float) -> dict[str, bytes]:
    cfg = daily_references.settings("imerg")
    files = {}
    for d in days:
        folder = f"{cfg['base_url']}/{cfg['day_dir'].format(year=d.year, month=d.month)}"
        name = f"3B-DAY-L.MS.MRG.3IMERG.{d:%Y%m%d}-S000000-E235959.V07B.nc4"
        files[folder + name] = imerg_file(tmp, d, mm)
    return files


def test_cpc_days_are_read_checked_and_summed(tmp_path, monkeypatch):
    days = [date(2026, 10, 11) + timedelta(days=n) for n in range(10)]
    monkeypatch.setattr(chirps, "download", chc(cpc_files("arc2", days, 2.5)))
    total, origin = daily_references.days_total("arc2", days, tmp_path)
    assert origin["days"] == 10 and origin["first_url"].endswith("africa_arc.20261011.tif.zip")
    assert float(total.max()) == pytest.approx(25.0)
    # Cropped to the region, latitude ascending, nodata missing.
    assert total["latitude"].values[0] < total["latitude"].values[-1]
    assert float(total["longitude"].min()) > 19.0 and float(total["latitude"].max()) < 25.0
    assert np.isnan(total.values).sum() == 0  # the nodata cell lies outside the region
    # Each day is kept, so the next total reads no file again.
    monkeypatch.setattr(chirps, "download", chc({}))
    again, _ = daily_references.days_total("arc2", days, tmp_path)
    np.testing.assert_allclose(again.values, total.values)
    # A world file georeferences a GeoTIFF without tags.
    values, latitude, longitude, _ = daily_references.read_cpc(cpc_zip(1.0, world_file=True))
    assert latitude[0] == pytest.approx(27.95) and longitude[0] == pytest.approx(15.05)
    with pytest.raises(daily_references.ReferenceUnavailable, match="not published yet"):
        daily_references.fetch_day("rfe2", date(2026, 10, 30), tmp_path)


def test_imerg_needs_an_earthdata_token(tmp_path, monkeypatch):
    days = [date(2026, 10, 11), date(2026, 10, 12)]
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    with pytest.raises(daily_references.ReferenceUnavailable, match="Earthdata token"):
        daily_references.days_total("imerg", days, tmp_path)
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")
    files = imerg_files(tmp_path, days, 4.0)
    sent = []

    def download(url: str, secret: str) -> bytes | None:
        sent.append(secret)
        return chc(files)(url)

    monkeypatch.setattr(daily_references, "authorised_download", download)
    total, origin = daily_references.days_total("imerg", days, tmp_path / "held")
    assert float(np.nanmax(total.values)) == pytest.approx(8.0)
    assert origin["last_url"].endswith("3IMERG.20261012-S000000-E235959.V07B.nc4")
    assert set(sent) == {"test-token"}  # the listing and the files carry the token


def test_monitoring_sums_the_newest_complete_dekad(env, monkeypatch):
    today = date.today()
    newest = daily_references.ended_dekads("rfe2", today)[0]
    monkeypatch.setattr(
        chirps, "download", chc(cpc_files("rfe2", daily_references.dekad_days(newest), 3.0))
    )
    service = MonitoringService(env.platform, "rfe2")
    assert service.update("Joe N") == {"source": "rfe2", "dekad": newest.id, "new": True}
    latest = env.client.get("/monitoring/dekads/latest?source=rfe2").json()
    days = len(daily_references.dekad_days(newest))
    assert latest["region"]["mean_mm"] == pytest.approx(3.0 * days, rel=1e-3)
    assert latest["product"] == "daily totals" and "CHIRPS" in latest["percent_of_normal"]["reason"]
    assert service.update("Joe N")["new"] is False
    # A dekad with a missing day is passed over for the one before.
    previous = daily_references.ended_dekads("arc2", today)[1]
    files = cpc_files("arc2", daily_references.dekad_days(previous), 1.0)
    files.update(cpc_files("arc2", daily_references.dekad_days(newest)[:-1], 1.0))
    monkeypatch.setattr(chirps, "download", chc(files))
    assert MonitoringService(env.platform, "arc2").update("Joe N")["dekad"] == previous.id
    # Each check is kept, with why a source has no dekad.
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    assert MonitoringService(env.platform, "rfe2").check("Joe N")["new"] is False
    with pytest.raises(daily_references.ReferenceUnavailable):
        MonitoringService(env.platform, "imerg").check("Joe N")
    sources = {s["id"]: s for s in env.client.get("/data/sources").json()}
    assert sources["rfe2"]["status"] == "active" and sources["rfe2"]["fetched"] == 1
    assert sources["rfe2"]["last_check"]["status"] == "held"
    assert sources["imerg"]["last_check"]["status"] == "failed"
    assert "Earthdata token" in sources["imerg"]["last_check"]["reason"]
    assert sources["arc2"]["last_check"] is None and sources["chirps"]["last_check"] is None
    # The Copilot reads every estimate, with each one's difference from CHIRPS.
    rainfall = agent.ToolBox(env.platform, {}).run("get_rainfall_monitoring", {})
    assert rainfall["rfe2"]["period"] and "Earthdata token" in rainfall["imerg"]["reason"]
    assert "minus_chirps_mm" not in rainfall  # no CHIRPS dekad to compare with here
    estimates = {e["source"]: e for e in env.client.get("/monitoring/estimates").json()}
    assert list(estimates) == ["chirps", "tamsat", "arc2", "rfe2", "imerg"]
    assert (
        estimates["rfe2"]["latest"]["dekad"] == newest.id and estimates["chirps"]["latest"] is None
    )
    assert estimates["imerg"]["name"] == "GPM IMERG" and estimates["imerg"]["latest"] is None
    assert estimates["imerg"]["last_check"]["status"] == "failed"
    assert env.client.get("/monitoring/dekads/latest?source=gsmap").status_code == 422


def test_verified_forecasts_are_compared_with_the_further_references(env, fast_maps, monkeypatch):
    record = run(env, "2026-09-14")
    start = date(2026, 9, 21)
    days = [start + timedelta(days=n) for n in range(7)]
    files = week(start)
    files.update(cpc_files("arc2", days, 3.0))  # the same as CHIRPS
    files.update(cpc_files("rfe2", days, 6.0))
    monkeypatch.setattr(chirps, "download", chc(files))
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    seen_from(monkeypatch, date(2026, 10, 15))
    service = forecasts.ForecastService(env.platform)
    result = service.verify_due("Joe N")
    assert result["verified"] == [record["forecast_id"]] and result["compared"] == 2
    chirps_scores = env.client.get(f"/forecasts/{record['forecast_id']}/verification").json()
    compared = {
        c["source"]: c
        for c in env.client.get(f"/forecasts/{record['forecast_id']}/references").json()
    }
    assert compared["arc2"]["status"] == "available" and compared["arc2"]["name"] == "ARC 2.0"
    arc2, rfe2 = compared["arc2"]["domain"]["hybrid"], compared["rfe2"]["domain"]["hybrid"]
    assert arc2["observed_mean"] == pytest.approx(
        chirps_scores["domain"]["hybrid"]["observed_mean"], rel=1e-3
    )
    assert rfe2["observed_mean"] == pytest.approx(42.0, rel=1e-3)
    assert compared["imerg"]["status"] == "unavailable"
    assert "Earthdata token" in compared["imerg"]["reason"]
    # The Copilot's checked answer gives the comparisons.
    answer = env.client.post(
        "/chat",
        json={"message": "Compare CHIRPS and ARC 2.0", "context_mode": "operational"},
    ).json()
    assert "Against ARC 2.0: MAE" in answer["text"]
    assert "Against GPM IMERG: not compared yet" in answer["text"]
    # A comparison is made once; an unavailable one is tried again in the next pass.
    monkeypatch.setattr(chirps, "download", chc({}))
    again = service.compare_references(record["forecast_id"], "Joe N")
    assert [c["status"] for c in again] == ["available", "available", "unavailable"]
