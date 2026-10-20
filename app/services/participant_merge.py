from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    BOOKING_ATTENDED,
    BOOKING_BOOKED,
    PARTICIPANT_COMPLETED,
    PARTICIPANT_DISABLED,
    PARTICIPANT_MERGED,
    ROOM_ARCHIVED,
)
from ..models import (
    Booking,
    Participant,
    ParticipantIdentity,
    Payment,
    QuestionnaireDraft,
    QuestionnaireResponse,
    Room,
    RoomEvent,
    RoomParticipant,
)
from ..security import encrypt_phone, phone_hash

_MERGE_TABLES = (
    ("questionnaire_drafts", QuestionnaireDraft),
    ("questionnaire_responses", QuestionnaireResponse),
    ("participant_identities", ParticipantIdentity),
    ("payments", Payment),
    ("room_participants", RoomParticipant),
    ("bookings", Booking),
)


async def _conflicting_rooms(
    db: AsyncSession, model, source_id: str, target_id: str
) -> list[str]:
    target_rooms = select(model.room_id).where(model.participant_id == target_id)
    rows = await db.execute(
        select(model.room_id).where(
            model.participant_id == source_id,
            model.room_id.in_(target_rooms),
        )
    )
    return list(rows.scalars().all())


async def _has_active_booking(db: AsyncSession, participant_id: str) -> bool:
    rows = await db.execute(
        select(Booking.id)
        .join(Room, Room.id == Booking.room_id)
        .where(
            Booking.participant_id == participant_id,
            Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED)),
            Room.status != ROOM_ARCHIVED,
        )
        .limit(1)
    )
    return rows.first() is not None


async def merge_participants(
    db: AsyncSession,
    source: Participant,
    target: Participant,
    *,
    keep_phone_from: str,
    final_name: str | None,
    reason: str,
) -> dict:
    if source.id == target.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能合并同一个账号")
    if source.status == PARTICIPANT_MERGED or target.status == PARTICIPANT_MERGED:
        raise HTTPException(status.HTTP_409_CONFLICT, "已合并账号不能再次合并")
    if source.status == PARTICIPANT_DISABLED or target.status == PARTICIPANT_DISABLED:
        raise HTTPException(status.HTTP_409_CONFLICT, "已停用账号不能合并")
    if not reason.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须填写合并原因")
    if keep_phone_from not in ("source", "target"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "保留手机号来源无效")
    if await _has_active_booking(db, source.id) or await _has_active_booking(
        db, target.id
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "存在进行中或未归档的预约，不能合并账号",
        )

    conflicts = []
    for table_name, model in _MERGE_TABLES:
        room_ids = await _conflicting_rooms(db, model, source.id, target.id)
        for room_id in sorted(set(room_ids)):
            conflicts.append({"table": table_name, "roomId": room_id})
    if conflicts:
        details = "、".join(
            f"{item['table']}（{item['roomId']}）" for item in conflicts
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"两个账号在同一实验存在记录，不能合并：{details}",
        )

    moved: dict[str, int] = {}
    for table_name, model in _MERGE_TABLES:
        result = await db.execute(
            update(model)
            .where(model.participant_id == source.id)
            .values(participant_id=target.id)
        )
        moved[table_name] = result.rowcount or 0

    event_rows = await db.execute(
        select(RoomEvent).where(RoomEvent.participant_id == source.id)
    )
    events = list(event_rows.scalars().all())
    for event in events:
        event.participant_id = target.id
        payload = event.payload_json
        if isinstance(payload, dict) and payload.get("participantId") == source.id:
            updated_payload = dict(payload)
            updated_payload["participantId"] = target.id
            event.payload_json = updated_payload
    moved["room_events"] = len(events)

    if target.consent_version_id is None and source.consent_version_id is not None:
        target.consent_version_id = source.consent_version_id
        target.consented_at = source.consented_at
    if source.status == PARTICIPANT_COMPLETED or target.status == PARTICIPANT_COMPLETED:
        target.status = PARTICIPANT_COMPLETED
    if final_name is not None:
        cleaned_name = final_name.strip()
        if not cleaned_name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "姓名不能为空")
        target.name = cleaned_name

    if keep_phone_from == "source":
        source_phone_hash = source.phone_hash
        source_phone_encrypted = source.phone_encrypted
        target_phone_hash = target.phone_hash
        target_phone_encrypted = target.phone_encrypted
        temporary = f"merge-temp:{source.id}"
        source.phone_hash = phone_hash(temporary)
        source.phone_encrypted = encrypt_phone(temporary)
        await db.flush()
        target.phone_hash = source_phone_hash
        target.phone_encrypted = source_phone_encrypted
        await db.flush()
        source.phone_hash = target_phone_hash
        source.phone_encrypted = target_phone_encrypted

    source.status = PARTICIPANT_MERGED
    source.merged_into_id = target.id
    source_note = "已合并到目标账号"
    source.notes = (
        f"{source.notes}\n{source_note}" if source.notes else source_note
    )
    await db.flush()
    return {
        "sourceId": source.id,
        "targetId": target.id,
        "moved": moved,
        "keepPhoneFrom": keep_phone_from,
        "finalName": target.name,
    }
