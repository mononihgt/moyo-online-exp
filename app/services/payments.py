import logging
from decimal import ROUND_FLOOR, Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    ARCHIVE_ADMIN_CANCELLED,
    ARCHIVE_REASONS,
    ARCHIVE_TECHNICAL_ABORT,
    BOOKING_ATTENDED,
    BOOKING_CANCELED,
    PAYMENT_PAID,
    PAYMENT_PENDING,
    PAYMENT_SOURCE_COMPUTED,
    PAYMENT_SOURCE_MANUAL_COMPENSATION,
    PAYMENT_SOURCE_MANUAL_COMPLETION,
    PAYMENT_SOURCE_MANUAL_SHOWUP,
    QUESTIONNAIRE_COMPLETED,
    ROOM_ARCHIVED,
)
from ..models import (
    Booking,
    GameTrial,
    MapGroupVersion,
    Payment,
    Room,
    RoomParticipant,
)
from ..timeutil import isoformat_utc, utcnow, week_deadline_utc
from .events import add_event
from .identities import has_identity, upsert_identity_values
from .questionnaires import QuestionnaireValidationError, validate_identity_values

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


def payment_deadline(completed_at):
    settings = get_settings()
    return week_deadline_utc(completed_at, settings.timezone)


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
            select(Booking).where(
                Booking.room_id == room.id,
                Booking.participant_id == participant_id,
                Booking.status == BOOKING_ATTENDED,
            )
        )
        booking = query.scalars().first()
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
    if room_participant is None:
        return None

    existing_query = await db.execute(
        select(Payment).where(
            Payment.room_id == room.id, Payment.participant_id == participant_id
        )
    )
    payment = existing_query.scalars().first()
    if payment is not None and payment.source != PAYMENT_SOURCE_COMPUTED:
        return payment

    completed = room_participant.questionnaire_status == QUESTIONNAIRE_COMPLETED
    attended = booking is not None and booking.status == BOOKING_ATTENDED
    technical_abort = room.status == ROOM_ARCHIVED and room.archive_reason == ARCHIVE_TECHNICAL_ABORT

    base = 0
    performance = 0
    showup = 0
    deadline = None
    if technical_abort:
        if not completed or not attended:
            return None
        params = await load_payment_parameters(db, room)
        if params["showupPayCents"] <= 0:
            return None
        showup = params["showupPayCents"]
    elif completed:
        params = await load_payment_parameters(db, room)
        if attended:
            trials_query = await db.execute(
                select(GameTrial).where(GameTrial.room_id == room.id).order_by(GameTrial.trial_index)
            )
            trials = list(trials_query.scalars().all())
            performance_cents = compute_performance_cents(
                room, trials, room_participant.role, payment=params
            )
            if performance_cents is None:
                logger.error(
                    "房间 %s 参与者 %s 没有已结束的正式对局，跳过完成付款计算",
                    room.id,
                    participant_id,
                )
                return None
            base = params["basePayCents"]
            performance = performance_cents
        # 管理端已把预约改为缺席时，保留一条 0 元记录，不产生完成报酬。
    else:
        return None
    if room_participant.completed_at is None:
        logger.error(
            "房间 %s 参与者 %s 没有问卷提交时间，跳过付款计算",
            room.id,
            participant_id,
        )
        return None
    deadline = payment_deadline(room_participant.completed_at)

    if payment is None:
        payment = Payment(
            room_id=room.id,
            participant_id=participant_id,
            source=PAYMENT_SOURCE_COMPUTED,
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


MANUAL_PAYMENT_ARCHIVE_REASONS = ARCHIVE_REASONS


async def create_manual_payment(
    db: AsyncSession,
    room: Room,
    participant_id: str,
    *,
    booking_id: str,
    kind: str,
    amount_cents: int,
    admin_note: str,
    identity_values: dict | None = None,
) -> Payment:
    if room.status != ROOM_ARCHIVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有已归档实验可以创建手工付款")
    if room.archive_reason not in MANUAL_PAYMENT_ARCHIVE_REASONS:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前归档原因不允许创建手工付款")
    if kind not in (
        PAYMENT_SOURCE_MANUAL_SHOWUP,
        PAYMENT_SOURCE_MANUAL_COMPLETION,
        PAYMENT_SOURCE_MANUAL_COMPENSATION,
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "付款类型无效")
    if amount_cents <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "付款金额必须大于 0")
    note = admin_note.strip()
    if not note:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须填写付款备注")

    booking = await db.get(Booking, booking_id)
    if (
        booking is None
        or booking.room_id != room.id
        or booking.participant_id != participant_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该预约不存在或不属于该参与者")
    if kind in (
        PAYMENT_SOURCE_MANUAL_SHOWUP,
        PAYMENT_SOURCE_MANUAL_COMPLETION,
    ) and booking.status != BOOKING_ATTENDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有到场参与者可以创建该类型付款")
    if kind == PAYMENT_SOURCE_MANUAL_COMPENSATION:
        if room.archive_reason != ARCHIVE_ADMIN_CANCELLED and booking.status == BOOKING_CANCELED:
            raise HTTPException(status.HTTP_409_CONFLICT, "已取消预约不能创建补偿付款")

    existing_query = await db.execute(
        select(Payment).where(
            Payment.room_id == room.id,
            Payment.participant_id == participant_id,
        )
    )
    if existing_query.scalars().first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "该参与者在本场已有付款记录，请使用金额覆盖调整",
        )

    if not await has_identity(db, room.id, participant_id):
        if identity_values is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "该参与者没有身份记录，必须同时录入姓名、支付宝手机号和证件信息",
            )
        try:
            validated_identity = validate_identity_values(
                identity_values.get("real_name"),
                identity_values.get("alipay_phone"),
                identity_values.get("document_type"),
                identity_values.get("document_number"),
            )
        except QuestionnaireValidationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        await upsert_identity_values(
            db, room.id, participant_id, validated_identity
        )

    now = utcnow()

    base = 0
    performance = 0
    showup = 0
    override: int | None = None
    if kind == PAYMENT_SOURCE_MANUAL_SHOWUP:
        showup = amount_cents
    elif kind == PAYMENT_SOURCE_MANUAL_COMPLETION:
        base = amount_cents
    else:
        override = amount_cents

    payment = Payment(
        room_id=room.id,
        participant_id=participant_id,
        base_pay_cents=base,
        performance_pay_cents=performance,
        showup_pay_cents=showup,
        override_amount_cents=override,
        total_cents=amount_cents,
        source=kind,
        status=PAYMENT_PENDING,
        computed_at=now,
        deadline_at=payment_deadline(now),
        admin_note=note,
    )
    db.add(payment)
    await db.flush()
    add_event(
        db,
        room,
        "manual_payment_created",
        participant_id,
        {"kind": kind, "amountCents": amount_cents},
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
        "source": payment.source,
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
    if (
        setting_override
        and override_amount_cents is None
        and payment.source == PAYMENT_SOURCE_MANUAL_COMPENSATION
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "手工补偿不能清空金额，请填写新金额或撤销付款",
        )
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
