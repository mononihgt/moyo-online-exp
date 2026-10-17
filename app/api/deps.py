from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import AdminUser, Participant
from ..security import assert_csrf, current_admin, current_participant

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def participant_dependency(request: Request, db: DbSession) -> Participant:
    return await current_participant(request, db)


async def admin_dependency(request: Request, db: DbSession) -> AdminUser:
    return await current_admin(request, db)


ParticipantDep = Annotated[Participant, Depends(participant_dependency)]
AdminDep = Annotated[AdminUser, Depends(admin_dependency)]


def require_csrf(request: Request) -> None:
    assert_csrf(request)
