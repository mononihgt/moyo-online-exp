from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from ..constants import (
    ARCHIVE_ADMIN_ABORTED,
    ARCHIVE_ADMIN_CANCELLED,
    ARCHIVE_COMPLETED,
    ARCHIVE_QUESTIONNAIRE_INCOMPLETE,
    ARCHIVE_REASONS,
    ARCHIVE_TECHNICAL_ABORT,
    BOOKING_ATTENDED,
    BOOKING_BOOKED,
    BOOKING_CANCELED,
    BOOKING_NO_SHOW,
    PARTICIPANT_COMPLETED,
    PARTICIPANT_DISABLED,
    QUESTIONNAIRE_COMPLETED,
    ROOM_ARCHIVED,
    ROOM_FULL,
    ROOM_INSTRUCTIONS,
    ROOM_OPEN,
    ROOM_PLAYING,
    ROOM_QUESTIONNAIRE,
    ROOM_WAITING,
)
from ..models import (
    Booking,
    GameTrial,
    Participant,
    Payment,
    Room,
    RoomConfigRevision,
    RoomEvent,
    RoomParticipant,
    RoomTimer,
)
from ..schemas import (
    BookingCreate,
    IdentityUpdate,
    RoomAction,
    RoomBatchCreate,
    RoomCopy,
    RoomCreate,
    RoomPatch,
)
from ..security import decrypt_phone, mask_phone
from ..services.events import add_event
from ..services.export import build_analysis_zip, build_room_export
from ..services.identities import get_identity, upsert_identity_values
from ..services.jatos import build_questionnaire_url, jatos_config
from ..services.locking import room_lock
from ..services.payments import serialize_payment
from ..services.questionnaire_flow import complete_questionnaire
from ..services.questionnaires import QuestionnaireValidationError, validate_identity_values
from ..services.rooms import (
    add_config_revision,
    allowed_archive_reason_corrections,
    archive_room,
    book_room,
    cancel_room,
    close_booking,
    correct_archive_reason,
    count_room_sections,
    create_room,
    list_rooms_by_section,
    publish_room,
    restore_attendance,
    room_config_dict,
    room_summary,
    technical_abort_showup_eligible,
    update_room,
)
from ..services.runtime import runtime_manager
from ..timeutil import isoformat_utc, utcnow
from .admin_common import audit
from .deps import AdminDep, DbSession, require_csrf

router = APIRouter()


@router.get("/rooms")
async def list_rooms(
    admin: AdminDep,
    db: DbSession,
    section: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
):
    rooms = await list_rooms_by_section(db, section, limit, offset)
    return {
        "rooms": [await room_summary(db, room) for room in rooms],
        "counts": await count_room_sections(db),
    }


async def _get_room(db, room_id: str) -> Room:
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "房间不存在")
    return room


@router.post("/rooms", dependencies=[Depends(require_csrf)])
async def post_room(payload: RoomCreate, admin: AdminDep, db: DbSession):
    room = await create_room(db, payload.model_dump())
    audit(db, admin, "room_created", "room", room.id)
    await db.commit()
    return {"room": await room_summary(db, room)}


@router.post("/rooms/batch", dependencies=[Depends(require_csrf)])
async def post_rooms_batch(payload: RoomBatchCreate, admin: AdminDep, db: DbSession):
    template = payload.template.model_dump()
    map_group_ids = payload.map_group_version_ids or [template["map_group_version_id"]]
    rooms = []
    for index in range(payload.count):
        data = dict(template)
        data["internal_label"] = f"{template['internal_label']} {index + 1}"
        data["map_group_version_id"] = map_group_ids[index % len(map_group_ids)]
        room = await create_room(db, data)
        audit(db, admin, "room_created", "room", room.id, {"batch": True})
        rooms.append(room)
    await db.commit()
    return {"rooms": [await room_summary(db, room) for room in rooms]}


@router.post("/rooms/{room_id}/copy", dependencies=[Depends(require_csrf)])
async def copy_room(room_id: str, payload: RoomCopy, admin: AdminDep, db: DbSession):
    source = await _get_room(db, room_id)
    data = {
        "internal_label": payload.internal_label or f"{source.internal_label} 副本",
        "starts_at": payload.starts_at or source.starts_at,
        "map_group_version_id": source.map_group_version_id,
        "instruction_version_p1_id": source.instruction_version_p1_id,
        "instruction_version_p2_id": source.instruction_version_p2_id,
        "questionnaire_version_id": source.questionnaire_version_id,
        "wait_window_seconds": source.wait_window_seconds,
        "reconnect_window_seconds": source.reconnect_window_seconds,
    }
    room = await create_room(db, data)
    audit(db, admin, "room_copied", "room", room.id, {"sourceRoomId": source.id})
    await db.commit()
    return {"room": await room_summary(db, room)}


@router.get("/rooms/{room_id}")
async def get_room(room_id: str, admin: AdminDep, db: DbSession):
    room = await _get_room(db, room_id)
    return await _room_detail(db, room)


async def _room_detail(db, room: Room) -> dict:
    summary = await room_summary(db, room)
    revisions = await db.execute(
        select(RoomConfigRevision)
        .where(RoomConfigRevision.room_id == room.id)
        .order_by(RoomConfigRevision.revision)
    )
    booking_rows = await db.execute(
        select(Booking, Participant)
        .join(Participant, Participant.id == Booking.participant_id)
        .where(Booking.room_id == room.id)
        .order_by(Booking.created_at)
    )
    participant_rows = await db.execute(
        select(RoomParticipant, Participant)
        .join(Participant, Participant.id == RoomParticipant.participant_id)
        .where(RoomParticipant.room_id == room.id)
        .order_by(RoomParticipant.role)
    )
    participants = []
    for row, participant in participant_rows.all():
        participants.append(
            {
                "id": row.id,
                "role": row.role,
                "analysisCode": row.analysis_code,
                "name": participant.name,
                "phoneMasked": mask_phone(decrypt_phone(participant.phone_encrypted)),
                "participantStatus": participant.status,
                "instructionStartedAt": isoformat_utc(row.instruction_started_at),
                "instructionCompletedAt": isoformat_utc(row.instruction_completed_at),
                "instructionConnectedSeconds": row.instruction_connected_seconds,
                "questionnaireStatus": row.questionnaire_status,
                "completedAt": isoformat_utc(row.completed_at),
                "online": participant.id in runtime_manager.connections.get(room.id, {}),
            }
        )
    bookings = [
        {
            "id": booking.id,
            "participantId": participant.id,
            "name": participant.name,
            "phoneMasked": mask_phone(decrypt_phone(participant.phone_encrypted)),
            "participantStatus": participant.status,
            "status": booking.status,
            "createdAt": isoformat_utc(booking.created_at),
            "canceledAt": isoformat_utc(booking.canceled_at),
            "attendedAt": isoformat_utc(booking.attended_at),
            "canRestoreAttendance": (
                room.status == ROOM_ARCHIVED
                and room.archive_reason != ARCHIVE_ADMIN_CANCELLED
                and booking.status == BOOKING_NO_SHOW
                and booking.attended_at is not None
                and booking.canceled_at is None
            ),
        }
        for booking, participant in booking_rows.all()
    ]
    payments_rows = await db.execute(
        select(Payment, RoomParticipant, Participant)
        .join(Participant, Participant.id == Payment.participant_id)
        .outerjoin(
            RoomParticipant,
            (RoomParticipant.room_id == Payment.room_id)
            & (RoomParticipant.participant_id == Payment.participant_id),
        )
        .where(Payment.room_id == room.id)
    )
    payments = []
    for payment, role_row, participant in payments_rows.all():
        item = serialize_payment(
            payment, role_row.analysis_code if role_row else None
        )
        item.update({"participantId": participant.id, "name": participant.name})
        payments.append(item)
    allowed_corrections = await allowed_archive_reason_corrections(db, room)
    jatos_base_url, jatos_study_code = await jatos_config(db)
    return {
        "room": summary,
        "config": room_config_dict(room),
        "configRevisions": [
            {"revision": row.revision, "createdAt": isoformat_utc(row.created_at), "config": row.config_json}
            for row in revisions.scalars().all()
        ],
        "configSnapshot": room.config_snapshot,
        "bookings": bookings,
        "participants": participants,
        "payments": payments,
        "archiveReasonCorrectionOptions": allowed_corrections,
        "jatosAdminUrl": f"{jatos_base_url}/jatos" if jatos_base_url else None,
        "jatosStudyCode": jatos_study_code or None,
    }


def _serialize_identity(identity: dict | None) -> dict | None:
    if identity is None:
        return None
    return {
        "realName": identity["real_name"],
        "alipayPhone": identity["alipay_phone"],
        "documentType": identity["document_type"],
        "documentNumber": identity["document_number"],
    }


async def _participant_in_room(db, room_id: str, participant_id: str) -> bool:
    booking = await db.execute(
        select(Booking.id).where(
            Booking.room_id == room_id,
            Booking.participant_id == participant_id,
        )
    )
    if booking.first() is not None:
        return True
    room_participant = await db.execute(
        select(RoomParticipant.id).where(
            RoomParticipant.room_id == room_id,
            RoomParticipant.participant_id == participant_id,
        )
    )
    return room_participant.first() is not None


@router.get("/rooms/{room_id}/participants/{participant_id}/identity")
async def read_participant_identity(
    room_id: str,
    participant_id: str,
    admin: AdminDep,
    db: DbSession,
    response: Response,
):
    room = await _get_room(db, room_id)
    if not await _participant_in_room(db, room.id, participant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该参与者不属于本次实验")
    identity = await get_identity(db, room.id, participant_id)
    audit(
        db,
        admin,
        "identity_viewed",
        "participant_identity",
        f"{room.id}:{participant_id}",
        {"roomId": room.id, "participantId": participant_id},
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"identity": _serialize_identity(identity)}


@router.put(
    "/rooms/{room_id}/participants/{participant_id}/identity",
    dependencies=[Depends(require_csrf)],
)
async def update_participant_identity(
    room_id: str,
    participant_id: str,
    payload: IdentityUpdate,
    admin: AdminDep,
    db: DbSession,
    response: Response,
):
    room = await _get_room(db, room_id)
    if not await _participant_in_room(db, room.id, participant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该参与者不属于本次实验")
    try:
        validated = validate_identity_values(
            payload.real_name,
            payload.alipay_phone,
            payload.document_type,
            payload.document_number,
        )
    except QuestionnaireValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await upsert_identity_values(db, room.id, participant_id, validated)
    audit(
        db,
        admin,
        "participant_identity_updated",
        "participant_identity",
        f"{room.id}:{participant_id}",
        {
            "roomId": room.id,
            "participantId": participant_id,
            "reason": payload.reason,
            "changedFields": [
                "real_name",
                "alipay_phone",
                "document_type",
                "document_number",
            ],
        },
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {
        "identity": _serialize_identity(
            await get_identity(db, room.id, participant_id)
        )
    }


@router.patch("/rooms/{room_id}", dependencies=[Depends(require_csrf)])
async def patch_room(room_id: str, payload: RoomPatch, admin: AdminDep, db: DbSession):
    async with room_lock(room_id):
        await db.commit()
        room = await _get_room(db, room_id)
        room = await update_room(db, room, payload.model_dump(exclude_unset=True))
        audit(
            db,
            admin,
            "room_updated",
            "room",
            room.id,
            payload.model_dump(mode="json", exclude_unset=True),
        )
        await db.commit()
    return {"room": await room_summary(db, room)}


@router.post("/rooms/{room_id}/publish", dependencies=[Depends(require_csrf)])
async def post_publish_room(room_id: str, admin: AdminDep, db: DbSession):
    async with room_lock(room_id):
        await db.commit()
        room = await _get_room(db, room_id)
        room = await publish_room(db, room)
        audit(db, admin, "room_published", "room", room.id)
        await db.commit()
    return {"room": await room_summary(db, room)}


@router.post("/rooms/{room_id}/close-booking", dependencies=[Depends(require_csrf)])
async def post_close_booking(room_id: str, admin: AdminDep, db: DbSession):
    async with room_lock(room_id):
        await db.commit()
        room = await _get_room(db, room_id)
        room = await close_booking(db, room)
        audit(db, admin, "room_booking_closed", "room", room.id)
        await db.commit()
    return {"room": await room_summary(db, room)}


@router.post("/rooms/{room_id}/cancel", dependencies=[Depends(require_csrf)])
async def post_cancel_room(room_id: str, admin: AdminDep, db: DbSession):
    async with room_lock(room_id):
        await db.commit()
        room = await _get_room(db, room_id)
        await cancel_room(db, room)
        audit(db, admin, "room_cancelled", "room", room.id)
        await db.commit()
    await runtime_manager.notify_room(room.id)
    return {"room": await room_summary(db, room)}


@router.post("/rooms/{room_id}/archive", dependencies=[Depends(require_csrf)])
async def post_archive_room(room_id: str, payload: RoomAction, admin: AdminDep, db: DbSession):
    async with room_lock(room_id):
        await db.commit()
        room = await _get_room(db, room_id)
        reason = payload.reason or _default_archive_reason(room)
        await _validate_archive_reason(db, room, reason)
        await archive_room(db, room, reason)
        audit(db, admin, "room_archived", "room", room.id, {"reason": reason})
        await db.commit()
    await runtime_manager.notify_room(room.id)
    return {"room": await room_summary(db, room)}


def _default_archive_reason(room: Room) -> str:
    if room.status == ROOM_QUESTIONNAIRE:
        return ARCHIVE_QUESTIONNAIRE_INCOMPLETE
    if room.status in (ROOM_WAITING, ROOM_INSTRUCTIONS, ROOM_PLAYING) or utcnow() >= room.starts_at:
        return ARCHIVE_ADMIN_ABORTED
    return ARCHIVE_ADMIN_CANCELLED


async def _validate_archive_reason(db, room: Room, reason: str) -> None:
    if reason not in ARCHIVE_REASONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "归档原因无效")
    if room.status == ROOM_ARCHIVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "房间已归档")
    if room.status == ROOM_QUESTIONNAIRE:
        allowed = {ARCHIVE_QUESTIONNAIRE_INCOMPLETE}
    elif (
        room.status in (ROOM_WAITING, ROOM_INSTRUCTIONS, ROOM_PLAYING)
        or utcnow() >= room.starts_at
    ):
        allowed = {ARCHIVE_ADMIN_ABORTED}
    else:
        allowed = {ARCHIVE_ADMIN_CANCELLED}
    statuses = list(
        (
            await db.execute(
                select(RoomParticipant.questionnaire_status).where(RoomParticipant.room_id == room.id)
            )
        )
        .scalars()
        .all()
    )
    if statuses and all(status == QUESTIONNAIRE_COMPLETED for status in statuses):
        allowed.add(ARCHIVE_COMPLETED)
    if reason not in allowed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前阶段不允许该归档原因")


@router.post("/rooms/{room_id}/bookings", dependencies=[Depends(require_csrf)])
async def add_booking(room_id: str, payload: BookingCreate, admin: AdminDep, db: DbSession):
    async with room_lock(room_id):
        await db.commit()
        room = await _get_room(db, room_id)
        participant = await db.get(Participant, payload.participant_id)
        if participant is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "参与者不存在")
        booking = await book_room(db, room, participant, allow_after_start=True)
        audit(db, admin, "booking_added", "room", room.id, {"participantId": participant.id})
        await db.commit()
    return {"bookingId": booking.id}


@router.delete("/rooms/{room_id}/bookings/{booking_id}", dependencies=[Depends(require_csrf)])
async def remove_booking(room_id: str, booking_id: str, admin: AdminDep, db: DbSession):
    async with room_lock(room_id):
        await db.commit()
        room = await _get_room(db, room_id)
        booking = await db.get(Booking, booking_id)
        if booking is None or booking.room_id != room.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "预约不存在")
        if room.status in (ROOM_INSTRUCTIONS, ROOM_PLAYING, ROOM_QUESTIONNAIRE, ROOM_ARCHIVED):
            raise HTTPException(status.HTTP_409_CONFLICT, "当前房间状态不允许移除预约")
        if booking.status not in (BOOKING_BOOKED, BOOKING_ATTENDED):
            raise HTTPException(status.HTTP_409_CONFLICT, "预约当前状态不允许移除")
        booking.status = BOOKING_CANCELED
        booking.canceled_at = utcnow()
        if room.status == ROOM_FULL:
            room.status = ROOM_OPEN
        add_event(db, room, "booking_canceled", booking.participant_id, {"by": "admin"})
        audit(db, admin, "booking_removed", "room", room.id, {"bookingId": booking.id})
        await db.commit()
    await runtime_manager.notify_room(room_id)
    return {"removed": True}


@router.get("/rooms/{room_id}/monitor")
async def monitor_room(room_id: str, admin: AdminDep, db: DbSession):
    room = await _get_room(db, room_id)
    state = room.runtime_state or {}
    events_query = await db.execute(
        select(RoomEvent)
        .where(RoomEvent.room_id == room.id)
        .order_by(RoomEvent.created_at.desc())
        .limit(60)
    )
    timers_query = await db.execute(
        select(RoomTimer).where(RoomTimer.room_id == room.id).order_by(RoomTimer.due_at.desc()).limit(20)
    )
    trials_query = await db.execute(
        select(GameTrial).where(GameTrial.room_id == room.id).order_by(GameTrial.trial_index)
    )
    rows = await db.execute(
        select(RoomParticipant, Participant)
        .join(Participant, Participant.id == RoomParticipant.participant_id)
        .where(RoomParticipant.room_id == room.id)
        .order_by(RoomParticipant.role)
    )
    participants = [
        {
            "role": row.role,
            "name": participant.name,
            "online": participant.id in runtime_manager.connections.get(room.id, {}),
            "instructionCompleted": row.instruction_completed_at is not None,
            "questionnaireStatus": row.questionnaire_status,
            "disconnectedUntil": state.get("disconnected", {}).get(participant.id),
        }
        for row, participant in rows.all()
    ]
    return {
        "room": await room_summary(db, room),
        "phase": state.get("phase"),
        "trialIndex": state.get("trial_index"),
        "round": state.get("round"),
        "turnDeadline": state.get("turn_deadline"),
        "restDeadline": state.get("rest_deadline"),
        "participants": participants,
        "trials": [
            {
                "trialIndex": trial.trial_index,
                "isPractice": trial.is_practice,
                "formalTrial": trial.formal_trial,
                "startedAt": isoformat_utc(trial.started_at),
                "endedAt": isoformat_utc(trial.ended_at),
                "winner": trial.winner,
                "endReason": trial.end_reason,
            }
            for trial in trials_query.scalars().all()
        ],
        "events": [
            {
                "type": event.type,
                "createdAt": isoformat_utc(event.created_at),
                "payload": event.payload_json,
            }
            for event in events_query.scalars().all()
        ],
        "timers": [
            {
                "kind": timer.kind,
                "dueAt": isoformat_utc(timer.due_at),
                "status": timer.status,
                "firedAt": isoformat_utc(timer.fired_at),
            }
            for timer in timers_query.scalars().all()
        ],
    }


@router.post("/rooms/{room_id}/actions", dependencies=[Depends(require_csrf)])
async def room_action(room_id: str, payload: RoomAction, admin: AdminDep, db: DbSession):
    notify = False
    async with room_lock(room_id):
        await db.commit()
        room = await _get_room(db, room_id)
        action = payload.action
        if action == "correct_archive_reason":
            if not payload.reason:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须提供目标结束原因")
            if payload.note is None or not payload.note.strip():
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须填写更正说明")
            previous_reason = room.archive_reason
            await correct_archive_reason(
                db,
                room,
                payload.reason,
                payload.note,
                expected_current_reason=payload.expected_current_reason,
            )
            audit(
                db,
                admin,
                "archive_reason_corrected",
                "room",
                room.id,
                {
                    "previousReason": previous_reason,
                    "reason": room.archive_reason,
                    "note": payload.note.strip(),
                },
            )
            await db.commit()
            result = {
                "ok": True,
                "previousReason": previous_reason,
                "reason": room.archive_reason,
            }
            notify = True
        elif action == "restore_attendance":
            if not payload.booking_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须提供预约")
            if payload.note is None or not payload.note.strip():
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须填写恢复说明")
            booking = await db.get(Booking, payload.booking_id)
            if booking is None or booking.room_id != room.id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "预约不存在")
            payment_before_query = await db.execute(
                select(Payment).where(
                    Payment.room_id == room.id,
                    Payment.participant_id == booking.participant_id,
                )
            )
            payment_before = payment_before_query.scalars().first()
            previous_amount = payment_before.total_cents if payment_before else None
            previous_reason = room.archive_reason
            payment_after = await restore_attendance(db, room, booking, payload.note)
            audit(
                db,
                admin,
                "booking_attendance_restored",
                "booking",
                booking.id,
                {
                    "roomId": room.id,
                    "participantId": booking.participant_id,
                    "previousStatus": BOOKING_NO_SHOW,
                    "status": booking.status,
                    "previousArchiveReason": previous_reason,
                    "archiveReason": room.archive_reason,
                    "previousAmountCents": previous_amount,
                    "amountCents": (
                        payment_after.total_cents if payment_after is not None else None
                    ),
                },
            )
            await db.commit()
            result = {
                "ok": True,
                "bookingId": booking.id,
                "archiveReason": room.archive_reason,
                "payment": (
                    serialize_payment(payment_after)
                    if payment_after is not None
                    else None
                ),
            }
            notify = True
        elif action == "force_archive":
            reason = payload.reason or _default_archive_reason(room)
            await _validate_archive_reason(db, room, reason)
            await archive_room(db, room, reason)
            audit(db, admin, "room_force_archived", "room", room.id, {"reason": reason})
            await db.commit()
            result = {"ok": True, "reason": reason}
            notify = True
        elif action == "extend_wait":
            if room.status != ROOM_WAITING:
                raise HTTPException(status.HTTP_409_CONFLICT, "只有等待阶段可以延长等待窗口")
            if payload.minutes is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须提供延长分钟数")
            room.wait_window_seconds += payload.minutes * 60
            await add_config_revision(db, room)
            add_event(db, room, "admin_action", payload={"action": action, "minutes": payload.minutes})
            audit(db, admin, "wait_window_extended", "room", room.id, {"minutes": payload.minutes})
            await db.commit()
            result = {"ok": True, "waitWindowSeconds": room.wait_window_seconds}
            notify = True
        elif action == "resend_questionnaire":
            technical_abort = (
                room.status == ROOM_ARCHIVED
                and room.archive_reason == ARCHIVE_TECHNICAL_ABORT
            )
            if room.status != ROOM_QUESTIONNAIRE and not technical_abort:
                raise HTTPException(status.HTTP_409_CONFLICT, "房间不在问卷阶段")
            rows_query = await db.execute(
                select(RoomParticipant).where(RoomParticipant.room_id == room.id)
            )
            rows = list(rows_query.scalars().all())
            if payload.participant_id:
                rows = [row for row in rows if row.participant_id == payload.participant_id]
            if technical_abort:
                eligible_rows = []
                for row in rows:
                    if row.questionnaire_status == QUESTIONNAIRE_COMPLETED:
                        continue
                    if await technical_abort_showup_eligible(
                        db, room, row.participant_id, room_participant=row
                    ):
                        eligible_rows.append(row)
                rows = eligible_rows
            if not rows:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到参与者")
            links = []
            for row in rows:
                url = await build_questionnaire_url(db, room, row)
                links.append({"participantId": row.participant_id, "url": url})
            add_event(db, room, "admin_action", payload={"action": action})
            audit(db, admin, "questionnaire_resent", "room", room.id)
            await db.commit()
            result = {"links": links}
        elif action == "mark_absent":
            booking: Booking | None = None
            if payload.booking_id is not None:
                booking = await db.get(Booking, payload.booking_id)
                if booking is None or booking.room_id != room.id:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "预约不存在")
                if (
                    payload.participant_id is not None
                    and payload.participant_id != booking.participant_id
                ):
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "预约与参与者不匹配")
                payload.participant_id = booking.participant_id
            else:
                if payload.participant_id is None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须提供参与者")
                booking = (
                    await db.execute(
                        select(Booking).where(
                            Booking.room_id == room.id,
                            Booking.participant_id == payload.participant_id,
                            Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED)),
                        )
                    )
                ).scalars().first()
                if booking is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "预约不存在")
            if (
                room.status == ROOM_ARCHIVED
                and room.archive_reason == ARCHIVE_TECHNICAL_ABORT
                and booking.status == BOOKING_ATTENDED
            ):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "技术中止后不能把到场参与者标记缺席",
                )
            if booking.status not in (BOOKING_BOOKED, BOOKING_ATTENDED):
                raise HTTPException(status.HTTP_409_CONFLICT, "预约当前状态不允许标记缺席")
            room_participant_query = await db.execute(
                select(RoomParticipant).where(
                    RoomParticipant.room_id == room.id,
                    RoomParticipant.participant_id == payload.participant_id,
                )
            )
            room_participant = room_participant_query.scalars().first()
            if (
                room_participant is not None
                and room_participant.questionnaire_status == QUESTIONNAIRE_COMPLETED
            ):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "参与者已完成问卷，不能改为缺席"
                )
            payment_query = await db.execute(
                select(Payment).where(
                    Payment.room_id == room.id,
                    Payment.participant_id == payload.participant_id,
                )
            )
            if payment_query.scalars().first() is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "参与者已有付款记录，不能改为缺席"
                )
            booking.status = BOOKING_NO_SHOW
            add_event(db, room, "admin_action", payload={"action": action, "participantId": payload.participant_id})
            audit(db, admin, "participant_marked_absent", "room", room.id, {"participantId": payload.participant_id})
            await db.commit()
            result = {"ok": True}
            notify = True
        elif action == "mark_completed":
            if payload.participant_id is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须提供参与者")
            if (
                room.status == ROOM_ARCHIVED
                and room.archive_reason == ARCHIVE_TECHNICAL_ABORT
            ):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "技术中止参与者请通过提交后测问卷生成到场费",
                )
            participant = await db.get(Participant, payload.participant_id)
            if participant is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "参与者不存在")
            participant.status = PARTICIPANT_COMPLETED
            add_event(db, room, "admin_action", payload={"action": action, "participantId": participant.id})
            audit(db, admin, "participant_marked_completed", "participant", participant.id)
            await db.commit()
            result = {"ok": True}
        elif action == "disable_participant":
            if payload.participant_id is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须提供参与者")
            participant = await db.get(Participant, payload.participant_id)
            if participant is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "参与者不存在")
            participant.status = PARTICIPANT_DISABLED
            add_event(db, room, "admin_action", payload={"action": action, "participantId": participant.id})
            audit(db, admin, "participant_disabled", "participant", participant.id)
            await db.commit()
            result = {"ok": True}
        elif action == "import_jatos_result":
            if payload.participant_id is None or not payload.jatos_study_result_id or not payload.jatos_component_result_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "缺少 JATOS 结果字段")
            if payload.answers is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "缺少问卷答案")
            row = (
                await db.execute(
                    select(RoomParticipant).where(
                        RoomParticipant.room_id == room.id,
                        RoomParticipant.participant_id == payload.participant_id,
                    )
                )
            ).scalars().first()
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "参与者不属于该房间")
            result = await complete_questionnaire(
                db,
                room,
                row,
                answers=payload.answers,
                jatos_worker_id=payload.jatos_worker_id,
                jatos_study_result_id=payload.jatos_study_result_id,
                jatos_component_result_id=payload.jatos_component_result_id,
                source="admin",
            )
            audit(db, admin, "jatos_result_imported", "room", room.id, {"participantId": payload.participant_id})
            await db.commit()
            notify = True
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "未知操作")
    if notify:
        await runtime_manager.notify_room(room_id)
    return result


@router.get("/rooms/{room_id}/export.json")
async def export_room_json(room_id: str, admin: AdminDep, db: DbSession):
    room = await _get_room(db, room_id)
    data = await build_room_export(db, room)
    audit(db, admin, "room_export_json", "room", room.id)
    await db.commit()
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="room-{room.id}.json"'})


@router.get("/rooms/{room_id}/analysis.zip")
async def export_room_zip(room_id: str, admin: AdminDep, db: DbSession):
    room = await _get_room(db, room_id)
    data = await build_analysis_zip(db, room)
    audit(db, admin, "room_export_zip", "room", room.id)
    await db.commit()
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="analysis-{room.id}.zip"'},
    )
