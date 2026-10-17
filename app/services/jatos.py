from urllib.parse import quote

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Participant, Room, RoomParticipant, SystemSetting
from ..security import sign_payload, verify_signed_payload

QUESTIONNAIRE_TOKEN_SALT = "questionnaire-token"
QUESTIONNAIRE_TOKEN_MAX_AGE = 60 * 60 * 24 * 7


async def _setting(db: AsyncSession, key: str) -> str | None:
    row = await db.get(SystemSetting, key)
    if row is None or not isinstance(row.value_json, dict):
        return None
    value = row.value_json.get("value")
    return value if isinstance(value, str) and value else None


async def jatos_config(db: AsyncSession) -> tuple[str, str]:
    settings = get_settings()
    base_url = await _setting(db, "jatos_base_url") or settings.jatos_base_url
    study_code = await _setting(db, "jatos_study_code") or settings.jatos_study_code
    return base_url.rstrip("/"), study_code


def build_questionnaire_token(room: Room, room_participant: RoomParticipant) -> str:
    return sign_payload(
        {
            "roomId": room.id,
            "participantId": room_participant.participant_id,
            "roomParticipantId": room_participant.id,
            "questionnaireVersionId": room.questionnaire_version_id,
            "purpose": "questionnaire",
        },
        QUESTIONNAIRE_TOKEN_SALT,
    )


def read_questionnaire_token(token: str) -> dict:
    payload = verify_signed_payload(token, QUESTIONNAIRE_TOKEN_SALT, QUESTIONNAIRE_TOKEN_MAX_AGE)
    if payload.get("purpose") != "questionnaire":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "问卷链接无效")
    for field in ("roomId", "participantId", "roomParticipantId", "questionnaireVersionId"):
        if not payload.get(field):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "问卷链接无效")
    return payload


async def build_questionnaire_url(db: AsyncSession, room: Room, room_participant: RoomParticipant) -> str:
    base_url, study_code = await jatos_config(db)
    if not base_url or not study_code:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "JATOS 问卷地址尚未配置")
    token = build_questionnaire_token(room, room_participant)
    return f"{base_url}/publix/{study_code}?rt={quote(token)}&pid={quote(room_participant.analysis_code)}"


async def fetch_jatos_result(study_result_id: str) -> dict:
    settings = get_settings()
    if not settings.jatos_api_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "JATOS API token 未配置")
    url = f"{settings.jatos_base_url.rstrip('/')}/jatos/api/v1/results/{quote(study_result_id)}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {settings.jatos_api_token}"})
    if response.status_code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"JATOS 返回 {response.status_code}")
    return response.json()


async def participant_for_token(db: AsyncSession, payload: dict) -> Participant:
    participant = await db.get(Participant, payload["participantId"])
    if participant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "参与者不存在")
    return participant
