import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .constants import (
    DEFAULT_RECONNECT_WINDOW_SECONDS,
    DEFAULT_WAIT_WINDOW_SECONDS,
    PAYMENT_PENDING,
    PAYMENT_SOURCE_COMPUTED,
    QUESTIONNAIRE_NOT_STARTED,
)
from .db import Base
from .timeutil import utcnow


def new_id() -> str:
    return str(uuid.uuid4())


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    phone_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="eligible", index=True)
    merged_into_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("participants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    consent_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("consent_versions.id", ondelete="SET NULL"), nullable=True
    )
    consented_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class ConsentVersion(Base):
    __tablename__ = "consent_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class TroopProfile(Base):
    __tablename__ = "troop_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    built_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class TroopProfileVersion(Base):
    __tablename__ = "troop_profile_versions"
    __table_args__ = (
        UniqueConstraint("troop_profile_id", "version", name="uq_troop_profile_versions_profile_version"),
        Index("ix_troop_profile_versions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    troop_profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("troop_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_json: Mapped[list] = mapped_column(JSON, nullable=False)
    practice_trials: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    formal_trials: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    troop_profile: Mapped[TroopProfile] = relationship(lazy="selectin")


class MapGroupVersion(Base):
    __tablename__ = "map_group_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_map_group_versions_name_version"),
        Index("ix_map_group_versions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False)
    cols: Mapped[int] = mapped_column(Integer, nullable=False)
    spawn_a_index: Mapped[int] = mapped_column(Integer, nullable=False)
    spawn_b_index: Mapped[int] = mapped_column(Integer, nullable=False)
    troop_profile_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("troop_profile_versions.id", ondelete="RESTRICT"), nullable=False
    )
    practice_trials: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    formal_trials: Mapped[int] = mapped_column(Integer, nullable=False)
    practice_turn_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    practice_turn_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    formal_turn_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    formal_turn_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    rest_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    randomize_formal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    base_pay_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    performance_rate_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    performance_floor_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=3500)
    performance_cap_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=5500)
    showup_pay_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    troop_profile_version: Mapped[TroopProfileVersion] = relationship(lazy="selectin")
    maps: Mapped[list["Map"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class Map(Base):
    __tablename__ = "maps"
    __table_args__ = (
        UniqueConstraint("map_group_version_id", "slot", name="uq_maps_group_slot"),
        UniqueConstraint("map_group_version_id", "name", name="uq_maps_group_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    map_group_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("map_group_versions.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    size_token: Mapped[str] = mapped_column(String(20), nullable=False)
    factor_level: Mapped[str] = mapped_column(String(200), nullable=False)
    player_suffix: Mapped[str] = mapped_column(String(10), nullable=False)
    cells_json: Mapped[list] = mapped_column(JSON, nullable=False)
    colors_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class ParticipantIdentity(Base):
    __tablename__ = "participant_identities"
    __table_args__ = (
        UniqueConstraint("room_id", "participant_id", name="uq_participant_identities_room_participant"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rooms.id", ondelete="RESTRICT"), nullable=False
    )
    participant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False
    )
    real_name_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    alipay_phone_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(String(20), nullable=False)
    document_number_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class InstructionVersion(Base):
    __tablename__ = "instruction_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_instruction_versions_name_version"),
        Index("ix_instruction_versions_status", "status"),
        Index("ix_instruction_versions_map_group_prefix", "map_group_prefix"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    map_group_prefix: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[int] = mapped_column(Integer, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    min_reading_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class QuestionnaireVersion(Base):
    __tablename__ = "questionnaire_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_questionnaire_versions_name_version"),
        Index("ix_questionnaire_versions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        Index("ix_rooms_status", "status"),
        Index("ix_rooms_starts_at", "starts_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    internal_label: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    archive_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    map_group_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("map_group_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    instruction_version_p1_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instruction_versions.id", ondelete="RESTRICT"), nullable=False
    )
    instruction_version_p2_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instruction_versions.id", ondelete="RESTRICT"), nullable=False
    )
    questionnaire_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("questionnaire_versions.id", ondelete="RESTRICT"), nullable=False
    )
    wait_window_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_WAIT_WINDOW_SECONDS
    )
    reconnect_window_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_RECONNECT_WINDOW_SECONDS
    )
    config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    archive_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    config_locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trial_plan_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    runtime_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    map_group_version: Mapped[MapGroupVersion] = relationship(lazy="selectin")


class RoomConfigRevision(Base):
    __tablename__ = "room_config_revisions"
    __table_args__ = (UniqueConstraint("room_id", "revision", name="uq_room_config_revisions_room_revision"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class RoomTimer(Base):
    __tablename__ = "room_timers"
    __table_args__ = (Index("ix_room_timers_due", "status", "due_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("active_key", name="uq_bookings_active_key"),
        Index("ix_bookings_room_status", "room_id", "status"),
        Index("ix_bookings_participant_status", "participant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="booked")
    active_key: Mapped[str | None] = mapped_column(
        String(36),
        Computed("(CASE WHEN status = 'booked' THEN participant_id ELSE NULL END)", persisted=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RoomParticipant(Base):
    __tablename__ = "room_participants"
    __table_args__ = (
        UniqueConstraint("room_id", "participant_id", name="uq_room_participants_room_participant"),
        UniqueConstraint("room_id", "role", name="uq_room_participants_room_role"),
        UniqueConstraint("room_id", "analysis_code", name="uq_room_participants_room_analysis_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_code: Mapped[str] = mapped_column(String(20), nullable=False)
    instruction_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    instruction_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    instruction_connected_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    questionnaire_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=QUESTIONNAIRE_NOT_STARTED
    )
    questionnaire_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class QuestionnaireDraft(Base):
    __tablename__ = "questionnaire_drafts"
    __table_args__ = (UniqueConstraint("room_id", "participant_id", name="uq_questionnaire_drafts_room_participant"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("participants.id", ondelete="CASCADE"), nullable=False
    )
    answers_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class QuestionnaireResponse(Base):
    __tablename__ = "questionnaire_responses"
    __table_args__ = (
        UniqueConstraint(
            "room_id",
            "participant_id",
            "jatos_study_result_id",
            "jatos_component_result_id",
            name="uq_questionnaire_responses_attempt",
        ),
        Index("ix_questionnaire_responses_room_participant", "room_id", "participant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("participants.id", ondelete="CASCADE"), nullable=False
    )
    questionnaire_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("questionnaire_versions.id", ondelete="RESTRICT"), nullable=False
    )
    jatos_worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    jatos_study_result_id: Mapped[str] = mapped_column(String(120), nullable=False)
    jatos_component_result_id: Mapped[str] = mapped_column(String(120), nullable=False)
    answers_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    canonical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="jatos")
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class GameTrial(Base):
    __tablename__ = "game_trials"
    __table_args__ = (UniqueConstraint("room_id", "trial_index", name="uq_game_trials_room_trial_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    trial_index: Mapped[int] = mapped_column(Integer, nullable=False)
    game_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_practice: Mapped[bool] = mapped_column(Boolean, nullable=False)
    formal_trial: Mapped[int] = mapped_column(Integer, nullable=False)
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    seed: Mapped[str] = mapped_column(String(16), nullable=False)
    initial_state_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    winner: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    end_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_rounds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forced_rounds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (UniqueConstraint("game_trial_id", "round", name="uq_turns_game_trial_round"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    game_trial_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_trials.id", ondelete="CASCADE"), nullable=False
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_seed: Mapped[str | None] = mapped_column(String(16), nullable=True)
    selections_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    policy_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    board_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    war_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    losses_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    logistics_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    num_of_war: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selection_sources_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    auto_selected_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    forced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class TurnSubmission(Base):
    __tablename__ = "turn_submissions"
    __table_args__ = (
        UniqueConstraint(
            "game_trial_id", "room_participant_id", "client_msg_id", name="uq_turn_submissions_client_msg"
        ),
        Index("ix_turn_submissions_trial_participant", "game_trial_id", "room_participant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    game_trial_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_trials.id", ondelete="CASCADE"), nullable=False
    )
    room_participant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("room_participants.id", ondelete="CASCADE"), nullable=False
    )
    client_msg_id: Mapped[str] = mapped_column(String(80), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    cells_json: Mapped[list] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RoomEvent(Base):
    __tablename__ = "room_events"
    __table_args__ = (Index("ix_room_events_room_created", "room_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("participants.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("room_id", "participant_id", name="uq_payments_room_participant"),
        Index("ix_payments_status", "status"),
        Index("ix_payments_source", "source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False
    )
    base_pay_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    performance_pay_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    showup_pay_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    override_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PAYMENT_SOURCE_COMPUTED
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PAYMENT_PENDING)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (Index("ix_admin_audit_log_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    admin_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
