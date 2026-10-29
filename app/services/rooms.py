import copy
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..constants import (
    ARCHIVE_ABANDONED,
    ARCHIVE_ADMIN_ABORTED,
    ARCHIVE_ADMIN_CANCELLED,
    ARCHIVE_COMPLETED,
    ARCHIVE_NO_SHOW,
    ARCHIVE_NO_START,
    ARCHIVE_NOT_FULL,
    ARCHIVE_QUESTIONNAIRE_INCOMPLETE,
    ARCHIVE_TECHNICAL_ABORT,
    BOOKING_ATTENDED,
    BOOKING_BOOKED,
    BOOKING_CANCELED,
    BOOKING_NO_SHOW,
    PARTICIPANT_COMPLETED,
    PARTICIPANT_ELIGIBLE,
    PAYMENT_PAID,
    PAYMENT_PENDING,
    PAYMENT_SOURCE_COMPUTED,
    PAYMENT_SOURCE_MANUAL_COMPENSATION,
    PAYMENT_SOURCE_MANUAL_COMPLETION,
    PAYMENT_SOURCE_MANUAL_SHOWUP,
    QUESTIONNAIRE_COMPLETED,
    ROOM_ARCHIVED,
    ROOM_CAPACITY,
    ROOM_DRAFT,
    ROOM_FULL,
    ROOM_INSTRUCTIONS,
    ROOM_OPEN,
    ROOM_PLAYING,
    ROOM_QUESTIONNAIRE,
    ROOM_SECTION_ARCHIVED,
    ROOM_SECTION_DRAFT,
    ROOM_SECTION_IN_PROGRESS,
    ROOM_SECTION_OPEN,
    ROOM_SECTION_UNPAID,
    ROOM_SECTIONS,
    ROOM_STATUSES,
    ROOM_WAITING,
    VERSION_ARCHIVED,
    VERSION_PUBLISHED,
)
from ..models import (
    Booking,
    InstructionVersion,
    MapGroupVersion,
    Participant,
    Payment,
    QuestionnaireDraft,
    QuestionnaireResponse,
    QuestionnaireVersion,
    Room,
    RoomConfigRevision,
    RoomEvent,
    RoomParticipant,
    RoomTimer,
)
from ..timeutil import isoformat_utc, utcnow
from .events import add_event
from .payments import upsert_payment
from .instructions import serialize_instruction
from .map_groups import map_group_payment, serialize_map, serialize_map_group_snapshot
from .participants import current_consent_version
from .questionnaires import (
    QuestionnaireValidationError,
    serialize_questionnaire,
    validate_room_questionnaire_schema,
)

CAPACITY = ROOM_CAPACITY


async def _get_version(db: AsyncSession, model, version_id: str, label: str):
    version = await db.get(model, version_id)
    if version is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{label}不存在")
    if version.status not in (VERSION_PUBLISHED, VERSION_ARCHIVED):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{label}尚未发布")
    return version


async def validate_room_config(db: AsyncSession, room: Room) -> None:
    map_group = await _get_version(db, MapGroupVersion, room.map_group_version_id, "地图组版本")
    instruction_a = await _get_version(db, InstructionVersion, room.instruction_version_p1_id, "玩家1指导语")
    instruction_b = await _get_version(db, InstructionVersion, room.instruction_version_p2_id, "玩家2指导语")
    questionnaire = await _get_version(db, QuestionnaireVersion, room.questionnaire_version_id, "问卷版本")
    if instruction_a.role != 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "玩家1指导语的角色必须是 1")
    if instruction_b.role != 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "玩家2指导语的角色必须是 2")
    if instruction_a.map_group_prefix != map_group.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "玩家1指导语的名称前缀必须与地图组名称一致")
    if instruction_b.map_group_prefix != map_group.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "玩家2指导语的名称前缀必须与地图组名称一致")
    try:
        validate_room_questionnaire_schema(questionnaire.schema_json)
    except QuestionnaireValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if room.wait_window_seconds < 1 or room.reconnect_window_seconds < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "等待窗口和重连窗口必须大于 0")
    room.map_group_version = map_group


def room_config_dict(room: Room) -> dict:
    return {
        "startsAt": isoformat_utc(room.starts_at),
        "mapGroupVersionId": room.map_group_version_id,
        "instructionVersionP1Id": room.instruction_version_p1_id,
        "instructionVersionP2Id": room.instruction_version_p2_id,
        "questionnaireVersionId": room.questionnaire_version_id,
        "waitWindowSeconds": room.wait_window_seconds,
        "reconnectWindowSeconds": room.reconnect_window_seconds,
        "internalLabel": room.internal_label,
    }


def payment_from_map_group_snapshot(data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return None
    map_group = data.get("mapGroup")
    if not isinstance(map_group, dict):
        return None
    payment = map_group.get("payment")
    if not isinstance(payment, dict):
        return None
    return {
        "basePayCents": int(payment.get("basePayCents", 0)),
        "performanceRateCents": int(payment.get("performanceRateCents", 0)),
        "performanceFloorCents": int(payment.get("performanceFloorCents", 0)),
        "performanceCapCents": int(payment.get("performanceCapCents", 0)),
        "showupPayCents": int(payment.get("showupPayCents", 0)),
    }


def get_room_payment(room: Room, snapshot: dict | None = None) -> dict:
    if snapshot is not None:
        payment = payment_from_map_group_snapshot(snapshot)
        if payment is not None:
            return payment
    payment = payment_from_map_group_snapshot(room.config_snapshot)
    if payment is not None:
        return payment
    payment = payment_from_map_group_snapshot(room.archive_snapshot_json)
    if payment is not None:
        return payment
    if room.map_group_version is None:
        raise RuntimeError("房间未绑定地图组，无法读取费用参数")
    return map_group_payment(room.map_group_version)


async def add_config_revision(db: AsyncSession, room: Room) -> None:
    query = await db.execute(
        select(func.max(RoomConfigRevision.revision)).where(RoomConfigRevision.room_id == room.id)
    )
    current = query.scalar_one_or_none() or 0
    db.add(RoomConfigRevision(room_id=room.id, revision=current + 1, config_json=room_config_dict(room)))
    await db.flush()


def _room_from_config(data: dict) -> Room:
    return Room(
        internal_label=data["internal_label"],
        starts_at=data["starts_at"],
        status=ROOM_DRAFT,
        map_group_version_id=data["map_group_version_id"],
        instruction_version_p1_id=data["instruction_version_p1_id"],
        instruction_version_p2_id=data["instruction_version_p2_id"],
        questionnaire_version_id=data["questionnaire_version_id"],
        wait_window_seconds=data["wait_window_seconds"],
        reconnect_window_seconds=data["reconnect_window_seconds"],
    )


async def create_room(db: AsyncSession, data: dict) -> Room:
    room = _room_from_config(data)
    await validate_room_config(db, room)
    db.add(room)
    await db.flush()
    await add_config_revision(db, room)
    return room


async def update_room(db: AsyncSession, room: Room, patch: dict) -> Room:
    now = utcnow()
    changed = False
    if "starts_at" in patch and patch["starts_at"] is not None:
        if room.status != ROOM_DRAFT:
            raise HTTPException(status.HTTP_409_CONFLICT, "仅草稿房间可以修改开始时间")
        room.starts_at = patch["starts_at"]
        changed = True
    config_fields = (
        "internal_label",
        "map_group_version_id",
        "instruction_version_p1_id",
        "instruction_version_p2_id",
        "questionnaire_version_id",
        "wait_window_seconds",
        "reconnect_window_seconds",
    )
    config_patch = {
        field: patch[field]
        for field in config_fields
        if field in patch and patch[field] is not None
    }
    if config_patch:
        if room.status == ROOM_ARCHIVED:
            raise HTTPException(status.HTTP_409_CONFLICT, "房间已归档，不可修改配置")
        if room.status not in (ROOM_DRAFT, ROOM_OPEN, ROOM_FULL) or now >= room.starts_at:
            raise HTTPException(status.HTTP_409_CONFLICT, "房间开始后不可修改配置")
        for field, value in config_patch.items():
            setattr(room, field, value)
        changed = True
    if not changed:
        return room
    await validate_room_config(db, room)
    await add_config_revision(db, room)
    return room


async def publish_room(db: AsyncSession, room: Room) -> Room:
    if room.status != ROOM_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有草稿房间可以开放预约")
    await validate_room_config(db, room)
    if room.starts_at <= utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "开始时间必须晚于当前时间")
    room.status = ROOM_OPEN
    room.published_at = utcnow()
    add_event(db, room, "room_published")
    return room


async def close_booking(db: AsyncSession, room: Room) -> Room:
    await db.refresh(room, with_for_update=True)
    if room.status not in (ROOM_OPEN, ROOM_FULL):
        raise HTTPException(status.HTTP_409_CONFLICT, "只有开放预约的房间可以关闭预约")
    if utcnow() >= room.starts_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "房间开始后不可关闭预约")
    if await booked_count(db, room.id) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "存在有效预约，无法关闭预约")
    room.status = ROOM_DRAFT
    add_event(db, room, "booking_closed")
    return room


async def booked_count(db: AsyncSession, room_id: str) -> int:
    query = await db.execute(
        select(func.count(Booking.id)).where(
            Booking.room_id == room_id, Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED))
        )
    )
    return query.scalar_one()


async def active_booking_for_participant(db: AsyncSession, participant_id: str) -> Booking | None:
    query = await db.execute(
        select(Booking)
        .join(Room, Room.id == Booking.room_id)
        .where(
            Booking.participant_id == participant_id,
            Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED)),
            Room.status != ROOM_ARCHIVED,
        )
        .order_by(Booking.created_at.desc())
    )
    return query.scalars().first()


async def blocking_booking_for_participant(db: AsyncSession, participant_id: str) -> Booking | None:
    query = await db.execute(
        select(Booking)
        .join(Room, Room.id == Booking.room_id)
        .where(
            Booking.participant_id == participant_id,
            Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED)),
            Room.status != ROOM_ARCHIVED,
        )
        .order_by(Booking.created_at.desc())
    )
    return query.scalars().first()


async def technical_abort_showup_eligible(
    db: AsyncSession,
    room: Room,
    participant_id: str,
    *,
    room_participant: RoomParticipant | None = None,
    booking: Booking | None = None,
) -> bool:
    if room.status != ROOM_ARCHIVED or room.archive_reason != ARCHIVE_TECHNICAL_ABORT:
        return False
    if room_participant is None:
        query = await db.execute(
            select(RoomParticipant).where(
                RoomParticipant.room_id == room.id,
                RoomParticipant.participant_id == participant_id,
            )
        )
        room_participant = query.scalars().first()
    if room_participant is None:
        return False
    if booking is None:
        query = await db.execute(
            select(Booking).where(
                Booking.room_id == room.id,
                Booking.participant_id == participant_id,
                Booking.status == BOOKING_ATTENDED,
            )
        )
        booking = query.scalars().first()
    if booking is None or booking.status != BOOKING_ATTENDED:
        return False
    return get_room_payment(room)["showupPayCents"] > 0


@dataclass(frozen=True)
class ExperimentLock:
    locked: bool
    pending_questionnaire: bool
    pending_showup_questionnaire: bool
    has_payment: bool
    reason: str | None


async def one_time_experiment_lock(db: AsyncSession, participant_id: str) -> ExperimentLock:
    participant = await db.get(Participant, participant_id)
    if participant is None:
        return ExperimentLock(False, False, False, False, None)
    rows = await db.execute(
        select(RoomParticipant.questionnaire_status)
        .join(Room, Room.id == RoomParticipant.room_id)
        .where(
            RoomParticipant.participant_id == participant_id,
            or_(
                Room.status == ROOM_QUESTIONNAIRE,
                and_(
                    Room.status == ROOM_ARCHIVED,
                    Room.archive_reason.in_((ARCHIVE_QUESTIONNAIRE_INCOMPLETE, ARCHIVE_COMPLETED)),
                ),
            ),
        )
    )
    statuses = list(rows.scalars().all())
    pending = any(status != QUESTIONNAIRE_COMPLETED for status in statuses)
    showup_rows = await db.execute(
        select(RoomParticipant.id)
        .join(Room, Room.id == RoomParticipant.room_id)
        .join(
            Booking,
            and_(
                Booking.room_id == RoomParticipant.room_id,
                Booking.participant_id == RoomParticipant.participant_id,
                Booking.status == BOOKING_ATTENDED,
            ),
        )
        .join(MapGroupVersion, MapGroupVersion.id == Room.map_group_version_id)
        .outerjoin(
            Payment,
            and_(
                Payment.room_id == RoomParticipant.room_id,
                Payment.participant_id == RoomParticipant.participant_id,
            ),
        )
        .where(
            RoomParticipant.participant_id == participant_id,
            Room.status == ROOM_ARCHIVED,
            Room.archive_reason == ARCHIVE_TECHNICAL_ABORT,
            MapGroupVersion.showup_pay_cents > 0,
            RoomParticipant.questionnaire_status != QUESTIONNAIRE_COMPLETED,
            Payment.id.is_(None),
        )
        .limit(1)
    )
    pending_showup = showup_rows.first() is not None
    payment_query = await db.execute(
        select(Payment.id).where(Payment.participant_id == participant_id).limit(1)
    )
    has_payment = payment_query.first() is not None
    if pending:
        reason = "pending_questionnaire"
    elif pending_showup:
        reason = "pending_showup_questionnaire"
    elif participant.status == PARTICIPANT_COMPLETED or bool(statuses):
        reason = "completed"
    elif has_payment:
        reason = "payment"
    else:
        reason = None
    return ExperimentLock(
        locked=reason is not None,
        pending_questionnaire=pending,
        pending_showup_questionnaire=pending_showup,
        has_payment=has_payment,
        reason=reason,
    )


def booking_lock_message(lock: ExperimentLock) -> str:
    if lock.reason == "pending_questionnaire":
        return "你已完成本次正式实验，但后测问卷尚未提交。请先提交问卷；提交问卷前后都无法预约新的场次。"
    if lock.reason == "pending_showup_questionnaire":
        return "本次实验因网络或系统故障提前结束，你已到场。请先填写并提交后测问卷，提交后生成到场费；本次实验结束后，你不能再预约新的实验。"
    if lock.reason == "payment":
        return "你已产生实验报酬，无法再预约新的场次。如有疑问，请联系实验工作人员。"
    return "你已完成全部实验，无法再预约新的场次。"


def participant_reward_kind(payment: Payment | None) -> str:
    if payment is None:
        return "none"
    if payment.source == PAYMENT_SOURCE_MANUAL_COMPENSATION:
        return "manual"
    if payment.source == PAYMENT_SOURCE_MANUAL_SHOWUP:
        return "showup"
    if payment.source == PAYMENT_SOURCE_MANUAL_COMPLETION:
        return "completion"
    if (
        payment.showup_pay_cents > 0
        and payment.base_pay_cents == 0
        and payment.performance_pay_cents == 0
    ):
        return "showup"
    return "completion"


CORRECTABLE_ARCHIVE_REASONS = (
    ARCHIVE_ABANDONED,
    ARCHIVE_TECHNICAL_ABORT,
    ARCHIVE_ADMIN_ABORTED,
)


def _update_archive_snapshot_reason(room: Room, reason: str) -> None:
    if not isinstance(room.archive_snapshot_json, dict):
        return
    snapshot = copy.deepcopy(room.archive_snapshot_json)
    room_data = snapshot.get("room")
    if not isinstance(room_data, dict):
        return
    room_data["archiveReason"] = reason
    room.archive_snapshot_json = snapshot
    flag_modified(room, "archive_snapshot_json")


async def _has_exit_event(db: AsyncSession, room_id: str) -> bool:
    rows = await db.execute(
        select(RoomEvent.payload_json).where(
            RoomEvent.room_id == room_id,
            RoomEvent.type == "participant_exited",
        )
    )
    for payload in rows.scalars().all():
        reason = (payload or {}).get("reason")
        if reason in (None, "manual", "inactivity"):
            return True
    return False


async def _has_attended_booking(db: AsyncSession, room_id: str) -> bool:
    rows = await db.execute(
        select(Booking.id).where(
            Booking.room_id == room_id,
            Booking.status == BOOKING_ATTENDED,
        )
    )
    return rows.first() is not None


async def _archive_correction_block_reason(
    db: AsyncSession, room: Room, target_reason: str
) -> str | None:
    if room.status != ROOM_ARCHIVED:
        return "只有已归档实验可以更正结束原因"
    if room.archive_reason not in CORRECTABLE_ARCHIVE_REASONS:
        return "当前结束原因不允许更正"
    if target_reason not in CORRECTABLE_ARCHIVE_REASONS:
        return "目标结束原因不允许选择"
    if target_reason == room.archive_reason:
        return "目标结束原因与当前原因相同"
    payment_rows = await db.execute(
        select(Payment.id).where(Payment.room_id == room.id).limit(1)
    )
    if payment_rows.first() is not None:
        return "该实验已有付款记录，不能更正结束原因"
    response_rows = await db.execute(
        select(QuestionnaireResponse.id)
        .where(QuestionnaireResponse.room_id == room.id)
        .limit(1)
    )
    if response_rows.first() is not None:
        return "该实验已有问卷提交记录，不能更正结束原因"
    draft_rows = await db.execute(
        select(QuestionnaireDraft.id)
        .where(QuestionnaireDraft.room_id == room.id)
        .limit(1)
    )
    if draft_rows.first() is not None:
        return "该实验已有问卷草稿，不能更正结束原因"
    if target_reason == ARCHIVE_ABANDONED:
        if not await _has_exit_event(db, room.id):
            return "没有参与者退出记录，不能更正为参与者退出"
    if target_reason == ARCHIVE_TECHNICAL_ABORT:
        if not await _has_attended_booking(db, room.id):
            return "没有到场预约，不能更正为故障中止"
    return None


async def allowed_archive_reason_corrections(
    db: AsyncSession, room: Room
) -> list[str]:
    options = []
    for reason in CORRECTABLE_ARCHIVE_REASONS:
        if reason == room.archive_reason:
            continue
        if await _archive_correction_block_reason(db, room, reason) is None:
            options.append(reason)
    return options


async def correct_archive_reason(
    db: AsyncSession,
    room: Room,
    target_reason: str,
    note: str,
    *,
    expected_current_reason: str | None = None,
) -> None:
    if expected_current_reason is not None and room.archive_reason != expected_current_reason:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "房间结束原因已变化，请刷新页面后重试",
        )
    block_reason = await _archive_correction_block_reason(db, room, target_reason)
    if block_reason is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, block_reason)
    if not note.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须填写更正说明")
    previous_reason = room.archive_reason
    room.archive_reason = target_reason
    _update_archive_snapshot_reason(room, target_reason)
    add_event(
        db,
        room,
        "archive_reason_corrected",
        payload={
            "previousReason": previous_reason,
            "reason": target_reason,
        },
    )
    await db.flush()


async def restore_attendance(
    db: AsyncSession,
    room: Room,
    booking: Booking,
    note: str,
) -> Payment | None:
    if room.status != ROOM_ARCHIVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有已归档实验可以恢复到场")
    if not note.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须填写恢复到场说明")
    if room.archive_reason == ARCHIVE_ADMIN_CANCELLED:
        raise HTTPException(status.HTTP_409_CONFLICT, "主试取消的实验不能恢复到场")
    if booking.room_id != room.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "预约不属于本次实验")
    if booking.status != BOOKING_NO_SHOW:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有未到场预约可以恢复到场")
    if booking.attended_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该预约没有到场记录，不能恢复到场")
    if booking.canceled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "已取消预约不能恢复到场")
    duplicate = await db.execute(
        select(Booking.id).where(
            Booking.room_id == room.id,
            Booking.participant_id == booking.participant_id,
            Booking.status == BOOKING_ATTENDED,
            Booking.id != booking.id,
        )
    )
    if duplicate.first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该参与者已有到场预约记录")
    role_row_query = await db.execute(
        select(RoomParticipant).where(
            RoomParticipant.room_id == room.id,
            RoomParticipant.participant_id == booking.participant_id,
        )
    )
    role_row = role_row_query.scalars().first()
    if role_row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该参与者没有房间实验记录")
    payment_query = await db.execute(
        select(Payment).where(
            Payment.room_id == room.id,
            Payment.participant_id == booking.participant_id,
        )
    )
    payment = payment_query.scalars().first()
    if payment is not None:
        if payment.source != PAYMENT_SOURCE_COMPUTED:
            raise HTTPException(status.HTTP_409_CONFLICT, "已有手工付款，不能自动恢复到场")
        if payment.status == PAYMENT_PAID:
            raise HTTPException(status.HTTP_409_CONFLICT, "付款已经支付，不能自动恢复到场")
        if payment.override_amount_cents is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "付款已覆盖金额，不能自动恢复到场")
        if payment.status == PAYMENT_PENDING and payment.total_cents > 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "付款已计算金额，不能自动恢复到场")
    previous_reason = room.archive_reason
    booking.status = BOOKING_ATTENDED
    updated_payment = await upsert_payment(
        db,
        room,
        booking.participant_id,
        room_participant=role_row,
    )
    if payment is not None and updated_payment is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "恢复到场后付款重算失败")
    if (
        payment is None
        and room.archive_reason in (ARCHIVE_COMPLETED, ARCHIVE_QUESTIONNAIRE_INCOMPLETE)
        and role_row.questionnaire_status == QUESTIONNAIRE_COMPLETED
        and updated_payment is None
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "恢复到场后付款重算失败")
    if room.archive_reason == ARCHIVE_NO_SHOW:
        bookings_rows = await db.execute(
            select(Booking.status).where(
                Booking.room_id == room.id,
                Booking.status != BOOKING_CANCELED,
            )
        )
        statuses = list(bookings_rows.scalars().all())
        if statuses and all(status_value == BOOKING_ATTENDED for status_value in statuses):
            room.archive_reason = ARCHIVE_NO_START
            _update_archive_snapshot_reason(room, ARCHIVE_NO_START)
    add_event(
        db,
        room,
        "admin_action",
        booking.participant_id,
        {
            "action": "restore_attendance",
            "bookingId": booking.id,
            "previousStatus": BOOKING_NO_SHOW,
            "previousArchiveReason": previous_reason,
            "archiveReason": room.archive_reason,
        },
    )
    await db.flush()
    return updated_payment


async def can_rebook_for_participant(db: AsyncSession, room: Room, participant_id: str) -> bool:
    if room.status != ROOM_ARCHIVED:
        return False
    if room.archive_reason in (ARCHIVE_COMPLETED, ARCHIVE_QUESTIONNAIRE_INCOMPLETE):
        return False
    lock = await one_time_experiment_lock(db, participant_id)
    return not lock.locked


async def book_room(
    db: AsyncSession, room: Room, participant, *, allow_after_start: bool = False
) -> Booking:
    lock = await one_time_experiment_lock(db, participant.id)
    if lock.locked:
        raise HTTPException(status.HTTP_409_CONFLICT, booking_lock_message(lock))
    if participant.status != PARTICIPANT_ELIGIBLE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "当前账号状态不允许报名")
    consent = await current_consent_version(db)
    if consent is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "平台尚未发布知情同意书")
    if participant.consent_version_id != consent.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请先阅读并同意当前版本的知情同意书")
    now = utcnow()
    allowed_statuses = (ROOM_OPEN, ROOM_FULL) + ((ROOM_WAITING,) if allow_after_start else ())
    if room.status not in allowed_statuses:
        raise HTTPException(status.HTTP_409_CONFLICT, "该场次当前不可报名")
    if now >= room.starts_at and not allow_after_start:
        raise HTTPException(status.HTTP_409_CONFLICT, "该场次已过报名截止时间")
    active = await blocking_booking_for_participant(db, participant.id)
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "你已有有效预约，请先取消当前预约")
    await db.refresh(room, with_for_update=True)
    if room.status not in allowed_statuses:
        raise HTTPException(status.HTTP_409_CONFLICT, "该场次当前不可报名")
    if utcnow() >= room.starts_at and not allow_after_start:
        raise HTTPException(status.HTTP_409_CONFLICT, "该场次已过报名截止时间")
    count_result = await db.execute(
        select(Booking.id)
        .where(
            Booking.room_id == room.id,
            Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED)),
        )
        .with_for_update()
    )
    count = len(count_result.scalars().all())
    if count >= CAPACITY:
        raise HTTPException(status.HTTP_409_CONFLICT, "该场次已满")
    existing = await db.execute(
        select(Booking)
        .where(
            Booking.room_id == room.id,
            Booking.participant_id == participant.id,
            Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED)),
        )
        .with_for_update()
    )
    if existing.scalars().first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "你已预约该场次")
    booking = Booking(room_id=room.id, participant_id=participant.id, status=BOOKING_BOOKED)
    db.add(booking)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "你已有有效预约，请先取消当前预约") from exc
    count += 1
    if room.status in (ROOM_OPEN, ROOM_FULL):
        room.status = ROOM_FULL if count >= CAPACITY else ROOM_OPEN
    add_event(db, room, "booking_created", participant.id)
    return booking


async def cancel_booking(db: AsyncSession, room: Room, booking: Booking) -> None:
    await db.refresh(room, with_for_update=True)
    await db.refresh(booking, with_for_update=True)
    if room.status not in (ROOM_OPEN, ROOM_FULL):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前状态不允许取消预约")
    if utcnow() >= room.starts_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "报名截止时间已过，无法取消预约")
    if booking.status != BOOKING_BOOKED:
        raise HTTPException(status.HTTP_409_CONFLICT, "该预约无法取消")
    booking.status = BOOKING_CANCELED
    booking.canceled_at = utcnow()
    if room.status == ROOM_FULL:
        room.status = ROOM_OPEN
    add_event(db, room, "booking_canceled", booking.participant_id)


async def mark_attended(db: AsyncSession, room: Room, booking: Booking) -> None:
    if booking.status == BOOKING_BOOKED:
        booking.status = BOOKING_ATTENDED
    if booking.attended_at is None:
        booking.attended_at = utcnow()
        add_event(db, room, "participant_entered", booking.participant_id)


async def transition_to_waiting(db: AsyncSession, room: Room) -> bool:
    if room.status in (ROOM_OPEN, ROOM_FULL) and utcnow() >= room.starts_at:
        room.status = ROOM_WAITING
        await db.flush()
        return True
    return False


async def lock_config(db: AsyncSession, room: Room) -> dict:
    map_group = await db.get(MapGroupVersion, room.map_group_version_id)
    instruction_a = await db.get(InstructionVersion, room.instruction_version_p1_id)
    instruction_b = await db.get(InstructionVersion, room.instruction_version_p2_id)
    questionnaire = await db.get(QuestionnaireVersion, room.questionnaire_version_id)
    snapshot = {
        "room": room_config_dict(room),
        "mapGroup": serialize_map_group_snapshot(map_group),
        "instructions": {
            "player1": serialize_instruction(instruction_a, include_html=False),
            "player2": serialize_instruction(instruction_b, include_html=False),
        },
        "questionnaire": serialize_questionnaire(questionnaire),
        "lockedAt": isoformat_utc(utcnow()),
    }
    room.config_snapshot = snapshot
    room.config_locked_at = utcnow()
    room.status = ROOM_INSTRUCTIONS
    add_event(db, room, "config_locked", payload={"mapGroupVersionId": map_group.id})
    await db.flush()
    return snapshot


async def archive_room(db: AsyncSession, room: Room, reason: str) -> None:
    if room.status == ROOM_ARCHIVED:
        return
    previous_status = room.status
    room.status = ROOM_ARCHIVED
    room.archive_reason = reason
    room.archived_at = utcnow()
    from .export import build_archive_snapshot

    room.archive_snapshot_json = await build_archive_snapshot(db, room)
    timers_query = await db.execute(
        select(RoomTimer).where(RoomTimer.room_id == room.id, RoomTimer.status == "scheduled")
    )
    for timer in timers_query.scalars().all():
        timer.status = "cancelled"
    bookings_query = await db.execute(select(Booking).where(Booking.room_id == room.id))
    bookings = list(bookings_query.scalars().all())
    for booking in bookings:
        if booking.status == BOOKING_BOOKED:
            booking.status = BOOKING_CANCELED if reason == ARCHIVE_ADMIN_CANCELLED else BOOKING_NO_SHOW
        elif booking.status in (BOOKING_ATTENDED, BOOKING_NO_SHOW):
            pass
        elif booking.status == BOOKING_CANCELED:
            pass
    add_event(
        db,
        room,
        "room_archived",
        payload={"reason": reason, "previousStatus": previous_status},
    )
    await db.flush()


async def cancel_room(db: AsyncSession, room: Room) -> None:
    if room.status not in (ROOM_DRAFT, ROOM_OPEN, ROOM_FULL):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前状态不允许取消房间")
    if utcnow() >= room.starts_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "开始时间已到，无法取消房间")
    await archive_room(db, room, ARCHIVE_ADMIN_CANCELLED)


def archive_reason_for_wait_expiry(bookings: list[Booking]) -> str:
    remaining = [booking for booking in bookings if booking.status != BOOKING_CANCELED]
    if len(remaining) < 2:
        return ARCHIVE_NOT_FULL
    if any(booking.status != BOOKING_ATTENDED for booking in remaining):
        return ARCHIVE_NO_SHOW
    return ARCHIVE_NO_START


async def room_summary(db: AsyncSession, room: Room) -> dict:
    count = await booked_count(db, room.id)
    map_group = await db.get(MapGroupVersion, room.map_group_version_id)
    profile_version = map_group.troop_profile_version
    profile = profile_version.troop_profile
    instruction_a = await db.get(InstructionVersion, room.instruction_version_p1_id)
    instruction_b = await db.get(InstructionVersion, room.instruction_version_p2_id)
    questionnaire = await db.get(QuestionnaireVersion, room.questionnaire_version_id)
    payment = payment_from_map_group_snapshot(room.config_snapshot)
    if payment is None:
        payment = payment_from_map_group_snapshot(room.archive_snapshot_json)
    if payment is None:
        payment = map_group_payment(map_group)
    maps = serialize_map(map_group)
    return {
        "id": room.id,
        "internalLabel": room.internal_label,
        "startsAt": isoformat_utc(room.starts_at),
        "status": room.status,
        "archiveReason": room.archive_reason,
        "bookedCount": count,
        "capacity": CAPACITY,
        "mapGroup": {
            "id": map_group.id,
            "versionId": map_group.id,
            "name": map_group.name,
            "version": map_group.version,
            "mode": map_group.mode,
            "rows": map_group.rows,
            "cols": map_group.cols,
            "practiceTrials": map_group.practice_trials,
            "formalTrials": map_group.formal_trials,
            "factors": map_group.factors_json or {},
            "maps": [
                {
                    "slot": item["slot"],
                    "name": item["name"],
                    "description": item["description"],
                    "factorLevel": item["factorLevel"],
                }
                for item in maps
            ],
            "troopProfile": {
                "id": profile.id,
                "versionId": profile_version.id,
                "name": profile.name,
                "version": profile_version.version,
                "builtIn": profile.built_in,
            },
            "payment": payment,
        },
        "instructions": {
            "player1": {"id": instruction_a.id, "name": instruction_a.name, "version": instruction_a.version},
            "player2": {"id": instruction_b.id, "name": instruction_b.name, "version": instruction_b.version},
        },
        "questionnaire": {"id": questionnaire.id, "name": questionnaire.name, "version": questionnaire.version},
        "waitWindowSeconds": room.wait_window_seconds,
        "reconnectWindowSeconds": room.reconnect_window_seconds,
        "configLockedAt": isoformat_utc(room.config_locked_at),
        "publishedAt": isoformat_utc(room.published_at),
        "archivedAt": isoformat_utc(room.archived_at),
        "createdAt": isoformat_utc(room.created_at),
    }


def validate_room_status(value: str) -> str:
    if value not in ROOM_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "房间状态无效")
    return value


def validate_room_section(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in ROOM_SECTIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "房间分区无效")
    return value


def _pending_payment_exists():
    return (
        select(Payment.id)
        .where(Payment.room_id == Room.id, Payment.status == PAYMENT_PENDING)
        .exists()
    )


async def list_rooms_by_section(
    db: AsyncSession, section: str | None, limit: int = 100, offset: int = 0
) -> list[Room]:
    section = validate_room_section(section)
    statement = select(Room)
    if section == ROOM_SECTION_DRAFT:
        statement = statement.where(Room.status == ROOM_DRAFT)
    elif section == ROOM_SECTION_OPEN:
        statement = statement.where(Room.status.in_((ROOM_OPEN, ROOM_FULL)))
    elif section == ROOM_SECTION_IN_PROGRESS:
        statement = statement.where(
            Room.status.in_((ROOM_WAITING, ROOM_INSTRUCTIONS, ROOM_PLAYING, ROOM_QUESTIONNAIRE))
        )
    elif section == ROOM_SECTION_UNPAID:
        statement = statement.where(Room.status == ROOM_ARCHIVED, _pending_payment_exists())
    elif section == ROOM_SECTION_ARCHIVED:
        statement = statement.where(Room.status == ROOM_ARCHIVED, ~_pending_payment_exists())
    rows = await db.execute(
        statement.order_by(Room.starts_at.desc(), Room.id).offset(offset).limit(limit)
    )
    return list(rows.scalars().all())


async def count_room_sections(db: AsyncSession) -> dict:
    status_rows = await db.execute(select(Room.status, func.count(Room.id)).group_by(Room.status))
    counts = {status_value: count for status_value, count in status_rows.all()}
    unpaid = (
        await db.execute(
            select(func.count(Room.id)).where(Room.status == ROOM_ARCHIVED, _pending_payment_exists())
        )
    ).scalar_one()
    archived_total = counts.get(ROOM_ARCHIVED, 0)
    return {
        ROOM_SECTION_DRAFT: counts.get(ROOM_DRAFT, 0),
        ROOM_SECTION_OPEN: counts.get(ROOM_OPEN, 0) + counts.get(ROOM_FULL, 0),
        ROOM_SECTION_IN_PROGRESS: sum(counts.get(value, 0) for value in (
            ROOM_WAITING,
            ROOM_INSTRUCTIONS,
            ROOM_PLAYING,
            ROOM_QUESTIONNAIRE,
        )),
        ROOM_SECTION_UNPAID: unpaid,
        ROOM_SECTION_ARCHIVED: archived_total - unpaid,
    }
