"""Probabilistic verification: member probabilities, reliability, ROC, Brier skill and the
95% intervals from resampling weeks."""

import numpy as np
import xarray as xr

from backend.app.services import forecasts
from backend.tests.test_forecasts import env as env
from backend.tests.test_forecasts import fast_maps as fast_maps
from backend.tests.test_forecasts import run, write_observation
from climate_engine.verification import probabilistic


def week(members: int, rng, skill: float) -> list[list[int]]:
    """A week's table from cells whose event follows the forecast probability with the
    given skill (1: reliable, 0: no relation)."""
    counts = rng.integers(0, members + 1, size=5000)
    chance = skill * counts / members + (1 - skill) * 0.3
    event = rng.random(5000) < chance
    observed = np.where(event, 30.0, 0.0)
    return probabilistic.table(counts, members, observed, 25.0)


def test_a_reliable_ensemble_scores_well_and_a_useless_one_does_not():
    rng = np.random.default_rng(1)
    reliable = probabilistic.summary([week(10, rng, 1.0) for _ in range(8)], 10)
    assert reliable["weeks"] == 8 and reliable["auc"] > 0.75
    assert reliable["brier_skill"] > 0.1
    for row in reliable["reliability"]:
        assert abs(row["observed"] - row["probability"]) < 0.06
        assert row["interval"][0] <= row["observed"] <= row["interval"][1]
    low, high = reliable["auc_interval"]
    assert low <= reliable["auc"] <= high
    useless = probabilistic.summary([week(10, rng, 0.0) for _ in range(8)], 10)
    assert abs(useless["auc"] - 0.5) < 0.05 and useless["brier_skill"] < 0.02
    # The ROC points run from the strictest warning (all members) to the loosest.
    rates = [p["hit_rate"] for p in reliable["roc"]]
    assert rates == sorted(rates, reverse=True)


def test_too_few_weeks_give_no_interval():
    rng = np.random.default_rng(2)
    two = probabilistic.summary([week(10, rng, 1.0) for _ in range(2)], 10)
    assert two["weeks"] == 2 and "auc_interval" not in two
    assert probabilistic.mean_interval([12.0, 14.0])["interval"] is None
    held = probabilistic.mean_interval([12.0, 14.0, 13.0, 15.0])
    assert held["mean"] == 13.5 and held["interval"][0] <= 13.5 <= held["interval"][1]
    change = probabilistic.change_interval([9.0, 10.0, 11.0], [10.0, 12.0, 13.0])
    assert round(change["change"], 3) == round(30 / 35 - 1, 3) and change["interval"]


def test_a_forecast_keeps_member_probabilities_and_its_verification_scores_them(env, fast_maps):
    record = run(env)
    directory = forecasts.package_root() / record["forecast_id"]
    with xr.open_dataset(directory / "forecast.nc") as stored:
        data = stored.load()
    members = int(data.attrs["probability_members"])
    assert members >= 2
    assert list(data["threshold_mm"].values) == [10.0, 25.0, 50.0]
    for layer in ("raw", "mbc", "hybrid"):
        counts = data[f"members_above_{layer}"].values
        assert counts.dtype == np.int8 and counts.max() <= members
    name = write_observation(env, record, "obs.nc")
    verified = env.client.post(
        f"/forecasts/{record['forecast_id']}/verification",
        json={"observation": name, "actor": "Joe"},
    )
    assert verified.status_code == 200, verified.text
    tables = verified.json()["probabilistic"]
    assert tables["members"] == members
    assert len(tables["tables"]["hybrid"]["25"]) == members + 1
    summary = env.client.get("/verification/probabilistic?layer=hybrid&threshold=25").json()
    assert summary["weeks"] == 1 and summary["observed_by"] == {"CHIRPS": 1}
    assert len(summary["reliability"]) == members + 1 and "auc_interval" not in summary
    means = env.client.get("/verification/summary").json()
    assert means["weeks"] == 1 and means["series"][0]["observed_by"] == "CHIRPS"
    assert means["layers"]["hybrid"]["rmse"]["mean"] >= 0
    assert "rmse_change_vs_raw" in means["layers"]["hybrid"]
    assert env.client.get("/verification/probabilistic?layer=other").status_code == 422
