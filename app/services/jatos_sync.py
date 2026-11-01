import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from ..config import get_settings
from ..constants import ROOM_ARCHIVED, ROOM_QUESTIONNAIRE
from ..db import session_scope
from ..models import QuestionnaireResponse, Room, RoomParticipant, SystemSetting
from ..timeutil import isoformat_utc, utcnow
from .jatos import (
    JatosApiError,
    fetch_component_result_data,
    fetch_results_metadata,
    iter_study_results,
    jatos_sync_config,
    parse_jatos_query_parameters,
    read_questionnaire_token,
    result_completion_time,
)
from .locking import room_lock
from .questionnaire_flow import complete_questionnaire
from .runtime import runtime_manager

logger = logging.getLogger(__name__)

SYNC_STATE_KEY = "jatos_sync_state"
ALLOWED_ARCHIVE_REASONS = {
    "technical_abort",
    "questionnaire_incomplete",
    "completed",
}


class SyncSkip(Exception):
    pass


@dataclass(frozen=True)
class SyncCandidate:
    study_result_id: str
    component_result_id: str
    worker_id: str | None
    query_parameters: dict[str, str]
    completion_time: datetime


@dataclass(frozen=True)
class SyncTarget:
    room_id: str
    participant_id: str
    room_participant_id: str
    analysis_code: str
    questionnaire_version_id: str


@dataclass(frozen=True)
class SyncRunResult:
    disabled: bool
    disabled_reason: str | None
    imported: int
    skipped: int
    errors: list[str]


def _candidate_sort_key(candidate: SyncCandidate) -> tuple:
    def numeric(value: str) -> tuple[int, object]:
        return (0, int(value)) if value.isdigit() else (1, value)

    return (numeric(candidate.study_result_id), numeric(candidate.component_result_id))


def build_candidates(
    payload: dict,
    imported_pairs: set[tuple[str, str]],
    *,
    sync_time: datetime,
) -> list[SyncCandidate]:
    candidates: list[SyncCandidate] = []
    for study_result in iter_study_results(payload):
        study_result_id = str(study_result.get("id") or "")
        if not study_result_id:
            continue
        component_results = study_result.get("componentResults")
        if not isinstance(component_results, list):
            continue
        study_query = parse_jatos_query_parameters(study_result.get("urlQueryParameters"))
        for component_result in component_results:
            if not isinstance(component_result, dict):
                continue
            component_result_id = str(component_result.get("id") or "")
            if not component_result_id:
                continue
            data_info = component_result.get("data")
            data_size = 0
            if isinstance(data_info, dict):
                try:
                    data_size = int(data_info.get("size") or 0)
                except (TypeError, ValueError):
                    data_size = 0
            if data_size <= 0:
                continue
            if (study_result_id, component_result_id) in imported_pairs:
                continue
            query_parameters = dict(study_query)
            component_query = parse_jatos_query_parameters(
                component_result.get("urlQueryParameters")
            )
            for key, value in component_query.items():
                query_parameters.setdefault(key, value)
            worker_id = study_result.get("workerId")
            candidates.append(
                SyncCandidate(
                    study_result_id=study_result_id,
                    component_result_id=component_result_id,
                    worker_id=str(worker_id) if worker_id is not None else None,
                    query_parameters=query_parameters,
                    completion_time=result_completion_time(
                        study_result, component_result, fallback=sync_time
                    ),
                )
            )
    candidates.sort(key=_candidate_sort_key)
    return candidates


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, JatosApiError):
        return str(exc)[:500]
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return detail[:500]
    if isinstance(exc, httpx.HTTPError):
        return f"JATOS 网络请求失败：{type(exc).__name__}"[:500]
    return "JATOS 结果处理失败"


async def read_sync_state() -> dict:
    async with session_scope() as db:
        row = await db.get(SystemSetting, SYNC_STATE_KEY)
        if row is None or not isinstance(row.value_json, dict):
            return {}
        value = row.value_json.get("value")
        return value if isinstance(value, dict) else {}


async def write_sync_state(state: dict) -> None:
    async with session_scope() as db:
        row = await db.get(SystemSetting, SYNC_STATE_KEY)
        if row is None:
            row = SystemSetting(key=SYNC_STATE_KEY, value_json={"value": state})
            db.add(row)
        else:
            row.value_json = {"value": state}
            row.updated_at = utcnow()
        await db.commit()


async def _write_sync_state_safely(state: dict) -> None:
    try:
        await write_sync_state(state)
    except Exception:
        logger.exception("JATOS 同步状态写入失败")


async def _imported_pairs() -> set[tuple[str, str]]:
    async with session_scope() as db:
        rows = await db.execute(
            select(
                QuestionnaireResponse.jatos_study_result_id,
                QuestionnaireResponse.jatos_component_result_id,
            )
        )
        return {(str(study_id), str(component_id)) for study_id, component_id in rows.all()}


async def _resolve_target(candidate: SyncCandidate) -> SyncTarget:
    token = candidate.query_parameters.get("rt")
    if not token:
        raise SyncSkip("JATOS 结果缺少问卷 token")
    try:
        payload = read_questionnaire_token(token)
    except HTTPException as exc:
        raise SyncSkip("问卷 token 无效或已过期") from exc
    async with session_scope() as db:
        room_participant = await db.get(
            RoomParticipant, str(payload["roomParticipantId"])
        )
        if room_participant is None:
            raise SyncSkip("目标参与者不存在")
        room = await db.get(Room, str(payload["roomId"]))
        if room is None:
            raise SyncSkip("目标 Room 不存在")
        if room_participant.room_id != payload["roomId"]:
            raise SyncSkip("问卷 token 的 Room 不匹配")
        if room_participant.participant_id != payload["participantId"]:
            raise SyncSkip("问卷 token 的参与者不匹配")
        if room.questionnaire_version_id != payload["questionnaireVersionId"]:
            raise SyncSkip("问卷 token 的问卷版本不匹配")
        pid = candidate.query_parameters.get("pid")
        if pid and pid != room_participant.analysis_code:
            raise SyncSkip("问卷 token 的分析编号不匹配")
        if room.status not in (ROOM_QUESTIONNAIRE, ROOM_ARCHIVED):
            raise SyncSkip("Room 不在问卷阶段")
        if room.status == ROOM_ARCHIVED and room.archive_reason not in ALLOWED_ARCHIVE_REASONS:
            raise SyncSkip("Room 已归档且不能补交问卷")
        return SyncTarget(
            room_id=room.id,
            participant_id=room_participant.participant_id,
            room_participant_id=room_participant.id,
            analysis_code=room_participant.analysis_code,
            questionnaire_version_id=room.questionnaire_version_id,
        )


def _answers_from_payload(target: SyncTarget, payload: dict) -> dict:
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise SyncSkip("JATOS 结果缺少问卷答案")
    analysis_code = payload.get("analysisCode")
    if not isinstance(analysis_code, str) or analysis_code != target.analysis_code:
        raise SyncSkip("JATOS 结果分析编号不匹配")
    version_id = payload.get("questionnaireVersionId")
    if not isinstance(version_id, str) or version_id != target.questionnaire_version_id:
        raise SyncSkip("JATOS 结果问卷版本不匹配")
    return answers


async def _check_pair_ownership(
    db, candidate: SyncCandidate, target: SyncTarget
) -> None:
    rows = await db.execute(
        select(
            QuestionnaireResponse.room_id,
            QuestionnaireResponse.participant_id,
        ).where(
            QuestionnaireResponse.jatos_study_result_id == candidate.study_result_id,
            QuestionnaireResponse.jatos_component_result_id == candidate.component_result_id,
        )
    )
    for room_id, participant_id in rows.all():
        if str(room_id) != target.room_id or str(participant_id) != target.participant_id:
            raise SyncSkip("JATOS 结果已归属其他 Room 或参与者")


async def _import_candidate(
    candidate: SyncCandidate, target: SyncTarget, answers: dict
) -> bool:
    async with room_lock(target.room_id):
        async with session_scope() as db:
            await db.commit()
            room = await db.get(Room, target.room_id)
            room_participant = await db.get(RoomParticipant, target.room_participant_id)
            if room is None or room_participant is None:
                raise SyncSkip("目标 Room 或参与者不存在")
            if room_participant.room_id != target.room_id:
                raise SyncSkip("目标参与者不属于该 Room")
            if room_participant.participant_id != target.participant_id:
                raise SyncSkip("目标参与者的回答与 token 不匹配")
            if room.questionnaire_version_id != target.questionnaire_version_id:
                raise SyncSkip("Room 问卷版本已变化")
            if room_participant.analysis_code != target.analysis_code:
                raise SyncSkip("Room 参与者分析编号已变化")
            await _check_pair_ownership(db, candidate, target)
            result = await complete_questionnaire(
                db,
                room,
                room_participant,
                answers=answers,
                jatos_worker_id=candidate.worker_id,
                jatos_study_result_id=candidate.study_result_id,
                jatos_component_result_id=candidate.component_result_id,
                source="jatos_sync",
                completed_at=candidate.completion_time,
            )
            return bool(result.get("inserted"))


class JatosSyncManager:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.sync_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("JATOS 同步循环失败")
            await asyncio.sleep(get_settings().jatos_sync_interval_seconds)

    async def sync_once(self) -> None:
        async with self._lock:
            previous = await read_sync_state()
            try:
                result = await self._run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("JATOS 同步运行失败")
                state = {
                    **previous,
                    "status": "error",
                    "lastRunAt": isoformat_utc(utcnow()),
                    "lastError": _safe_error(exc),
                    "lastErrorAt": isoformat_utc(utcnow()),
                }
                await _write_sync_state_safely(state)
                return

            now = utcnow()
            if result.disabled:
                state = {
                    **previous,
                    "status": "disabled",
                    "lastRunAt": isoformat_utc(now),
                    "lastImported": 0,
                    "lastSkipped": 0,
                }
                if result.disabled_reason:
                    state["lastError"] = result.disabled_reason
                    state["lastErrorAt"] = isoformat_utc(now)
                await _write_sync_state_safely(state)
                return

            state = {
                **previous,
                "status": "ok",
                "lastRunAt": isoformat_utc(now),
                "lastSuccessAt": isoformat_utc(now),
                "lastImported": result.imported,
                "lastSkipped": result.skipped,
            }
            if result.errors:
                state["lastError"] = result.errors[-1]
                state["lastErrorAt"] = isoformat_utc(now)
            else:
                state["lastError"] = None
                state["lastErrorAt"] = None
            await _write_sync_state_safely(state)

    async def _run(self) -> SyncRunResult:
        async with session_scope() as db:
            base_url, study_id, api_token = await jatos_sync_config(db)
        if not base_url or not study_id or not api_token:
            reasons = []
            if not base_url:
                reasons.append("未配置 JATOS 地址")
            if not study_id:
                reasons.append("未配置 JATOS study ID")
            if not api_token:
                reasons.append("未配置 JATOS API token")
            return SyncRunResult(
                disabled=True,
                disabled_reason="；".join(reasons) or "JATOS 自动同步未配置",
                imported=0,
                skipped=0,
                errors=[],
            )

        imported_pairs = await _imported_pairs()
        sync_time = utcnow()
        imported = 0
        skipped = 0
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=60) as client:
            metadata = await fetch_results_metadata(client, base_url, api_token, study_id)
            candidates = build_candidates(
                metadata, imported_pairs, sync_time=sync_time
            )
            for candidate in candidates:
                try:
                    target = await _resolve_target(candidate)
                    payload = await fetch_component_result_data(
                        client, base_url, api_token, candidate.component_result_id
                    )
                    answers = _answers_from_payload(target, payload)
                    inserted = await _import_candidate(candidate, target, answers)
                except SyncSkip as exc:
                    skipped += 1
                    errors.append(str(exc))
                    logger.warning(
                        "JATOS 同步跳过结果 %s/%s：%s",
                        candidate.study_result_id,
                        candidate.component_result_id,
                        exc,
                    )
                    continue
                except (JatosApiError, HTTPException, httpx.HTTPError) as exc:
                    skipped += 1
                    message = _safe_error(exc)
                    errors.append(message)
                    logger.warning(
                        "JATOS 同步处理失败 %s/%s：%s",
                        candidate.study_result_id,
                        candidate.component_result_id,
                        message,
                    )
                    continue
                if inserted:
                    imported += 1
                    try:
                        await runtime_manager.notify_room(target.room_id)
                    except Exception:
                        logger.exception(
                            "JATOS 同步导入后通知 Room 失败：%s", target.room_id
                        )
        return SyncRunResult(
            disabled=False,
            disabled_reason=None,
            imported=imported,
            skipped=skipped,
            errors=errors,
        )


jatos_sync_manager = JatosSyncManager()
