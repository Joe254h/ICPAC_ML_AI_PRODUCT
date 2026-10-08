"""Copilot evidence and sentences for the operational forecast (the model in use).

Values come from the latest forecast package: its interpretation facts, its verification
record, the model registry and the rainfall classes the weekly bulletin derives from the
forecast grid. Nothing here estimates a value the package does not hold.
"""

from typing import Any

from backend.app.services.forecasts import ForecastService
from climate_engine.products import weekly_bulletin as weekly
from climate_engine.products.bulletin import BulletinInputs

GHA = "GHA"
METHOD_NAMES = {"MBC + ATMOS37 CATBOOST": "MBC + Atmos37 CatBoost"}
SCHEMA_NAMES = {"atmos37": "Atmos37"}
CLASS_KEYS = ("heavy", "moderate", "light")
MISSING_PRODUCTS = (
    "Rainfall anomaly, exceptional rainfall, temperature and heat-stress products are not "
    "available for this forecast."
)


def latest_record(platform) -> dict[str, Any] | None:
    """The newest forecast package (real input first), or None before the first run."""
    service = ForecastService(platform)
    if not service.runs():
        return None
    return service.latest()


def forecast_evidence(platform, record: dict[str, Any], area: str) -> dict[str, Any]:
    facts = record["interpretation"]
    service = ForecastService(platform)
    inputs = BulletinInputs.from_package(service.directory(record["forecast_id"]))
    grid = weekly.read_layer(inputs, "hybrid")
    masks = weekly.country_masks(grid)
    if area != GHA:
        masks = {name: mask for name, mask in masks.items() if name == area}
    classes = (
        weekly.rainfall_bullets(grid, masks, weekly.LEADS, weekly.REGION if area == GHA else area)
        if masks
        else []
    )
    return {
        "forecast_id": record["forecast_id"],
        "area": area,
        "initialization": facts["initialization"],
        "valid_start": facts["valid_start"],
        "valid_end": facts["valid_end"],
        "period": weekly.period_label(facts["valid_start"], facts["valid_end"]),
        "method": facts["method"]["label"],
        "model": facts["model"],
        "input": facts["input"],
        "domain_mean_mm": facts["domain_mean_mm"] if area == GHA else None,
        "country": next((r for r in facts["countries"] if r["country"] == area), None),
        "rainfall_classes": [lead + rest for lead, rest in classes],
        "verification": record["verification"],
    }


def model_evidence(platform, model_id: str) -> dict[str, Any]:
    record = platform.repo.get("model", model_id)
    keys = (
        "model_id",
        "model_name",
        "version",
        "status",
        "test_status",
        "trees",
        "feature_count",
        "feature_schema",
        "training_period",
        "validation_period",
        "test_period",
        "checksum",
        "metrics",
        "metrics_scope",
    )
    return {key: record.get(key) for key in keys}


def method_name(evidence: dict[str, Any]) -> str:
    return METHOD_NAMES.get(evidence["method"], evidence["method"])


def scope(evidence: dict[str, Any]) -> str:
    model = evidence["model"]
    source = (
        "synthetic test input, not a forecast of real weather"
        if evidence["input"]["synthetic"]
        else evidence["input"]["label"]
    )
    return (
        f"{evidence['area']} · Week-2 forecast for {evidence['period']} "
        f"(initialised {evidence['initialization']}) · {model['model_id']}, {model['role']} · "
        f"{source}."
    )


def limitations(evidence: dict[str, Any]) -> str:
    model = evidence["model"]
    parts = (
        [
            f"{model['model_id']} is a {model['status']} model, not the production model; "
            "this is a draft for forecaster review."
        ]
        if model["status"] != "production"
        else ["Forecaster review is required before release."]
    )
    parts.append(MISSING_PRODUCTS)
    return " ".join(parts)


def _mm(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.1f} mm"


def amount(evidence: dict[str, Any]) -> str:
    name = method_name(evidence)
    row = evidence["country"]
    if row is not None:
        return (
            f"{name} mean rainfall over {row['country']}: {_mm(row['hybrid_mean_mm'])} for "
            f"the week (median {_mm(row['hybrid_median_mm'])}, grid-cell range "
            f"{_mm(row['hybrid_min_mm'])} to {_mm(row['hybrid_max_mm'])}); MBC alone "
            f"{_mm(row['mbc_mean_mm'])}, raw ECMWF {_mm(row['raw_mean_mm'])}."
        )
    means = evidence["domain_mean_mm"] or {}
    return (
        f"{name} mean rainfall over the GHA domain: {_mm(means.get('hybrid'))} for the week; "
        f"MBC alone {_mm(means.get('mbc'))}, raw ECMWF {_mm(means.get('raw'))}."
    )


def verification(evidence: dict[str, Any]) -> str:
    record = evidence["verification"] or {}
    if record.get("status") != "available":
        reason = record.get("reason", "no observed Week-2 total has been supplied")
        return f"Not verified yet: {reason[0].lower() + reason[1:]}."
    area = evidence["area"]
    scores = record["domain"] if area == GHA else record.get("countries", {}).get(area)
    if not scores:
        return f"Verified over the domain, but {area} has no verified cells."
    hybrid, mbc, raw = scores["hybrid"], scores["mbc"], scores["raw"]
    observation = (record.get("observation") or {}).get("file", "the observed total")
    correlation = (
        "undefined" if hybrid.get("correlation") is None else f"{hybrid['correlation']:.3f}"
    )
    return (
        f"Against {observation}: {method_name(evidence)} RMSE {hybrid['rmse']:.2f} mm, MAE "
        f"{hybrid['mae']:.2f} mm, bias {hybrid['bias']:.2f} mm, spatial correlation "
        f"{correlation}; MBC RMSE {mbc['rmse']:.2f} mm, raw ECMWF RMSE {raw['rmse']:.2f} mm. "
        "This is one Week-2 case, not long-term skill."
    )


def forecast_sentences(evidence: dict[str, Any]) -> dict[str, str]:
    sentences = {"scope": scope(evidence), "amount": amount(evidence)}
    sentences.update(zip(CLASS_KEYS, evidence["rainfall_classes"], strict=False))
    sentences["verification"] = verification(evidence)
    sentences["limitations"] = limitations(evidence)
    return sentences


def comparison_sentences(evidence: dict[str, Any]) -> dict[str, str]:
    sentences = {"scope": scope(evidence), "amount": amount(evidence)}
    sentences["verification"] = verification(evidence)
    sentences["caution"] = (
        "One forecast cannot establish which method is better; promotion to production needs "
        "the independent 2022-2024 test and a named reviewer."
    )
    sentences["limitations"] = limitations(evidence)
    return sentences


def model_sentences(model: dict[str, Any]) -> dict[str, str]:
    metrics = model.get("metrics") or {}
    sentences = {
        "model": (
            f"{model['model_name']} ({model['model_id']}) version {model['version']}: "
            f"{model['trees']} CatBoost trees on {model['feature_count']} "
            f"{SCHEMA_NAMES.get(model['feature_schema'], model['feature_schema'])} features, "
            f"trained {model['training_period']} and "
            f"validated {model['validation_period']}."
        ),
        "status": (
            f"Status {model['status']}; independent {model['test_period']} test "
            f"{model['test_status']}."
        ),
        "artifact": f"Model artifact checksum: {model['checksum']}.",
    }
    if {"rainfall_RMSE", "rainfall_MAE", "rainfall_pearson_r"} <= set(metrics):
        sentences["validation"] = (
            f"Validation {model['validation_period']}: rainfall RMSE "
            f"{metrics['rainfall_RMSE']:.2f} mm, MAE {metrics['rainfall_MAE']:.2f} mm, "
            f"Pearson r {metrics['rainfall_pearson_r']:.3f}."
        )
    return sentences
