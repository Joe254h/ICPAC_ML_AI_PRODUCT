from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


class ForecastModel(ABC):
    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def predict(self, dataset: xr.DataArray) -> xr.DataArray: ...

    @abstractmethod
    def metadata(self) -> dict: ...

    def health_check(self) -> bool:
        return True


class MockForecastModel(ForecastModel):
    def load(self) -> None:
        pass

    def predict(self, dataset: xr.DataArray) -> xr.DataArray:
        if dataset.attrs.get("feature_schema") != "rainfall_total_v1":
            raise ValueError("Feature schema mismatch")
        return (dataset * 0.83 + 1.2).assign_attrs(dataset.attrs)

    def metadata(self) -> dict:
        return {"model_type": "mock", "feature_schema": "rainfall_total_v1"}


class RawECMWFModel(MockForecastModel):
    def predict(self, dataset: xr.DataArray) -> xr.DataArray:
        return dataset.copy()

    def metadata(self) -> dict:
        return {"model_type": "raw", "feature_schema": "rainfall_total_v1"}


class ArtifactModel(ForecastModel):
    """Native model loading only. Pickle is deliberately unsupported."""

    def __init__(self, model_type: str, artifact: str, feature_schema: str):
        self.model_type, self.artifact, self.feature_schema = (
            model_type,
            Path(artifact),
            feature_schema,
        )
        self.estimator: Any = None

    def load(self) -> None:
        if not self.artifact.is_file():
            raise FileNotFoundError("Model artifact unavailable")
        if self.feature_schema != "rainfall_total_v1":
            raise ValueError("Add a versioned feature builder for this schema before inference")
        if self.model_type == "catboost":
            from catboost import CatBoostRegressor

            self.estimator = CatBoostRegressor()
            self.estimator.load_model(str(self.artifact))
        elif self.model_type == "lightgbm":
            import lightgbm

            self.estimator = lightgbm.Booster(model_file=str(self.artifact))
        elif self.model_type == "xgboost":
            from xgboost import XGBRegressor

            self.estimator = XGBRegressor()
            self.estimator.load_model(str(self.artifact))
        else:
            raise ValueError(f"{self.model_type} adapter requires a validated implementation")

    def predict(self, dataset: xr.DataArray) -> xr.DataArray:
        if dataset.attrs.get("feature_schema") != self.feature_schema:
            raise ValueError("Feature schema mismatch")
        if self.estimator is None:
            self.load()
        values = np.asarray(self.estimator.predict(dataset.values.reshape(-1, 1)))
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError("Model returned invalid rainfall")
        return dataset.copy(data=values.reshape(dataset.shape))

    def metadata(self) -> dict:
        return {"model_type": self.model_type, "feature_schema": self.feature_schema}

    def health_check(self) -> bool:
        return self.artifact.is_file()
