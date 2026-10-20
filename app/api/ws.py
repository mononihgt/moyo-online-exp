import json
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketDisconnected

from ..config import get_settings
from ..db import session_scope
from ..security import PARTICIPANT_COOKIE, read_participant_session
from ..services.runtime import runtime_manager

router = APIRouter()


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    settings = get_settings()
    allowed = {urlsplit(settings.public_base_url).netloc}
    if settings.jatos_origin:
        allowed.add(urlsplit(settings.jatos_origin).netloc)
    return urlsplit(origin).netloc in allowed


@router.websocket("/ws/room")
async def room_socket(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if not _origin_allowed(origin):
        await websocket.close(code=4403)
        return
    token = websocket.cookies.get(PARTICIPANT_COOKIE)
    if not token:
        await websocket.close(code=4401)
        return
    try:
        participant_id = read_participant_session(token, get_settings())
    except Exception:
        await websocket.close(code=4401)
        return
    async with session_scope() as db:
        from ..models import Participant

        participant = await db.get(Participant, participant_id)
        if participant is None:
            await websocket.close(code=4401)
            return
    room_id = await runtime_manager.connect(participant, websocket)
    if room_id is None:
        return
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "code": "invalid_json", "message": "消息不是有效 JSON"})
                continue
            if not isinstance(message, dict):
                await websocket.send_json({"type": "error", "code": "invalid_message", "message": "消息必须是对象"})
                continue
            await runtime_manager.handle(participant, message, websocket)
    except (WebSocketDisconnect, WebSocketDisconnected):
        await runtime_manager.disconnect(participant, websocket)
    except Exception:
        await runtime_manager.disconnect(participant, websocket)
        raise
