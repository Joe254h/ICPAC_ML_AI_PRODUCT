import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    # The Copilot answers from operational forecasts only.
    context_mode: Literal["operational"] = "operational"
    forecast_id: str | None = Field(default=None, pattern=r"^w2-\d{4}-\d{2}-\d{2}-[0-9a-f]{8}$")
    country: str | None = Field(default=None, max_length=80)
    variant: Literal["hybrid", "mbc", "raw"] | None = None
    reset_context: bool = False
    #: The name the person gave, for the drafts the Copilot writes at their request.
    actor: str | None = Field(default=None, max_length=80)
    #: An uploaded forecast of another model the question is about.
    external_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    #: The answer's language (chatbot.agent.LANGUAGES).
    language: Literal["en", "sw", "am", "so", "ar", "fr", "ti", "om", "rw", "rn", "lg"] = "en"
    #: Files attached to this question (chatbot/attachments.py).
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)
    #: Editing an earlier question: the position of that question in the conversation;
    #: it and everything after it are replaced by this question and its answer.
    edit_index: int | None = Field(default=None, ge=0, le=200)

    @field_validator("attachment_ids")
    @classmethod
    def attachment_identifiers(cls, value: list[str]) -> list[str]:
        for item in value:
            if not re.fullmatch(r"[0-9a-f-]{36}", item):
                raise ValueError("Unknown attachment")
        return value

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a message")
        return value


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


class RealtimeReviewRequest(BaseModel):
    """A reviewer confirms (or withdraws) that a real-time ECMWF input source is compatible
    with a frozen model, naming a run of that model whose input checks all passed."""

    source: Literal["ecmwf_opendata", "ecmwf_files"]
    forecast_id: str | None = Field(default=None, pattern=r"^w2-\d{4}-\d{2}-\d{2}-[0-9a-f]{8}$")
    withdraw: bool = False
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


class DescriptorRegisterRequest(BaseModel):
    """Register a model version from its reviewed descriptor (config/model_registry/*.yaml)."""

    descriptor: str = Field(
        pattern=r"^config/model_registry/[A-Za-z0-9_.-]+\.ya?ml$", max_length=200
    )
    actor: str = Field(default="registry", min_length=2, max_length=80)

    @field_validator("descriptor")
    @classmethod
    def inside_registry(cls, value: str) -> str:
        if ".." in value:
            raise ValueError("Descriptors are read from config/model_registry only")
        return value


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


FORECAST_ID = r"^w2-\d{4}-\d{2}-\d{2}-[0-9a-f]{8}$"


class ForecastRunRequest(BaseModel):
    """Run the operational Week-2 forecast for one initialization (00 UTC).

    ``ecmwf_opendata`` downloads the ECMWF ensemble rainfall from ECMWF Open Data when it is
    not already in FORECAST_INPUT_ROOT (the newest published run if no date is given);
    ``ecmwf_files`` uses files placed there by the documented naming convention.
    """

    initialization: date | None = None
    source: Literal["ecmwf_opendata", "ecmwf_files"] = "ecmwf_opendata"
    model_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]+$", max_length=80)
    actor: str = Field(min_length=2, max_length=80)


class OperationRequest(BaseModel):
    """A background operational task (see backend/app/services/operations.py)."""

    action: Literal[
        "fetch_ecmwf",
        "run_forecast",
        "verify_due",
        "verify_forecast",
        "update_chirps",
        "cycle",
        "end_to_end",
        "past_weeks",
        "check_ecmwf",
        "observations",
        "refresh_archive",
    ]
    initialization: date | None = None
    forecast_id: str | None = Field(default=None, pattern=FORECAST_ID)
    #: past_weeks: how many past weeks to forecast and verify; refresh_archive: how many of
    #: the newest ECMWF runs to bring up to the model in use.
    weeks: int = Field(default=4, ge=1, le=12)
    #: The registered model to forecast with (run_forecast, cycle, end_to_end, past_weeks,
    #: refresh_archive); empty: the model in use.
    model_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]+$", max_length=80)
    actor: str = Field(min_length=2, max_length=80)


class UploadStartRequest(BaseModel):
    """A file sent in parts (backend/app/services/staged_uploads.py)."""

    purpose: Literal["model", "attachment"]
    name: str = Field(min_length=1, max_length=200)
    size: int = Field(gt=0)


class UploadFinishRequest(BaseModel):
    upload_id: str = Field(pattern=r"^[0-9a-f-]{32,36}$")


class StopRequest(BaseModel):
    """Who stops a task (the name typed in the public evaluation app)."""

    actor: str | None = Field(default=None, max_length=80)


class PackageImportRequest(BaseModel):
    """Register a package written by scripts/run_operational.py under RUN_ROOT/forecasts."""

    forecast_id: str = Field(pattern=FORECAST_ID)
    actor: str = Field(min_length=2, max_length=80)


class VerificationRequest(BaseModel):
    """Observed Week-2 total (NetCDF inside DATA_ROOT) for a forecast's valid window."""

    observation: str = Field(pattern=r"^[A-Za-z0-9_./-]+\.nc$", max_length=200)
    actor: str = Field(min_length=2, max_length=80)


class EmailActionRequest(BaseModel):
    """A decision taken from an emailed link: the link's token and who confirmed it."""

    token: str = Field(min_length=20, max_length=600)
    decision: Literal["approve", "reject", "publish"]
    name: str | None = Field(default=None, max_length=60)
    comment: str | None = Field(default=None, max_length=1000)


class ResendRequest(BaseModel):
    actor: str = Field(min_length=2, max_length=80)


class BulletinSectionEdit(BaseModel):
    section: Literal["headline", "decision_support", "rainfall", "focus"]
    paragraphs: list[str] = Field(min_length=1, max_length=12)
    why: str | None = Field(default=None, max_length=1200)


class BulletinNote(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    paragraphs: list[str] = Field(min_length=1, max_length=12)


class BulletinEditRequest(BaseModel):
    """A forecaster's edit of a weekly bulletin draft on the website."""

    changes: list[BulletinSectionEdit] = Field(default_factory=list, max_length=4)
    add_notes: list[BulletinNote] = Field(default_factory=list, max_length=6)
    remove_notes: list[str] = Field(default_factory=list, max_length=6)
    summary: str = Field(default="", max_length=300)
    actor: str | None = Field(default=None, max_length=80)


class BulletinTranslateRequest(BaseModel):
    language: Literal["sw", "am", "so", "ar", "fr", "ti", "om", "rw", "rn", "lg"]
    actor: str | None = Field(default=None, max_length=80)


class BulletinRequest(BaseModel):
    """Generate the weekly bulletin draft of a forecast (the latest by default)."""

    forecast_id: str | None = Field(default=None, pattern=FORECAST_ID)
    actor: str = Field(default="forecaster", min_length=2, max_length=80)
