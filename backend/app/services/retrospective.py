"""The typical error (RMSE) of each layer of a forecast, from the frozen 2022-2024 scores.

The figures come from the checksum-verified evidence sets in ``evidence``: the final
refit's retrospective comparison (2022-2024 had been consulted to choose the policy, so it
is not an independent test) or the pre-refit models' independent test. A forecast gets the
set that describes its own model; any other model gets nothing.

The month figure is pooled from the per-case sums by the forecast's issue (initialization)
month, the cases' own grouping. Country figures cover all months. The two stay separate:
a country figure is never adjusted by month, and none of them is the error of this
particular week, which is known only once the week is verified.
"""

from __future__ import annotations

from typing import Any

from backend.app.services import evidence
from climate_engine.models.hybrid7_pc17 import INDEPENDENT_ROW

KIND = {
    "refit": "retrospective (post-selection, not an independent test)",
    "prerefit": "independent test",
}


def table_models(provenance: dict[str, Any]) -> dict[str, str]:
    """The evidence row of each layer of this forecast's model."""
    out = {"mbc": "MBC", "raw": "RawECMWF"}
    policy = (provenance.get("hybrid_policy") or {}).get("policy")
    if policy in INDEPENDENT_ROW and policy != "mbc_only":
        out["hybrid"] = INDEPENDENT_ROW[policy]
    return out


def _score(item: dict[str, Any] | None) -> dict[str, float] | None:
    if not item or item.get("rmse") is None:
        return None
    return {
        key: round(float(item[key]), 2)
        for key in ("rmse", "mae", "bias")
        if item.get(key) is not None
    }


def _pick(items: list[dict[str, Any]], model: str) -> dict[str, float] | None:
    return _score(next((item for item in items if item["model"] == model), None))


def summary(model_id: str | None, provenance: dict[str, Any], month: int) -> dict[str, Any] | None:
    """RMSE (with MAE and bias) per layer: all cases, the issue month and each country."""
    which = next((s.key for s in evidence.SETS.values() if model_id in s.model_ids), None)
    if which is None:
        return None
    try:
        body = evidence.summary(which)
    except (evidence.EvidenceError, OSError, KeyError, ValueError):
        return None
    layers: dict[str, Any] = {}
    for layer, model in table_models(provenance).items():
        overall = _pick(body["regional"], model)
        if overall is None:
            continue
        layers[layer] = {
            "all": overall,
            "month": _pick(body["monthly"].get(f"{month:02d}", []), model),
            "countries": {
                country: score
                for country, items in body["countries"].items()
                if (score := _pick(items, model)) is not None
            },
        }
    if not layers:
        return None
    return {
        "set": which,
        "label": f"Typical grid-cell error (RMSE), 2022–2024 {KIND[which]}",
        "kind": KIND[which],
        "month": month,
        "month_basis": "forecast issue month",
        "reference": "CHIRPS",
        "units": "mm/week",
        "layers": layers,
        "note": "The average size of a grid cell's error over 2022–2024 reforecasts, not the "
        "error of this week and not a range around the mean.",
    }
