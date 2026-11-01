import io
import json
import zipfile
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Participant, Room, RoomParticipant, SystemSetting
from ..security import sign_payload, verify_signed_payload

QUESTIONNAIRE_TOKEN_SALT = "questionnaire-token"
QUESTIONNAIRE_TOKEN_MAX_AGE = 60 * 60 * 24 * 7


class JatosApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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


async def jatos_study_id(db: AsyncSession) -> str:
    settings = get_settings()
    return (await _setting(db, "jatos_study_id") or settings.jatos_study_id).strip()


async def jatos_sync_config(db: AsyncSession) -> tuple[str, str, str]:
    base_url, _study_code = await jatos_config(db)
    study_id = await jatos_study_id(db)
    return base_url.rstrip("/"), study_id, get_settings().jatos_api_token.strip()


def parse_jatos_query_parameters(value: object) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            str(key): str(item)
            for key, item in value.items()
            if isinstance(item, (str, int, float, bool))
        }
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        return {
            str(key): str(item)
            for key, item in parsed.items()
            if isinstance(item, (str, int, float, bool))
        }
    parsed_query = parse_qs(text)
    return {key: values[0] for key, values in parsed_query.items() if values}


def _datetime_from_epoch(value: float) -> datetime | None:
    if value <= 0:
        return None
    seconds = value / 1000 if value > 10_000_000_000 else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def parse_jatos_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _datetime_from_epoch(float(value))
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None:
        return _datetime_from_epoch(numeric)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def iter_study_results(payload: dict) -> Iterator[dict]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise JatosApiError("JATOS 结果元数据缺少 data")
    for group in data:
        if not isinstance(group, dict):
            continue
        study_results = group.get("studyResults")
        if not isinstance(study_results, list):
            continue
        for study_result in study_results:
            if isinstance(study_result, dict):
                yield study_result


def result_completion_time(
    study_result: dict, component_result: dict, *, fallback: datetime
) -> datetime:
    for value in (
        component_result.get("endDate"),
        study_result.get("endDate"),
        component_result.get("lastSeenDate"),
        study_result.get("lastSeenDate"),
    ):
        parsed = parse_jatos_datetime(value)
        if parsed is not None:
            return parsed
    return fallback


async def fetch_results_metadata(
    client: httpx.AsyncClient, base_url: str, api_token: str, study_id: str
) -> dict:
    params = {"download": "false"}
    if study_id.isdigit():
        params["studyId"] = study_id
    else:
        params["studyUuid"] = study_id
    response = await client.post(
        f"{base_url.rstrip('/')}/jatos/api/v1/results/metadata",
        params=params,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
        },
    )
    if response.status_code != 200:
        raise JatosApiError(
            f"JATOS 结果元数据请求失败，HTTP {response.status_code}",
            status_code=response.status_code,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise JatosApiError("JATOS 结果元数据不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise JatosApiError("JATOS 结果元数据格式异常")
    return payload


async def fetch_component_result_data(
    client: httpx.AsyncClient,
    base_url: str,
    api_token: str,
    component_result_id: str,
) -> dict:
    response = await client.post(
        f"{base_url.rstrip('/')}/jatos/api/v1/results/data",
        params={"componentResultId": str(component_result_id)},
        headers={"Authorization": f"Bearer {api_token}"},
    )
    if response.status_code != 200:
        raise JatosApiError(
            f"JATOS 结果数据请求失败，HTTP {response.status_code}",
            status_code=response.status_code,
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(response.content))
    except zipfile.BadZipFile as exc:
        raise JatosApiError("JATOS 结果数据不是有效 ZIP") from exc
    data_names = [
        name
        for name in archive.namelist()
        if name == "data.txt" or name.endswith("/data.txt")
    ]
    if len(data_names) != 1:
        raise JatosApiError("JATOS 结果缺少唯一的 data.txt")
    try:
        payload = json.loads(archive.read(data_names[0]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JatosApiError("JATOS 结果数据不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise JatosApiError("JATOS 结果数据格式异常")
    return payload


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


async def participant_for_token(db: AsyncSession, payload: dict) -> Participant:
    participant = await db.get(Participant, payload["participantId"])
    if participant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "参与者不存在")
    return participant
