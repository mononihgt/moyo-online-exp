from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    ARCHIVE_TECHNICAL_ABORT,
    BOOKING_ATTENDED,
    PAYMENT_PAID,
    PAYMENT_PENDING,
    QUESTIONNAIRE_COMPLETED,
    ROOM_ARCHIVED,
)
from ..models import Booking, GameTrial, Payment, Room, RoomParticipant
from ..timeutil import isoformat_utc, utcnow, week_deadline_utc
from .events import add_event


def compute_performance_cents(room: Room, trials: list[GameTrial], role: int) -> int:
    finals: list[int] = []
    key = "player1" if role == 1 else "player2"
    for trial in trials:
        if trial.is_practice or trial.ended_at is None or not trial.summary_json:
            continue
        final_soldiers = trial.summary_json.get("finalSoldiers", {})
        if key in final_soldiers:
            finals.append(int(final_soldiers[key]))
    if not finals:
        return 0
    mean = Decimal(sum(finals)) / Decimal(len(finals))
    amount = mean * Decimal(room.performance_rate_cents)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def payment_deadline(room: Room, completed_at):
    settings = get_settings()
    base_deadline = week_deadline_utc(room.starts_at, settings.timezone)
    if completed_at is not None:
        completion_deadline = week_deadline_utc(completed_at, settings.timezone)
        if completion_deadline > base_deadline:
            return completion_deadline
    return base_deadline


async def upsert_payment(
    db: AsyncSession,
    room: Room,
    participant_id: str,
    *,
    booking: Booking | None = None,
    room_participant: RoomParticipant | None = None,
) -> Payment | None:
    if booking is None:
        query = await db.execute(
            select(Booking).where(Booking.room_id == room.id, Booking.participant_id == participant_id)
        )
        booking = query.scalars().first()
    if room_participant is None:
        query = await db.execute(
            select(RoomParticipant).where(
                RoomParticipant.room_id == room.id, RoomParticipant.participant_id == participant_id
            )
        )
        room_participant = query.scalars().first()

    existing_query = await db.execute(
        select(Payment).where(Payment.room_id == room.id, Payment.participant_id == participant_id)
    )
    payment = existing_query.scalars().first()

    completed = room_participant is not None and room_participant.questionnaire_status == QUESTIONNAIRE_COMPLETED
    attended = booking is not None and booking.status == BOOKING_ATTENDED
    settings = get_settings()

    base = 0
    performance = 0
    showup = 0
    if completed:
        trials_query = await db.execute(
            select(GameTrial).where(GameTrial.room_id == room.id).order_by(GameTrial.trial_index)
        )
        trials = list(trials_query.scalars().all())
        base = room.base_pay_cents
        performance = compute_performance_cents(room, trials, room_participant.role)
        deadline = payment_deadline(room, room_participant.completed_at)
    elif (
        room.status == ROOM_ARCHIVED
        and room.archive_reason == ARCHIVE_TECHNICAL_ABORT
        and attended
        and room.showup_pay_cents > 0
    ):
        showup = room.showup_pay_cents
        deadline = week_deadline_utc(room.archived_at or utcnow(), settings.timezone)
    else:
        return None

    if payment is None:
        payment = Payment(
            room_id=room.id,
            participant_id=participant_id,
            status=PAYMENT_PENDING,
        )
        db.add(payment)
    payment.base_pay_cents = base
    payment.performance_pay_cents = performance
    payment.showup_pay_cents = showup
    payment.total_cents = (
        payment.override_amount_cents
        if payment.override_amount_cents is not None
        else base + performance + showup
    )
    payment.deadline_at = deadline
    payment.computed_at = utcnow()
    if payment.status == PAYMENT_PAID:
        payment.status = PAYMENT_PAID
    else:
        payment.status = PAYMENT_PENDING
    await db.flush()
    add_event(
        db,
        room,
        "payment_computed",
        participant_id,
        {
            "basePayCents": base,
            "performancePayCents": performance,
            "showupPayCents": showup,
            "totalCents": payment.total_cents,
        },
    )
    return payment


def serialize_payment(payment: Payment, analysis_code: str | None = None) -> dict:
    return {
        "id": payment.id,
        "analysisCode": analysis_code,
        "roomId": payment.room_id,
        "basePayCents": payment.base_pay_cents,
        "performancePayCents": payment.performance_pay_cents,
        "showupPayCents": payment.showup_pay_cents,
        "overrideAmountCents": payment.override_amount_cents,
        "totalCents": payment.total_cents,
        "status": payment.status,
        "computedAt": isoformat_utc(payment.computed_at),
        "deadlineAt": isoformat_utc(payment.deadline_at),
        "paidAt": isoformat_utc(payment.paid_at),
        "note": payment.admin_note,
    }


UNSET = object()


def apply_override(
    payment: Payment,
    *,
    override_amount_cents: int | None | object = UNSET,
    note: str | None | object = UNSET,
    new_status: str | None = None,
) -> None:
    setting_override = override_amount_cents is not UNSET
    setting_note = note is not UNSET
    if setting_override or setting_note:
        resolved_override = (
            override_amount_cents if setting_override else payment.override_amount_cents
        )
        resolved_note = note if setting_note else payment.admin_note
        if resolved_override is not None and not (resolved_note or "").strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "覆盖金额必须填写备注")
    if setting_override:
        payment.override_amount_cents = override_amount_cents
        payment.total_cents = (
            override_amount_cents
            if override_amount_cents is not None
            else payment.base_pay_cents + payment.performance_pay_cents + payment.showup_pay_cents
        )
    if setting_note:
        payment.admin_note = note
    if new_status is not None:
        if new_status == PAYMENT_PAID:
            payment.status = PAYMENT_PAID
            if payment.paid_at is None:
                payment.paid_at = utcnow()
        elif new_status == PAYMENT_PENDING:
            payment.status = PAYMENT_PENDING
            payment.paid_at = None
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "付款状态无效")
