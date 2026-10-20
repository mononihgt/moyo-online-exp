from contextlib import asynccontextmanager

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    PARTICIPANT_COMPLETED,
    QUESTIONNAIRE_COMPLETED,
    QUESTIONNAIRE_IN_PROGRESS,
    ROOM_ARCHIVED,
    ROOM_QUESTIONNAIRE,
)
from ..models import (
    Participant,
    ParticipantIdentity,
    QuestionnaireDraft,
    QuestionnaireResponse,
    QuestionnaireVersion,
    Room,
    RoomParticipant,
)
from ..security import encrypt_identity
from ..timeutil import isoformat_utc, utcnow
from .events import add_event
from .jatos import build_questionnaire_token, read_questionnaire_token
from .locking import room_lock
from .payments import serialize_payment, upsert_payment
from .questionnaires import (
    QuestionnaireValidationError,
    protected_question_ids,
    serialize_questionnaire,
    split_protected_answers,
)
from .rooms import archive_room, technical_abort_showup_eligible


@asynccontextmanager
async def _room_write_lock(db: AsyncSession, room_id: str):
    async with room_lock(room_id):
        await db.commit()
        yield


def _strip_protected_answers(schema: dict, answers: dict | None) -> dict | None:
    if not isinstance(answers, dict):
        return answers
    protected_ids = set(protected_question_ids(schema))
    return {key: value for key, value in answers.items() if key not in protected_ids}


def _split_answers(
    schema: dict, answers: dict, *, enforce_required: bool
) -> tuple[dict, dict | None]:
    try:
        return split_protected_answers(schema, answers, enforce_required=enforce_required)
    except QuestionnaireValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


async def _upsert_identity(
    db: AsyncSession,
    room: Room,
    room_participant: RoomParticipant,
    identity: dict,
) -> None:
    row = await db.execute(
        select(ParticipantIdentity).where(
            ParticipantIdentity.room_id == room.id,
            ParticipantIdentity.participant_id == room_participant.participant_id,
        )
    )
    existing = row.scalars().first()
    now = utcnow()
    real_name_encrypted = encrypt_identity(identity["real_name"])
    alipay_phone_encrypted = encrypt_identity(identity["alipay_phone"])
    document_number_encrypted = encrypt_identity(identity["document_number"])
    if existing is None:
        db.add(
            ParticipantIdentity(
                room_id=room.id,
                participant_id=room_participant.participant_id,
                real_name_encrypted=real_name_encrypted,
                alipay_phone_encrypted=alipay_phone_encrypted,
                document_type=identity["document_type"],
                document_number_encrypted=document_number_encrypted,
                created_at=now,
                updated_at=now,
            )
        )
        return
    existing.real_name_encrypted = real_name_encrypted
    existing.alipay_phone_encrypted = alipay_phone_encrypted
    existing.document_type = identity["document_type"]
    existing.document_number_encrypted = document_number_encrypted
    existing.updated_at = now


async def load_context(db: AsyncSession, token: str) -> tuple[Room, RoomParticipant, QuestionnaireVersion]:
    payload = read_questionnaire_token(token)
    room = await db.get(Room, payload["roomId"])
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实验不存在")
    room_participant = await db.get(RoomParticipant, payload["roomParticipantId"])
    if room_participant is None or room_participant.room_id != room.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "参与者记录不存在")
    if room_participant.participant_id != payload["participantId"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "问卷链接与参与者不匹配")
    if room.questionnaire_version_id != payload["questionnaireVersionId"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "问卷版本已变化，请向实验工作人员申请新链接")
    questionnaire = await db.get(QuestionnaireVersion, room.questionnaire_version_id)
    if questionnaire is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "问卷版本不存在")
    return room, room_participant, questionnaire


async def _technical_abort_questionnaire_allowed(
    db: AsyncSession, room: Room, room_participant: RoomParticipant
) -> bool:
    return await technical_abort_showup_eligible(
        db,
        room,
        room_participant.participant_id,
        room_participant=room_participant,
    )


async def _questionnaire_archive_allowed(
    db: AsyncSession, room: Room, room_participant: RoomParticipant
) -> bool:
    if room.archive_reason in ("questionnaire_incomplete", "completed"):
        return True
    return await _technical_abort_questionnaire_allowed(db, room, room_participant)


async def _questionnaire_draft_allowed(
    db: AsyncSession, room: Room, room_participant: RoomParticipant
) -> bool:
    if room.archive_reason == "questionnaire_incomplete":
        return True
    return await _technical_abort_questionnaire_allowed(db, room, room_participant)


async def questionnaire_context(db: AsyncSession, token: str) -> dict:
    payload = read_questionnaire_token(token)
    async with _room_write_lock(db, payload["roomId"]):
        return await _questionnaire_context_locked(db, token)


async def _questionnaire_context_locked(db: AsyncSession, token: str) -> dict:
    room, room_participant, questionnaire = await load_context(db, token)
    if room.status not in (ROOM_QUESTIONNAIRE, ROOM_ARCHIVED):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前实验尚未进入问卷阶段")
    if room.status == ROOM_ARCHIVED and not await _questionnaire_archive_allowed(
        db, room, room_participant
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "本次实验已结束")
    existing = await _canonical_response(db, room.id, room_participant.participant_id)
    draft = await db.execute(
        select(QuestionnaireDraft).where(
            QuestionnaireDraft.room_id == room.id,
            QuestionnaireDraft.participant_id == room_participant.participant_id,
        )
    )
    draft_row = draft.scalars().first()
    actions = []
    if room_participant.questionnaire_status != QUESTIONNAIRE_COMPLETED:
        if room_participant.questionnaire_status != QUESTIONNAIRE_IN_PROGRESS:
            room_participant.questionnaire_status = QUESTIONNAIRE_IN_PROGRESS
            room_participant.questionnaire_started_at = utcnow()
            add_event(db, room, "questionnaire_started", room_participant.participant_id)
            actions.append("questionnaire_started")
        else:
            room_participant.questionnaire_started_at = room_participant.questionnaire_started_at or utcnow()
    await db.commit()
    settings = get_settings()
    return {
        "roomId": room.id,
        "roomStatus": room.status,
        "archiveReason": room.archive_reason,
        "analysisCode": room_participant.analysis_code,
        "completed": room_participant.questionnaire_status == QUESTIONNAIRE_COMPLETED,
        "questionnaire": serialize_questionnaire(questionnaire),
        "draftAnswers": (
            _strip_protected_answers(questionnaire.schema_json, draft_row.answers_json)
            if draft_row is not None and existing is None
            else None
        ),
        "existingAnswers": (
            _strip_protected_answers(questionnaire.schema_json, existing.answers_json)
            if existing is not None
            else None
        ),
        "redirectUrl": f"{settings.public_base_url.rstrip('/')}/complete?room={room.id}",
    }


async def _canonical_response(db: AsyncSession, room_id: str, participant_id: str) -> QuestionnaireResponse | None:
    rows = await db.execute(
        select(QuestionnaireResponse)
        .where(
            QuestionnaireResponse.room_id == room_id,
            QuestionnaireResponse.participant_id == participant_id,
            QuestionnaireResponse.canonical.is_(True),
        )
        .order_by(QuestionnaireResponse.completed_at)
        .limit(1)
    )
    return rows.scalars().first()


async def save_draft(db: AsyncSession, token: str, answers: dict) -> dict:
    payload = read_questionnaire_token(token)
    async with _room_write_lock(db, payload["roomId"]):
        return await _save_draft_locked(db, token, answers)


async def _save_draft_locked(db: AsyncSession, token: str, answers: dict) -> dict:
    room, room_participant, questionnaire = await load_context(db, token)
    if room_participant.questionnaire_status == QUESTIONNAIRE_COMPLETED:
        raise HTTPException(status.HTTP_409_CONFLICT, "问卷已经提交")
    if room.status == ROOM_ARCHIVED and not await _questionnaire_draft_allowed(
        db, room, room_participant
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "本次实验已结束")
    if room.status not in (ROOM_QUESTIONNAIRE, ROOM_ARCHIVED):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前实验不在问卷阶段")
    sanitized_answers, _identity = _split_answers(
        questionnaire.schema_json, answers, enforce_required=False
    )
    row = await db.execute(
        select(QuestionnaireDraft).where(
            QuestionnaireDraft.room_id == room.id,
            QuestionnaireDraft.participant_id == room_participant.participant_id,
        )
    )
    draft = row.scalars().first()
    if draft is None:
        draft = QuestionnaireDraft(
            room_id=room.id,
            participant_id=room_participant.participant_id,
            answers_json=sanitized_answers,
        )
        db.add(draft)
    else:
        draft.answers_json = sanitized_answers
        draft.updated_at = utcnow()
    await db.commit()
    return {"saved": True, "updatedAt": isoformat_utc(draft.updated_at)}


async def complete_questionnaire(
    db: AsyncSession,
    room: Room,
    room_participant: RoomParticipant,
    *,
    answers: dict,
    jatos_worker_id: str | None,
    jatos_study_result_id: str,
    jatos_component_result_id: str,
    source: str,
) -> dict:
    if room.status not in (ROOM_QUESTIONNAIRE, ROOM_ARCHIVED):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前实验尚未进入问卷阶段")
    if room.status == ROOM_ARCHIVED and not await _questionnaire_archive_allowed(
        db, room, room_participant
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "本次实验已结束")
    technical_abort = (
        room.status == ROOM_ARCHIVED and room.archive_reason == "technical_abort"
    )
    existing_attempt_query = await db.execute(
        select(QuestionnaireResponse).where(
            QuestionnaireResponse.room_id == room.id,
            QuestionnaireResponse.participant_id == room_participant.participant_id,
            QuestionnaireResponse.jatos_study_result_id == jatos_study_result_id,
            QuestionnaireResponse.jatos_component_result_id == jatos_component_result_id,
        )
    )
    existing_attempt = existing_attempt_query.scalars().first()
    questionnaire = await db.get(QuestionnaireVersion, room.questionnaire_version_id)
    sanitized_answers, identity = _split_answers(
        questionnaire.schema_json, answers, enforce_required=True
    )
    if identity is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "缺少受保护身份字段")

    if existing_attempt is not None:
        redirect = f"{get_settings().public_base_url.rstrip('/')}/complete?room={room.id}"
        return {"saved": True, "canonical": existing_attempt.canonical, "redirectUrl": redirect}

    canonical = await _canonical_response(db, room.id, room_participant.participant_id)
    response = QuestionnaireResponse(
        room_id=room.id,
        participant_id=room_participant.participant_id,
        questionnaire_version_id=questionnaire.id,
        jatos_worker_id=jatos_worker_id,
        jatos_study_result_id=jatos_study_result_id,
        jatos_component_result_id=jatos_component_result_id,
        answers_json=sanitized_answers,
        canonical=canonical is None,
        source=source,
        completed_at=utcnow(),
    )
    db.add(response)
    await db.flush()

    draft_query = await db.execute(
        select(QuestionnaireDraft).where(
            QuestionnaireDraft.room_id == room.id,
            QuestionnaireDraft.participant_id == room_participant.participant_id,
        )
    )
    for draft in draft_query.scalars().all():
        await db.delete(draft)

    if canonical is None:
        await _upsert_identity(db, room, room_participant, identity)
        room_participant.questionnaire_status = QUESTIONNAIRE_COMPLETED
        room_participant.completed_at = utcnow()
        add_event(
            db,
            room,
            "questionnaire_completed",
            room_participant.participant_id,
            {"jatosStudyResultId": jatos_study_result_id, "source": source},
        )
        payment = await upsert_payment(
            db, room, room_participant.participant_id, room_participant=room_participant
        )
        if payment is None:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "到场费计算失败，请联系实验工作人员"
                if technical_abort
                else "报酬计算失败，请联系实验工作人员",
            )
        if not technical_abort:
            participant = await db.get(Participant, room_participant.participant_id)
            participant.status = PARTICIPANT_COMPLETED

            all_completed_query = await db.execute(
                select(RoomParticipant).where(RoomParticipant.room_id == room.id)
            )
            all_completed = all(
                item.questionnaire_status == QUESTIONNAIRE_COMPLETED
                for item in all_completed_query.scalars().all()
            )
            if all_completed and room.status == ROOM_QUESTIONNAIRE:
                await archive_room(db, room, "completed")
    elif technical_abort:
        await _upsert_identity(db, room, room_participant, identity)
        room_participant.questionnaire_status = QUESTIONNAIRE_COMPLETED
        room_participant.completed_at = (
            room_participant.completed_at or canonical.completed_at or utcnow()
        )
        payment = await upsert_payment(
            db, room, room_participant.participant_id, room_participant=room_participant
        )
        if payment is None:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "到场费计算失败，请联系实验工作人员",
            )
    await db.commit()
    redirect = f"{get_settings().public_base_url.rstrip('/')}/complete?room={room.id}"
    return {"saved": True, "canonical": canonical is None, "redirectUrl": redirect}


async def complete_with_token(db: AsyncSession, token: str, payload: dict) -> dict:
    token_payload = read_questionnaire_token(token)
    async with _room_write_lock(db, token_payload["roomId"]):
        return await _complete_with_token_locked(db, token, payload)


async def _complete_with_token_locked(db: AsyncSession, token: str, payload: dict) -> dict:
    room, room_participant, _questionnaire = await load_context(db, token)
    if room_participant.questionnaire_status == QUESTIONNAIRE_COMPLETED:
        canonical = await _canonical_response(db, room.id, room_participant.participant_id)
        if canonical is not None and canonical.jatos_study_result_id == payload["jatos_study_result_id"]:
            redirect = f"{get_settings().public_base_url.rstrip('/')}/complete?room={room.id}"
            return {"saved": True, "canonical": True, "redirectUrl": redirect}
    return await complete_questionnaire(
        db,
        room,
        room_participant,
        answers=payload["answers"],
        jatos_worker_id=payload.get("jatos_worker_id"),
        jatos_study_result_id=payload["jatos_study_result_id"],
        jatos_component_result_id=payload["jatos_component_result_id"],
        source="jatos",
    )


async def complete_with_participant(
    db: AsyncSession, participant: Participant, room_id: str, payload: dict
) -> dict:
    async with _room_write_lock(db, room_id):
        return await _complete_with_participant_locked(db, participant, room_id, payload)


async def _complete_with_participant_locked(
    db: AsyncSession, participant: Participant, room_id: str, payload: dict
) -> dict:
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实验不存在")
    room_participant_query = await db.execute(
        select(RoomParticipant).where(
            RoomParticipant.room_id == room.id, RoomParticipant.participant_id == participant.id
        )
    )
    room_participant = room_participant_query.scalars().first()
    if room_participant is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "你不属于本次实验")
    return await complete_questionnaire(
        db,
        room,
        room_participant,
        answers=payload["answers"],
        jatos_worker_id=payload.get("jatos_worker_id"),
        jatos_study_result_id=payload["jatos_study_result_id"],
        jatos_component_result_id=payload["jatos_component_result_id"],
        source="platform",
    )


async def payment_for_participant(db: AsyncSession, room_id: str, participant_id: str) -> dict | None:
    from ..models import Payment

    row = await db.execute(
        select(Payment).where(Payment.room_id == room_id, Payment.participant_id == participant_id)
    )
    payment = row.scalars().first()
    if payment is None:
        return None
    return serialize_payment(payment)


async def questionnaire_link_for_participant(
    db: AsyncSession, room: Room, room_participant: RoomParticipant
) -> str | None:
    from .jatos import build_questionnaire_url

    try:
        return await build_questionnaire_url(db, room, room_participant)
    except HTTPException:
        return None


__all__ = [
    "build_questionnaire_token",
    "load_context",
    "questionnaire_context",
    "save_draft",
    "complete_questionnaire",
    "complete_with_token",
    "complete_with_participant",
    "payment_for_participant",
    "questionnaire_link_for_participant",
]
