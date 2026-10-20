import asyncio
import copy
import logging
import random
import secrets
import time
from datetime import datetime, timedelta

from fastapi import WebSocket
from sqlalchemy import case, or_, select

from ..config import get_settings
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from ..constants import (
    ARCHIVE_ABANDONED,
    ARCHIVE_TECHNICAL_ABORT,
    BOOKING_ATTENDED,
    BOOKING_BOOKED,
    END_REASON_ANNIHILATION,
    END_REASON_TURN_LIMIT,
    MAP_MODE_BOTH,
    MAP_SLOT_BOTH,
    MAP_SLOT_BY_ROLE,
    PHASE_INSTRUCTIONS,
    PHASE_QUESTIONNAIRE,
    PHASE_REST,
    PHASE_TURN,
    PHASE_WAITING,
    QUESTIONNAIRE_COMPLETED,
    QUESTIONNAIRE_IN_PROGRESS,
    QUESTIONNAIRE_NOT_STARTED,
    ROLE_PLAYER_1,
    ROOM_ARCHIVED,
    ROOM_FULL,
    ROOM_INSTRUCTIONS,
    ROOM_OPEN,
    ROOM_PLAYING,
    ROOM_QUESTIONNAIRE,
    ROOM_WAITING,
    SELECTION_FORCED,
    SELECTION_MANUAL,
    SELECTION_TIMEOUT,
)
from ..db import session_scope
from ..game.engine import (
    Board,
    initial_board,
    player_without_territory,
    resolve_forced_turn,
    resolve_turn,
    total_soldiers,
    valid_selection,
)
from ..game.trials import generate_trial_plan, seed_from_hex, seed_to_hex, turn_seed
from ..models import (
    Booking,
    GameTrial,
    Payment,
    Room,
    RoomEvent,
    RoomParticipant,
    RoomTimer,
    Turn,
    TurnSubmission,
)
from ..timeutil import isoformat_utc, utcnow
from .events import add_event
from .instructions import render_markdown
from .locking import room_lock
from .participants import new_analysis_code
from .questionnaire_flow import questionnaire_link_for_participant
from .rooms import (
    archive_reason_for_wait_expiry,
    archive_room,
    can_rebook_for_participant,
    get_room_payment,
    lock_config,
    mark_attended,
    participant_reward_kind,
    transition_to_waiting,
)

logger = logging.getLogger(__name__)

RESULT_ANIMATION_MS = 1000


def _default_state() -> dict:
    return {
        "phase": None,
        "start_requests": [],
        "enter_requests": [],
        "instruction": {"accumulated": {}, "connected_since": {}, "saved_at": None},
        "disconnected": {},
        "trial_index": 0,
        "round": 1,
        "submissions": {},
        "turn_deadline": None,
        "turn_paused_remaining": None,
        "turn_generation": 1,
        "recovery_count": 0,
        "rest_ready": {},
        "rest_deadline": None,
        "rest_paused_remaining": None,
        "last_real_selections": {},
        "board": None,
        "num_of_war": 0,
        "trial_started_at": None,
    }


def _state(room: Room) -> dict:
    state = _default_state()
    if room.runtime_state:
        for key, value in room.runtime_state.items():
            if key in state and isinstance(state[key], dict) and isinstance(value, dict):
                merged = state[key]
                merged.update(value)
                state[key] = merged
            else:
                state[key] = value
    return copy.deepcopy(state)


def _save_state(room: Room, state: dict) -> None:
    room.runtime_state = copy.deepcopy(state)


def _board_payload(board) -> dict:
    return {"rows": board.rows, "cols": board.cols, "owners": list(board.owners), "soldiers": list(board.soldiers)}


def _board_from_payload(payload: dict) -> Board:
    return Board(
        rows=payload["rows"],
        cols=payload["cols"],
        owners=tuple(payload["owners"]),
        soldiers=tuple(payload["soldiers"]),
    )


def _role_map(rows) -> dict[int, RoomParticipant]:
    return {row.role: row for row in rows}


def _trial_parameter_payload(params: dict) -> dict:
    return {
        "initialSoldiersA": params["soldiersA"],
        "initialSoldiersB": params["soldiersB"],
        "reinforcementA": params["soldiersA"],
        "reinforcementB": params["soldiersB"],
        "sourceIndex": params["sourceIndex"],
    }


def _role_visuals(map_group: dict, role: int) -> list[dict]:
    if role not in (1, 2):
        raise ValueError("role 必须是 1 或 2")
    slot = MAP_SLOT_BOTH if map_group["mode"] == MAP_MODE_BOTH else MAP_SLOT_BY_ROLE[role]
    selected = next((item for item in map_group["maps"] if item["slot"] == slot), None)
    if selected is None:
        raise RuntimeError("地图组缺少角色对应的地图")
    cells = selected["cells"]
    colors = selected.get("colors") or []
    return [
        {
            "color": colors[index] if index < len(colors) and isinstance(colors[index], str) else None,
            "backgroundAssetId": cell,
        }
        for index, cell in enumerate(cells)
    ]


class RuntimeManager:
    def __init__(self) -> None:
        self.connections: dict[str, dict[str, WebSocket]] = {}
        self.last_activity: dict[str, dict[str, float]] = {}
        self.activity_warned: dict[str, set[str]] = {}
        self.visibility: dict[str, dict[str, bool]] = {}
        self._ticker: asyncio.Task | None = None

    def _touch_activity(self, room_id: str, participant_id: str) -> None:
        self.last_activity.setdefault(room_id, {})[participant_id] = time.monotonic()
        self.activity_warned.setdefault(room_id, set()).discard(participant_id)

    def _set_visibility(self, room_id: str, participant_id: str, visible: bool) -> None:
        self.visibility.setdefault(room_id, {})[participant_id] = visible
        if visible:
            self._touch_activity(room_id, participant_id)

    async def start(self) -> None:
        await self._recover_rooms()
        if self._ticker is None or self._ticker.done():
            self._ticker = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        if self._ticker is not None:
            self._ticker.cancel()
            try:
                await self._ticker
            except asyncio.CancelledError:
                pass
            self._ticker = None

    async def connect(self, participant, websocket: WebSocket) -> str | None:
        await websocket.accept()
        async with session_scope() as db:
            bookings = await db.execute(
                select(Booking)
                .join(Room, Room.id == Booking.room_id)
                .where(
                    Booking.participant_id == participant.id,
                    or_(
                        (Room.status != ROOM_ARCHIVED)
                        & Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED)),
                        (Room.status == ROOM_ARCHIVED) & (Booking.status == BOOKING_ATTENDED),
                    ),
                )
                .order_by(case((Room.status == ROOM_ARCHIVED, 1), else_=0), Room.starts_at.desc())
            )
            booking = bookings.scalars().first()
            if booking is None:
                await self._safe_send(
                    websocket,
                    {"type": "error", "code": "no_active_room", "message": "当前没有可进入的房间"},
                )
                await websocket.close(code=4404)
                return None
            room_id = booking.room_id

        async with room_lock(room_id):
            async with session_scope() as db:
                room = await db.get(Room, room_id)
                if room is None:
                    await self._safe_send(
                        websocket,
                        {"type": "error", "code": "no_active_room", "message": "当前没有可进入的房间"},
                    )
                    await websocket.close(code=4404)
                    return None
                if room.status == ROOM_ARCHIVED:
                    self.connections.setdefault(room_id, {})[participant.id] = websocket
                    await self._send_snapshot(db, room, participant.id)
                    await self._send_json(
                        room.id,
                        participant.id,
                        {"type": "room_archived", "roomId": room.id, **await self._archive_payload(db, room, participant.id)},
                    )
                    return room.id
                old = self.connections.get(room_id, {}).get(participant.id)
                self.connections.setdefault(room_id, {})[participant.id] = websocket
                self._touch_activity(room_id, participant.id)
                self.visibility.setdefault(room_id, {})[participant.id] = True
                if old is not None and old is not websocket:
                    await self._safe_close(old, 4000)
                state = _state(room)
                rows = await self._room_participant_rows(db, room.id)
                role_rows = _role_map(rows)
                now = utcnow()
                reconnected = participant.id in state["disconnected"]
                resumed = False
                if room.status == ROOM_INSTRUCTIONS:
                    state["disconnected"].pop(participant.id, None)
                    incomplete_ids = [
                        row.participant_id
                        for row in rows
                        if row.instruction_completed_at is None
                    ]
                    if all(
                        pid in self.connections.get(room_id, {}) for pid in incomplete_ids
                    ):
                        self._resume_instruction_clocks(state, incomplete_ids, now)
                    await self._persist_instruction_seconds(db, room, role_rows, state)
                elif room.status == ROOM_PLAYING:
                    state["disconnected"].pop(participant.id, None)
                    if self._all_connected(room.id, role_rows):
                        self._resume_game_clock(state, now, room)
                        resumed = True
                if reconnected:
                    add_event(db, room, "reconnect", participant.id, {"phase": state["phase"]})
                _save_state(room, state)
                await db.commit()
                await self._send_snapshot(db, room, participant.id)
                await self._broadcast_partner_state(db, room)
                if resumed and state["phase"] == PHASE_TURN:
                    await self._broadcast_turn(db, room, state)
                elif resumed and state["phase"] == PHASE_REST:
                    await self._broadcast_rest(db, room, state)
                return room.id

    async def disconnect(self, participant, websocket: WebSocket) -> None:
        for room_id, connections in list(self.connections.items()):
            if connections.get(participant.id) is not websocket:
                continue
            async with room_lock(room_id):
                async with session_scope() as db:
                    room = await db.get(Room, room_id)
                    if room is None or room.status == ROOM_ARCHIVED:
                        connections.pop(participant.id, None)
                        return
                    connections.pop(participant.id, None)
                    if not connections:
                        self.connections.pop(room_id, None)
                    state = _state(room)
                    now = utcnow()
                    rows = await self._room_participant_rows(db, room.id)
                    participant_row = next(
                        (row for row in rows if row.participant_id == participant.id), None
                    )
                    payload = {"phase": state["phase"]}
                    if room.status in (ROOM_INSTRUCTIONS, ROOM_PLAYING):
                        if participant_row is not None:
                            payload["role"] = participant_row.role
                        if room.status == ROOM_PLAYING:
                            payload["trialIndex"] = state["trial_index"]
                            payload["round"] = state["round"]
                        due = now + timedelta(seconds=room.reconnect_window_seconds)
                        state["disconnected"][participant.id] = isoformat_utc(due)
                        if room.status == ROOM_INSTRUCTIONS:
                            self._pause_instruction_clocks(state, now)
                        else:
                            self._pause_game_clock(state)
                        add_event(db, room, "disconnect", participant.id, payload)
                    _save_state(room, state)
                    await db.commit()
                    await self._broadcast_partner_state(db, room)
            return
        return

    async def handle(
        self, participant, message: dict, websocket: WebSocket | None = None
    ) -> None:
        message_type = message.get("type")
        if message_type in ("activity", "visibility"):
            room_id = message.get("roomId")
            if not room_id:
                return
            if self.connections.get(room_id, {}).get(participant.id) is not websocket:
                return
            if message_type == "activity":
                self._touch_activity(room_id, participant.id)
            else:
                self._set_visibility(room_id, participant.id, message.get("visible") is True)
            return
        if message_type == "ping":
            room_id = message.get("roomId")
            websocket = None
            if room_id:
                websocket = self.connections.get(room_id, {}).get(participant.id)
            if websocket is None:
                for connections in self.connections.values():
                    websocket = connections.get(participant.id)
                    if websocket is not None:
                        break
            if websocket is not None:
                await self._safe_send(websocket, {"type": "pong", "serverNow": isoformat_utc(utcnow())})
            return
        if message_type not in (
            "enter_room",
            "start_matching",
            "exit_room",
            "instruction_complete",
            "enter_game",
            "submit_selection",
            "rest_ready",
        ):
            await self._send_error(participant.id, None, "unknown_message", "未知消息类型")
            return
        async with session_scope() as db:
            bookings = await db.execute(
                select(Booking)
                .join(Room, Room.id == Booking.room_id)
                .where(
                    Booking.participant_id == participant.id,
                    Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED)),
                    Room.status != ROOM_ARCHIVED,
                )
                .order_by(Room.starts_at.desc())
            )
            booking = bookings.scalars().first()
            if booking is None:
                await self._send_error(participant.id, None, "no_active_room", "当前没有可进入的房间")
                return
            room_id = booking.room_id
        if websocket is not None and self.connections.get(room_id, {}).get(participant.id) is not websocket:
            return
        async with room_lock(room_id):
            async with session_scope() as db:
                room = await db.get(Room, room_id)
                booking = await db.get(Booking, booking.id)
                if room is None or room.status == ROOM_ARCHIVED:
                    await self._send_error(
                        participant.id, room_id, "room_archived", "房间已归档"
                    )
                    return
                requested_room = message.get("roomId")
                if requested_room is not None and requested_room != room.id:
                    await self._send_error(participant.id, room_id, "room_mismatch", "房间不匹配")
                    return
                self._touch_activity(room_id, participant.id)
                if message_type == "enter_room":
                    await self._handle_enter_room(db, room, booking, participant)
                elif message_type == "start_matching":
                    await self._handle_start_matching(db, room, participant)
                elif message_type == "exit_room":
                    await self._handle_exit(db, room, participant)
                elif message_type == "instruction_complete":
                    await self._handle_instruction_complete(db, room, participant)
                elif message_type == "enter_game":
                    await self._handle_enter_game(db, room, participant)
                elif message_type == "submit_selection":
                    await self._handle_submit(db, room, participant, message)
                elif message_type == "rest_ready":
                    await self._handle_rest_ready(db, room, participant)

    async def _handle_enter_room(self, db: AsyncSession, room: Room, booking: Booking, participant) -> None:
        if room.status in (ROOM_OPEN, ROOM_FULL):
            if utcnow() < room.starts_at:
                await self._send_error(participant.id, room.id, "not_started", "实验尚未开始")
                return
            await transition_to_waiting(db, room)
        if room.status in (ROOM_WAITING, ROOM_INSTRUCTIONS, ROOM_PLAYING, ROOM_QUESTIONNAIRE):
            await mark_attended(db, room, booking)
        state = _state(room)
        if room.status == ROOM_WAITING:
            state["phase"] = PHASE_WAITING
            self._ensure_wait_timer(db, room)
        elif room.status == ROOM_INSTRUCTIONS:
            state["phase"] = PHASE_INSTRUCTIONS
        elif room.status == ROOM_PLAYING and state["phase"] is None:
            state["phase"] = PHASE_TURN
        _save_state(room, state)
        await db.commit()
        await self._send_snapshot(db, room, participant.id)
        await self._broadcast_partner_state(db, room)

    async def _handle_start_matching(self, db: AsyncSession, room: Room, participant) -> None:
        await transition_to_waiting(db, room)
        if room.status != ROOM_WAITING:
            await self._send_error(participant.id, room.id, "invalid_state", "当前状态不能开始匹配")
            return
        bookings = await self._active_bookings(db, room.id)
        if len(bookings) != 2:
            add_event(db, room, "partner_absent", participant.id, {"reason": "partner_missing"})
            await db.commit()
            await self._send_error(participant.id, room.id, "partner_missing", "另一名参与者尚未进入实验。")
            return
        if any(booking.status != BOOKING_ATTENDED for booking in bookings):
            add_event(db, room, "partner_absent", participant.id, {"reason": "not_entered"})
            await db.commit()
            await self._send_error(participant.id, room.id, "partner_absent", "另一名参与者尚未进入实验。")
            await self._broadcast_partner_state(db, room)
            return
        participants = [booking.participant_id for booking in bookings]
        if any(pid not in self.connections.get(room.id, {}) for pid in participants):
            add_event(db, room, "partner_absent", participant.id, {"reason": "offline"})
            await db.commit()
            await self._send_error(
                participant.id,
                room.id,
                "partner_absent",
                "另一名参与者当前不在线，请等待其重新连接。",
            )
            await self._broadcast_partner_state(db, room)
            return
        state = _state(room)
        if participant.id not in state["start_requests"]:
            state["start_requests"].append(participant.id)
        add_event(db, room, "start_matching", participant.id)
        if set(state["start_requests"]) >= set(participants):
            await self._assign_roles_and_start_instructions(db, room, state, bookings)
        else:
            _save_state(room, state)
            await db.commit()
            await self._broadcast_partner_state(db, room)

    async def _assign_roles_and_start_instructions(
        self, db: AsyncSession, room: Room, state: dict, bookings: list[Booking]
    ) -> None:
        existing_query = await db.execute(select(RoomParticipant).where(RoomParticipant.room_id == room.id))
        existing = list(existing_query.scalars().all())
        if not existing:
            ordered = sorted(bookings, key=lambda item: item.created_at)
            if secrets.randbelow(2) == 0:
                role_assignment = [(1, ordered[0]), (2, ordered[1])]
            else:
                role_assignment = [(2, ordered[0]), (1, ordered[1])]
            used_codes: set[str] = set()
            for role, booking in role_assignment:
                code = new_analysis_code()
                while code in used_codes:
                    code = new_analysis_code()
                used_codes.add(code)
                row = RoomParticipant(
                    room_id=room.id,
                    participant_id=booking.participant_id,
                    role=role,
                    analysis_code=code,
                    questionnaire_status=QUESTIONNAIRE_NOT_STARTED,
                )
                db.add(row)
                add_event(db, room, "role_assigned", booking.participant_id, {"role": role})
            await db.flush()
        await lock_config(db, room)
        state["phase"] = PHASE_INSTRUCTIONS
        state["start_requests"] = []
        state["instruction"] = {
            "accumulated": {},
            "connected_since": {},
            "saved_at": isoformat_utc(utcnow()),
        }
        state["disconnected"] = {}
        rows = await self._room_participant_rows(db, room.id)
        now = utcnow()
        for row in rows:
            row.instruction_started_at = row.instruction_started_at or now
            state["instruction"]["accumulated"][row.participant_id] = row.instruction_connected_seconds
            if row.participant_id in self.connections.get(room.id, {}):
                state["instruction"]["connected_since"][row.participant_id] = isoformat_utc(now)
            add_event(db, room, "instruction_started", row.participant_id)
        _save_state(room, state)
        await db.commit()
        for row in rows:
            await self._send_snapshot(db, room, row.participant_id)
            await self._send_json(
                room.id,
                row.participant_id,
                {"type": "instruction_state", "roomId": room.id, "instruction": self._instruction_payload(room, state, row, rows)},
            )
        await self._broadcast_partner_state(db, room)

    async def _handle_instruction_complete(self, db: AsyncSession, room: Room, participant) -> None:
        if room.status != ROOM_INSTRUCTIONS:
            await self._send_error(participant.id, room.id, "invalid_state", "当前不在指导语阶段")
            return
        rows = await self._room_participant_rows(db, room.id)
        row = next((item for item in rows if item.participant_id == participant.id), None)
        if row is None:
            await self._send_error(participant.id, room.id, "not_in_room", "你不属于该房间")
            return
        state = _state(room)
        if row.instruction_completed_at is not None:
            _save_state(room, state)
            await db.commit()
            await self._send_snapshot(db, room, participant.id)
            return
        elapsed = self._instruction_elapsed(state, participant.id, utcnow())
        min_seconds = room.config_snapshot["instructions"][f"player{row.role}"]["minReadingSeconds"]
        if elapsed < min_seconds:
            await self._send_error(
                participant.id,
                room.id,
                "reading_incomplete",
                f"请继续阅读，剩余 {max(0, min_seconds - int(elapsed))} 秒",
            )
            return
        row.instruction_completed_at = utcnow()
        row.instruction_connected_seconds = int(elapsed)
        self._accumulate_instruction_seconds(state, participant.id, utcnow())
        state["instruction"]["connected_since"].pop(participant.id, None)
        add_event(db, room, "instruction_completed", participant.id)
        _save_state(room, state)
        await db.commit()
        await self._send_snapshot(db, room, participant.id)
        await self._broadcast_partner_state(db, room)
        for role_row in rows:
            await self._send_json(
                room.id,
                role_row.participant_id,
                {
                    "type": "instruction_state",
                    "roomId": room.id,
                    "instruction": self._instruction_payload(room, state, role_row, rows),
                },
            )

    async def _handle_enter_game(self, db: AsyncSession, room: Room, participant) -> None:
        if room.status != ROOM_INSTRUCTIONS:
            await self._send_error(participant.id, room.id, "invalid_state", "当前不能进入实验")
            return
        rows = await self._room_participant_rows(db, room.id)
        row = next((item for item in rows if item.participant_id == participant.id), None)
        if row is None or row.instruction_completed_at is None:
            await self._send_error(participant.id, room.id, "instruction_incomplete", "请先完成阅读指导语")
            return
        if any(item.instruction_completed_at is None for item in rows):
            await self._send_error(participant.id, room.id, "partner_instruction", "另一名参与者尚未完成指导语")
            return
        state = _state(room)
        if participant.id not in state["enter_requests"]:
            state["enter_requests"].append(participant.id)
        if set(state["enter_requests"]) >= {item.participant_id for item in rows}:
            await self._begin_game(db, room, state)
        else:
            _save_state(room, state)
            await db.commit()
            await self._broadcast_partner_state(db, room)

    async def _handle_exit(self, db: AsyncSession, room: Room, participant) -> None:
        if room.status == ROOM_WAITING:
            bookings = await self._active_bookings(db, room.id)
            if sum(1 for booking in bookings if booking.status == BOOKING_ATTENDED) >= 2:
                await self._send_error(
                    participant.id, room.id, "partner_present", "另一名参与者已到场，不能退出实验"
                )
                return
        elif room.status not in (ROOM_INSTRUCTIONS, ROOM_PLAYING):
            await self._send_error(participant.id, room.id, "invalid_state", "当前状态不能退出")
            return
        add_event(db, room, "participant_exited", participant.id)
        await archive_room(db, room, ARCHIVE_ABANDONED)
        await db.commit()
        await self._notify_archived(db, room)

    async def _handle_submit(self, db: AsyncSession, room: Room, participant, message: dict) -> None:
        if room.status != ROOM_PLAYING:
            await self._send_error(participant.id, room.id, "invalid_state", "当前不在对局中")
            return
        state = _state(room)
        if state["phase"] != PHASE_TURN:
            await self._send_error(participant.id, room.id, "invalid_phase", "当前不在回合阶段")
            return
        if message.get("trialIndex") != state["trial_index"] or message.get("round") != state["round"]:
            await self._send_error(participant.id, room.id, "stale_round", "回合已过期")
            return
        rows = await self._room_participant_rows(db, room.id)
        row = next((item for item in rows if item.participant_id == participant.id), None)
        if row is None:
            await self._send_error(participant.id, room.id, "not_in_room", "你不属于该房间")
            return
        role_key = str(row.role)
        cells = message.get("cells")
        if not isinstance(cells, list):
            await self._send_error(participant.id, room.id, "invalid_selection", "至少选择一个格子")
            return
        try:
            valid_cells = valid_selection(cells, state["board"]["rows"], state["board"]["cols"])
        except ValueError as exc:
            await self._send_error(participant.id, room.id, "invalid_selection", str(exc))
            return
        client_msg_id = str(message.get("clientMsgId") or secrets.token_hex(8))
        existing = state["submissions"].get(role_key)
        if existing is not None:
            if existing.get("clientMsgId") == client_msg_id:
                await self._send_snapshot(db, room, participant.id)
                return
            await self._send_error(participant.id, room.id, "already_submitted", "本回合已提交")
            return
        trial = await self._current_trial(db, room.id, state["trial_index"])
        if trial is None:
            await self._send_error(participant.id, room.id, "invalid_state", "当前 trial 不存在")
            return
        db.add(
            TurnSubmission(
                game_trial_id=trial.id,
                room_participant_id=row.id,
                client_msg_id=client_msg_id,
                round=state["round"],
                cells_json=valid_cells,
                source=SELECTION_MANUAL,
                accepted=True,
            )
        )
        state["submissions"][role_key] = {
            "cells": valid_cells,
            "source": SELECTION_MANUAL,
            "clientMsgId": client_msg_id,
            "at": isoformat_utc(utcnow()),
        }
        _save_state(room, state)
        if len(state["submissions"]) == 2:
            outcome = await self._resolve_current_round(db, room, state)
            _save_state(room, state)
            await db.commit()
            await self._broadcast_resolution(db, room, state, outcome)
        else:
            await db.flush()
            await db.commit()
            await self._broadcast_turn(db, room, state)

    async def _handle_rest_ready(self, db: AsyncSession, room: Room, participant) -> None:
        if room.status != ROOM_PLAYING or _state(room)["phase"] != PHASE_REST:
            await self._send_error(participant.id, room.id, "invalid_state", "当前不在休息阶段")
            return
        rows = await self._room_participant_rows(db, room.id)
        row = next((item for item in rows if item.participant_id == participant.id), None)
        if row is None:
            return
        state = _state(room)
        state["rest_ready"][str(row.role)] = True
        if len(state["rest_ready"]) == 2 and all(state["rest_ready"].values()):
            await self._start_next_trial(db, room, state)
            await db.commit()
            await self._broadcast_trial_start(db, room, state)
        else:
            _save_state(room, state)
            await db.commit()
            await self._broadcast_partner_state(db, room)
            await self._broadcast_rest(db, room, state)

    async def _begin_game(self, db: AsyncSession, room: Room, state: dict) -> None:
        map_group = self._map_group(room)
        seed = secrets.randbits(63)
        plan = generate_trial_plan(
            map_group["profile"]["rows"],
            map_group["practiceTrials"],
            map_group["formalTrials"],
            map_group["randomizeFormal"],
            seed,
        )
        room.trial_plan_json = {
            "seed": seed_to_hex(seed),
            "order": [entry.source_index for entry in plan],
            "generatedAt": isoformat_utc(utcnow()),
        }
        room.status = ROOM_PLAYING
        state["phase"] = PHASE_TURN
        state["trial_index"] = 0
        state["enter_requests"] = []
        now = utcnow()
        connected = set(self.connections.get(room.id, {}))
        state["disconnected"] = {
            participant_id: due
            for participant_id, due in state["disconnected"].items()
            if participant_id not in connected
        }
        for row in await self._room_participant_rows(db, room.id):
            if row.participant_id not in connected and row.participant_id not in state["disconnected"]:
                state["disconnected"][row.participant_id] = isoformat_utc(
                    now + timedelta(seconds=room.reconnect_window_seconds)
                )
        add_event(db, room, "game_started")
        await self._start_next_trial(db, room, state)
        await db.commit()
        await self._broadcast_trial_start(db, room, state, announce_game_start=True)

    async def _start_next_trial(self, db: AsyncSession, room: Room, state: dict) -> None:
        map_group = self._map_group(room)
        order = room.trial_plan_json["order"]
        if state["phase"] == PHASE_REST:
            rows = await self._room_participant_rows(db, room.id)
            for row in rows:
                await self._send_json(
                    room.id,
                    row.participant_id,
                    {
                        "type": "rest_complete",
                        "roomId": room.id,
                        "trialIndex": state["trial_index"],
                        "round": state["round"],
                    },
                )
        trial_index = 0 if state["phase"] != PHASE_REST else state["trial_index"] + 1
        if trial_index >= len(order):
            await self._enter_questionnaire(db, room, state)
            return
        source_index = order[trial_index]
        params = self._trial_params(room, trial_index)
        board = initial_board(
            map_group["rows"],
            map_group["cols"],
            map_group["spawns"]["A"],
            map_group["spawns"]["B"],
            params["soldiersA"],
            params["soldiersB"],
        )
        seed_hex = room.trial_plan_json["seed"]
        trial = GameTrial(
            room_id=room.id,
            trial_index=trial_index,
            game_number=trial_index + 1,
            source_index=source_index,
            is_practice=params["isPractice"],
            formal_trial=params["formalTrial"],
            params_json={
                "soldiersA": params["soldiersA"],
                "soldiersB": params["soldiersB"],
                "sourceIndex": source_index,
            },
            seed=seed_hex,
            initial_state_json=_board_payload(board),
            started_at=utcnow(),
        )
        db.add(trial)
        await db.flush()
        db.add(
            Turn(
                game_trial_id=trial.id,
                round=0,
                turn_seed=None,
                selections_json={"player1": [], "player2": []},
                policy_json={"player1": [], "player2": []},
                board_json=_board_payload(board),
                war_json={"location": []},
                losses_json={"player1": [], "player2": []},
                logistics_json={"player1": 0, "player2": 0},
                num_of_war=0,
                selection_sources_json={"player1": None, "player2": None},
                auto_selected_json={"player1": False, "player2": False},
                forced=False,
            )
        )
        _, turn_seconds = self._trial_settings(room, trial_index)
        state["phase"] = PHASE_TURN
        state["trial_index"] = trial_index
        state["round"] = 1
        state["submissions"] = {}
        self._set_turn_deadline(state, turn_seconds)
        state["turn_generation"] = state.get("turn_generation", 0) + 1
        state["recovery_count"] = 0
        state["rest_deadline"] = None
        state["rest_ready"] = {}
        state["last_real_selections"] = {}
        state["board"] = _board_payload(board)
        state["num_of_war"] = 0
        state["trial_started_at"] = isoformat_utc(utcnow())
        add_event(
            db,
            room,
            "trial_started",
            payload={
                "trialIndex": trial_index,
                "sourceIndex": source_index,
                "isPractice": params["isPractice"],
            },
        )
        if state["turn_deadline"] is not None:
            self._record_timer(db, room, "turn", utcnow() + timedelta(seconds=turn_seconds))
        _save_state(room, state)
        await db.flush()

    async def _resolve_current_round(self, db: AsyncSession, room: Room, state: dict) -> dict:
        map_group = self._map_group(room)
        board = _board_from_payload(state["board"])
        params = self._trial_params(room, state["trial_index"])
        if params is None:
            raise RuntimeError("当前对局计划不存在")
        turn_cap, turn_seconds = self._trial_settings(room, state["trial_index"])
        grids = self._reinforcement_grids(map_group, params)
        submission_a = state["submissions"].get("1")
        submission_b = state["submissions"].get("2")
        if submission_a is None or submission_b is None:
            raise RuntimeError("resolve_current_round 需要双方提交")
        round_number = state["round"]
        trial = await self._current_trial(db, room.id, state["trial_index"])
        seed = turn_seed(
            seed_from_hex(room.trial_plan_json["seed"]),
            state["trial_index"],
            round_number,
            state["recovery_count"],
        )
        resolution = resolve_turn(
            board,
            submission_a["cells"],
            submission_b["cells"],
            seed=seed,
            base_a_index=map_group["spawns"]["A"],
            base_b_index=map_group["spawns"]["B"],
            reinforcement_a=grids[0],
            reinforcement_b=grids[1],
        )
        state["num_of_war"] += len(resolution.war_location)
        db.add(
            Turn(
                game_trial_id=trial.id,
                round=round_number,
                turn_seed=seed_to_hex(seed),
                selections_json={"player1": submission_a["cells"], "player2": submission_b["cells"]},
                policy_json={
                    "player1": list(resolution.soldier_policy_p1),
                    "player2": list(resolution.soldier_policy_p2),
                },
                board_json=_board_payload(resolution.board),
                war_json={"location": list(resolution.war_location)},
                losses_json={
                    "player1": list(resolution.war_lost_p1),
                    "player2": list(resolution.war_lost_p2),
                },
                logistics_json={"player1": resolution.logistics_p1, "player2": resolution.logistics_p2},
                num_of_war=state["num_of_war"],
                selection_sources_json={
                    "player1": submission_a["source"],
                    "player2": submission_b["source"],
                },
                auto_selected_json={
                    "player1": submission_a["source"] == SELECTION_TIMEOUT,
                    "player2": submission_b["source"] == SELECTION_TIMEOUT,
                },
                forced=False,
            )
        )
        add_event(
            db,
            room,
            "turn_resolved",
            payload={"trialIndex": state["trial_index"], "round": round_number},
        )
        state["last_real_selections"] = {
            "player1": submission_a["cells"],
            "player2": submission_b["cells"],
        }
        state["board"] = _board_payload(resolution.board)
        state["submissions"] = {}
        result_animation_ms = RESULT_ANIMATION_MS if resolution.war_location else 0
        result = {
            "round": round_number,
            "selections": {
                "player1": submission_a["cells"],
                "player2": submission_b["cells"],
            },
            "selectionSources": {
                "player1": submission_a["source"],
                "player2": submission_b["source"],
            },
            "autoSelected": {
                "player1": submission_a["source"] == SELECTION_TIMEOUT,
                "player2": submission_b["source"] == SELECTION_TIMEOUT,
            },
            "warLocation": list(resolution.war_location),
            "warLost": {
                "player1": list(resolution.war_lost_p1),
                "player2": list(resolution.war_lost_p2),
            },
            "logistics": {"player1": resolution.logistics_p1, "player2": resolution.logistics_p2},
            "board": _board_payload(resolution.board),
            "trialEnded": False,
            "resultDisplayMs": result_animation_ms,
            **_trial_parameter_payload(params),
        }
        without_territory = player_without_territory(resolution.board)
        if without_territory is not None:
            result["trialEnded"] = True
            await self._finalize_trial(
                db,
                room,
                state,
                final_board=resolution.board,
                winner=3 - without_territory,
                end_reason=END_REASON_ANNIHILATION,
                end_turn=round_number,
                result_animation_ms=result_animation_ms,
            )
        elif round_number >= turn_cap:
            result["trialEnded"] = True
            await self._finalize_trial(
                db,
                room,
                state,
                final_board=resolution.board,
                winner=None,
                end_reason=END_REASON_TURN_LIMIT,
                end_turn=round_number,
                result_animation_ms=result_animation_ms,
            )
        else:
            next_turn_seconds = turn_seconds + result_animation_ms // 1000
            state["round"] = round_number + 1
            self._set_turn_deadline(
                state, next_turn_seconds, paused_seconds=turn_seconds
            )
            state["turn_generation"] += 1
            if state["turn_deadline"] is not None:
                self._record_timer(db, room, "turn", utcnow() + timedelta(seconds=next_turn_seconds))
            result["nextRound"] = state["round"]
            result["deadline"] = state["turn_deadline"]
        _save_state(room, state)
        return result

    async def _finalize_trial(
        self,
        db: AsyncSession,
        room: Room,
        state: dict,
        *,
        final_board,
        winner,
        end_reason: str,
        end_turn: int,
        result_animation_ms: int = 0,
    ) -> None:
        map_group = self._map_group(room)
        params = self._trial_params(room, state["trial_index"])
        if params is None:
            raise RuntimeError("当前对局计划不存在")
        turn_cap, _ = self._trial_settings(room, state["trial_index"])
        grids = self._reinforcement_grids(map_group, params)
        board = final_board
        forced_rounds = 0
        if end_reason == END_REASON_ANNIHILATION:
            for round_number in range(end_turn + 1, turn_cap + 1):
                seed = turn_seed(
                    seed_from_hex(room.trial_plan_json["seed"]),
                    state["trial_index"],
                    round_number,
                    state["recovery_count"],
                )
                resolution = resolve_forced_turn(
                    board,
                    seed=seed,
                    base_a_index=map_group["spawns"]["A"],
                    base_b_index=map_group["spawns"]["B"],
                    reinforcement_a=grids[0],
                    reinforcement_b=grids[1],
                )
                board = resolution.board
                forced_rounds += 1
                state["num_of_war"] += len(resolution.war_location)
                trial = await self._current_trial(db, room.id, state["trial_index"])
                db.add(
                    Turn(
                        game_trial_id=trial.id,
                        round=round_number,
                        turn_seed=seed_to_hex(seed),
                        selections_json=state["last_real_selections"],
                        policy_json={
                            "player1": list(resolution.soldier_policy_p1),
                            "player2": list(resolution.soldier_policy_p2),
                        },
                        board_json=_board_payload(board),
                        war_json={"location": list(resolution.war_location)},
                        losses_json={
                            "player1": list(resolution.war_lost_p1),
                            "player2": list(resolution.war_lost_p2),
                        },
                        logistics_json={
                            "player1": resolution.logistics_p1,
                            "player2": resolution.logistics_p2,
                        },
                        num_of_war=state["num_of_war"],
                        selection_sources_json={"player1": SELECTION_FORCED, "player2": SELECTION_FORCED},
                        auto_selected_json={"player1": False, "player2": False},
                        forced=True,
                    )
                )
        trial = await self._current_trial(db, room.id, state["trial_index"])
        final_soldiers = {
            "player1": total_soldiers(board, 1),
            "player2": total_soldiers(board, 2),
        }
        summary = {
            "winner": winner,
            "endReason": end_reason,
            "endTurn": end_turn,
            "completedRounds": turn_cap,
            "forcedRounds": forced_rounds,
            "finalSoldiers": final_soldiers,
        }
        trial.ended_at = utcnow()
        trial.winner = winner
        trial.end_reason = end_reason
        trial.end_turn = end_turn
        trial.completed_rounds = turn_cap
        trial.forced_rounds = forced_rounds
        trial.summary_json = summary
        state["board"] = _board_payload(board)
        state["phase"] = PHASE_REST
        total_trials = len(room.trial_plan_json["order"])
        if state["trial_index"] + 1 >= total_trials:
            await self._enter_questionnaire(db, room, state)
        else:
            rest_seconds = map_group["restSeconds"] + result_animation_ms // 1000
            self._set_rest_deadline(
                state, rest_seconds, paused_seconds=map_group["restSeconds"]
            )
            state["rest_ready"] = {}
            if state["rest_deadline"] is not None:
                self._record_timer(db, room, "rest", utcnow() + timedelta(seconds=rest_seconds))
        _save_state(room, state)

    async def _enter_questionnaire(self, db: AsyncSession, room: Room, state: dict) -> None:
        room.status = ROOM_QUESTIONNAIRE
        state["phase"] = PHASE_QUESTIONNAIRE
        state["turn_deadline"] = None
        state["rest_deadline"] = None
        rows = await self._room_participant_rows(db, room.id)
        for row in rows:
            if row.questionnaire_status == QUESTIONNAIRE_NOT_STARTED:
                row.questionnaire_status = QUESTIONNAIRE_IN_PROGRESS
                row.questionnaire_started_at = utcnow()
        add_event(db, room, "game_completed")
        _save_state(room, state)
        await db.flush()

    async def _tick_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(0.5)
                async with session_scope() as db:
                    room_ids = list(
                        (
                            await db.execute(
                                select(Room.id).where(
                                    Room.status.in_((ROOM_OPEN, ROOM_FULL, ROOM_WAITING, ROOM_INSTRUCTIONS, ROOM_PLAYING, ROOM_QUESTIONNAIRE))
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                for room_id in room_ids:
                    try:
                        await self._tick_room(room_id)
                    except Exception:
                        logger.exception("room tick failed: %s", room_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("runtime ticker failed")

    async def _tick_room(self, room_id: str) -> None:
        async with room_lock(room_id):
            async with session_scope() as db:
                room = await db.get(Room, room_id)
                if room is None or room.status not in (
                    ROOM_OPEN,
                    ROOM_FULL,
                    ROOM_WAITING,
                    ROOM_INSTRUCTIONS,
                    ROOM_PLAYING,
                    ROOM_QUESTIONNAIRE,
                ):
                    return
                now = utcnow()
                state = _state(room)
                if room.status in (ROOM_OPEN, ROOM_FULL):
                    if now >= room.starts_at:
                        room.status = ROOM_WAITING
                        state["phase"] = PHASE_WAITING
                        self._ensure_wait_timer(db, room)
                        _save_state(room, state)
                        await db.commit()
                        await self._broadcast_snapshots(db, room)
                        await self._broadcast_partner_state(db, room)
                    return
                if room.status == ROOM_WAITING:
                    wait_deadline = room.starts_at + timedelta(seconds=room.wait_window_seconds)
                    if now >= wait_deadline:
                        bookings = await self._room_bookings(db, room.id)
                        reason = archive_reason_for_wait_expiry(bookings)
                        await archive_room(db, room, reason)
                        await db.commit()
                        await self._notify_archived(db, room)
                        return
                    return
                if room.status == ROOM_INSTRUCTIONS:
                    expired = self._expired_disconnections(state, room, now)
                    if expired:
                        await archive_room(db, room, ARCHIVE_TECHNICAL_ABORT)
                        await db.commit()
                        await self._notify_archived(db, room)
                        return
                    if await self._check_inactivity(db, room, state):
                        return
                    rows = await self._room_participant_rows(db, room.id)
                    saved_at = state["instruction"].get("saved_at")
                    if saved_at is None or (
                        now - datetime.fromisoformat(saved_at.replace("Z", "+00:00")).replace(tzinfo=None)
                    ).total_seconds() >= 5:
                        await self._persist_instruction_seconds(db, room, _role_map(rows), state)
                        state["instruction"]["saved_at"] = isoformat_utc(now)
                        _save_state(room, state)
                        await db.commit()
                    return
                if room.status == ROOM_PLAYING:
                    expired = self._expired_disconnections(state, room, now)
                    if expired:
                        await archive_room(db, room, ARCHIVE_TECHNICAL_ABORT)
                        await db.commit()
                        await self._notify_archived(db, room)
                        return
                    if await self._check_inactivity(db, room, state):
                        return
                    if state["phase"] == PHASE_TURN and len(state["submissions"]) == 2:
                        outcome = await self._resolve_current_round(db, room, state)
                        _save_state(room, state)
                        await db.commit()
                        await self._broadcast_resolution(db, room, state, outcome)
                        return
                    if state["phase"] == PHASE_TURN and state["turn_deadline"] is not None:
                        deadline = datetime.fromisoformat(state["turn_deadline"].replace("Z", "+00:00")).replace(tzinfo=None)
                        if now >= deadline:
                            await self._auto_select_missing(db, room, state)
                            outcome = await self._resolve_current_round(db, room, state)
                            _save_state(room, state)
                            await db.commit()
                            await self._broadcast_resolution(db, room, state, outcome)
                        return
                    if state["phase"] == PHASE_REST and state["rest_deadline"] is not None:
                        deadline = datetime.fromisoformat(state["rest_deadline"].replace("Z", "+00:00")).replace(tzinfo=None)
                        if now >= deadline:
                            await self._start_next_trial(db, room, state)
                            await db.commit()
                            if room.status == ROOM_QUESTIONNAIRE:
                                await self._broadcast_questionnaire(db, room, state)
                            else:
                                await self._broadcast_trial_start(db, room, state)
                    return
                return

    async def _auto_select_missing(self, db: AsyncSession, room: Room, state: dict) -> None:
        trial = await self._current_trial(db, room.id, state["trial_index"])
        rows = await self._room_participant_rows(db, room.id)
        board = _board_from_payload(state["board"])
        for row in rows:
            role_key = str(row.role)
            if role_key in state["submissions"]:
                continue
            seed = turn_seed(
                seed_from_hex(room.trial_plan_json["seed"]),
                state["trial_index"],
                state["round"],
                state["recovery_count"],
            ) + row.role * 7919
            candidates = [index for index, owner in enumerate(board.owners) if owner == row.role]
            if not candidates:
                candidates = list(range(len(board.owners)))
            cells = [random.Random(seed).choice(candidates)]
            client_msg_id = f"timeout-{row.role}-{state['round']}-{state['turn_generation']}"
            db.add(
                TurnSubmission(
                    game_trial_id=trial.id,
                    room_participant_id=row.id,
                    client_msg_id=client_msg_id,
                    round=state["round"],
                    cells_json=cells,
                    source=SELECTION_TIMEOUT,
                    accepted=True,
                )
            )
            state["submissions"][role_key] = {
                "cells": cells,
                "source": SELECTION_TIMEOUT,
                "clientMsgId": client_msg_id,
                "at": isoformat_utc(utcnow()),
            }
        _save_state(room, state)
        await db.flush()

    async def _persist_instruction_seconds(
        self, db: AsyncSession, room: Room, role_rows: dict[int, RoomParticipant], state: dict
    ) -> None:
        now = utcnow()
        for row in role_rows.values():
            elapsed = self._instruction_elapsed(state, row.participant_id, now)
            row.instruction_connected_seconds = int(elapsed)

    def _instruction_elapsed(self, state: dict, participant_id: str, now: datetime) -> float:
        accumulated = float(state["instruction"]["accumulated"].get(participant_id, 0))
        since = state["instruction"]["connected_since"].get(participant_id)
        if since:
            started = datetime.fromisoformat(since.replace("Z", "+00:00")).replace(tzinfo=None)
            accumulated += max(0.0, (now - started).total_seconds())
        return accumulated

    def _resume_instruction_clocks(
        self, state: dict, participant_ids: list[str], now: datetime
    ) -> None:
        for participant_id in participant_ids:
            state["instruction"]["connected_since"][participant_id] = isoformat_utc(now)

    def _pause_instruction_clocks(self, state: dict, now: datetime) -> None:
        for participant_id in list(state["instruction"]["connected_since"]):
            self._accumulate_instruction_seconds(state, participant_id, now)

    def _accumulate_instruction_seconds(self, state: dict, participant_id: str, now: datetime) -> None:
        since = state["instruction"]["connected_since"].get(participant_id)
        if since:
            started = datetime.fromisoformat(since.replace("Z", "+00:00")).replace(tzinfo=None)
            accumulated = float(state["instruction"]["accumulated"].get(participant_id, 0))
            state["instruction"]["accumulated"][participant_id] = accumulated + max(
                0.0, (now - started).total_seconds()
            )
        state["instruction"]["connected_since"].pop(participant_id, None)

    def _set_turn_deadline(
        self, state: dict, seconds: int, paused_seconds: int | None = None
    ) -> None:
        if state["disconnected"]:
            state["turn_deadline"] = None
            state["turn_paused_remaining"] = float(
                paused_seconds if paused_seconds is not None else seconds
            )
            return
        state["turn_deadline"] = isoformat_utc(utcnow() + timedelta(seconds=seconds))
        state["turn_paused_remaining"] = None

    def _set_rest_deadline(
        self, state: dict, seconds: int, paused_seconds: int | None = None
    ) -> None:
        if state["disconnected"]:
            state["rest_deadline"] = None
            state["rest_paused_remaining"] = float(
                paused_seconds if paused_seconds is not None else seconds
            )
            return
        state["rest_deadline"] = isoformat_utc(utcnow() + timedelta(seconds=seconds))
        state["rest_paused_remaining"] = None

    def _pause_game_clock(self, state: dict) -> None:
        now = utcnow()
        if state["phase"] == PHASE_TURN and state["turn_deadline"] is not None:
            deadline = datetime.fromisoformat(state["turn_deadline"].replace("Z", "+00:00")).replace(tzinfo=None)
            state["turn_paused_remaining"] = max(1.0, (deadline - now).total_seconds())
            state["turn_deadline"] = None
        elif state["phase"] == PHASE_REST and state["rest_deadline"] is not None:
            deadline = datetime.fromisoformat(state["rest_deadline"].replace("Z", "+00:00")).replace(tzinfo=None)
            state["rest_paused_remaining"] = max(1.0, (deadline - now).total_seconds())
            state["rest_deadline"] = None

    def _resume_game_clock(self, state: dict, now: datetime, room: Room) -> None:
        map_group = room.config_snapshot.get("mapGroup") if room.config_snapshot else None
        if state["phase"] == PHASE_TURN and state["turn_deadline"] is None:
            remaining = state["turn_paused_remaining"]
            if remaining is None:
                if map_group is not None:
                    _, remaining = self._trial_settings(room, state["trial_index"])
                else:
                    remaining = 30
            state["turn_deadline"] = isoformat_utc(now + timedelta(seconds=remaining))
            state["turn_paused_remaining"] = None
        elif state["phase"] == PHASE_REST and state["rest_deadline"] is None:
            remaining = state["rest_paused_remaining"]
            if remaining is None:
                remaining = map_group["restSeconds"] if map_group else 60
            state["rest_deadline"] = isoformat_utc(now + timedelta(seconds=remaining))
            state["rest_paused_remaining"] = None

    async def _recover_rooms(self) -> None:
        async with session_scope() as db:
            rooms = list(
                (
                    await db.execute(
                        select(Room).where(
                            Room.status.in_((ROOM_OPEN, ROOM_FULL, ROOM_WAITING, ROOM_INSTRUCTIONS, ROOM_PLAYING, ROOM_QUESTIONNAIRE))
                        )
                    )
                )
                .scalars()
                .all()
            )
            for room in rooms:
                previous_status = room.status
                add_event(db, room, "server_restart", payload={"previousStatus": previous_status})
                state = _state(room)
                now = utcnow()
                if room.status in (ROOM_OPEN, ROOM_FULL) and now >= room.starts_at:
                    room.status = ROOM_WAITING
                    state["phase"] = PHASE_WAITING
                if room.status == ROOM_WAITING:
                    state["phase"] = PHASE_WAITING
                elif room.status == ROOM_INSTRUCTIONS:
                    state["phase"] = PHASE_INSTRUCTIONS
                    await self._mark_all_disconnected(db, room, state, now)
                elif room.status == ROOM_PLAYING:
                    map_group = room.config_snapshot.get("mapGroup") if room.config_snapshot else None
                    if state["phase"] == PHASE_TURN:
                        turn_seconds = map_group["formalTurnSeconds"] if map_group else 30
                        if map_group is not None:
                            params = self._trial_params(room, state["trial_index"])
                            if params is not None and params["isPractice"]:
                                turn_seconds = map_group["practiceTurnSeconds"]
                        state["turn_paused_remaining"] = turn_seconds
                        state["turn_deadline"] = None
                    elif state["phase"] == PHASE_REST:
                        state["rest_paused_remaining"] = map_group["restSeconds"] if map_group else 60
                        state["rest_deadline"] = None
                    state["turn_generation"] += 1
                    state["recovery_count"] += 1
                    await self._mark_all_disconnected(db, room, state, now)
                elif room.status == ROOM_QUESTIONNAIRE:
                    state["phase"] = PHASE_QUESTIONNAIRE
                _save_state(room, state)
            await db.commit()

    async def _mark_all_disconnected(
        self, db: AsyncSession, room: Room, state: dict, now: datetime
    ) -> None:
        rows = await self._room_participant_rows(db, room.id)
        if room.status == ROOM_INSTRUCTIONS:
            for row in rows:
                accumulated = float(state["instruction"]["accumulated"].get(row.participant_id, 0))
                state["instruction"]["accumulated"][row.participant_id] = max(
                    accumulated, float(row.instruction_connected_seconds)
                )
        state["instruction"]["connected_since"] = {}
        due = isoformat_utc(now + timedelta(seconds=room.reconnect_window_seconds))
        for row in rows:
            state["disconnected"].setdefault(row.participant_id, due)

    async def _room_participant_rows(self, db: AsyncSession, room_id: str) -> list[RoomParticipant]:
        rows = await db.execute(select(RoomParticipant).where(RoomParticipant.room_id == room_id))
        return list(rows.scalars().all())

    async def _active_bookings(self, db: AsyncSession, room_id: str) -> list[Booking]:
        rows = await db.execute(
            select(Booking)
            .where(Booking.room_id == room_id, Booking.status.in_((BOOKING_BOOKED, BOOKING_ATTENDED)))
            .order_by(Booking.created_at)
        )
        return list(rows.scalars().all())

    async def _room_bookings(self, db: AsyncSession, room_id: str) -> list[Booking]:
        rows = await db.execute(select(Booking).where(Booking.room_id == room_id))
        return list(rows.scalars().all())

    async def _current_trial(self, db: AsyncSession, room_id: str, trial_index: int) -> GameTrial | None:
        rows = await db.execute(
            select(GameTrial).where(GameTrial.room_id == room_id, GameTrial.trial_index == trial_index)
        )
        return rows.scalars().first()

    def _map_group(self, room: Room) -> dict:
        snapshot = room.config_snapshot or {}
        map_group = snapshot.get("mapGroup")
        if map_group is None:
            raise RuntimeError("房间缺少地图组配置快照")
        return map_group

    def _trial_params(self, room: Room, trial_index: int) -> dict | None:
        order = room.trial_plan_json["order"] if room.trial_plan_json else []
        if trial_index < 0 or trial_index >= len(order):
            return None
        map_group = self._map_group(room)
        source_index = order[trial_index]
        rows = map_group["profile"]["rows"]
        if source_index < 0 or source_index >= len(rows):
            raise RuntimeError("对局计划的 sourceIndex 超出配置方案范围")
        is_practice = trial_index < map_group["practiceTrials"]
        row = rows[source_index]
        return {
            "sourceIndex": source_index,
            "isPractice": is_practice,
            "formalTrial": 0 if is_practice else trial_index - map_group["practiceTrials"] + 1,
            "soldiersA": int(row["soldiersA"]),
            "soldiersB": int(row["soldiersB"]),
        }

    def _trial_settings(self, room: Room, trial_index: int) -> tuple[int, int]:
        map_group = self._map_group(room)
        params = self._trial_params(room, trial_index)
        if params is not None and params["isPractice"]:
            return map_group["practiceTurnCap"], map_group["practiceTurnSeconds"]
        return map_group["formalTurnCap"], map_group["formalTurnSeconds"]

    def _reinforcement_grids(self, map_group: dict, params: dict) -> tuple[list[int], list[int]]:
        total = map_group["rows"] * map_group["cols"]
        # 当前配置按“每个己方格 + 当前行兵力”结算，双方各自使用统一的增援值。
        return [params["soldiersA"]] * total, [params["soldiersB"]] * total

    def _all_connected(self, room_id: str, role_rows: dict[int, RoomParticipant]) -> bool:
        connections = self.connections.get(room_id, {})
        return all(row.participant_id in connections for row in role_rows.values()) and len(role_rows) == 2

    def _expired_disconnections(self, state: dict, room: Room, now: datetime) -> bool:
        for due in state["disconnected"].values():
            due_at = datetime.fromisoformat(due.replace("Z", "+00:00")).replace(tzinfo=None)
            if due_at <= now:
                return True
        return False

    async def _check_inactivity(
        self, db: AsyncSession, room: Room, state: dict
    ) -> bool:
        if room.status not in (ROOM_INSTRUCTIONS, ROOM_PLAYING):
            return False
        if state["disconnected"]:
            return False
        connections = self.connections.get(room.id, {})
        if len(connections) < 2:
            return False
        settings = get_settings()
        timeout = settings.inactivity_timeout_seconds
        warning_lead = settings.inactivity_warning_seconds
        now = time.monotonic()
        expired: list[tuple[float, str]] = []
        for participant_id in connections:
            if not self.visibility.get(room.id, {}).get(participant_id, True):
                continue
            last = self.last_activity.get(room.id, {}).get(participant_id)
            if last is None:
                self._touch_activity(room.id, participant_id)
                continue
            elapsed = now - last
            if elapsed >= timeout:
                expired.append((elapsed, participant_id))
                continue
            if elapsed >= timeout - warning_lead:
                warned = self.activity_warned.setdefault(room.id, set())
                if participant_id not in warned:
                    warned.add(participant_id)
                    await self._send_json(
                        room.id,
                        participant_id,
                        {
                            "type": "inactivity_warning",
                            "roomId": room.id,
                            "remainingSeconds": max(0, int(timeout - elapsed)),
                        },
                    )
        if not expired:
            return False
        _, participant_id = max(expired)
        add_event(db, room, "participant_exited", participant_id, {"reason": "inactivity"})
        await archive_room(db, room, ARCHIVE_ABANDONED)
        await db.commit()
        await self._notify_archived(db, room)
        return True

    def _ensure_wait_timer(self, db: AsyncSession, room: Room) -> None:
        due = room.starts_at + timedelta(seconds=room.wait_window_seconds)
        self._record_timer(db, room, "wait_window", due)

    def _record_timer(self, db: AsyncSession, room: Room, kind: str, due_at: datetime) -> None:
        db.add(RoomTimer(room_id=room.id, kind=kind, generation=1, due_at=due_at, status="scheduled"))

    def _instruction_payload(
        self, room: Room, state: dict, row: RoomParticipant, rows: list[RoomParticipant]
    ) -> dict:
        snapshot = room.config_snapshot["instructions"][f"player{row.role}"]
        elapsed = self._instruction_elapsed(state, row.participant_id, utcnow())
        partner_row = next((item for item in rows if item.participant_id != row.participant_id), None)
        all_completed = all(item.instruction_completed_at is not None for item in rows)
        return {
            "role": row.role,
            "contentMarkdown": snapshot["contentMarkdown"],
            "contentHtml": render_markdown(snapshot["contentMarkdown"]),
            "minReadingSeconds": snapshot["minReadingSeconds"],
            "connectedSeconds": int(elapsed),
            "completed": row.instruction_completed_at is not None,
            "partnerCompleted": bool(partner_row and partner_row.instruction_completed_at is not None),
            "bothCompleted": all_completed,
            "canEnterGame": all_completed,
            "enterRequested": row.participant_id in state["enter_requests"],
            "bothEnterRequested": set(state["enter_requests"]) >= {item.participant_id for item in rows},
        }

    async def _send_snapshot(self, db: AsyncSession, room: Room, participant_id: str) -> None:
        if participant_id not in self.connections.get(room.id, {}):
            return
        state = _state(room)
        rows = await self._room_participant_rows(db, room.id)
        role_row = next((row for row in rows if row.participant_id == participant_id), None)
        bookings = await self._active_bookings(db, room.id)
        partner_id = None
        if role_row is not None:
            for row in rows:
                if row.participant_id != participant_id:
                    partner_id = row.participant_id
        else:
            for booking in bookings:
                if booking.participant_id != participant_id:
                    partner_id = booking.participant_id
        partner_row = next((row for row in rows if row.participant_id == partner_id), None)
        attended_count = sum(1 for booking in bookings if booking.status == BOOKING_ATTENDED)
        can_exit = (
            room.status == ROOM_WAITING and attended_count < 2
        ) or room.status in (ROOM_INSTRUCTIONS, ROOM_PLAYING)
        partner = {
            "online": bool(partner_id and partner_id in self.connections.get(room.id, {})),
            "entered": bool(
                partner_id
                and any(
                    booking.participant_id == partner_id and booking.status == BOOKING_ATTENDED
                    for booking in bookings
                )
            ),
            "startRequested": bool(partner_id and partner_id in state["start_requests"]),
            "instructionCompleted": bool(partner_row and partner_row.instruction_completed_at is not None),
            "disconnectedUntil": state["disconnected"].get(partner_id) if partner_id else None,
            "submitted": bool(
                partner_row and str(partner_row.role) in state["submissions"]
            ),
            "ready": bool(partner_row and state["rest_ready"].get(str(partner_row.role))),
        }
        payload = {
            "type": "room_state",
            "roomId": room.id,
            "status": room.status,
            "archiveReason": room.archive_reason,
            "serverNow": isoformat_utc(utcnow()),
            "startsAt": isoformat_utc(room.starts_at),
            "waitDeadline": isoformat_utc(room.starts_at + timedelta(seconds=room.wait_window_seconds)),
            "bookedCount": len(bookings),
            "capacity": 2,
            "phase": state["phase"],
            "role": role_row.role if role_row is not None else None,
            "self": {
                "startRequested": participant_id in state["start_requests"],
                "instructionCompleted": bool(role_row and role_row.instruction_completed_at is not None),
                "questionnaireStatus": role_row.questionnaire_status if role_row else None,
                "completedAt": isoformat_utc(role_row.completed_at) if role_row else None,
                "canExit": can_exit,
            },
            "partner": partner,
        }
        if room.status == ROOM_INSTRUCTIONS and role_row is not None:
            payload["instruction"] = self._instruction_payload(room, state, role_row, rows)
        if room.status in (ROOM_PLAYING, ROOM_QUESTIONNAIRE) and room.config_snapshot and role_row is not None:
            payload["game"] = self._game_payload(room, state, role_row)
        if room.status == ROOM_QUESTIONNAIRE and role_row is not None:
            url = await questionnaire_link_for_participant(db, room, role_row)
            payload["questionnaire"] = {
                "url": url,
                "status": role_row.questionnaire_status,
                "submitted": role_row.questionnaire_status == QUESTIONNAIRE_COMPLETED,
            }
        if room.status == ROOM_ARCHIVED:
            archive_payload = await self._archive_payload(db, room, participant_id)
            payload["archive"] = {
                "reason": archive_payload["reason"],
                "canRebook": archive_payload["canRebook"],
                "selfExited": archive_payload["selfExited"],
                "selfAttended": archive_payload["selfAttended"],
                "selfQuestionnaireStatus": archive_payload["selfQuestionnaireStatus"],
                "selfCompleted": archive_payload["selfCompleted"],
                "questionnaireRequired": archive_payload["questionnaireRequired"],
                "showupPayCents": archive_payload["showupPayCents"],
                "rewardKind": archive_payload["rewardKind"],
            }
        await self._send_json(room.id, participant_id, payload)

    def _game_payload(self, room: Room, state: dict, role_row: RoomParticipant) -> dict:
        map_group = self._map_group(room)
        order = room.trial_plan_json["order"] if room.trial_plan_json else []
        trial_index = state["trial_index"]
        params = self._trial_params(room, trial_index)
        turn_cap, turn_seconds = self._trial_settings(room, trial_index)
        payload = {
            "phase": state["phase"],
            "trialIndex": trial_index,
            "gameNumber": trial_index + 1,
            "totalTrials": len(order),
            "practiceTrials": map_group["practiceTrials"],
            "formalTrials": map_group["formalTrials"],
            "isPractice": params["isPractice"] if params else None,
            "formalTrial": params["formalTrial"] if params else None,
            "round": state["round"],
            "turnCount": turn_cap,
            "turnSeconds": turn_seconds,
            "restSeconds": map_group["restSeconds"],
            "board": state["board"],
            "visuals": _role_visuals(map_group, role_row.role),
            "turnDeadline": state["turn_deadline"],
            "restDeadline": state["rest_deadline"],
            "submitted": str(role_row.role) in state["submissions"],
            "restReady": state["rest_ready"],
            "finalSoldiers": self._final_soldiers(state) if state["phase"] == PHASE_REST else None,
        }
        if params is not None:
            payload.update(_trial_parameter_payload(params))
        else:
            payload.update(
                {
                    "initialSoldiersA": None,
                    "initialSoldiersB": None,
                    "reinforcementA": None,
                    "reinforcementB": None,
                    "sourceIndex": None,
                }
            )
        if role_row.role == ROLE_PLAYER_1:
            payload["partnerSubmitted"] = "2" in state["submissions"]
        else:
            payload["partnerSubmitted"] = "1" in state["submissions"]
        return payload

    async def _broadcast_turn(self, db: AsyncSession, room: Room, state: dict) -> None:
        rows = await self._room_participant_rows(db, room.id)
        has_map_group = bool(room.config_snapshot and room.config_snapshot.get("mapGroup"))
        params = self._trial_params(room, state["trial_index"]) if has_map_group else None
        turn_cap = turn_seconds = None
        if has_map_group:
            turn_cap, turn_seconds = self._trial_settings(room, state["trial_index"])
        for row in rows:
            if row.participant_id not in self.connections.get(room.id, {}):
                continue
            other_role = "2" if row.role == 1 else "1"
            payload = {
                "type": "turn",
                "roomId": room.id,
                "trialIndex": state["trial_index"],
                "round": state["round"],
                "turnCount": turn_cap,
                "turnSeconds": turn_seconds,
                "deadline": state["turn_deadline"],
                "board": state["board"],
                "submitted": str(row.role) in state["submissions"],
                "partnerSubmitted": other_role in state["submissions"],
            }
            if params is not None:
                payload.update(_trial_parameter_payload(params))
            await self._send_json(room.id, row.participant_id, payload)

    async def _broadcast_resolution(self, db: AsyncSession, room: Room, state: dict, outcome: dict) -> None:
        rows = await self._room_participant_rows(db, room.id)
        params = self._trial_params(room, state["trial_index"])
        turn_cap, turn_seconds = self._trial_settings(room, state["trial_index"])
        for row in rows:
            if row.participant_id not in self.connections.get(room.id, {}):
                continue
            payload = {
                "type": "turn_result",
                "roomId": room.id,
                "trialIndex": state["trial_index"],
                "round": outcome["round"],
                "selections": outcome["selections"],
                "selectionSources": outcome["selectionSources"],
                "autoSelected": outcome["autoSelected"],
                "warLocation": outcome["warLocation"],
                "warLost": outcome["warLost"],
                "logistics": outcome["logistics"],
                "board": outcome["board"],
                "trialEnded": outcome["trialEnded"],
                "resultDisplayMs": outcome["resultDisplayMs"],
            }
            if params is not None:
                payload.update(_trial_parameter_payload(params))
            if not outcome["trialEnded"]:
                payload["nextRound"] = outcome["nextRound"]
                payload["deadline"] = outcome["deadline"]
            await self._send_json(room.id, row.participant_id, payload)
            if outcome["trialEnded"]:
                await self._send_snapshot(db, room, row.participant_id)
                if room.status == ROOM_QUESTIONNAIRE:
                    await self._send_game_over(db, room, state, row)
                else:
                    payload_rest = {"type": "rest", "roomId": room.id, **self._rest_payload(state, room)}
                    await self._send_json(room.id, row.participant_id, payload_rest)
            else:
                turn_payload = {
                    "type": "turn",
                    "roomId": room.id,
                    "trialIndex": state["trial_index"],
                    "round": state["round"],
                    "turnCount": turn_cap,
                    "turnSeconds": turn_seconds,
                    "deadline": state["turn_deadline"],
                    "board": state["board"],
                    "submitted": False,
                    "partnerSubmitted": False,
                }
                if params is not None:
                    turn_payload.update(_trial_parameter_payload(params))
                await self._send_json(room.id, row.participant_id, turn_payload)

    def _final_soldiers(self, state: dict) -> dict[str, int]:
        board = _board_from_payload(state["board"])
        return {
            "player1": total_soldiers(board, 1),
            "player2": total_soldiers(board, 2),
        }

    def _rest_payload(self, state: dict, room: Room) -> dict:
        map_group = self._map_group(room)
        order = room.trial_plan_json["order"]
        next_index = state["trial_index"] + 1
        next_params = self._trial_params(room, next_index) if next_index < len(order) else None
        completed_params = self._trial_params(room, state["trial_index"])
        if completed_params is None:
            raise RuntimeError("当前对局计划不存在")
        return {
            "trialIndex": state["trial_index"],
            "round": state["round"],
            "completedTrialIndex": state["trial_index"],
            "completedIsPractice": completed_params["isPractice"],
            "completedFormalTrial": completed_params["formalTrial"],
            "nextTrialIndex": next_index if next_params else None,
            "nextIsPractice": next_params["isPractice"] if next_params else None,
            "nextFormalTrial": next_params["formalTrial"] if next_params else None,
            "nextSourceIndex": next_params["sourceIndex"] if next_params else None,
            "restSeconds": map_group["restSeconds"],
            "formalTrials": map_group["formalTrials"],
            "finalSoldiers": self._final_soldiers(state),
            "deadline": state["rest_deadline"],
            "ready": state["rest_ready"],
        }

    async def _broadcast_rest(self, db: AsyncSession, room: Room, state: dict) -> None:
        rows = await self._room_participant_rows(db, room.id)
        payload = {"type": "rest", "roomId": room.id, **self._rest_payload(state, room)}
        for row in rows:
            await self._send_json(room.id, row.participant_id, payload)

    async def _broadcast_trial_start(
        self, db: AsyncSession, room: Room, state: dict, *, announce_game_start: bool = False
    ) -> None:
        rows = await self._room_participant_rows(db, room.id)
        await self._broadcast_snapshots(db, room)
        map_group = self._map_group(room)
        order = room.trial_plan_json["order"]
        trial_index = state["trial_index"]
        params = self._trial_params(room, trial_index)
        if params is None:
            raise RuntimeError("当前对局计划不存在")
        turn_cap, turn_seconds = self._trial_settings(room, trial_index)
        for row in rows:
            if row.participant_id not in self.connections.get(room.id, {}):
                continue
            if announce_game_start:
                await self._send_json(
                    room.id,
                    row.participant_id,
                    {
                        "type": "game_start",
                        "roomId": room.id,
                        "totalTrials": len(order),
                    },
                )
            await self._send_json(
                room.id,
                row.participant_id,
                {
                    "type": "trial_start",
                    "roomId": room.id,
                    "trialIndex": trial_index,
                    "gameNumber": trial_index + 1,
                    "totalTrials": len(order),
                    "practiceTrials": map_group["practiceTrials"],
                    "formalTrials": map_group["formalTrials"],
                    "isPractice": params["isPractice"],
                    "formalTrial": params["formalTrial"],
                    "round": 1,
                    "turnCount": turn_cap,
                    "turnSeconds": turn_seconds,
                    "board": state["board"],
                    "visuals": _role_visuals(map_group, row.role),
                    **_trial_parameter_payload(params),
                },
            )
        await self._broadcast_turn(db, room, state)

    async def _broadcast_questionnaire(self, db: AsyncSession, room: Room, state: dict) -> None:
        rows = await self._room_participant_rows(db, room.id)
        for row in rows:
            await self._send_game_over(db, room, state, row)

    async def _send_game_over(self, db: AsyncSession, room: Room, state: dict, row: RoomParticipant) -> None:
        if row.participant_id not in self.connections.get(room.id, {}):
            return
        url = await questionnaire_link_for_participant(db, room, row)
        payload = {
            "type": "game_over",
            "roomId": room.id,
            "trialsCompleted": len(room.trial_plan_json["order"]) if room.trial_plan_json else 0,
            "questionnaireUrl": url,
        }
        await self._send_json(room.id, row.participant_id, payload)
        await self._send_json(
            room.id,
            row.participant_id,
            {
                "type": "questionnaire_required",
                "roomId": room.id,
                "url": url,
                "status": row.questionnaire_status,
            },
        )

    async def _broadcast_partner_state(self, db: AsyncSession, room: Room) -> None:
        state = _state(room)
        rows = await self._room_participant_rows(db, room.id)
        bookings = await self._active_bookings(db, room.id)
        role_by_pid = {row.participant_id: row for row in rows}
        participant_ids = list(dict.fromkeys([row.participant_id for row in rows] + [b.participant_id for b in bookings]))
        attended_ids = {
            booking.participant_id for booking in bookings if booking.status == BOOKING_ATTENDED
        }
        for participant_id in participant_ids:
            partner_id = next((pid for pid in participant_ids if pid != participant_id), None)
            partner_row = role_by_pid.get(partner_id) if partner_id else None
            await self._send_json(
                room.id,
                participant_id,
                {
                    "type": "partner_state",
                    "roomId": room.id,
                    "partner": {
                        "online": bool(partner_id and partner_id in self.connections.get(room.id, {})),
                        "entered": bool(partner_id in attended_ids),
                        "startRequested": bool(partner_id and partner_id in state["start_requests"]),
                        "instructionCompleted": bool(partner_row and partner_row.instruction_completed_at is not None),
                        "submitted": bool(partner_row and str(partner_row.role) in state["submissions"]),
                        "ready": bool(partner_row and state["rest_ready"].get(str(partner_row.role))),
                        "disconnectedUntil": state["disconnected"].get(partner_id) if partner_id else None,
                    },
                },
            )

    async def _archive_payload(self, db: AsyncSession, room: Room, participant_id: str) -> dict:
        rows = await db.execute(
            select(RoomParticipant).where(
                RoomParticipant.room_id == room.id, RoomParticipant.participant_id == participant_id
            )
        )
        role_row = rows.scalars().first()
        exited_query = await db.execute(
            select(RoomEvent.id)
            .where(
                RoomEvent.room_id == room.id,
                RoomEvent.participant_id == participant_id,
                RoomEvent.type == "participant_exited",
            )
            .limit(1)
        )
        self_exited = exited_query.first() is not None
        booking_query = await db.execute(
            select(Booking).where(
                Booking.room_id == room.id,
                Booking.participant_id == participant_id,
                Booking.status == BOOKING_ATTENDED,
            )
        )
        booking = booking_query.scalars().first()
        if booking is None:
            booking_query = await db.execute(
                select(Booking).where(Booking.room_id == room.id, Booking.participant_id == participant_id)
            )
            booking = booking_query.scalars().first()
        payment_query = await db.execute(
            select(Payment).where(Payment.room_id == room.id, Payment.participant_id == participant_id)
        )
        payment = payment_query.scalars().first()
        self_attended = booking is not None and booking.status == BOOKING_ATTENDED
        showup_pay_cents = 0
        if room.archive_reason == ARCHIVE_TECHNICAL_ABORT and self_attended:
            showup_pay_cents = get_room_payment(room)["showupPayCents"]
        return {
            "reason": room.archive_reason,
            "selfExited": self_exited,
            "selfAttended": self_attended,
            "selfQuestionnaireStatus": role_row.questionnaire_status if role_row else None,
            "selfCompleted": bool(
                role_row is not None and role_row.questionnaire_status == QUESTIONNAIRE_COMPLETED
            ),
            "questionnaireRequired": (
                showup_pay_cents > 0
                and (role_row is None or role_row.questionnaire_status != QUESTIONNAIRE_COMPLETED)
            ),
            "showupPayCents": showup_pay_cents,
            "canRebook": await can_rebook_for_participant(db, room, participant_id),
            "rewardKind": participant_reward_kind(payment),
        }

    async def notify_room(self, room_id: str) -> None:
        async with room_lock(room_id):
            async with session_scope() as db:
                room = await db.get(Room, room_id)
                if room is None:
                    return
                if room.status == ROOM_ARCHIVED:
                    for participant_id in list(self.connections.get(room.id, {}).keys()):
                        await self._send_json(
                            room.id,
                            participant_id,
                            {
                                "type": "room_archived",
                                "roomId": room.id,
                                **await self._archive_payload(db, room, participant_id),
                            },
                        )
                for participant_id in list(self.connections.get(room.id, {}).keys()):
                    await self._send_snapshot(db, room, participant_id)

    async def _notify_archived(self, db: AsyncSession, room: Room) -> None:
        await db.refresh(room)
        for participant_id in list(self.connections.get(room.id, {}).keys()):
            await self._send_json(
                room.id,
                participant_id,
                {
                    "type": "room_archived",
                    "roomId": room.id,
                    **await self._archive_payload(db, room, participant_id),
                },
            )
            await self._send_snapshot(db, room, participant_id)

    async def _broadcast_snapshots(self, db: AsyncSession, room: Room) -> None:
        for participant_id in list(self.connections.get(room.id, {}).keys()):
            await self._send_snapshot(db, room, participant_id)

    async def _send_json(self, room_id: str, participant_id: str, payload: dict) -> None:
        websocket = self.connections.get(room_id, {}).get(participant_id)
        if websocket is None:
            return
        await self._safe_send(websocket, payload)

    async def _safe_send(self, websocket: WebSocket, payload: dict) -> None:
        try:
            await websocket.send_json(payload)
        except (RuntimeError, OSError, WebSocketDisconnect):
            pass

    async def _safe_close(self, websocket: WebSocket, code: int) -> None:
        try:
            await websocket.close(code=code)
        except (RuntimeError, OSError, WebSocketDisconnect):
            pass

    async def _send_error(self, participant_id: str | None, room_id: str | None, code: str, message: str) -> None:
        payload = {"type": "error", "code": code, "message": message}
        if room_id is not None and participant_id is not None:
            await self._send_json(room_id, participant_id, payload)
            return
        if participant_id is None:
            return
        for rid, connections in self.connections.items():
            websocket = connections.get(participant_id)
            if websocket is not None:
                await self._safe_send(websocket, payload)
                return


runtime_manager = RuntimeManager()
