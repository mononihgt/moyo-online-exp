from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ParticipantIdentity
from ..security import decrypt_identity, encrypt_identity
from ..timeutil import utcnow


async def get_identity(
    db: AsyncSession, room_id: str, participant_id: str
) -> dict | None:
    row = await db.execute(
        select(ParticipantIdentity).where(
            ParticipantIdentity.room_id == room_id,
            ParticipantIdentity.participant_id == participant_id,
        )
    )
    identity = row.scalars().first()
    if identity is None:
        return None
    return {
        "real_name": decrypt_identity(identity.real_name_encrypted),
        "alipay_phone": decrypt_identity(identity.alipay_phone_encrypted),
        "document_type": identity.document_type,
        "document_number": decrypt_identity(identity.document_number_encrypted),
    }


async def create_identity_if_absent(
    db: AsyncSession,
    room_id: str,
    participant_id: str,
    identity: dict,
) -> ParticipantIdentity:
    row = await db.execute(
        select(ParticipantIdentity).where(
            ParticipantIdentity.room_id == room_id,
            ParticipantIdentity.participant_id == participant_id,
        )
    )
    existing = row.scalars().first()
    if existing is not None:
        return existing
    now = utcnow()
    created = ParticipantIdentity(
        room_id=room_id,
        participant_id=participant_id,
        real_name_encrypted=encrypt_identity(identity["real_name"]),
        alipay_phone_encrypted=encrypt_identity(identity["alipay_phone"]),
        document_type=identity["document_type"],
        document_number_encrypted=encrypt_identity(identity["document_number"]),
        created_at=now,
        updated_at=now,
    )
    db.add(created)
    await db.flush()
    return created


async def has_identity(db: AsyncSession, room_id: str, participant_id: str) -> bool:
    row = await db.execute(
        select(ParticipantIdentity.id).where(
            ParticipantIdentity.room_id == room_id,
            ParticipantIdentity.participant_id == participant_id,
        )
    )
    return row.first() is not None


async def upsert_identity_values(
    db: AsyncSession,
    room_id: str,
    participant_id: str,
    identity: dict,
) -> ParticipantIdentity:
    row = await db.execute(
        select(ParticipantIdentity).where(
            ParticipantIdentity.room_id == room_id,
            ParticipantIdentity.participant_id == participant_id,
        )
    )
    existing = row.scalars().first()
    now = utcnow()
    real_name_encrypted = encrypt_identity(identity["real_name"])
    alipay_phone_encrypted = encrypt_identity(identity["alipay_phone"])
    document_number_encrypted = encrypt_identity(identity["document_number"])
    if existing is None:
        existing = ParticipantIdentity(
            room_id=room_id,
            participant_id=participant_id,
            real_name_encrypted=real_name_encrypted,
            alipay_phone_encrypted=alipay_phone_encrypted,
            document_type=identity["document_type"],
            document_number_encrypted=document_number_encrypted,
            created_at=now,
            updated_at=now,
        )
        db.add(existing)
        await db.flush()
        return existing
    existing.real_name_encrypted = real_name_encrypted
    existing.alipay_phone_encrypted = alipay_phone_encrypted
    existing.document_type = identity["document_type"]
    existing.document_number_encrypted = document_number_encrypted
    existing.updated_at = now
    await db.flush()
    return existing
