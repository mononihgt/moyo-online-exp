import logging
from decimal import ROUND_FLOOR, Decimal

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
from ..models import Booking, GameTrial, MapGroupVersion, Payment, Room, RoomParticipant
from ..timeutil import isoformat_utc, utcnow, week_deadline_utc
from .events import add_event

logger = logging.getLogger(__name__)


def _payment_from_snapshot(snapshot: dict | None) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    map_group = snapshot.get("mapGroup")
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


def _payment_from_version(version: MapGroupVersion) -> dict:
    return {
        "basePayCents": version.base_pay_cents,
        "performanceRateCents": version.performance_rate_cents,
        "performanceFloorCents": version.performance_floor_cents,
        "performanceCapCents": version.performance_cap_cents,
        "showupPayCents": version.showup_pay_cents,
    }


def _snapshot_payment(room: Room) -> dict | None:
    for snapshot in (room.config_snapshot, room.archive_snapshot_json):
        payment = _payment_from_snapshot(snapshot)
        if payment is not None:
            return payment
    return None


def payment_parameters(room: Room, map_group: MapGroupVersion | None = None) -> dict:
    payment = _snapshot_payment(room)
    if payment is not None:
        return payment
    if map_group is None:
        # 直接读取已加载的关系，避免在异步上下文触发惰性加载
        map_group = room.__dict__.get("map_group_version")
    if map_group is None:
        raise RuntimeError("房间缺少冻结的地图组快照，且地图组版本未加载")
    return _payment_from_version(map_group)


async def load_payment_parameters(db: AsyncSession, room: Room) -> dict:
    payment = _snapshot_payment(room)
    if payment is not None:
        return payment
    map_group = room.__dict__.get("map_group_version")
    if map_group is None:
        map_group = await db.get(MapGroupVersion, room.map_group_version_id)
    if map_group is None:
        raise RuntimeError("房间绑定的地图组版本不存在")
    return _payment_from_version(map_group)


def compute_performance_cents(
    room: Room, trials: list[GameTrial], role: int, payment: dict | None = None
) -> int | None:
    if payment is None:
        payment = payment_parameters(room)
    key = "player1" if role == 1 else "player2"
    finals: list[int] = []
    for trial in trials:
        if trial.is_practice or trial.ended_at is None or not trial.summary_json:
            continue
        final_soldiers = trial.summary_json.get("finalSoldiers") or {}
        if key in final_soldiers:
            finals.append(int(final_soldiers[key]))
    if not finals:
        return None
    mean = Decimal(sum(finals)) / Decimal(len(finals))
    performance_yuan = (mean * Decimal(payment["performanceRateCents"]) / Decimal(100)).to_integral_value(
        rounding=ROUND_FLOOR
    )
    amount = int(performance_yuan) * 100
    floor = int(payment.get("performanceFloorCents", 0))
    cap = int(payment["performanceCapCents"])
    return max(floor, min(cap, amount))


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

    completed = room_participant is not None and room_participant.questionnaire_status == QUESTIONNAIRE_COMPLETED
    attended = booking is not None and booking.status == BOOKING_ATTENDED

    base = 0
    performance = 0
    showup = 0
    if completed:
        params = await load_payment_parameters(db, room)
        trials_query = await db.execute(
            select(GameTrial).where(GameTrial.room_id == room.id).order_by(GameTrial.trial_index)
        )
        trials = list(trials_query.scalars().all())
        performance_cents = compute_performance_cents(room, trials, room_participant.role, payment=params)
        if performance_cents is None:
            logger.error(
                "房间 %s 参与者 %s 没有已结束的正式对局，跳过完成付款计算",
                room.id,
                participant_id,
            )
            return None
        base = params["basePayCents"]
        performance = performance_cents
        deadline = payment_deadline(room, room_participant.completed_at)
    elif room.status == ROOM_ARCHIVED and room.archive_reason == ARCHIVE_TECHNICAL_ABORT:
        if not attended:
            return None
        params = await load_payment_parameters(db, room)
        if params["showupPayCents"] <= 0:
            return None
        showup = params["showupPayCents"]
        settings = get_settings()
        deadline = week_deadline_utc(room.archived_at or utcnow(), settings.timezone)
    else:
        return None

    existing_query = await db.execute(
        select(Payment).where(Payment.room_id == room.id, Payment.participant_id == participant_id)
    )
    payment = existing_query.scalars().first()
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
    if payment.status != PAYMENT_PAID:
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
