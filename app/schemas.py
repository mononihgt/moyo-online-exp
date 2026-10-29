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
    phone: str | None = Field(default=None, min_length=5, max_length=30)
    status: Literal["eligible", "completed", "disabled"] | None = None
    notes: str | None = None


class IdentityInput(ApiModel):
    real_name: str
    alipay_phone: str
    document_type: Literal["id_card", "passport"]
    document_number: str


class IdentityUpdate(IdentityInput):
    reason: str = Field(min_length=1)


class ManualPaymentCreate(ApiModel):
    room_id: str
    participant_id: str
    booking_id: str
    kind: Literal[
        "manual_showup",
        "manual_completion",
        "manual_compensation",
    ]
    amount_cents: int = Field(ge=1)
    admin_note: str = Field(min_length=1)
    identity: IdentityInput | None = None


class ParticipantMerge(ApiModel):
    source_id: str
    target_id: str
    keep_phone_from: Literal["target", "source"]
    final_name: str | None = Field(default=None, min_length=1, max_length=120)
    reason: str = Field(min_length=1)


class ConsentVersionCreate(ApiModel):
    markdown: str


class ConsentVersionPatch(ApiModel):
    markdown: str


class TroopProfileCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    rows: list[dict[str, Any]]


class TroopProfilePatch(ApiModel):
    rows: list[dict[str, Any]] | None = None


class TroopProfileCopy(ApiModel):
    name: str = Field(min_length=1, max_length=200)


class MapPaymentInput(ApiModel):
    base_pay_cents: int = Field(default=1000, ge=0)
    performance_rate_cents: int = Field(default=1, ge=0)
    performance_floor_cents: int = Field(default=3500, ge=0)
    performance_cap_cents: int = Field(default=5500, ge=0)
    showup_pay_cents: int = Field(default=1000, ge=0)


class MapDefinition(ApiModel):
    slot: Literal["A", "B", "Both"]
    description: str
    factor_level: str
    cells: list[str | None]
    colors: list[str | None] | None = None
    landmark_cells: list[int] | None = None


class MapGroupCreate(ApiModel):
    mode: Literal["both", "ab"]
    rows: int
    cols: int
    spawns: dict[str, int]
    troop_profile_version_id: str
    practice_trials: int = 1
    formal_trials: int
    practice_turn_cap: int = 20
    practice_turn_seconds: int = 60
    formal_turn_cap: int = 20
    formal_turn_seconds: int = 30
    rest_seconds: int = 60
    randomize_formal: bool = True
    factors: dict[str, str] | None = None
    payment: MapPaymentInput = Field(default_factory=MapPaymentInput)
    maps: list[MapDefinition]


class MapGroupPatch(ApiModel):
    mode: Literal["both", "ab"] | None = None
    rows: int | None = None
    cols: int | None = None
    spawns: dict[str, int] | None = None
    troop_profile_version_id: str | None = None
    practice_trials: int | None = None
    formal_trials: int | None = None
    practice_turn_cap: int | None = None
    practice_turn_seconds: int | None = None
    formal_turn_cap: int | None = None
    formal_turn_seconds: int | None = None
    rest_seconds: int | None = None
    randomize_formal: bool | None = None
    factors: dict[str, str] | None = None
    payment: MapPaymentInput | None = None
    maps: list[MapDefinition] | None = None


class InstructionVersionCreate(ApiModel):
    map_group_version_id: str
    role: Literal[1, 2]
    markdown: str
    min_reading_seconds: int = Field(default=120, ge=0)


class InstructionVersionPatch(ApiModel):
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
    map_group_version_id: str
    instruction_version_p1_id: str
    instruction_version_p2_id: str
    questionnaire_version_id: str
    wait_window_seconds: int = Field(default=600, ge=1)
    reconnect_window_seconds: int = Field(default=600, ge=1)

    @field_validator("starts_at")
    @classmethod
    def normalize_starts_at(cls, value: datetime) -> datetime:
        return parse_datetime(value.isoformat())


class RoomPatch(ApiModel):
    internal_label: str | None = Field(default=None, min_length=1, max_length=200)
    starts_at: datetime | None = None
    map_group_version_id: str | None = None
    instruction_version_p1_id: str | None = None
    instruction_version_p2_id: str | None = None
    questionnaire_version_id: str | None = None
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
    map_group_version_ids: list[str] | None = None


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
    note: str | None = None
    expected_current_reason: str | None = None
    minutes: int | None = Field(default=None, ge=1, le=1440)
    participant_id: str | None = None
    booking_id: str | None = None
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
