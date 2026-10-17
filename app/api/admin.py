from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select

from ..config import get_settings
from ..constants import (
    ARCHIVE_ADMIN_CANCELLED,
    ARCHIVE_QUESTIONNAIRE_INCOMPLETE,
    ARCHIVE_REASONS,
    ARCHIVE_TECHNICAL_ABORT,
    BOOKING_ATTENDED,
    BOOKING_BOOKED,
    BOOKING_CANCELED,
    BOOKING_NO_SHOW,
    PARTICIPANT_COMPLETED,
    PARTICIPANT_DISABLED,
    PAYMENT_PAID,
    ROOM_ARCHIVED,
    ROOM_FULL,
    ROOM_INSTRUCTIONS,
    ROOM_OPEN,
    ROOM_PLAYING,
    ROOM_QUESTIONNAIRE,
    ROOM_WAITING,
    VERSION_ARCHIVED,
    VERSION_DRAFT,
    VERSION_PUBLISHED,
)
from ..models import (
    AdminAuditLog,
    Booking,
    ConditionVersion,
    ConsentVersion,
    GameTrial,
    InstructionVersion,
    MediaAsset,
    Participant,
    Payment,
    QuestionnaireVersion,
    Room,
    RoomConfigRevision,
    RoomEvent,
    RoomParticipant,
    RoomTimer,
    SystemSetting,
)
from ..schemas import (
    BookingCreate,
    ConditionVersionCreate,
    ConditionVersionPatch,
    ConsentVersionCreate,
    ConsentVersionPatch,
    InstructionVersionCreate,
    InstructionVersionPatch,
    ParticipantPatch,
    PaymentPatch,
    QuestionnaireVersionCreate,
    QuestionnaireVersionPatch,
    RoomAction,
    RoomBatchCreate,
    RoomCopy,
    RoomCreate,
    RoomPatch,
    SettingsPatch,
)
from ..security import decrypt_phone, mask_phone
from ..services.conditions import (
    ConditionValidationError,
    create_condition,
    publish_condition,
    serialize_condition,
    update_condition,
)
from ..services.events import add_audit, add_event
from ..services.export import build_analysis_zip, build_payment_export_csv, build_room_export
from ..services.instructions import (
    create_instruction,
    publish_instruction,
    serialize_instruction,
    update_instruction,
)
from ..services.jatos import build_questionnaire_url
from ..services.media import save_image, serialize_media
from ..services.participants import import_completed, import_roster
from ..services.payments import apply_override, serialize_payment
from ..services.questionnaire_flow import complete_questionnaire
from ..services.questionnaires import (
    QuestionnaireValidationError,
    create_questionnaire,
    publish_questionnaire,
    serialize_questionnaire,
    update_questionnaire,
)
from ..services.rooms import (
    add_config_revision,
    archive_room,
    book_room,
    create_room,
    publish_room,
    room_config_dict,
    room_summary,
    update_room,
)
from ..services.runtime import runtime_manager
from ..timeutil import isoformat_utc, utcnow
from .deps import AdminDep, DbSession, require_csrf

router = APIRouter(prefix="/admin/api")


def _audit(db, admin, action: str, target_type: str, target_id: str, payload: dict | None = None) -> None:
    add_audit(db, admin.id, action, target_type, target_id, payload)


@router.get("/dashboard")
async def dashboard(admin: AdminDep, db: DbSession):
    status_rows = await db.execute(select(Room.status, func.count(Room.id)).group_by(Room.status))
    counts = {status_value: count for status_value, count in status_rows.all()}
    pending_payments = await db.execute(
        select(func.count(Payment.id)).where(Payment.status == "pending")
    )
    pending_questionnaires = await db.execute(
        select(func.count(Room.id)).where(Room.status == ROOM_QUESTIONNAIRE)
    )
    upcoming = await db.execute(
        select(Room)
        .where(Room.status.in_((ROOM_OPEN, ROOM_FULL)), Room.starts_at > utcnow())
        .order_by(Room.starts_at)
        .limit(5)
    )
    attention = await db.execute(
        select(Room)
        .where(Room.status.in_((ROOM_WAITING, ROOM_PLAYING, ROOM_QUESTIONNAIRE)))
        .order_by(Room.starts_at)
        .limit(10)
    )
    upcoming_items = [await room_summary(db, room) for room in upcoming.scalars().all()]
    attention_items = [await room_summary(db, room) for room in attention.scalars().all()]
    return {
        "roomCounts": counts,
        "pendingPayments": pending_payments.scalar_one(),
        "pendingQuestionnaireRooms": pending_questionnaires.scalar_one(),
        "upcomingRooms": upcoming_items,
        "attentionRooms": attention_items,
        "pendingQuestionnaireCount": counts.get(ROOM_QUESTIONNAIRE, 0),
    }


@router.get("/participants")
async def list_participants(
    admin: AdminDep,
    db: DbSession,
    query: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    statement = select(Participant)
    count_statement = select(func.count(Participant.id))
    if query:
        like = f"%{query.strip()}%"
        statement = statement.where(or_(Participant.name.like(like), Participant.notes.like(like)))
        count_statement = count_statement.where(or_(Participant.name.like(like), Participant.notes.like(like)))
    if status_filter:
        statement = statement.where(Participant.status == status_filter)
        count_statement = count_statement.where(Participant.status == status_filter)
    total = (await db.execute(count_statement)).scalar_one()
    rows = await db.execute(statement.order_by(Participant.created_at.desc()).limit(limit).offset(offset))
    items = []
    for participant in rows.scalars().all():
        items.append(
            {
                "id": participant.id,
                "name": participant.name,
                "phoneMasked": mask_phone(decrypt_phone(participant.phone_encrypted)),
                "status": participant.status,
                "consentedAt": isoformat_utc(participant.consented_at),
                "notes": participant.notes,
                "createdAt": isoformat_utc(participant.created_at),
            }
        )
    return {"participants": items, "total": total}


@router.post("/participants/import", dependencies=[Depends(require_csrf)])
async def import_participants(
    admin: AdminDep, db: DbSession, file: UploadFile = File(...)
):
    data = await file.read()
    report = await import_roster(db, data, file.filename or "roster.csv")
    _audit(db, admin, "participants_import", "participant", "bulk", report)
    await db.commit()
    return report


@router.post("/participants/import-completed", dependencies=[Depends(require_csrf)])
async def import_completed_participants(
    admin: AdminDep, db: DbSession, file: UploadFile = File(...)
):
    data = await file.read()
    report = await import_completed(db, data, file.filename or "completed.csv")
    _audit(db, admin, "participants_import_completed", "participant", "bulk", report)
    await db.commit()
    return report


@router.patch("/participants/{participant_id}", dependencies=[Depends(require_csrf)])
async def patch_participant(
    participant_id: str, payload: ParticipantPatch, admin: AdminDep, db: DbSession
):
    participant = await db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "参与者不存在")
    if payload.name is not None:
        participant.name = payload.name.strip()
    if payload.status is not None:
        participant.status = payload.status
    if payload.notes is not None:
        participant.notes = payload.notes
    _audit(db, admin, "participant_updated", "participant", participant.id, payload.model_dump(exclude_none=True))
    await db.commit()
    return {"updated": True}


@router.get("/consent-versions")
async def list_consent_versions(admin: AdminDep, db: DbSession):
    rows = await db.execute(select(ConsentVersion).order_by(ConsentVersion.version.desc()))
    return {
        "versions": [
            {
                "id": row.id,
                "version": row.version,
                "markdown": row.markdown,
                "status": row.status,
                "publishedAt": isoformat_utc(row.published_at),
                "createdAt": isoformat_utc(row.created_at),
            }
            for row in rows.scalars().all()
        ]
    }


@router.post("/consent-versions", dependencies=[Depends(require_csrf)])
async def create_consent_version(payload: ConsentVersionCreate, admin: AdminDep, db: DbSession):
    max_version = (
        await db.execute(select(func.max(ConsentVersion.version)))
    ).scalar_one_or_none() or 0
    row = ConsentVersion(version=max_version + 1, markdown=payload.markdown, status=VERSION_DRAFT)
    db.add(row)
    await db.flush()
    _audit(db, admin, "consent_version_created", "consent_version", row.id)
    await db.commit()
    return {"id": row.id, "version": row.version}


@router.patch("/consent-versions/{version_id}", dependencies=[Depends(require_csrf)])
async def patch_consent_version(
    version_id: str, payload: ConsentVersionPatch, admin: AdminDep, db: DbSession
):
    row = await db.get(ConsentVersion, version_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "同意书版本不存在")
    if row.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "已发布的同意书不可修改")
    row.markdown = payload.markdown
    _audit(db, admin, "consent_version_updated", "consent_version", row.id)
    await db.commit()
    return {"updated": True}


@router.post("/consent-versions/{version_id}/publish", dependencies=[Depends(require_csrf)])
async def publish_consent_version(version_id: str, admin: AdminDep, db: DbSession):
    row = await db.get(ConsentVersion, version_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "同意书版本不存在")
    if not row.markdown.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "同意书正文不能为空")
    previous = await db.execute(
        select(ConsentVersion).where(ConsentVersion.status == VERSION_PUBLISHED)
    )
    for old in previous.scalars().all():
        old.status = VERSION_ARCHIVED
    row.status = VERSION_PUBLISHED
    row.published_at = utcnow()
    _audit(db, admin, "consent_version_published", "consent_version", row.id)
    await db.commit()
    return {"published": True, "version": row.version}


@router.get("/media")
async def list_media(admin: AdminDep, db: DbSession, limit: int = Query(default=100, ge=1, le=500)):
    rows = await db.execute(select(MediaAsset).order_by(MediaAsset.uploaded_at.desc()).limit(limit))
    return {"media": [serialize_media(asset) for asset in rows.scalars().all()]}


@router.post("/media", dependencies=[Depends(require_csrf)])
async def upload_media(
    admin: AdminDep,
    db: DbSession,
    file: UploadFile = File(...),
    kind: str = Form(default="upload"),
):
    data = await file.read()
    asset = await save_image(db, data, file.filename or "image", kind)
    _audit(db, admin, "media_uploaded", "media_asset", asset.id, {"sha256": asset.sha256})
    await db.commit()
    return {"asset": serialize_media(asset)}


@router.get("/conditions")
async def list_conditions(admin: AdminDep, db: DbSession):
    rows = await db.execute(select(ConditionVersion).order_by(ConditionVersion.name, ConditionVersion.version.desc()))
    return {"conditions": [serialize_condition(row) for row in rows.scalars().all()]}


async def _get_condition(db, condition_id: str) -> ConditionVersion:
    row = await db.get(ConditionVersion, condition_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "条件版本不存在")
    return row


@router.get("/conditions/{condition_id}")
async def get_condition(condition_id: str, admin: AdminDep, db: DbSession):
    return {"condition": serialize_condition(await _get_condition(db, condition_id))}


@router.post("/conditions", dependencies=[Depends(require_csrf)])
async def post_condition(payload: ConditionVersionCreate, admin: AdminDep, db: DbSession):
    try:
        condition = await create_condition(db, payload.model_dump())
    except ConditionValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _audit(db, admin, "condition_created", "condition_version", condition.id)
    await db.commit()
    return {"condition": serialize_condition(condition)}


@router.patch("/conditions/{condition_id}", dependencies=[Depends(require_csrf)])
async def patch_condition(
    condition_id: str, payload: ConditionVersionPatch, admin: AdminDep, db: DbSession
):
    condition = await _get_condition(db, condition_id)
    try:
        condition = await update_condition(db, condition, payload.model_dump(exclude_unset=True))
    except ConditionValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _audit(db, admin, "condition_updated", "condition_version", condition.id)
    await db.commit()
    return {"condition": serialize_condition(condition)}


@router.post("/conditions/{condition_id}/publish", dependencies=[Depends(require_csrf)])
async def post_publish_condition(condition_id: str, admin: AdminDep, db: DbSession):
    condition = await _get_condition(db, condition_id)
    if condition.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有草稿版本可以发布")
    try:
        condition = await publish_condition(db, condition)
    except ConditionValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _audit(db, admin, "condition_published", "condition_version", condition.id)
    await db.commit()
    return {"condition": serialize_condition(condition)}


@router.get("/instructions")
async def list_instructions(admin: AdminDep, db: DbSession):
    rows = await db.execute(
        select(InstructionVersion).order_by(InstructionVersion.name, InstructionVersion.version.desc())
    )
    return {"instructions": [serialize_instruction(row) for row in rows.scalars().all()]}


async def _get_instruction(db, instruction_id: str) -> InstructionVersion:
    row = await db.get(InstructionVersion, instruction_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "指导语版本不存在")
    return row


@router.get("/instructions/{instruction_id}")
async def get_instruction(instruction_id: str, admin: AdminDep, db: DbSession):
    return {"instruction": serialize_instruction(await _get_instruction(db, instruction_id))}


@router.post("/instructions", dependencies=[Depends(require_csrf)])
async def post_instruction(payload: InstructionVersionCreate, admin: AdminDep, db: DbSession):
    try:
        instruction = await create_instruction(db, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _audit(db, admin, "instruction_created", "instruction_version", instruction.id)
    await db.commit()
    return {"instruction": serialize_instruction(instruction)}


@router.patch("/instructions/{instruction_id}", dependencies=[Depends(require_csrf)])
async def patch_instruction(
    instruction_id: str, payload: InstructionVersionPatch, admin: AdminDep, db: DbSession
):
    instruction = await _get_instruction(db, instruction_id)
    try:
        instruction = await update_instruction(db, instruction, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _audit(db, admin, "instruction_updated", "instruction_version", instruction.id)
    await db.commit()
    return {"instruction": serialize_instruction(instruction)}


@router.post("/instructions/{instruction_id}/publish", dependencies=[Depends(require_csrf)])
async def post_publish_instruction(instruction_id: str, admin: AdminDep, db: DbSession):
    instruction = await _get_instruction(db, instruction_id)
    if instruction.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有草稿版本可以发布")
    try:
        instruction = await publish_instruction(db, instruction)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _audit(db, admin, "instruction_published", "instruction_version", instruction.id)
    await db.commit()
    return {"instruction": serialize_instruction(instruction)}


@router.get("/questionnaires")
async def list_questionnaires(admin: AdminDep, db: DbSession):
    rows = await db.execute(
        select(QuestionnaireVersion).order_by(QuestionnaireVersion.name, QuestionnaireVersion.version.desc())
    )
    return {"questionnaires": [serialize_questionnaire(row) for row in rows.scalars().all()]}


async def _get_questionnaire(db, questionnaire_id: str) -> QuestionnaireVersion:
    row = await db.get(QuestionnaireVersion, questionnaire_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "问卷版本不存在")
    return row


@router.get("/questionnaires/{questionnaire_id}")
async def get_questionnaire(questionnaire_id: str, admin: AdminDep, db: DbSession):
    return {"questionnaire": serialize_questionnaire(await _get_questionnaire(db, questionnaire_id))}


@router.post("/questionnaires", dependencies=[Depends(require_csrf)])
async def post_questionnaire(payload: QuestionnaireVersionCreate, admin: AdminDep, db: DbSession):
    try:
        questionnaire = await create_questionnaire(db, payload.name, payload.definition)
    except QuestionnaireValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _audit(db, admin, "questionnaire_created", "questionnaire_version", questionnaire.id)
    await db.commit()
    return {"questionnaire": serialize_questionnaire(questionnaire)}


@router.patch("/questionnaires/{questionnaire_id}", dependencies=[Depends(require_csrf)])
async def patch_questionnaire(
    questionnaire_id: str, payload: QuestionnaireVersionPatch, admin: AdminDep, db: DbSession
):
    questionnaire = await _get_questionnaire(db, questionnaire_id)
    patch = payload.model_dump(exclude_unset=True)
    if "definition" in patch:
        patch["schema_json"] = patch.pop("definition")
    try:
        questionnaire = await update_questionnaire(db, questionnaire, patch)
    except QuestionnaireValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _audit(db, admin, "questionnaire_updated", "questionnaire_version", questionnaire.id)
    await db.commit()
    return {"questionnaire": serialize_questionnaire(questionnaire)}


@router.post("/questionnaires/{questionnaire_id}/publish", dependencies=[Depends(require_csrf)])
async def post_publish_questionnaire(questionnaire_id: str, admin: AdminDep, db: DbSession):
    questionnaire = await _get_questionnaire(db, questionnaire_id)
    if questionnaire.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有草稿版本可以发布")
    try:
        questionnaire = await publish_questionnaire(db, questionnaire)
    except QuestionnaireValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _audit(db, admin, "questionnaire_published", "questionnaire_version", questionnaire.id)
    await db.commit()
    return {"questionnaire": serialize_questionnaire(questionnaire)}


@router.get("/rooms")
async def list_rooms(
    admin: AdminDep,
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=300),
):
    statement = select(Room)
    if status_filter:
        statement = statement.where(Room.status == status_filter)
    rows = await db.execute(statement.order_by(Room.starts_at.desc()).limit(limit))
    return {"rooms": [await room_summary(db, room) for room in rows.scalars().all()]}


async def _get_room(db, room_id: str) -> Room:
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "房间不存在")
    return room


@router.post("/rooms", dependencies=[Depends(require_csrf)])
async def post_room(payload: RoomCreate, admin: AdminDep, db: DbSession):
    room = await create_room(db, payload.model_dump())
    _audit(db, admin, "room_created", "room", room.id)
    await db.commit()
    return {"room": await room_summary(db, room)}


@router.post("/rooms/batch", dependencies=[Depends(require_csrf)])
async def post_rooms_batch(payload: RoomBatchCreate, admin: AdminDep, db: DbSession):
    template = payload.template.model_dump()
    condition_ids = payload.condition_version_ids or [template["condition_version_id"]]
    rooms = []
    for index in range(payload.count):
        data = dict(template)
        data["internal_label"] = f"{template['internal_label']} {index + 1}"
        data["condition_version_id"] = condition_ids[index % len(condition_ids)]
        room = await create_room(db, data)
        _audit(db, admin, "room_created", "room", room.id, {"batch": True})
        rooms.append(room)
    await db.commit()
    return {"rooms": [await room_summary(db, room) for room in rooms]}


@router.post("/rooms/{room_id}/copy", dependencies=[Depends(require_csrf)])
async def copy_room(room_id: str, payload: RoomCopy, admin: AdminDep, db: DbSession):
    source = await _get_room(db, room_id)
    data = {
        "internal_label": payload.internal_label or f"{source.internal_label} 副本",
        "starts_at": payload.starts_at or source.starts_at,
        "condition_version_id": source.condition_version_id,
        "instruction_version_p1_id": source.instruction_version_p1_id,
        "instruction_version_p2_id": source.instruction_version_p2_id,
        "questionnaire_version_id": source.questionnaire_version_id,
        "base_pay_cents": source.base_pay_cents,
        "performance_rate_cents": source.performance_rate_cents,
        "showup_pay_cents": source.showup_pay_cents,
        "wait_window_seconds": source.wait_window_seconds,
        "reconnect_window_seconds": source.reconnect_window_seconds,
    }
    room = await create_room(db, data)
    _audit(db, admin, "room_copied", "room", room.id, {"sourceRoomId": source.id})
    await db.commit()
    return {"room": await room_summary(db, room)}


@router.get("/rooms/{room_id}")
async def get_room(room_id: str, admin: AdminDep, db: DbSession):
    room = await _get_room(db, room_id)
    detail = await _room_detail(db, room)
    return detail


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
        }
        for booking, participant in booking_rows.all()
    ]
    payments_rows = await db.execute(
        select(Payment, RoomParticipant)
        .outerjoin(
            RoomParticipant,
            (RoomParticipant.room_id == Payment.room_id)
            & (RoomParticipant.participant_id == Payment.participant_id),
        )
        .where(Payment.room_id == room.id)
    )
    payments = [
        serialize_payment(payment, role_row.analysis_code if role_row else None)
        for payment, role_row in payments_rows.all()
    ]
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
    }


@router.patch("/rooms/{room_id}", dependencies=[Depends(require_csrf)])
async def patch_room(room_id: str, payload: RoomPatch, admin: AdminDep, db: DbSession):
    room = await _get_room(db, room_id)
    room = await update_room(db, room, payload.model_dump(exclude_unset=True))
    _audit(db, admin, "room_updated", "room", room.id, payload.model_dump(exclude_unset=True))
    await db.commit()
    return {"room": await room_summary(db, room)}


@router.post("/rooms/{room_id}/publish", dependencies=[Depends(require_csrf)])
async def post_publish_room(room_id: str, admin: AdminDep, db: DbSession):
    room = await _get_room(db, room_id)
    room = await publish_room(db, room)
    _audit(db, admin, "room_published", "room", room.id)
    await db.commit()
    return {"room": await room_summary(db, room)}


@router.post("/rooms/{room_id}/cancel", dependencies=[Depends(require_csrf)])
async def post_cancel_room(room_id: str, admin: AdminDep, db: DbSession):
    from ..services.rooms import cancel_room

    room = await _get_room(db, room_id)
    await cancel_room(db, room)
    _audit(db, admin, "room_cancelled", "room", room.id)
    await db.commit()
    await runtime_manager.notify_room(room.id)
    return {"room": await room_summary(db, room)}


@router.post("/rooms/{room_id}/archive", dependencies=[Depends(require_csrf)])
async def post_archive_room(room_id: str, payload: RoomAction, admin: AdminDep, db: DbSession):
    room = await _get_room(db, room_id)
    reason = payload.reason or _default_archive_reason(room)
    _validate_archive_reason(reason)
    await archive_room(db, room, reason)
    _audit(db, admin, "room_archived", "room", room.id, {"reason": reason})
    await db.commit()
    await runtime_manager.notify_room(room.id)
    return {"room": await room_summary(db, room)}


def _default_archive_reason(room: Room) -> str:
    if room.status == ROOM_QUESTIONNAIRE:
        return ARCHIVE_QUESTIONNAIRE_INCOMPLETE
    if room.status in (ROOM_INSTRUCTIONS, ROOM_PLAYING):
        return ARCHIVE_TECHNICAL_ABORT
    return ARCHIVE_ADMIN_CANCELLED


def _validate_archive_reason(reason: str) -> None:
    if reason not in ARCHIVE_REASONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "归档原因无效")


@router.post("/rooms/{room_id}/bookings", dependencies=[Depends(require_csrf)])
async def add_booking(room_id: str, payload: BookingCreate, admin: AdminDep, db: DbSession):
    room = await _get_room(db, room_id)
    participant = await db.get(Participant, payload.participant_id)
    if participant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "参与者不存在")
    if participant.status != "eligible":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "参与者当前状态不允许报名")
    booking = await book_room(db, room, participant, allow_after_start=True)
    _audit(db, admin, "booking_added", "room", room.id, {"participantId": participant.id})
    await db.commit()
    return {"bookingId": booking.id}


@router.delete("/rooms/{room_id}/bookings/{booking_id}", dependencies=[Depends(require_csrf)])
async def remove_booking(room_id: str, booking_id: str, admin: AdminDep, db: DbSession):
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
    _audit(db, admin, "booking_removed", "room", room.id, {"bookingId": booking.id})
    await db.commit()
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
    room = await _get_room(db, room_id)
    action = payload.action
    if action == "force_archive":
        reason = payload.reason or _default_archive_reason(room)
        _validate_archive_reason(reason)
        await archive_room(db, room, reason)
        _audit(db, admin, "room_force_archived", "room", room.id, {"reason": reason})
        await db.commit()
        await runtime_manager.notify_room(room.id)
        return {"ok": True, "reason": reason}
    if action == "extend_wait":
        if room.status != ROOM_WAITING:
            raise HTTPException(status.HTTP_409_CONFLICT, "只有等待阶段可以延长等待窗口")
        if payload.minutes is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须提供延长分钟数")
        room.wait_window_seconds += payload.minutes * 60
        await add_config_revision(db, room)
        add_event(db, room, "admin_action", payload={"action": action, "minutes": payload.minutes})
        _audit(db, admin, "wait_window_extended", "room", room.id, {"minutes": payload.minutes})
        await db.commit()
        await runtime_manager.notify_room(room.id)
        return {"ok": True, "waitWindowSeconds": room.wait_window_seconds}
    if action == "resend_questionnaire":
        if room.status != ROOM_QUESTIONNAIRE:
            raise HTTPException(status.HTTP_409_CONFLICT, "房间不在问卷阶段")
        rows_query = await db.execute(
            select(RoomParticipant).where(RoomParticipant.room_id == room.id)
        )
        rows = list(rows_query.scalars().all())
        if payload.participant_id:
            rows = [row for row in rows if row.participant_id == payload.participant_id]
        if not rows:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到参与者")
        links = []
        for row in rows:
            url = await build_questionnaire_url(db, room, row)
            links.append({"participantId": row.participant_id, "url": url})
        add_event(db, room, "admin_action", payload={"action": action})
        _audit(db, admin, "questionnaire_resent", "room", room.id)
        await db.commit()
        return {"links": links}
    if action == "mark_absent":
        if payload.participant_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须提供参与者")
        booking = (
            await db.execute(
                select(Booking).where(
                    Booking.room_id == room.id, Booking.participant_id == payload.participant_id
                )
            )
        ).scalars().first()
        if booking is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "预约不存在")
        booking.status = BOOKING_NO_SHOW
        add_event(db, room, "admin_action", payload={"action": action, "participantId": payload.participant_id})
        _audit(db, admin, "participant_marked_absent", "room", room.id, {"participantId": payload.participant_id})
        await db.commit()
        return {"ok": True}
    if action == "mark_completed":
        if payload.participant_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须提供参与者")
        participant = await db.get(Participant, payload.participant_id)
        if participant is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "参与者不存在")
        participant.status = PARTICIPANT_COMPLETED
        add_event(db, room, "admin_action", payload={"action": action, "participantId": participant.id})
        _audit(db, admin, "participant_marked_completed", "participant", participant.id)
        await db.commit()
        return {"ok": True}
    if action == "disable_participant":
        if payload.participant_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须提供参与者")
        participant = await db.get(Participant, payload.participant_id)
        if participant is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "参与者不存在")
        participant.status = PARTICIPANT_DISABLED
        add_event(db, room, "admin_action", payload={"action": action, "participantId": participant.id})
        _audit(db, admin, "participant_disabled", "participant", participant.id)
        await db.commit()
        return {"ok": True}
    if action == "import_jatos_result":
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
        _audit(db, admin, "jatos_result_imported", "room", room.id, {"participantId": payload.participant_id})
        await db.commit()
        await runtime_manager.notify_room(room.id)
        return result
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "未知操作")


@router.get("/rooms/{room_id}/export.json")
async def export_room_json(room_id: str, admin: AdminDep, db: DbSession):
    room = await _get_room(db, room_id)
    data = await build_room_export(db, room)
    _audit(db, admin, "room_export_json", "room", room.id)
    await db.commit()
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="room-{room.id}.json"'})


@router.get("/rooms/{room_id}/analysis.zip")
async def export_room_zip(room_id: str, admin: AdminDep, db: DbSession):
    room = await _get_room(db, room_id)
    data = await build_analysis_zip(db, room)
    _audit(db, admin, "room_export_zip", "room", room.id)
    await db.commit()
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="analysis-{room.id}.zip"'},
    )


@router.get("/payments")
async def list_payments(
    admin: AdminDep,
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
):
    statement = (
        select(Payment, Participant, Room, RoomParticipant)
        .join(Participant, Participant.id == Payment.participant_id)
        .join(Room, Room.id == Payment.room_id)
        .outerjoin(
            RoomParticipant,
            (RoomParticipant.room_id == Payment.room_id)
            & (RoomParticipant.participant_id == Payment.participant_id),
        )
    )
    if status_filter:
        statement = statement.where(Payment.status == status_filter)
    rows = await db.execute(statement.order_by(Room.starts_at.desc()).limit(limit))
    items = []
    for payment, participant, room, role_row in rows.all():
        data = serialize_payment(payment, role_row.analysis_code if role_row else None)
        data.update(
            {
                "participantId": participant.id,
                "name": participant.name,
                "phoneMasked": mask_phone(decrypt_phone(participant.phone_encrypted)),
                "roomStartsAt": isoformat_utc(room.starts_at),
            }
        )
        items.append(data)
    return {"payments": items}


@router.patch("/payments/{payment_id}", dependencies=[Depends(require_csrf)])
async def patch_payment(payment_id: str, payload: PaymentPatch, admin: AdminDep, db: DbSession):
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "付款记录不存在")
    previous_status = payment.status
    apply_override(payment, payload.override_amount_cents, payload.admin_note, payload.status)
    if payload.status == PAYMENT_PAID and previous_status != PAYMENT_PAID:
        room = await db.get(Room, payment.room_id)
        add_event(db, room, "payment_paid", payment.participant_id, {"totalCents": payment.total_cents})
    _audit(db, admin, "payment_updated", "payment", payment.id, payload.model_dump(exclude_none=True))
    await db.commit()
    return {"payment": serialize_payment(payment)}


@router.get("/payments/export.csv")
async def export_payments(admin: AdminDep, db: DbSession):
    data = await build_payment_export_csv(db)
    _audit(db, admin, "payments_exported", "payment", "bulk")
    await db.commit()
    filename = f"payments-{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit")
async def audit_log(
    admin: AdminDep,
    db: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    total = (await db.execute(select(func.count(AdminAuditLog.id)))).scalar_one()
    rows = await db.execute(
        select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(limit).offset(offset)
    )
    return {
        "entries": [
            {
                "id": row.id,
                "adminUserId": row.admin_user_id,
                "action": row.action,
                "targetType": row.target_type,
                "targetId": row.target_id,
                "payload": row.payload_json,
                "createdAt": isoformat_utc(row.created_at),
            }
            for row in rows.scalars().all()
        ],
        "total": total,
    }


@router.get("/settings")
async def get_settings_api(admin: AdminDep, db: DbSession):
    settings = get_settings()
    rows = await db.execute(select(SystemSetting))
    values = {
        row.key: (row.value_json or {}).get("value") if isinstance(row.value_json, dict) else None
        for row in rows.scalars().all()
    }
    return {
        "jatosBaseUrl": values.get("jatos_base_url") or settings.jatos_base_url,
        "jatosStudyCode": values.get("jatos_study_code") or settings.jatos_study_code,
        "contactInfo": values.get("contact_info"),
        "timezone": values.get("timezone") or settings.timezone,
        "hasJatosToken": bool(settings.jatos_api_token),
        "publicBaseUrl": settings.public_base_url,
    }


@router.patch("/settings", dependencies=[Depends(require_csrf)])
async def patch_settings(payload: SettingsPatch, admin: AdminDep, db: DbSession):
    if payload.timezone is not None and payload.timezone != "Asia/Shanghai":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "时区固定为 Asia/Shanghai")
    mapping = {
        "jatos_base_url": payload.jatos_base_url,
        "jatos_study_code": payload.jatos_study_code,
        "contact_info": payload.contact_info,
        "timezone": payload.timezone,
    }
    for key, value in mapping.items():
        if value is None:
            continue
        row = await db.get(SystemSetting, key)
        if row is None:
            row = SystemSetting(key=key, value_json={"value": value})
            db.add(row)
        else:
            row.value_json = {"value": value}
            row.updated_at = utcnow()
    _audit(db, admin, "settings_updated", "system", "settings", payload.model_dump(exclude_none=True))
    await db.commit()
    return {"updated": True}
