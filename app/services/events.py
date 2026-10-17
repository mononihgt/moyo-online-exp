from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AdminAuditLog, Room, RoomEvent


def add_event(
    db: AsyncSession,
    room: Room,
    event_type: str,
    participant_id: str | None = None,
    payload: dict | None = None,
) -> RoomEvent:
    event = RoomEvent(
        room_id=room.id,
        participant_id=participant_id,
        type=event_type,
        payload_json=payload or {},
    )
    db.add(event)
    return event


def add_audit(
    db: AsyncSession,
    admin_user_id: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict | None = None,
) -> AdminAuditLog:
    entry = AdminAuditLog(
        admin_user_id=admin_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload_json=payload or {},
    )
    db.add(entry)
    return entry
