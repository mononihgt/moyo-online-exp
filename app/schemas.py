from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from .timeutil import parse_datetime


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True, extra="forbid")


class LoginRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=5, max_length=30)


class ConsentRequest(ApiModel):
    version_id: str
    agree: bool


class AdminLoginRequest(ApiModel):
    username: str
    password: str


class ParticipantPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["eligible", "completed", "disabled"] | None = None
    notes: str | None = None


class ConsentVersionCreate(ApiModel):
    markdown: str


class ConsentVersionPatch(ApiModel):
    markdown: str


class ConditionVersionCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    rows: int
    cols: int
    cells: list[dict[str, Any]]
    visuals: dict[str, Any]
    base_a_index: int
    base_b_index: int
    trial_params: list[dict[str, Any]]
    practice_trials: int
    formal_trials: int
    turn_count: int
    turn_seconds: int
    rest_seconds: int
    randomize_formal: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConditionVersionPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    rows: int | None = None
    cols: int | None = None
    cells: list[dict[str, Any]] | None = None
    visuals: dict[str, Any] | None = None
    base_a_index: int | None = None
    base_b_index: int | None = None
    trial_params: list[dict[str, Any]] | None = None
    practice_trials: int | None = None
    formal_trials: int | None = None
    turn_count: int | None = None
    turn_seconds: int | None = None
    rest_seconds: int | None = None
    randomize_formal: bool | None = None
    metadata: dict[str, Any] | None = None


class InstructionVersionCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    role: Literal[1, 2]
    markdown: str
    min_reading_seconds: int = Field(default=120, ge=0)


class InstructionVersionPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    markdown: str | None = None
    min_reading_seconds: int | None = Field(default=None, ge=0)


class QuestionnaireVersionCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    definition: dict[str, Any] = Field(alias="schemaJson")


class QuestionnaireVersionPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    definition: dict[str, Any] | None = Field(default=None, alias="schemaJson")


class RoomCreate(ApiModel):
    internal_label: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    condition_version_id: str
    instruction_version_p1_id: str
    instruction_version_p2_id: str
    questionnaire_version_id: str
    base_pay_cents: int = Field(default=0, ge=0)
    performance_rate_cents: int = Field(default=0, ge=0)
    showup_pay_cents: int = Field(default=0, ge=0)
    wait_window_seconds: int = Field(default=900, ge=1)
    reconnect_window_seconds: int = Field(default=600, ge=1)

    @field_validator("starts_at")
    @classmethod
    def normalize_starts_at(cls, value: datetime) -> datetime:
        return parse_datetime(value.isoformat())


class RoomPatch(ApiModel):
    internal_label: str | None = Field(default=None, min_length=1, max_length=200)
    starts_at: datetime | None = None
    condition_version_id: str | None = None
    instruction_version_p1_id: str | None = None
    instruction_version_p2_id: str | None = None
    questionnaire_version_id: str | None = None
    base_pay_cents: int | None = Field(default=None, ge=0)
    performance_rate_cents: int | None = Field(default=None, ge=0)
    showup_pay_cents: int | None = Field(default=None, ge=0)
    wait_window_seconds: int | None = Field(default=None, ge=1)
    reconnect_window_seconds: int | None = Field(default=None, ge=1)

    @field_validator("starts_at")
    @classmethod
    def normalize_starts_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return parse_datetime(value.isoformat())


class RoomBatchCreate(ApiModel):
    template: RoomCreate
    count: int = Field(ge=1, le=20)
    condition_version_ids: list[str] | None = None


class RoomCopy(ApiModel):
    starts_at: datetime | None = None
    internal_label: str | None = None

    @field_validator("starts_at")
    @classmethod
    def normalize_starts_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return parse_datetime(value.isoformat())


class BookingCreate(ApiModel):
    participant_id: str


class RoomAction(ApiModel):
    action: str = ""
    reason: str | None = None
    minutes: int | None = Field(default=None, ge=1, le=1440)
    participant_id: str | None = None
    jatos_worker_id: str | None = None
    jatos_study_result_id: str | None = None
    jatos_component_result_id: str | None = None
    answers: dict[str, Any] | None = None


class PaymentPatch(ApiModel):
    override_amount_cents: int | None = Field(default=None, ge=0)
    admin_note: str | None = None
    status: Literal["pending", "paid"] | None = None


class SettingsPatch(ApiModel):
    jatos_base_url: str | None = None
    jatos_study_code: str | None = None
    contact_info: str | None = None
    timezone: str | None = None


class QuestionnaireDraftRequest(ApiModel):
    token: str
    answers: dict[str, Any]


class QuestionnaireCompleteRequest(ApiModel):
    token: str
    answers: dict[str, Any]
    jatos_worker_id: str | None = None
    jatos_study_result_id: str
    jatos_component_result_id: str


class ParticipantQuestionnaireCompleteRequest(ApiModel):
    room_id: str
    answers: dict[str, Any]
    jatos_worker_id: str | None = None
    jatos_study_result_id: str
    jatos_component_result_id: str


class JatosImportRequest(ApiModel):
    participant_id: str
    answers: dict[str, Any]
    jatos_worker_id: str | None = None
    jatos_study_result_id: str
    jatos_component_result_id: str
