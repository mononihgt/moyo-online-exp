from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select

from ..config import get_settings
from ..constants import (
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
    ConsentVersion,
    MediaAsset,
    Participant,
    Payment,
    Room,
    SystemSetting,
)
from ..schemas import (
    ConsentVersionCreate,
    ConsentVersionPatch,
    ParticipantPatch,
    SettingsPatch,
)
from ..security import decrypt_phone, mask_phone
from ..services.media import save_image, serialize_media
from ..services.participants import import_completed, import_roster
from ..services.rooms import room_summary
from ..timeutil import isoformat_utc, utcnow
from .admin_common import audit, audit_import_report
from .admin_materials import router as materials_router
from .admin_payments import router as payments_router
from .admin_rooms import router as rooms_router
from .deps import AdminDep, DbSession, require_csrf

router = APIRouter(prefix="/admin/api")


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
    upcoming_count = await db.execute(
        select(func.count(Room.id)).where(
            Room.status.in_((ROOM_OPEN, ROOM_FULL)), Room.starts_at > utcnow()
        )
    )
    upcoming = await db.execute(
        select(Room)
        .where(Room.status.in_((ROOM_OPEN, ROOM_FULL)), Room.starts_at > utcnow())
        .order_by(Room.starts_at)
        .limit(5)
    )
    attention = await db.execute(
        select(Room)
        .where(
            Room.status.in_(
                (ROOM_WAITING, ROOM_INSTRUCTIONS, ROOM_PLAYING, ROOM_QUESTIONNAIRE)
            )
        )
        .order_by(Room.starts_at)
        .limit(10)
    )
    upcoming_items = [await room_summary(db, room) for room in upcoming.scalars().all()]
    attention_items = [await room_summary(db, room) for room in attention.scalars().all()]
    return {
        "roomCounts": counts,
        "pendingPayments": pending_payments.scalar_one(),
        "pendingQuestionnaireRooms": pending_questionnaires.scalar_one(),
        "upcomingCount": upcoming_count.scalar_one(),
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
    audit(db, admin, "participants_import", "participant", "bulk", audit_import_report(report))
    await db.commit()
    return report


@router.post("/participants/import-completed", dependencies=[Depends(require_csrf)])
async def import_completed_participants(
    admin: AdminDep, db: DbSession, file: UploadFile = File(...)
):
    data = await file.read()
    report = await import_completed(db, data, file.filename or "completed.csv")
    audit(
        db,
        admin,
        "participants_import_completed",
        "participant",
        "bulk",
        audit_import_report(report),
    )
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
    audit(db, admin, "participant_updated", "participant", participant.id, payload.model_dump(exclude_none=True))
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
    audit(db, admin, "consent_version_created", "consent_version", row.id)
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
    audit(db, admin, "consent_version_updated", "consent_version", row.id)
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
    audit(db, admin, "consent_version_published", "consent_version", row.id)
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
    audit(db, admin, "media_uploaded", "media_asset", asset.id, {"sha256": asset.sha256})
    await db.commit()
    return {"asset": serialize_media(asset)}


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
    audit(db, admin, "settings_updated", "system", "settings", payload.model_dump(exclude_none=True))
    await db.commit()
    return {"updated": True}


router.include_router(materials_router)
router.include_router(rooms_router)
router.include_router(payments_router)
