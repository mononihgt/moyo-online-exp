from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, func, or_, select

from ..config import get_settings
from ..constants import (
    ARCHIVE_ADMIN_CANCELLED,
    ARCHIVE_COMPLETED,
    ARCHIVE_QUESTIONNAIRE_INCOMPLETE,
    ARCHIVE_TECHNICAL_ABORT,
    BOOKING_ATTENDED,
    BOOKING_BOOKED,
    BOOKING_CANCELED,
    PARTICIPANT_ELIGIBLE,
    QUESTIONNAIRE_COMPLETED,
    ROOM_ARCHIVED,
    ROOM_FULL,
    ROOM_OPEN,
    ROOM_QUESTIONNAIRE,
)
from ..models import (
    Booking,
    MapGroupVersion,
    Payment,
    Room,
    RoomEvent,
    RoomParticipant,
    SystemSetting,
)
from ..schemas import ConsentRequest, ParticipantQuestionnaireCompleteRequest
from ..services.instructions import render_markdown
from ..services.jatos import build_questionnaire_url
from ..services.participants import current_consent_version, participant_me
from ..services.payments import serialize_payment
from ..services.questionnaire_flow import complete_with_participant
from ..services.rooms import (
    active_booking_for_participant,
    blocking_booking_for_participant,
    book_room,
    cancel_booking,
    get_room_payment,
    one_time_experiment_lock,
    participant_reward_kind,
    technical_abort_showup_eligible,
)
from ..timeutil import isoformat_utc, utcnow
from .auth import clear_participant_cookies
from .deps import DbSession, ParticipantDep, require_csrf

router = APIRouter()


@router.get("/api/consent")
async def get_consent(db: DbSession):
    consent = await current_consent_version(db)
    if consent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "平台尚未发布知情同意书")
    return {
        "versionId": consent.id,
        "version": consent.version,
        "markdown": consent.markdown,
        "html": render_markdown(consent.markdown),
        "publishedAt": isoformat_utc(consent.published_at),
    }


@router.post("/api/consent", dependencies=[Depends(require_csrf)])
async def submit_consent(
    payload: ConsentRequest, response: Response, participant: ParticipantDep, db: DbSession
):
    consent = await current_consent_version(db)
    if consent is None or consent.id != payload.version_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "知情同意书版本已更新，请刷新页面")
    if not payload.agree:
        clear_participant_cookies(response)
        return {"agreed": False, "loggedOut": True}
    participant.consent_version_id = consent.id
    participant.consented_at = utcnow()
    await db.commit()
    return {"agreed": True, "me": await participant_me(db, participant)}


@router.get("/api/rooms/bookable")
async def bookable_rooms(participant: ParticipantDep, db: DbSession):
    settings = get_settings()
    now = utcnow()
    rooms = list(
        (
            await db.execute(
                select(Room)
                .where(Room.status.in_((ROOM_OPEN, ROOM_FULL)), Room.starts_at > now)
                .order_by(Room.starts_at)
            )
        )
        .scalars()
        .all()
    )
    counts_query = await db.execute(
        select(Booking.room_id, func.count(Booking.id))
        .where(Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED)))
        .group_by(Booking.room_id)
    )
    counts = dict(counts_query.all())
    blocking_booking = await blocking_booking_for_participant(db, participant.id)
    consent = await current_consent_version(db)
    consent_ok = consent is not None and participant.consent_version_id == consent.id
    lock = await one_time_experiment_lock(db, participant.id)
    eligible = participant.status == PARTICIPANT_ELIGIBLE and consent_ok and not lock.locked
    items = []
    for room in rooms:
        count = int(counts.get(room.id, 0))
        already_booked = blocking_booking is not None and blocking_booking.room_id == room.id
        has_blocking_booking = blocking_booking is not None and not already_booked
        can_book = eligible and count < 2 and not has_blocking_booking and not already_booked
        items.append(
            {
                "id": room.id,
                "startsAt": isoformat_utc(room.starts_at),
                "bookedCount": count,
                "capacity": 2,
                "full": count >= 2,
                "canBook": can_book,
                "alreadyBooked": already_booked,
            }
        )
    return {
        "rooms": items,
        "serverNow": isoformat_utc(now),
        "timezone": settings.timezone,
        "canBook": eligible and (blocking_booking is None),
    }


@router.post("/api/rooms/{room_id}/book", dependencies=[Depends(require_csrf)])
async def create_booking(room_id: str, participant: ParticipantDep, db: DbSession):
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实验不存在")
    booking = await book_room(db, room, participant)
    await db.commit()
    count = await db.execute(
        select(func.count(Booking.id)).where(
            Booking.room_id == room.id, Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED))
        )
    )
    return {
        "booking": {"id": booking.id, "roomId": room.id, "status": booking.status},
        "bookedCount": count.scalar_one(),
        "capacity": 2,
        "roomStatus": room.status,
    }


@router.post("/api/bookings/{booking_id}/cancel", dependencies=[Depends(require_csrf)])
async def cancel(booking_id: str, participant: ParticipantDep, db: DbSession):
    booking = await db.get(Booking, booking_id)
    if booking is None or booking.participant_id != participant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "预约不存在")
    room = await db.get(Room, booking.room_id)
    await cancel_booking(db, room, booking)
    await db.commit()
    return {"canceled": True}


async def _room_public_state(db, room: Room, participant, booking: Booking) -> dict:
    count_query = await db.execute(
        select(func.count(Booking.id)).where(
            Booking.room_id == room.id, Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED))
        )
    )
    role_row_query = await db.execute(
        select(RoomParticipant).where(
            RoomParticipant.room_id == room.id, RoomParticipant.participant_id == participant.id
        )
    )
    role_row = role_row_query.scalars().first()
    now = utcnow()
    return {
        "roomId": room.id,
        "startsAt": isoformat_utc(room.starts_at),
        "bookedCount": count_query.scalar_one(),
        "capacity": 2,
        "status": room.status,
        "archiveReason": room.archive_reason,
        "canEnter": now >= room.starts_at or room.status not in (ROOM_OPEN, ROOM_FULL),
        "canCancel": (
            room.status in (ROOM_OPEN, ROOM_FULL)
            and now < room.starts_at
            and booking.status == BOOKING_BOOKED
        ),
        "bookingStatus": booking.status,
        "role": role_row.role if role_row else None,
        "instructionCompleted": bool(role_row and role_row.instruction_completed_at is not None),
        "questionnaireStatus": role_row.questionnaire_status if role_row else None,
        "completedAt": isoformat_utc(role_row.completed_at) if role_row else None,
    }


@router.get("/api/my-room")
async def my_room(participant: ParticipantDep, db: DbSession):
    pending_rows = await db.execute(
        select(Room, RoomParticipant)
        .join(RoomParticipant, RoomParticipant.room_id == Room.id)
        .where(
            RoomParticipant.participant_id == participant.id,
            RoomParticipant.questionnaire_status != QUESTIONNAIRE_COMPLETED,
            or_(
                Room.status == ROOM_QUESTIONNAIRE,
                and_(
                    Room.status == ROOM_ARCHIVED,
                    Room.archive_reason == "questionnaire_incomplete",
                ),
            ),
        )
        .order_by(Room.starts_at.desc())
    )
    pending_questionnaires = [
        {
            "roomId": room.id,
            "startsAt": isoformat_utc(room.starts_at),
            "questionnaireStatus": row.questionnaire_status,
            "archiveReason": room.archive_reason,
            "canContinue": True,
            "kind": "formal",
            "showupPayCents": 0,
            "questionnaireRequired": True,
        }
        for room, row in pending_rows.all()
    ]
    showup_rows = await db.execute(
        select(Room, RoomParticipant, MapGroupVersion.showup_pay_cents)
        .join(RoomParticipant, RoomParticipant.room_id == Room.id)
        .join(
            Booking,
            and_(
                Booking.room_id == Room.id,
                Booking.participant_id == RoomParticipant.participant_id,
                Booking.status == BOOKING_ATTENDED,
            ),
        )
        .join(MapGroupVersion, MapGroupVersion.id == Room.map_group_version_id)
        .where(
            RoomParticipant.participant_id == participant.id,
            RoomParticipant.questionnaire_status != QUESTIONNAIRE_COMPLETED,
            Room.status == ROOM_ARCHIVED,
            Room.archive_reason == ARCHIVE_TECHNICAL_ABORT,
            MapGroupVersion.showup_pay_cents > 0,
        )
        .order_by(Room.starts_at.desc())
    )
    pending_questionnaires.extend(
        {
            "roomId": room.id,
            "startsAt": isoformat_utc(room.starts_at),
            "questionnaireStatus": row.questionnaire_status,
            "archiveReason": room.archive_reason,
            "canContinue": True,
            "kind": "technical_abort",
            "showupPayCents": showup_pay_cents,
            "questionnaireRequired": True,
        }
        for room, row, showup_pay_cents in showup_rows.all()
    )
    booking = await active_booking_for_participant(db, participant.id)
    if booking is None:
        return {"room": None, "pendingQuestionnaires": pending_questionnaires}
    room = await db.get(Room, booking.room_id)
    return {
        "room": await _room_public_state(db, room, participant, booking),
        "bookingId": booking.id,
        "pendingQuestionnaires": pending_questionnaires,
    }


@router.get("/api/my-experiments")
async def my_experiments(participant: ParticipantDep, db: DbSession):
    rows = await db.execute(
        select(Booking, Room)
        .join(Room, Room.id == Booking.room_id)
        .where(
            Booking.participant_id == participant.id,
            or_(
                Booking.status != BOOKING_CANCELED,
                and_(
                    Booking.status == BOOKING_CANCELED,
                    Room.status == ROOM_ARCHIVED,
                    Room.archive_reason == ARCHIVE_ADMIN_CANCELLED,
                ),
            ),
        )
        .order_by(Room.starts_at.desc())
    )
    records = rows.all()
    room_ids = {room.id for _booking, room in records}
    canceled_by_participant: set[str] = set()
    exited_rooms: set[str] = set()
    if room_ids:
        canceled_rows = await db.execute(
            select(RoomEvent.room_id).where(
                RoomEvent.participant_id == participant.id,
                RoomEvent.type == "booking_canceled",
                RoomEvent.room_id.in_(room_ids),
            )
        )
        canceled_by_participant = set(canceled_rows.scalars().all())
        exited_rows = await db.execute(
            select(RoomEvent.room_id, RoomEvent.payload_json).where(
                RoomEvent.participant_id == participant.id,
                RoomEvent.type == "participant_exited",
                RoomEvent.room_id.in_(room_ids),
            )
        )
        exit_reasons_by_room: dict[str, str] = {}
        for exited_room_id, payload in exited_rows.all():
            exit_reasons_by_room[exited_room_id] = (
                "inactivity" if (payload or {}).get("reason") == "inactivity" else "manual"
            )
    lock = await one_time_experiment_lock(db, participant.id)
    items = []
    for booking, room in records:
        if booking.status == BOOKING_CANCELED and room.id in canceled_by_participant:
            continue
        role_row_query = await db.execute(
            select(RoomParticipant).where(
                RoomParticipant.room_id == room.id, RoomParticipant.participant_id == participant.id
            )
        )
        role_row = role_row_query.scalars().first()
        payment_query = await db.execute(
            select(Payment).where(Payment.room_id == room.id, Payment.participant_id == participant.id)
        )
        payment = payment_query.scalars().first()
        can_rebook = (
            room.status == ROOM_ARCHIVED
            and room.archive_reason not in (ARCHIVE_COMPLETED, ARCHIVE_QUESTIONNAIRE_INCOMPLETE)
            and not lock.locked
        )
        showup_pay_cents = 0
        if room.archive_reason == ARCHIVE_TECHNICAL_ABORT and booking.status == BOOKING_ATTENDED:
            showup_pay_cents = get_room_payment(room)["showupPayCents"]
        questionnaire_required = (
            showup_pay_cents > 0
            and (role_row is None or role_row.questionnaire_status != QUESTIONNAIRE_COMPLETED)
        )
        items.append(
            {
                "roomId": room.id,
                "startsAt": isoformat_utc(room.starts_at),
                "roomStatus": room.status,
                "archiveReason": room.archive_reason,
                "bookingStatus": booking.status,
                "role": role_row.role if role_row else None,
                "instructionCompleted": bool(role_row and role_row.instruction_completed_at is not None),
                "questionnaireStatus": role_row.questionnaire_status if role_row else None,
                "completedAt": isoformat_utc(role_row.completed_at) if role_row else None,
                "selfAttended": booking.status == BOOKING_ATTENDED,
                "selfExited": room.id in exit_reasons_by_room,
                "selfExitReason": exit_reasons_by_room.get(room.id),
                "canRebook": can_rebook,
                "questionnaireRequired": questionnaire_required,
                "showupPayCents": showup_pay_cents,
                "rewardKind": participant_reward_kind(payment),
                "payment": (
                    serialize_payment(payment, role_row.analysis_code if role_row else None)
                    if payment is not None
                    else None
                ),
            }
        )
    return {"experiments": items}


@router.get("/api/my-payments")
async def my_payments(participant: ParticipantDep, db: DbSession):
    rows = await db.execute(
        select(Payment, Room, RoomParticipant)
        .join(Room, Room.id == Payment.room_id)
        .outerjoin(
            RoomParticipant,
            (RoomParticipant.room_id == Payment.room_id)
            & (RoomParticipant.participant_id == Payment.participant_id),
        )
        .where(Payment.participant_id == participant.id)
        .order_by(Room.starts_at.desc())
    )
    items = []
    for payment, room, role_row in rows.all():
        data = serialize_payment(payment, role_row.analysis_code if role_row else None)
        data["roomStartsAt"] = isoformat_utc(room.starts_at)
        data["roomStatus"] = room.status
        data["roomArchiveReason"] = room.archive_reason
        items.append(data)
    return {"payments": items, "timezone": get_settings().timezone}


@router.get("/api/questionnaire/context")
async def questionnaire_context(
    participant: ParticipantDep,
    db: DbSession,
    room_id: str | None = Query(default=None, alias="roomId"),
):
    if room_id is None:
        booking = await active_booking_for_participant(db, participant.id)
        if booking is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "当前没有进行中的实验")
        room_id = booking.room_id
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实验不存在")
    if room.status not in (ROOM_QUESTIONNAIRE, ROOM_ARCHIVED):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前实验尚未进入问卷阶段")
    if room.status == ROOM_ARCHIVED:
        allowed = room.archive_reason in ("questionnaire_incomplete", "completed")
        if not allowed:
            allowed = await technical_abort_showup_eligible(db, room, participant.id)
        if not allowed:
            raise HTTPException(status.HTTP_409_CONFLICT, "当前实验已结束")
    row_query = await db.execute(
        select(RoomParticipant).where(
            RoomParticipant.room_id == room.id, RoomParticipant.participant_id == participant.id
        )
    )
    row = row_query.scalars().first()
    if row is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "你不属于本次实验")
    try:
        url = await build_questionnaire_url(db, room, row)
    except HTTPException:
        url = None
    return {
        "roomId": room.id,
        "roomStatus": room.status,
        "archiveReason": room.archive_reason,
        "url": url,
        "status": row.questionnaire_status,
        "submitted": row.questionnaire_status == QUESTIONNAIRE_COMPLETED,
    }


@router.post("/api/questionnaire/complete", dependencies=[Depends(require_csrf)])
async def questionnnaire_complete(
    payload: ParticipantQuestionnaireCompleteRequest, participant: ParticipantDep, db: DbSession
):
    from ..services.runtime import runtime_manager

    result = await complete_with_participant(
        db,
        participant,
        payload.room_id,
        {
            "answers": payload.answers,
            "jatos_worker_id": payload.jatos_worker_id,
            "jatos_study_result_id": payload.jatos_study_result_id,
            "jatos_component_result_id": payload.jatos_component_result_id,
        },
    )
    await runtime_manager.notify_room(payload.room_id)
    return result


@router.get("/api/contact")
async def contact_info(db: DbSession):
    row = await db.get(SystemSetting, "contact_info")
    value = row.value_json.get("value") if row is not None and isinstance(row.value_json, dict) else None
    return {"contact": value}
