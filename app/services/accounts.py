from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import PARTICIPANT_MERGED
from ..models import Participant


async def resolve_participant_alias(
    db: AsyncSession, participant: Participant
) -> Participant:
    current = participant
    seen: set[str] = set()
    while current.status == PARTICIPANT_MERGED:
        if current.id in seen or len(seen) >= 8:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "账号合并记录异常，请联系实验工作人员"
            )
        seen.add(current.id)
        if current.merged_into_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "账号合并记录异常，请联系实验工作人员"
            )
        target = await db.get(Participant, current.merged_into_id)
        if target is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "合并后的目标账号不存在，请联系实验工作人员"
            )
        current = target
    return current
