from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from ..models import MediaAsset
from ..security import current_admin, current_participant
from ..services.media import media_absolute_path
from .deps import DbSession

router = APIRouter()


@router.get("/media/{asset_id}")
async def get_media(asset_id: str, request: Request, db: DbSession):
    authorized = False
    try:
        await current_participant(request, db)
        authorized = True
    except HTTPException:
        pass
    if not authorized:
        try:
            await current_admin(request, db)
            authorized = True
        except HTTPException:
            pass
    if not authorized:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无权访问该媒体文件")
    asset = await db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "媒体文件不存在")
    path = media_absolute_path(asset)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "媒体文件不存在")
    return FileResponse(
        path,
        media_type=asset.content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
