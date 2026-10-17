"""Compare the full inference contract to a frozen HPC golden case, never fit it."""

import numpy as np

from climate_engine.operational.features import validate_feature_matrix


def compare(
    names: list[str],
    matrix: np.ndarray,
    residual: np.ndarray,
    hybrid: np.ndarray,
    golden,
    *,
    atol: float = 1e-6,
    rtol: float = 1e-6,
) -> dict:
    if not 0 <= atol <= 0.001 or not 0 <= rtol <= 0.001:
        raise ValueError("Parity tolerances must be finite and between zero and 0.001")
    expected_names = [str(name) for name in golden["names"]]
    if names != expected_names:
        raise ValueError("Golden feature names/order differ from the frozen schema")
    validate_feature_matrix(matrix, names, expected_names)
    expected_matrix = np.asarray(golden["features"])
    if expected_matrix.shape != matrix.shape or not np.isfinite(expected_matrix).all():
        raise ValueError("Golden features must cover the same full domain with finite values")
    difference = np.abs(matrix.astype(float) - expected_matrix.astype(float))
    matched = np.isclose(matrix, expected_matrix, atol=atol, rtol=rtol).all(axis=0)
    checks = {
        name: {
            "passed": bool(matched[index]),
            "max_absolute_difference": float(difference[:, index].max()),
        }
        for index, name in enumerate(names)
    }
    for name, actual in (("residual", residual), ("hybrid", hybrid)):
        expected = np.asarray(golden[name])
        if (
            expected.shape != actual.shape
            or actual.shape != (len(matrix),)
            or not np.isfinite(expected).all()
            or not np.isfinite(actual).all()
        ):
            raise ValueError(
                "Golden predictions must cover the same full domain with finite values"
            )
        checks[name] = {
            "passed": bool(np.allclose(actual, expected, atol=atol, rtol=rtol)),
            "max_absolute_difference": float(np.max(np.abs(actual - expected))),
        }
    return {
        "status": "passed" if all(value["passed"] for value in checks.values()) else "failed",
        "cells": len(matrix),
        "features": len(names),
        "atol": atol,
        "rtol": rtol,
        "checks": checks,
        "scope": "Numerical parity for one frozen input case; not independent forecast-skill validation or model promotion.",
    }
