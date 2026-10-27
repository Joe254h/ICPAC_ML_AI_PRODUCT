"""The ECMWF readiness page and the frozen experimental verification, through the API."""

import shutil
from dataclasses import replace
from datetime import date

import pytest

from backend.app.services import evidence
from backend.tests.test_forecasts import env as env
from backend.tests.test_forecasts import fast_maps as fast_maps
from backend.tests.test_forecasts import run
from backend.tests.test_inputs import mirror as mirror
from backend.tests.test_inputs import wait


def test_readiness_reports_only_recorded_states(env, fast_maps):
    client = env.client
    ready = client.get("/data/ecmwf/readiness").json()
    assert ready["availability"] is None  # never checked: nothing is assumed
    assert ready["rainfall"]["status"] == "missing"
    assert ready["compatibility"]["status"] == "unchecked"
    assert ready["generation"]["raw_mbc"]["allowed"] is False
    assert ready["model"]["model_id"] == "test_mbc_atmos37_catboost_v1"
    run(env)
    ready = client.get("/data/ecmwf/readiness").json()
    assert ready["rainfall"]["status"] == "available"
    assert ready["rainfall"]["type"] == "operator-supplied files"
    assert ready["last_run"]["hybrid"] == {"status": "available"}
    assert ready["compatibility"]["status"] == "compatible"
    assert ready["generation"]["raw_mbc"]["allowed"] is True


def test_check_ecmwf_records_the_published_run(env, mirror, monkeypatch):
    client = env.client
    operation = client.post(
        "/operations",
        json={"action": "check_ecmwf", "initialization": "2026-10-05", "actor": "Joe N"},
    ).json()
    done = wait(client, operation)
    assert done["status"] == "complete", done
    ready = client.get("/data/ecmwf/readiness").json()
    availability = ready["availability"]
    assert availability["status"] == "published"
    assert availability["initialization"] == "2026-10-05"
    assert availability["checked_by"]  # the signed-in operator
    assert availability["upper_air_listed"] is False  # the mirror holds rainfall only


def test_the_experimental_verification_is_served_from_the_frozen_tables(env):
    """The pre-refit model's independent 2022-2024 test, one of the two frozen sets."""
    client = env.client
    body = client.get("/verification/experimental?set=prerefit").json()
    assert body["set"] == "prerefit" and body["scope"]["kind"] == "independent"
    assert body["scope"]["cases"] == 551 and body["scope"]["rows"] == 113285600
    regional = {s["model"]: s for s in body["regional"]}
    assert regional["CatBoost"]["rmse"] == pytest.approx(15.203976, abs=1e-6)
    assert regional["MAMProtected"]["rmse"] == pytest.approx(15.270882, abs=1e-6)
    assert regional["RawECMWF"]["rmse"] == pytest.approx(17.268974, abs=1e-6)
    assert regional["TrainingClimatology"]["rmse"] == pytest.approx(17.613541, abs=1e-6)
    assert min(regional.values(), key=lambda s: s["rmse"])["model"] == "CatBoost"
    crps = {c["id"]: c["crps_mmweek"] for c in body["ensemble"]["crps"]}
    assert crps["ALL"] == pytest.approx(6.772580, abs=1e-6)
    assert "skill score" in body["ensemble"]["note"]
    assert sorted(body["ensemble"]["reliability"]) == ["1", "10", "100", "25", "50"]
    assert [c["id"] for c in body["ensemble"]["crps"]][:5] == ["ALL", "DJF", "MAM", "JJA", "SON"]
    # Monthly scores pool the per-case sums exactly: their union is the regional score.
    assert sum(item["cases"] for items in body["monthly"].values() for item in items) == 551 * 7
    assert sorted(body["thresholds_mmweek"]) == [1.0, 10.0, 25.0, 50.0, 100.0]
    assert {c["model"] for c in body["deterministic_roc"]} >= {"CatBoost", "MBC"}
    assert all(len(c["curve"]) <= 80 for c in body["deterministic_roc"])
    assert body["sudan"]["cells_outside_vector"] == 813
    assert body["comparison"] is None and body["figures"] == []
    png = client.get("/verification/experimental/maps/added_value_mbc?set=prerefit")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    path = "/verification/experimental/maps/country-south-sudan?set=prerefit"
    assert client.get(path).status_code == 200
    assert client.get("/verification/experimental/maps/secrets").status_code == 422


def test_the_refit_comparison_is_served_as_retrospective(env):
    """The final refit's 2022-2024 scores: retrospective, beside the pre-refit model's."""
    client = env.client
    body = client.get("/verification/experimental?set=refit").json()
    assert body["set"] == "refit" and body["scope"]["kind"] == "retrospective"
    assert "not a new independent test" in body["scope"]["statement"]
    assert body["scope"]["training"] == "2005–2021" and body["scope"]["training_cases"] == 3148
    regional = {s["model"]: s for s in body["regional"]}
    assert regional["CatBoost"]["rmse"] == pytest.approx(15.156135, abs=1e-6)
    assert regional["MBC"]["rmse"] == pytest.approx(15.363620, abs=1e-6)
    assert regional["CatBoost"]["skill_vs_raw"] == pytest.approx(1 - 15.156135 / 17.268974)
    assert "LightGBM" not in regional  # not refitted: never shown as if it were
    compared = {c["model"]: c for c in body["comparison"]["items"]}
    assert compared["CatBoost"]["prerefit_rmse"] == pytest.approx(15.203976, abs=1e-6)
    assert compared["CatBoost"]["refit_rmse"] == pytest.approx(15.156135, abs=1e-6)
    assert compared["CatBoost"]["low"] < 0 < compared["CatBoost"]["high"]
    assert sum(item["cases"] for items in body["monthly"].values() for item in items) == 551 * 6
    assert len(body["figures"]) == 22 and len(body["maps"]) == 8 and body["country_rain_maps"]
    for path in (
        "maps/regimes",
        "maps/rain-south-sudan",
        "maps/country-kenya",
        "figures/12-paired-old-vs-refit-ci-forest",
    ):
        png = client.get(f"/verification/experimental/{path}?set=refit")
        assert png.status_code == 200 and png.content[:4] == b"\x89PNG", path
    assert client.get("/verification/experimental/figures/../../x").status_code == 404
    assert client.get("/verification/experimental?set=other").status_code == 422
    # Without a set: the one describing the model in use.
    default = client.get("/verification/experimental").json()
    assert default["set"] in ("refit", "prerefit")
    assert isinstance(default["describes_model_in_use"], bool)


def test_changed_evidence_is_refused(tmp_path, monkeypatch):
    copy = tmp_path / "evidence"
    original = evidence.SETS["prerefit"]
    shutil.copytree(original.directory, copy)
    monkeypatch.setitem(evidence.SETS, "prerefit", replace(original, directory=copy))
    evidence.rows("T01_independent_regional_metrics.csv", "prerefit")
    table = copy / "tables" / "T01_independent_regional_metrics.csv"
    table.write_text(table.read_text().replace("15.20", "14.20", 1))
    with pytest.raises(evidence.EvidenceError, match="changed after it was frozen"):
        evidence.rows("T01_independent_regional_metrics.csv", "prerefit")
    with pytest.raises(evidence.EvidenceError, match="not part of the frozen evidence"):
        evidence.verified_file("tables/../../SHA256SUMS.txt", "prerefit")
    with pytest.raises(evidence.EvidenceError, match="No frozen evidence set"):
        evidence.summary("latest")


def test_the_realtime_gate_date_is_inclusive():
    from climate_engine.models.hybrid7_pc17 import MBCHybrid7PC17CatBoost

    model = MBCHybrid7PC17CatBoost.__new__(MBCHybrid7PC17CatBoost)
    model.realtime_from = date(2025, 1, 1)
    assert model.realtime_gated(date(2025, 1, 1)) and not model.realtime_gated(date(2024, 12, 31))


def test_a_map_downloads_as_pdf(env):
    import io

    from PIL import Image

    from backend.app.api.forecasts import pdf_of

    image = io.BytesIO()
    Image.new("RGBA", (40, 30), (20, 120, 60, 255)).save(image, format="PNG")
    assert pdf_of(image.getvalue())[:5] == b"%PDF-"
    record = run(env)
    response = env.client.get(f"/forecasts/{record['forecast_id']}/map?layer=mbc&format=pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"
    assert "icpac-week2-mbc.pdf" in response.headers["content-disposition"]
    bad = env.client.get(f"/forecasts/{record['forecast_id']}/map?layer=mbc&format=svg")
    assert bad.status_code == 422


def test_the_hybrid_status_follows_the_model_in_use():
    """A frozen bundle states its own upper-air hours; from 2025 its AI/ML layer waits for
    the reviewer's real-time confirmation; the MBC-only policy never produces one."""
    from backend.app.services.forecasts import REALTIME_CONFIRMATION, hybrid_status

    bundle = {
        "policy": "catboost_full",
        "pressure_steps_hours": [192, 216, 240, 264, 288, 312, 336],
        "model_info": {"realtime_gate_from": "2025-01-01"},
    }
    assert hybrid_status(bundle) == {"status": "in_progress", "reason": REALTIME_CONFIRMATION}
    confirmed = {**bundle, "realtime_reviews": {"ecmwf_opendata": {"actor": "Joe254h"}}}
    assert hybrid_status(confirmed) == {"status": "available", "reason": None}
    assert hybrid_status({**bundle, "policy": "mbc_only"})["status"] == "not_produced"
    # A model without its own hours needs the configured ones (unset in this release).
    assert hybrid_status({"policy": None})["status"] == "in_progress"
    assert hybrid_status()["status"] == "in_progress"
