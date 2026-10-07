from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("actor")
    @classmethod
    def named_reviewer(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("A named reviewer is required")
        return value


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


class DescriptorRegisterRequest(BaseModel):
    """Register a model version from its reviewed descriptor (config/model_registry/*.yaml)."""

    descriptor: str = Field(pattern=r"^[A-Za-z0-9_./-]+\.ya?ml$", max_length=200)
    actor: str = Field(default="registry", min_length=2, max_length=80)


class IndependentTestRequest(BaseModel):
    """Outcome of the independent test, run on the HPC and recorded once per model."""

    status: Literal["passed", "failed"]
    period: str = Field(pattern=r"^\d{4}-\d{4}$")
    report: str = Field(min_length=3, max_length=300)
    report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    metrics: dict[str, float] = Field(default_factory=dict)
    actor: str = Field(min_length=2, max_length=80)
    confirmed: bool = False
    comment: str = Field(default="", max_length=1000)

    @field_validator("actor")
    @classmethod
    def named_reviewer(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("A named reviewer is required")
        return value


class IngestRequest(BaseModel):
    source: Literal["CHIRPS", "TAMSAT", "RFE2"]
    path: str
    actor: str = Field(min_length=2, max_length=80)


FORECAST_ID = r"^w2-\d{4}-\d{2}-\d{2}-[0-9a-f]{8}$"


class ForecastRunRequest(BaseModel):
    """Run the operational Week-2 forecast for one initialization.

    ``ecmwf_files`` reads the documented input files for the date from FORECAST_INPUT_ROOT;
    ``synthetic_fixture`` generates labelled synthetic input (demonstration and tests,
    enabled only where ALLOW_SYNTHETIC_FORECASTS=true).
    """

    initialization: date
    source: Literal["ecmwf_files", "synthetic_fixture"] = "ecmwf_files"
    model_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]+$", max_length=80)
    actor: str = Field(min_length=2, max_length=80)


class PackageImportRequest(BaseModel):
    """Register a package written by scripts/run_operational.py under RUN_ROOT/forecasts."""

    forecast_id: str = Field(pattern=FORECAST_ID)
    actor: str = Field(min_length=2, max_length=80)


class VerificationRequest(BaseModel):
    """Observed Week-2 total (NetCDF inside DATA_ROOT) for a forecast's valid window."""

    observation: str = Field(pattern=r"^[A-Za-z0-9_./-]+\.nc$", max_length=200)
    actor: str = Field(min_length=2, max_length=80)
