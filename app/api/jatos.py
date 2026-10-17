from fastapi import APIRouter, Request

from ..config import get_settings
from ..schemas import QuestionnaireCompleteRequest, QuestionnaireDraftRequest
from ..security import client_ip, rate_limiter
from ..services.questionnaire_flow import complete_with_token, questionnaire_context, save_draft
from ..services.runtime import runtime_manager
from .deps import DbSession

router = APIRouter(prefix="/api/jatos")


def _limit(request: Request) -> None:
    settings = get_settings()
    rate_limiter.check(
        f"questionnaire:{client_ip(request, settings)}",
        settings.questionnaire_rate_limit_attempts,
        settings.questionnaire_rate_limit_seconds,
    )


@router.get("/questionnaire")
async def get_questionnaire(token: str, request: Request, db: DbSession):
    _limit(request)
    context = await questionnaire_context(db, token)
    context["platformBaseUrl"] = get_settings().public_base_url.rstrip("/")
    return context


@router.post("/questionnaire/draft")
async def post_draft(payload: QuestionnaireDraftRequest, request: Request, db: DbSession):
    _limit(request)
    return await save_draft(db, payload.token, payload.answers)


@router.post("/questionnaire/complete")
async def post_complete(payload: QuestionnaireCompleteRequest, request: Request, db: DbSession):
    _limit(request)
    result = await complete_with_token(
        db,
        payload.token,
        {
            "answers": payload.answers,
            "jatos_worker_id": payload.jatos_worker_id,
            "jatos_study_result_id": payload.jatos_study_result_id,
            "jatos_component_result_id": payload.jatos_component_result_id,
        },
    )
    from ..services.questionnaire_flow import load_context

    room, _room_participant, _questionnaire = await load_context(db, payload.token)
    await runtime_manager.notify_room(room.id)
    return result
