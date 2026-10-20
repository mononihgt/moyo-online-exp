from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import Field
from sqlalchemy import select

from ..constants import PAYMENT_PAID
from ..models import Participant, Payment, Room, RoomParticipant
from ..schemas import ApiModel, PaymentPatch
from ..security import decrypt_phone, mask_phone
from ..services.events import add_event
from ..services.payment_lists import (
    bulk_payments,
    mark_payments_paid,
    parse_date_range,
    payment_list_csv,
    range_bounds,
    reimbursement_list_csv,
)
from ..services.payments import UNSET, apply_override, serialize_payment
from ..timeutil import isoformat_utc
from .admin_common import audit
from .deps import AdminDep, DbSession, require_csrf

router = APIRouter()


class BulkMarkPaidRequest(ApiModel):
    payment_ids: list[str] = Field(min_length=1)


@router.get("/payments")
async def list_payments(
    admin: AdminDep,
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
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
    if (date_from is None) != (date_to is None):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "开始日期和结束日期必须同时提供"
        )
    if date_from is not None and date_to is not None:
        start, end = range_bounds(*parse_date_range(date_from, date_to))
        statement = statement.where(Room.starts_at >= start, Room.starts_at < end)
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
    fields = payload.model_dump(exclude_unset=True)
    apply_override(
        payment,
        override_amount_cents=fields.get("override_amount_cents", UNSET),
        note=fields.get("admin_note", UNSET),
        new_status=payload.status,
    )
    if payload.status == PAYMENT_PAID and previous_status != PAYMENT_PAID:
        room = await db.get(Room, payment.room_id)
        add_event(db, room, "payment_paid", payment.participant_id, {"totalCents": payment.total_cents})
    audit(db, admin, "payment_updated", "payment", payment.id, fields)
    await db.commit()
    return {"payment": serialize_payment(payment)}


@router.get("/payments/export-payment-list.csv")
async def export_payment_list(
    admin: AdminDep,
    db: DbSession,
    from_: str = Query(alias="from"),
    to: str = Query(),
):
    date_from, date_to = parse_date_range(from_, to)
    data = await payment_list_csv(db, date_from, date_to)
    audit(
        db,
        admin,
        "payments_payment_list_exported",
        "payment",
        f"{from_}~{to}",
        {"from": from_, "to": to},
    )
    await db.commit()
    return Response(
        data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="payment-list-{from_}-{to}.csv"',
        },
    )


@router.get("/payments/export-reimbursement-list.csv")
async def export_reimbursement_list(
    admin: AdminDep,
    db: DbSession,
    from_: str = Query(alias="from"),
    to: str = Query(),
):
    date_from, date_to = parse_date_range(from_, to)
    data = await reimbursement_list_csv(db, date_from, date_to)
    audit(
        db,
        admin,
        "payments_reimbursement_list_exported",
        "payment",
        f"{from_}~{to}",
        {"from": from_, "to": to},
    )
    await db.commit()
    return Response(
        data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="reimbursement-list-{from_}-{to}.csv"',
        },
    )


@router.get("/payments/bulk")
async def view_bulk_payments(
    admin: AdminDep,
    db: DbSession,
    from_: str = Query(alias="from"),
    to: str = Query(),
):
    date_from, date_to = parse_date_range(from_, to)
    items = await bulk_payments(db, date_from, date_to)
    audit(
        db,
        admin,
        "payments_bulk_viewed",
        "payment",
        f"{from_}~{to}",
        {"from": from_, "to": to, "count": len(items)},
    )
    await db.commit()
    return {"payments": items, "from": from_, "to": to}


@router.post("/payments/bulk-mark-paid", dependencies=[Depends(require_csrf)])
async def bulk_mark_paid(payload: BulkMarkPaidRequest, admin: AdminDep, db: DbSession):
    result = await mark_payments_paid(db, payload.payment_ids)
    audit(
        db,
        admin,
        "payments_bulk_marked_paid",
        "payment",
        "bulk",
        {
            "paymentIds": payload.payment_ids,
            "updated": result["updated"],
            "skipped": result["skipped"],
        },
    )
    await db.commit()
    return result
