from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
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
    PAYMENT_PENDING,
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
    QuestionnaireVersion,
    Room,
    RoomConfigRevision,
    RoomParticipant,
    RoomTimer,
)
from ..timeutil import isoformat_utc, utcnow
from .events import add_event
from .instructions import serialize_instruction
from .map_groups import map_group_payment, serialize_map, serialize_map_group_snapshot
from .participants import current_consent_version
from .payments import upsert_payment
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


async def one_time_experiment_lock(db: AsyncSession, participant_id: str) -> tuple[bool, bool]:
    participant = await db.get(Participant, participant_id)
    if participant is None:
        return False, False
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
    locked = participant.status == PARTICIPANT_COMPLETED or bool(statuses)
    return locked, pending


def booking_lock_message(pending: bool) -> str:
    if pending:
        return "你已完成本次正式实验，但后测问卷尚未提交。请先继续填写并提交问卷，目前无法预约新的场次。"
    return "你已完成全部实验，无法再预约新的场次。"


def participant_reward_kind(
    room: Room, room_participant: RoomParticipant | None, booking: Booking | None
) -> str:
    if room_participant is not None and room_participant.questionnaire_status == QUESTIONNAIRE_COMPLETED:
        return "completion"
    if (
        room.archive_reason == ARCHIVE_TECHNICAL_ABORT
        and booking is not None
        and booking.status == BOOKING_ATTENDED
        and get_room_payment(room)["showupPayCents"] > 0
    ):
        return "showup"
    return "none"


async def can_rebook_for_participant(db: AsyncSession, room: Room, participant_id: str) -> bool:
    if room.status != ROOM_ARCHIVED:
        return False
    if room.archive_reason in (ARCHIVE_COMPLETED, ARCHIVE_QUESTIONNAIRE_INCOMPLETE):
        return False
    locked, _pending = await one_time_experiment_lock(db, participant_id)
    return not locked


async def book_room(
    db: AsyncSession, room: Room, participant, *, allow_after_start: bool = False
) -> Booking:
    locked, pending = await one_time_experiment_lock(db, participant.id)
    if locked:
        raise HTTPException(status.HTTP_409_CONFLICT, booking_lock_message(pending))
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
        raise HTTPException(status.HTTP_409_CONFLICT, "该房间当前不可报名")
    if now >= room.starts_at and not allow_after_start:
        raise HTTPException(status.HTTP_409_CONFLICT, "该房间已过报名截止时间")
    active = await blocking_booking_for_participant(db, participant.id)
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "你已有有效预约，请先取消当前预约")
    await db.refresh(room, with_for_update=True)
    if room.status not in allowed_statuses:
        raise HTTPException(status.HTTP_409_CONFLICT, "该房间当前不可报名")
    if utcnow() >= room.starts_at and not allow_after_start:
        raise HTTPException(status.HTTP_409_CONFLICT, "该房间已过报名截止时间")
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
        raise HTTPException(status.HTTP_409_CONFLICT, "该房间已满")
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
        raise HTTPException(status.HTTP_409_CONFLICT, "你已报名该房间")
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
        raise HTTPException(status.HTTP_409_CONFLICT, "当前房间状态不允许取消预约")
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
    participants_query = await db.execute(select(RoomParticipant).where(RoomParticipant.room_id == room.id))
    room_participants = {item.participant_id: item for item in participants_query.scalars().all()}
    if reason == ARCHIVE_TECHNICAL_ABORT and get_room_payment(room)["showupPayCents"] > 0:
        for booking in bookings:
            if booking.status != BOOKING_ATTENDED:
                continue
            await upsert_payment(
                db,
                room,
                booking.participant_id,
                booking=booking,
                room_participant=room_participants.get(booking.participant_id),
            )
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
