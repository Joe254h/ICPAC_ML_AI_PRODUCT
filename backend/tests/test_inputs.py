"""ECMWF Open Data and CHIRPS inputs, end to end through the API, on the tiny grid."""

import gzip
import io
import time
from datetime import date, timedelta

import httpx
import numpy as np
import pytest
import tifffile
import xarray as xr

from backend.app.services import forecasts
from backend.tests import ecmwf_mirror
from backend.tests.test_forecasts import env as env
from backend.tests.test_forecasts import fast_maps as fast_maps
from backend.tests.test_forecasts import run
from backend.tests.tiny import LAT, LON, MASK
from climate_engine.inputs import chirps, ecmwf_opendata
from climate_engine.operational.ecmwf import coarsen


def wait(client, operation: dict, seconds: float = 120) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        record = client.get(f"/operations/{operation['id']}").json()
        if record["status"] not in {"queued", "running"}:
            return record
        time.sleep(0.2)
    raise AssertionError(f"operation {operation['id']} did not finish")


@pytest.fixture
def mirror(tmp_path, monkeypatch):
    root = tmp_path / "mirror"
    ecmwf_mirror.build(root, date(2026, 10, 5))
    with ecmwf_mirror.serve(root) as url:
        monkeypatch.setenv("ECMWF_OPENDATA_MIRRORS", url)
        yield url


def test_open_data_download_keeps_perturbed_tp_members(mirror, tmp_path):
    result = ecmwf_opendata.fetch(date(2026, 10, 5), tmp_path / "in")
    assert result.members == 3 and result.steps_hours == [168, 336]
    with xr.open_dataset(result.path) as data:
        assert list(data["number"].values) == [1, 2, 3]  # no control member, no 2 m temperature
        assert data["tp"].attrs["units"] == "m"
        assert data.attrs["initialization"] == "2026-10-05"
        assert float(data.latitude.min()) >= -16.5 and float(data.longitude.max()) <= 55.5
        week2 = data["tp"].isel(step=1) - data["tp"].isel(step=0)
        assert float(week2.min()) > 0
    with pytest.raises(ecmwf_opendata.ECMWFDataUnavailable):
        ecmwf_opendata.fetch(date(2026, 10, 4), tmp_path / "in")
    assert ecmwf_opendata.is_published(date(2026, 10, 5), mirror)
    assert not ecmwf_opendata.is_published(date(2026, 10, 6), mirror)
    assert ecmwf_opendata.latest_initialization(date(2026, 10, 7)) == date(2026, 10, 5)


def test_averaging_to_the_training_grid_preserves_the_mean():
    lat = np.arange(-16.5, 27.01, 0.25)
    lon = np.arange(16.5, 55.51, 0.25)
    field = xr.DataArray(
        np.add.outer(lat, 2 * lon),
        dims=("latitude", "longitude"),
        coords={"latitude": lat, "longitude": lon},
    )
    coarse = coarsen(field, 1.5)
    assert coarse.latitude.values[[0, -1]].tolist() == [-15.0, 25.5]
    assert coarse.longitude.values[[0, -1]].tolist() == [18.0, 54.0]
    expected = np.add.outer(coarse.latitude.values, 2 * coarse.longitude.values)
    np.testing.assert_allclose(coarse.values, expected)
    # Already coarse input is left alone.
    assert coarsen(coarse, 1.5) is not None and coarsen(coarse, 1.5).shape == coarse.shape


def test_fetch_and_run_from_open_data(env, fast_maps, mirror):
    client = env.client
    started = client.post(
        "/operations",
        json={"action": "fetch_ecmwf", "initialization": "2026-10-05", "actor": "Joe N"},
    )
    assert started.status_code == 202 and started.json()["status"] == "queued"
    done = wait(client, started.json())
    assert done["status"] == "complete", done
    assert done["result"]["initialization"] == "2026-10-05"
    fetched = client.get("/data/ecmwf").json()
    assert fetched[0]["members"] == 3 and fetched[0]["mirror"] == mirror
    sources = {s["id"]: s for s in client.get("/data/sources").json()}
    assert sources["ecmwf"]["fetched"] == 1

    response = client.post(
        "/forecasts/run",
        json={"initialization": "2026-10-05", "source": "ecmwf_opendata", "actor": "Joe N"},
    )
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["input_label"] == "ECMWF ENS (Open Data)" and not record["synthetic"]
    # The open data hold no pressure levels: the hybrid stays in progress.
    assert record["primary_layer"] == "mbc"
    assert "pressure-level input" in record["products"]["hybrid"]["reason"]
    assert any("averaged to 1.5 degree" in note for note in record["notes"])
    detail = client.get(f"/forecasts/{record['forecast_id']}").json()
    assert detail["provenance"]["input_attributes"]["mirror"] == mirror
    with xr.open_dataset(forecasts.package_root() / record["forecast_id"] / "forecast.nc") as data:
        raw = data["raw"].values[MASK]
    assert np.isfinite(raw).all() and (raw > 0).all()
    health = client.get("/health").json()["components"]
    assert health["ECMWF input"].startswith("Healthy · latest 2026-10-05")


def chirps_tile(daily_mm: float, missing: tuple[int, int] | None = None) -> bytes:
    """A gzipped CHIRPS-style GeoTIFF whose pixels line up with the tiny grid."""
    values = np.full((LAT.size, LON.size), daily_mm, dtype=np.float32)[::-1]  # north first
    if missing:
        values[LAT.size - 1 - missing[0], missing[1]] = -9999.0
    geokeys = (1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326)
    buffer = io.BytesIO()
    tifffile.imwrite(
        buffer,
        values,
        extratags=[
            (33550, 12, 3, (0.05, 0.05, 0.0), False),
            (
                33922,
                12,
                6,
                (0.0, 0.0, 0.0, float(LON[0]) - 0.025, float(LAT[-1]) + 0.025, 0.0),
                False,
            ),
            (34735, 3, len(geokeys), geokeys, False),
            (42113, 2, 0, "-9999", False),
        ],
    )
    return gzip.compress(buffer.getvalue())


def daily_url(product: str, day: date) -> str:
    """Where CHC publishes a day: the final Africa product compressed, the preliminary
    global product not."""
    name = f"chirps-v2.0.{day.year}.{day.month:02d}.{day.day:02d}.tif"
    return chirps.directory(product, day.year) + (name + ".gz" if product == "final" else name)


def chc(files: dict[str, bytes]):
    """A CHC server holding ``files``: directory URLs answer with an index page listing
    the files in them, as the real server does; anything else is a 404."""

    def get(url: str) -> bytes | None:
        if url.endswith("/"):
            names = [u[len(url) :] for u in files if u.startswith(url)]
            if not names:
                return None
            links = "".join(f'<tr><td><a href="{n}">{n}</a></td></tr>' for n in names)
            return f"<html><body><table>{links}</table></body></html>".encode()
        return files.get(url)

    return get


def week(start: date, product: str = "final", mm: float = 3.0) -> dict[str, bytes]:
    return {daily_url(product, start + timedelta(days=i)): chirps_tile(mm) for i in range(7)}


def test_chirps_week_total_reads_final_else_preliminary(env, tmp_path):
    first_missing = (1, 1)
    assert MASK[first_missing]
    start = date(2026, 9, 21)
    files = {}
    for offset in range(7):
        day = start + timedelta(days=offset)
        files[daily_url("prelim", day)] = chirps_tile(1.0)
        if day.day < 25:  # the last days are only in the preliminary product
            files[daily_url("final", day)] = chirps_tile(
                2.0, first_missing if day.day == 21 else None
            )
    requested: list[str] = []
    server = chc(files)

    def get(url: str) -> bytes | None:
        requested.append(url)
        return server(url)

    store = tmp_path / "chirps"
    result = chirps.week_total(start, env.grid, chirps.Server(get), store)
    assert [d.product for d in result.days] == ["final"] * 4 + ["prelim"] * 3
    assert result.products == ["final", "prelim"]
    # Files are found by listing their directory: one listing per product and year.
    assert sum(url.endswith("/") for url in requested) == 2
    cells = env.grid.to_cells(result.values)
    assert np.isnan(result.values[first_missing])
    assert np.allclose(cells[np.isfinite(cells)], 4 * 2.0 + 3 * 1.0)
    assert result.days[0].missing_domain_cells == 1
    assert np.isnan(result.values[~MASK]).all()
    assert len(list((store / "daily").glob("*.nc"))) == 7
    data = chirps.to_dataset(result, env.grid)
    assert data.attrs["valid_start"] == "2026-09-21T00:00:00+00:00"
    assert data.attrs["valid_end"] == "2026-09-28T00:00:00+00:00"
    with pytest.raises(chirps.CHIRPSUnavailable):
        chirps.week_total(start, env.grid, chirps.Server(chc({})))


def test_chirps_days_held_are_reused_until_the_final_product_appears(env, tmp_path):
    start = date(2026, 9, 21)
    store = tmp_path / "chirps"
    chirps.week_total(start, env.grid, chirps.Server(chc(week(start, "prelim", 1.0))), store)
    # Listed but not downloadable: the held preliminary days are used, nothing is fetched.
    listed_only = chc(week(start, "prelim", 1.0))
    fetched: list[str] = []

    def no_files(url: str) -> bytes | None:
        if not url.endswith("/"):
            fetched.append(url)
            return None
        return listed_only(url)

    again = chirps.week_total(start, env.grid, chirps.Server(no_files), store)
    assert fetched == [] and again.products == ["prelim"]
    # Once the final product is published, it replaces the preliminary days.
    both = {**week(start, "prelim", 1.0), **week(start, "final", 2.0)}
    final = chirps.week_total(start, env.grid, chirps.Server(chc(both)), store)
    assert final.products == ["final"]
    assert np.nanmax(final.values) == pytest.approx(14.0)
    # Final days are then used without asking the server at all.
    offline = chirps.week_total(start, env.grid, chirps.Server(chc({})), store)
    assert offline.products == ["final"]


def test_chirps_downloads_retry_with_a_doubling_wait():
    waits: list[float] = []
    calls = {"n": 0}

    def flaky(url: str) -> bytes | None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("connection reset")
        return b"ok"

    assert chirps.Server(flaky, sleep=waits.append).fetch("https://x/f.tif") == b"ok"
    assert waits == [5.0, 10.0]

    def down(url: str) -> bytes | None:
        raise httpx.ConnectError("unreachable")

    waits.clear()
    with pytest.raises(chirps.CHIRPSUnavailable, match="after 5 attempts"):
        chirps.Server(down, sleep=waits.append).fetch("https://x/f.tif")
    assert waits == [5.0, 10.0, 20.0, 40.0]

    def forbidden(url: str) -> bytes | None:
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("403", request=request, response=httpx.Response(403))

    waits.clear()
    with pytest.raises(chirps.CHIRPSUnavailable, match="after 1 attempt"):
        chirps.Server(forbidden, sleep=waits.append).fetch("https://x/f.tif")
    assert waits == []


def test_finished_forecasts_are_verified_against_chirps(env, fast_maps, monkeypatch):
    record = run(env, "2026-09-14")
    future = run(env, "2026-10-05")
    monkeypatch.setattr(chirps, "download", chc(week(date(2026, 9, 21))))
    service = forecasts.ForecastService(env.platform)
    result = service.verify_due("Joe N")
    assert result["verified"] == [record["forecast_id"]]
    assert result["waiting"] == [future["forecast_id"]]
    verified = env.client.get(f"/forecasts/{record['forecast_id']}/verification").json()
    assert verified["status"] == "available"
    assert verified["observation"]["file"] == "chirps_week2_2026-09-21.nc"
    assert verified["domain"]["hybrid"]["observed_mean"] == pytest.approx(21.0)
    windows = env.client.get("/data/chirps").json()
    assert windows[0]["valid_start"] == "2026-09-21" and windows[0]["products"] == ["final"]
    with pytest.raises(ValueError, match="already verified"):
        service.verify_with_chirps(record["forecast_id"], "Joe N")
    with pytest.raises(forecasts.Unavailable):
        service.verify_with_chirps(future["forecast_id"], "Joe N")


def test_the_weekly_cycle_runs_as_one_operation(env, fast_maps, mirror, monkeypatch):
    monkeypatch.setattr(ecmwf_opendata, "latest_initialization", lambda: date(2026, 10, 5))
    monkeypatch.setattr(chirps, "download", chc({}))  # CHIRPS lists nothing yet
    client = env.client
    operation = client.post("/operations", json={"action": "cycle", "actor": "Joe N"}).json()
    done = wait(client, operation)
    assert done["status"] == "complete", done
    forecast_id = done["result"]["forecast_id"]
    assert client.get("/forecasts/latest").json()["forecast_id"] == forecast_id
    assert done["result"]["verification"]["waiting"] == [forecast_id]
    texts = [m["text"] for m in done["messages"]]
    assert texts[0] == "Started" and texts[-1] == "Finished"
    # A CHIRPS outage is recorded, and the forecast stands.
    assert "error" in done["result"]["monitoring"]
    assert any("monitoring could not be updated" in text for text in texts)
    # A second cycle for the same run does not forecast it again.
    again = wait(
        client, client.post("/operations", json={"action": "cycle", "actor": "Joe N"}).json()
    )
    assert again["result"]["forecast_id"] == forecast_id
    assert len(client.get("/forecasts").json()) == 1
    # Failures are recorded on the operation, not raised at the caller.
    failed = wait(
        client,
        client.post(
            "/operations",
            json={"action": "fetch_ecmwf", "initialization": "2026-09-01", "actor": "Joe N"},
        ).json(),
    )
    assert failed["status"] == "failed" and "not available" in failed["error"]
    assert client.get("/operations").json()[0]["id"] == failed["id"]


def test_interrupted_operations_are_marked_on_restart(env):
    from backend.app.services.operations import KIND, OperationService

    record = env.platform.repo.save(
        KIND,
        {
            "action": "cycle",
            "status": "running",
            "created_at": "2026-10-08T00:00:00+00:00",
            "messages": [],
        },
    )
    OperationService(env.platform).recover()
    assert env.platform.repo.get(KIND, record["id"])["status"] == "interrupted"


def test_window_completeness_follows_chirps_latency():
    assert chirps.window_complete(date(2026, 9, 21), today=date(2026, 9, 29))
    assert not chirps.window_complete(date(2026, 9, 21), today=date(2026, 9, 28))
    assert chirps.window_days(date(2026, 9, 21))[-1] == date(2026, 9, 27)
    assert chirps.window_days(date(2026, 9, 21))[0] + timedelta(days=7) == date(2026, 9, 28)
