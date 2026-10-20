import csv
import io
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    PAYMENT_PAID,
    PAYMENT_PENDING,
    PAYMENT_SOURCE_COMPUTED,
    QUESTIONNAIRE_COMPLETED,
    TIMEZONE,
)
from ..models import Participant, ParticipantIdentity, Payment, Room, RoomParticipant
from ..security import decrypt_identity, decrypt_phone
from ..timeutil import isoformat_utc, localize
from .events import add_event
from .payments import apply_override

_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_date_range(from_value: str, to_value: str) -> tuple[date, date]:
    if _DATE_PATTERN.fullmatch(from_value or "") is None or _DATE_PATTERN.fullmatch(to_value or "") is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "日期格式必须为 YYYY-MM-DD")
    try:
        date_from = date.fromisoformat(from_value)
        date_to = date.fromisoformat(to_value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "日期格式必须为 YYYY-MM-DD") from exc
    if date_from > date_to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "开始日期不能晚于结束日期")
    return date_from, date_to


def range_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    tzinfo = ZoneInfo(TIMEZONE)
    start = datetime.combine(date_from, time.min, tzinfo=tzinfo).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tzinfo).astimezone(timezone.utc)
    return start, end.replace(tzinfo=None)


def _csv_bytes(header: list[str], rows: list[list]) -> bytes:
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if value is None else str(value) for value in row])
    return buffer.getvalue().encode("utf-8")


def _yuan(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    value = abs(cents)
    return f"{sign}{value // 100}.{value % 100:02d}"


def _local_date(value: datetime) -> str:
    return localize(value, TIMEZONE).strftime("%Y-%m-%d")


def _identity_join():
    return and_(
        ParticipantIdentity.room_id == Payment.room_id,
        ParticipantIdentity.participant_id == Payment.participant_id,
    )


def _room_participant_join():
    return and_(
        RoomParticipant.room_id == Payment.room_id,
        RoomParticipant.participant_id == Payment.participant_id,
    )


async def payment_list_csv(db: AsyncSession, date_from: date, date_to: date) -> bytes:
    start, end = range_bounds(date_from, date_to)
    statement = (
        select(Payment, Participant, Room, ParticipantIdentity)
        .join(Participant, Participant.id == Payment.participant_id)
        .join(Room, Room.id == Payment.room_id)
        .outerjoin(RoomParticipant, _room_participant_join())
        .outerjoin(ParticipantIdentity, _identity_join())
        .where(
            or_(
                and_(
                    Payment.source == PAYMENT_SOURCE_COMPUTED,
                    RoomParticipant.questionnaire_status == QUESTIONNAIRE_COMPLETED,
                ),
                Payment.source != PAYMENT_SOURCE_COMPUTED,
            ),
            Payment.status == PAYMENT_PENDING,
            Room.starts_at >= start,
            Room.starts_at < end,
        )
        .order_by(Room.starts_at, RoomParticipant.analysis_code)
    )
    rows = await db.execute(statement)
    data_rows = []
    for index, (payment, participant, room, identity) in enumerate(rows.all(), start=1):
        name = participant.name if identity is None else decrypt_identity(identity.real_name_encrypted)
        alipay_phone = "" if identity is None else decrypt_identity(identity.alipay_phone_encrypted)
        data_rows.append([index, alipay_phone, name, _yuan(payment.total_cents)])
    return _csv_bytes(["序号", "玩家支付宝手机号", "玩家姓名", "金额"], data_rows)


async def reimbursement_list_csv(db: AsyncSession, date_from: date, date_to: date) -> bytes:
    start, end = range_bounds(date_from, date_to)
    statement = (
        select(Payment, Participant, Room, ParticipantIdentity)
        .join(Participant, Participant.id == Payment.participant_id)
        .join(Room, Room.id == Payment.room_id)
        .outerjoin(RoomParticipant, _room_participant_join())
        .outerjoin(ParticipantIdentity, _identity_join())
        .where(
            or_(
                and_(
                    Payment.source == PAYMENT_SOURCE_COMPUTED,
                    RoomParticipant.questionnaire_status == QUESTIONNAIRE_COMPLETED,
                ),
                Payment.source != PAYMENT_SOURCE_COMPUTED,
            ),
            Payment.status == PAYMENT_PAID,
            Room.starts_at >= start,
            Room.starts_at < end,
        )
        .order_by(Room.starts_at, RoomParticipant.analysis_code)
    )
    rows = await db.execute(statement)
    data_rows = []
    for index, (payment, participant, room, identity) in enumerate(rows.all(), start=1):
        name = participant.name if identity is None else decrypt_identity(identity.real_name_encrypted)
        document_number = "" if identity is None else decrypt_identity(identity.document_number_encrypted)
        data_rows.append(
            [
                index,
                _local_date(room.starts_at),
                name,
                decrypt_phone(participant.phone_encrypted),
                document_number,
                _yuan(payment.total_cents),
            ]
        )
    return _csv_bytes(["序号", "参与日期", "玩家姓名", "玩家手机号", "玩家身份证", "金额"], data_rows)


def _bulk_statement():
    return (
        select(Payment, Participant, Room, RoomParticipant, ParticipantIdentity)
        .join(Participant, Participant.id == Payment.participant_id)
        .join(Room, Room.id == Payment.room_id)
        .outerjoin(RoomParticipant, _room_participant_join())
        .outerjoin(ParticipantIdentity, _identity_join())
    )


def _bulk_record(payment: Payment, participant: Participant, room: Room, role_row, identity) -> dict:
    name = participant.name if identity is None else decrypt_identity(identity.real_name_encrypted)
    alipay_phone = (
        None if identity is None else decrypt_identity(identity.alipay_phone_encrypted)
    )
    login_phone = decrypt_phone(participant.phone_encrypted)
    return {
        "paymentId": payment.id,
        "participantId": participant.id,
        "analysisCode": role_row.analysis_code if role_row else None,
        "name": name,
        "phone": login_phone,
        "alipayPhone": alipay_phone,
        "roomId": room.id,
        "roomStartsAt": isoformat_utc(room.starts_at),
        "archiveReason": room.archive_reason,
        "totalCents": payment.total_cents,
        "source": payment.source,
        "status": payment.status,
        "paidAt": isoformat_utc(payment.paid_at),
    }


async def bulk_payments(db: AsyncSession, date_from: date, date_to: date) -> list[dict]:
    start, end = range_bounds(date_from, date_to)
    rows = await db.execute(
        _bulk_statement()
        .where(Room.starts_at >= start, Room.starts_at < end)
        .order_by(Room.starts_at, RoomParticipant.analysis_code, Payment.id)
    )
    return [
        _bulk_record(payment, participant, room, role_row, identity)
        for payment, participant, room, role_row, identity in rows.all()
    ]


async def mark_payments_paid(db: AsyncSession, payment_ids: list[str]) -> dict:
    unique_ids = list(dict.fromkeys(payment_ids))
    if not unique_ids:
        return {"updated": 0, "skipped": 0, "payments": []}
    rows = await db.execute(
        select(Payment, Room)
        .join(Room, Room.id == Payment.room_id)
        .where(Payment.id.in_(unique_ids))
    )
    found = {payment.id: (payment, room) for payment, room in rows.all()}
    updated_ids: list[str] = []
    skipped = 0
    for payment_id in unique_ids:
        pair = found.get(payment_id)
        if pair is None:
            skipped += 1
            continue
        payment, room = pair
        if payment.status != PAYMENT_PENDING:
            skipped += 1
            continue
        apply_override(payment, new_status=PAYMENT_PAID)
        add_event(db, room, "payment_paid", payment.participant_id, {"totalCents": payment.total_cents})
        updated_ids.append(payment.id)
    await db.flush()
    records = []
    if updated_ids:
        updated_rows = await db.execute(
            _bulk_statement()
            .where(Payment.id.in_(updated_ids))
            .order_by(Room.starts_at, RoomParticipant.analysis_code, Payment.id)
        )
        records = [
            _bulk_record(payment, participant, room, role_row, identity)
            for payment, participant, room, role_row, identity in updated_rows.all()
        ]
    return {"updated": len(updated_ids), "skipped": skipped, "payments": records}
