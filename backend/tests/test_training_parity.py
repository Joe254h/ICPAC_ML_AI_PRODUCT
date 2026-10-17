from typing import Any

import numpy as np
import pytest

from climate_engine.operational.parity import compare


def test_training_parity_checks_every_column_and_both_predictions():
    names = ["X_mean", "MBC_forecast"]
    features = np.array([[1, 2], [3, 4]], dtype=np.float32)
    residual = np.array([0.1, 0.2])
    hybrid = np.array([2.1, 4.2])
    golden: dict[str, Any] = {
        "names": names,
        "features": features.copy(),
        "residual": residual.copy(),
        "hybrid": hybrid.copy(),
    }
    assert compare(names, features, residual, hybrid, golden)["status"] == "passed"
    golden["features"][1, 0] += 1
    assert compare(names, features, residual, hybrid, golden)["checks"]["X_mean"]["passed"] is False
    golden["features"] = features.copy()
    golden["hybrid"][0] += 1
    assert compare(names, features, residual, hybrid, golden)["status"] == "failed"
    golden["names"] = names[::-1]
    with pytest.raises(ValueError, match="order"):
        compare(names, features, residual, hybrid, golden)


def test_training_parity_refuses_partial_domains_nonfinite_values_and_large_tolerances():
    data = np.ones((2, 1), dtype=np.float32)
    golden = {
        "names": ["MBC_forecast"],
        "features": data[:1],
        "residual": np.ones(2),
        "hybrid": np.ones(2),
    }
    with pytest.raises(ValueError, match="full domain"):
        compare(["MBC_forecast"], data, np.ones(2), np.ones(2), golden)
    for tolerance in (float("nan"), -1, 1):
        with pytest.raises(ValueError, match="tolerances"):
            compare(["MBC_forecast"], data, np.ones(2), np.ones(2), golden, atol=tolerance)
