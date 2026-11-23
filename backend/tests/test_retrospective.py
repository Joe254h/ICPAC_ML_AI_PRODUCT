"""The forecast page's typical error comes from the verified 2022-2024 tables."""

import csv

from backend.app.services import evidence, retrospective

REFIT = "icpac_week2_catboost_refit_v1"
HYBRID = {"hybrid_policy": {"policy": "catboost_full"}}


def _monthly(model: str, month: int) -> float:
    path = evidence.SETS["refit"].directory / "tables" / "MONTHLY_METRICS.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["model"] == model and row["dimension_1"] == str(month):
                return float(row["rmse"])
    raise AssertionError(model)


def test_refit_layers_match_the_published_tables():
    s = retrospective.summary(REFIT, HYBRID, 11)
    assert s is not None and s["set"] == "refit"
    assert "not an independent test" in s["label"]
    assert s["layers"]["hybrid"]["all"]["rmse"] == 15.16
    assert s["layers"]["mbc"]["all"]["rmse"] == 15.36
    assert s["layers"]["raw"]["all"]["rmse"] == 17.27
    for layer, model in (("hybrid", "CatBoost"), ("mbc", "MBC")):
        assert abs(s["layers"][layer]["month"]["rmse"] - _monthly(model, 11)) < 0.01
    assert len(s["layers"]["hybrid"]["countries"]) == 11
    assert s["layers"]["hybrid"]["countries"]["Kenya"]["rmse"] == 20.34


def test_policy_picks_the_row_and_mbc_only_has_no_hybrid():
    blend = retrospective.summary(REFIT, {"hybrid_policy": {"policy": "global_alpha075"}}, 1)
    assert blend is not None
    assert blend["layers"]["hybrid"]["all"]["rmse"] == 15.16
    mbc = retrospective.summary(REFIT, {"hybrid_policy": {"policy": "mbc_only"}}, 1)
    assert mbc is not None
    assert "hybrid" not in mbc["layers"] and "mbc" in mbc["layers"]


def test_prerefit_is_the_independent_test_and_others_get_nothing():
    s = retrospective.summary("icpac_week2_catboost_prerefit_v1", HYBRID, 3)
    assert s is not None
    assert s["kind"] == "independent test"
    assert s["layers"]["hybrid"]["all"]["rmse"] == 15.2
    assert retrospective.summary("demo_model", HYBRID, 3) is None
    assert retrospective.summary(None, HYBRID, 3) is None
