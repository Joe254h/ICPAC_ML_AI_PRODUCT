"""Another model's forecast uploaded as NetCDF: read in an isolated process, put on the model
grid, compared with ICPAC's forecast of the same week and, once CHIRPS covers the week,
scored with it against the observations."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

from backend.app.schemas import ChatRequest
from backend.app.services import forecasts
from backend.tests.test_agent import claude as claude
from backend.tests.test_agent import tool_results
from backend.tests.test_forecasts import env as env
from backend.tests.test_forecasts import fast_maps as fast_maps
from backend.tests.test_forecasts import run
from backend.tests.test_inputs import chc, week
from chatbot.service import Copilot
from climate_engine.inputs import chirps
from climate_engine.inputs import external_forecast as reader

#: CHIRPS publication as on a given day (the shared helper cannot be applied twice).
WINDOW_COMPLETE = chirps.window_complete


def observed_by(monkeypatch, today: date) -> None:
    monkeypatch.setattr(
        chirps, "window_complete", lambda start, _=None: WINDOW_COMPLETE(start, today)
    )


LAT = np.arange(-15.0, 25.0, 0.25)
LON = np.arange(18.0, 55.0, 0.25)


def netcdf(
    tmp: Path,
    start: date | None,
    mm_per_day: float = 3.0,
    units: str = "mm/day",
    lat=LAT,
    lon=LON,
) -> bytes:
    """Seven daily rainfall totals (or, without a start, one undated field)."""
    if start is None:
        data = xr.Dataset(
            {"rainfall": (("lat", "lon"), np.full((lat.size, lon.size), 21.0), {"units": "mm"})},
            coords={"lat": lat, "lon": lon},
        )
    else:
        days = [np.datetime64(start + timedelta(days=n)) for n in range(7)]
        data = xr.Dataset(
            {
                "precip": (
                    ("time", "latitude", "longitude"),
                    np.full((7, lat.size, lon.size), mm_per_day, dtype=np.float32),
                    {"units": units},
                )
            },
            coords={"time": days, "latitude": lat, "longitude": lon},
        )
    path = tmp / f"upload-{len(list(tmp.glob('*.nc')))}.nc"
    data.to_netcdf(path)
    return path.read_bytes()


def upload(env, data: bytes, **params):
    return env.client.post(
        "/external-forecasts",
        params={"name": "Colleague CNN", **params},
        content=data,
        headers={"content-type": "application/x-netcdf"},
    )


def test_an_upload_is_compared_now_and_verified_once_observed(env, fast_maps, monkeypatch):
    ours = run(env, "2026-09-14")
    start = date(2026, 9, 21)
    observed_by(monkeypatch, date(2026, 9, 25))  # the week has not been observed yet
    monkeypatch.setattr(chirps, "download", chc({}))
    response = upload(env, netcdf(env.tmp, start), file_name="cnn_week2.nc")
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["valid_start"] == "2026-09-21" and record["name"] == "Colleague CNN"
    assert record["read_as"] == ["the sum of its seven daily totals"]
    assert record["summary"]["region_mean_mm"] == 21.0 and record["coverage"] > 0.99
    assert record["verification_status"] == "waiting"
    comparison = record["comparison"]
    assert comparison["ours"]["forecast_id"] == ours["forecast_id"]
    assert comparison["verification"] is None and "2026-09-27" in comparison["waiting_for"]

    # CHIRPS covers the week: the verification pass scores both forecasts against it.
    monkeypatch.setattr(chirps, "download", chc(week(start)))
    observed_by(monkeypatch, date(2026, 10, 15))
    result = forecasts.ForecastService(env.platform).verify_due("Joe N")
    assert result["uploads_verified"] == 1
    scored = env.client.get(f"/external-forecasts/{record['id']}").json()
    assert scored["verification_status"] == "available"
    region = scored["comparison"]["verification"]["region"]
    assert region["Colleague CNN"]["mae_mm"] == 0.0  # 3 mm a day, as observed
    assert {"Colleague CNN", "ICPAC MBC"} <= set(region)
    closer = scored["comparison"]["verification"]["closer"]
    assert closer["region_lowest_mae"] == "Colleague CNN" and closer["uploaded_is_closer"]
    listed = env.client.get("/external-forecasts").json()
    assert [u["id"] for u in listed] == [record["id"]]

    # The Copilot answers from the comparison even without the AI service.
    answer = env.client.post(
        "/chat", json={"message": "Which came closer?", "external_id": record["id"]}
    ).json()
    assert "Against CHIRPS, Colleague CNN had the lowest mean absolute error" in answer["text"]
    card = answer["comparison"]
    assert card["status"] == "available" and card["scores"][0]["label"] == "Colleague CNN"
    assert any(row["closer"] == "theirs" for row in card["countries"])

    assert env.client.delete(f"/external-forecasts/{record['id']}").status_code == 204
    assert env.client.get("/external-forecasts").json() == []


def test_uploads_are_refused_with_a_reason(env, monkeypatch):
    monkeypatch.setattr(chirps, "download", chc({}))

    def detail(response):
        return response.json()["detail"]

    assert "not a NetCDF file" in detail(upload(env, b"hello"))
    undated = netcdf(env.tmp, None)
    assert "no dates" in detail(upload(env, undated))
    assert upload(env, undated, valid_start="2026-09-21").status_code == 201
    dated = netcdf(env.tmp, date(2026, 9, 21))
    assert "2026-09-21, not 2026-09-28" in detail(upload(env, dated, valid_start="2026-09-28"))
    rate = netcdf(env.tmp, date(2026, 9, 21), units="kg m-2 s-1")
    assert "rate per second" in detail(upload(env, rate))
    far = netcdf(env.tmp, date(2026, 9, 21), lat=np.arange(40.0, 50.0, 1.0))
    assert "does not overlap the ICPAC region" in detail(upload(env, far))
    monkeypatch.setattr(reader, "MAX_BYTES", 100)
    assert upload(env, dated).status_code == 413
    assert upload(env, dated, name="x").status_code == 422


def test_the_copilot_shows_the_comparison_in_the_conversation(env, fast_maps, claude, monkeypatch):
    monkeypatch.setattr(chirps, "download", chc({}))
    run(env, "2026-09-14")
    record = upload(env, netcdf(env.tmp, date(2026, 9, 21))).json()

    def script(request):
        results = tool_results(request)
        if not results:
            return [
                {"type": "tool_use", "id": "t0", "name": "compare_uploaded_forecast", "input": {}}
            ]
        return [{"type": "text", "text": f"Compared {results[0]['model']}."}]

    fake = claude(script)
    answer = Copilot(env.platform).answer(
        ChatRequest(message="How does my colleague's forecast compare?", external_id=record["id"])
    )
    assert answer["text"] == "Compared Colleague CNN." and answer["fallback"] is None
    assert answer["comparison"]["name"] == "Colleague CNN"
    assert answer["context"]["external_id"] == record["id"]
    seen = tool_results(fake.requests[-1])[0]
    assert seen["icpac_forecast_same_week"]["main_layer"]
    assert seen["valid_period"] == "21 September 2026 to 27 September 2026"


def test_the_reader_runs_apart_from_the_service(tmp_path):
    """No secret reaches the process that opens an uploaded file."""
    import os

    os.environ["DATABASE_URL"] = "postgresql://secret"
    try:
        path = tmp_path / "f.nc"
        path.write_bytes(netcdf(tmp_path, date(2026, 9, 21)))
        values, latitude, longitude, meta = reader.read_isolated(path)
    finally:
        del os.environ["DATABASE_URL"]
    assert values.shape == (LAT.size, LON.size) and meta["valid"]["first_day"] == "2026-09-21"
