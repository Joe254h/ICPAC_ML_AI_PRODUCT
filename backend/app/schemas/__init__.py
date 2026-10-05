from typing import Any, Literal

from pydantic import BaseModel, Field


class Selection(BaseModel):
    cycle: str = "2026-09-28"
    observation: Literal["CHIRPS", "TAMSAT", "RFE2"] = "CHIRPS"
    model: str = "mock-v1"
    provider: str = "ECMWF S2S"
    country: str = "GHA"
    layer: Literal["corrected", "raw", "observed", "bias", "rmse", "improvement", "anomaly"] = (
        "corrected"
    )


class QCResult(BaseModel):
    status: str
    dataset: str
    checks: dict[str, Any]
    warnings: list[str]
    errors: list[str]


class ForecastResponse(BaseModel):
    selection: Selection
    label: str
    period: str
    metrics: dict[str, float | int | None]
    mean_rainfall_mm: float | None
    anomaly_percent: float | None
    countries: list[dict[str, Any]]
    model_comparison: list[dict[str, Any]]
    observation_comparison: list[dict[str, Any]]
    timeseries: list[dict[str, Any]]
    map: dict[str, Any]
    provenance: dict[str, Any]
    qc: list[QCResult]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    selection: Selection = Field(default_factory=Selection)


class ReviewRequest(BaseModel):
    actor: str = Field(min_length=2, max_length=80)
    confirmed: bool = False
    comment: str = Field(default="", max_length=1000)


class RegisterRequest(BaseModel):
    model_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=80)
    model_name: str
    version: str
    model_type: str
    artifact_path: str
    feature_schema: str
    training_period: str = "not supplied"
    validation_period: str = "not supplied"
    notes: str = ""
