import io
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from app.game.trials import generate_trial_plan

from conftest import (
    ApiClient,
    ServerHandle,
    WsClient,
    create_consent,
    create_instruction,
    create_map_group,
    create_questionnaire,
    create_room,
    create_troop_profile,
    fetch_all,
    fetch_one,
    questionnaire_answers,
    reset_database,
    upload_media,
    valid_identity_answers,
    wait_until,
)

DEFAULT_PLAYERS = (("运行时甲", "13700001001"), ("运行时乙", "13700001002"))
STAY_ROWS = [
    {"soldiersA": 7, "soldiersB": 7},
    {"soldiersA": 8, "soldiersB": 9},
    {"soldiersA": 6, "soldiersB": 5},
]
DUEL_ROWS = [
    {"soldiersA": 1, "soldiersB": 100},
    {"soldiersA": 1, "soldiersB": 100},
]
ANNIHILATION_ROWS = [
    {"soldiersA": 100, "soldiersB": 1},
    {"soldiersA": 100, "soldiersB": 1},
]
SPAWNS_2X2 = {"A": 0, "B": 1}


@dataclass
class RoomSetup:
    room: dict
    map_group: dict
    instruction_1: dict
    instruction_2: dict
    questionnaire: dict
    troop_rows: list[dict]
    rows: int
    cols: int
    spawns: dict


@dataclass
class Game:
    setup: RoomSetup
    ws_a: WsClient
    ws_b: WsClient
    participant_a: ApiClient
    participant_b: ApiClient
    role_a: int
    role_b: int
    state_a: dict
    state_b: dict
    start_a: dict
    start_b: dict
    turn_a: dict
    turn_b: dict

    @property
    def room_id(self) -> str:
        return self.setup.room["id"]


@dataclass
class Journey:
    trials: list[dict]
    state_a: dict
    state_b: dict
    game_over_a: dict
    game_over_b: dict
    required_a: dict
    required_b: dict


class Context:
    def __init__(self, server):
        self.server = server
        self.admin = ApiClient(server.base_url).login_admin()
        self.consent = create_consent(self.admin)
        self.questionnaire = create_questionnaire(self.admin)

    def participants(self, players=DEFAULT_PLAYERS):
        clients = []
        for name, phone in players:
            client = ApiClient(self.server.base_url).login_participant(name, phone)
            client.consent()
            clients.append(client)
        return clients

    def make_room(
        self,
        *,
        troop_rows,
        grid=(3, 3),
        spawns=None,
        mode="both",
        assets=None,
        colors=None,
        practice_cap=3,
        practice_seconds=3,
        formal_cap=3,
        formal_seconds=3,
        rest_seconds=1,
        randomize=True,
        base_pay=4500,
        rate=1,
        performance_floor=0,
        performance_cap=2000,
        showup=1000,
        min_reading=0,
        starts_in=2,
        wait_window=30,
        reconnect_window=5,
        publish=True,
        label=None,
    ) -> RoomSetup:
        rows, cols = grid
        total = rows * cols
        spawn_map = dict(spawns or {"A": 0, "B": total - 1})
        profile = create_troop_profile(self.admin, troop_rows)
        description = f"运行时地图{uuid.uuid4().hex[:6]}"
        map_group = create_map_group(
            self.admin,
            profile["id"],
            mode=mode,
            rows=rows,
            cols=cols,
            formal_trials=len(troop_rows) - 1,
            assets=assets,
            colors=colors,
            spawns=spawn_map,
            description=description,
            practice_turn_cap=practice_cap,
            practice_turn_seconds=practice_seconds,
            formal_turn_cap=formal_cap,
            formal_turn_seconds=formal_seconds,
            rest_seconds=rest_seconds,
            randomize_formal=randomize,
            base_pay_cents=base_pay,
            performance_rate_cents=rate,
            performance_floor_cents=performance_floor,
            performance_cap_cents=performance_cap,
            showup_pay_cents=showup,
        )
        instruction_1 = create_instruction(
            self.admin, map_group["id"], 1, "玩家1指导语", min_seconds=min_reading
        )
        instruction_2 = create_instruction(
            self.admin, map_group["id"], 2, "玩家2指导语", min_seconds=min_reading
        )
        room = create_room(
            self.admin,
            map_group["id"],
            instruction_1["id"],
            instruction_2["id"],
            self.questionnaire["id"],
            starts_in_seconds=starts_in,
            wait_window_seconds=wait_window,
            reconnect_window_seconds=reconnect_window,
            label=label or f"运行时房间-{uuid.uuid4().hex[:6]}",
            publish=publish,
        )
        return RoomSetup(
            room=room,
            map_group=map_group,
            instruction_1=instruction_1,
            instruction_2=instruction_2,
            questionnaire=self.questionnaire,
            troop_rows=list(troop_rows),
            rows=rows,
            cols=cols,
            spawns=spawn_map,
        )


def _me(client: ApiClient) -> dict:
    return client.json("GET", "/api/me")["me"]


def _connect(server, participant: ApiClient):
    socket = WsClient(server, participant.cookie_value("moyo_participant"))
    state = socket.recv_until("room_state")
    assert "enterRequests" not in state
    return socket, state


def _recv_while(ws: WsClient, predicate, description: str, timeout: float = 20, limit: int = 300) -> dict:
    for _ in range(limit):
        message = ws.recv(timeout=timeout)
        if predicate(message):
            return message
    raise AssertionError(f"没有收到{description}")


def _receive_any(ws: WsClient, wanted: set[str], timeout: float = 20) -> dict:
    return _recv_while(ws, lambda message: message.get("type") in wanted, f"消息 {wanted}", timeout=timeout)


def _book(setup: RoomSetup, *clients: ApiClient) -> list[dict]:
    return [
        client.json("POST", f"/api/rooms/{setup.room['id']}/book") for client in clients
    ]


def _wait_can_enter(*clients: ApiClient) -> None:
    def ready():
        return all(
            (client.json("GET", "/api/my-room")["room"] or {}).get("canEnter")
            for client in clients
        )

    wait_until(ready, timeout=20)


def _open_room(server, participant_a: ApiClient, participant_b: ApiClient):
    _wait_can_enter(participant_a, participant_b)
    ws_a, initial_a = _connect(server, participant_a)
    ws_b, initial_b = _connect(server, participant_b)
    ws_a.send("enter_room")
    ws_b.send("enter_room")
    waiting_a = ws_a.recv_until("room_state")
    waiting_b = ws_b.recv_until("room_state")
    return ws_a, ws_b, waiting_a, waiting_b


def _start_instructions(ws_a: WsClient, ws_b: WsClient):
    ws_a.send("start_matching")
    ws_b.send("start_matching")
    state_a = _recv_while(
        ws_a,
        lambda message: message.get("type") == "instruction_state",
        "instruction_state",
    )
    state_b = _recv_while(
        ws_b,
        lambda message: message.get("type") == "instruction_state",
        "instruction_state",
    )
    return state_a["instruction"], state_b["instruction"]


def _wait_instruction_completed(ws: WsClient) -> dict:
    return _recv_while(
        ws,
        lambda message: message.get("type") == "instruction_state"
        and message["instruction"]["completed"],
        "已完成的 instruction_state",
    )


def _complete_instructions(ws_a: WsClient, ws_b: WsClient) -> None:
    ws_a.send("instruction_complete")
    ws_b.send("instruction_complete")
    _wait_instruction_completed(ws_a)
    _wait_instruction_completed(ws_b)


def _playing_state(ws: WsClient) -> dict:
    return _recv_while(
        ws,
        lambda message: message.get("type") == "room_state"
        and message.get("status") == "playing",
        "playing room_state",
    )


def _enter_game_messages(ws_a: WsClient, ws_b: WsClient):
    ws_a.send("enter_game")
    ws_b.send("enter_game")
    state_a = _playing_state(ws_a)
    state_b = _playing_state(ws_b)
    start_a = ws_a.recv_until("trial_start")
    start_b = ws_b.recv_until("trial_start")
    turn_a = ws_a.recv_until("turn")
    turn_b = ws_b.recv_until("turn")
    return state_a, state_b, start_a, start_b, turn_a, turn_b


def _start_game(server, setup: RoomSetup, participant_a: ApiClient, participant_b: ApiClient) -> Game:
    _book(setup, participant_a, participant_b)
    ws_a, ws_b, _waiting_a, _waiting_b = _open_room(server, participant_a, participant_b)
    info_a, info_b = _start_instructions(ws_a, ws_b)
    _complete_instructions(ws_a, ws_b)
    state_a, state_b, start_a, start_b, turn_a, turn_b = _enter_game_messages(ws_a, ws_b)
    return Game(
        setup=setup,
        ws_a=ws_a,
        ws_b=ws_b,
        participant_a=participant_a,
        participant_b=participant_b,
        role_a=info_a["role"],
        role_b=info_b["role"],
        state_a=state_a,
        state_b=state_b,
        start_a=start_a,
        start_b=start_b,
        turn_a=turn_a,
        turn_b=turn_b,
    )


def _owned_cell(board: dict, role: int) -> int:
    owned = [index for index, owner in enumerate(board["owners"]) if owner == role]
    assert owned, f"玩家 {role} 没有领地"
    return owned[0]


def _opponent_cell(board: dict, role: int) -> int:
    targets = [index for index, owner in enumerate(board["owners"]) if owner == 3 - role]
    assert targets, f"玩家 {role} 没有可攻击的对手格子"
    return targets[0]


def _selection(board: dict, role: int, attack: bool) -> list[int]:
    if attack and role == 1:
        return [_opponent_cell(board, role)]
    return [_owned_cell(board, role)]


def _send_selection(ws: WsClient, turn: dict, cells: list[int], tag: str) -> None:
    ws.send(
        "submit_selection",
        roomId=turn["roomId"],
        trialIndex=turn["trialIndex"],
        round=turn["round"],
        cells=cells,
        clientMsgId=f"{tag}-{uuid.uuid4().hex}",
    )


def _submit_round(game: Game, turn_a: dict, turn_b: dict, *, attack=False, tag="round"):
    cells_a = _selection(turn_a["board"], game.role_a, attack)
    cells_b = _selection(turn_b["board"], game.role_b, attack)
    _send_selection(game.ws_a, turn_a, cells_a, f"{tag}-a")
    _send_selection(game.ws_b, turn_b, cells_b, f"{tag}-b")
    result_a = game.ws_a.recv_until("turn_result")
    result_b = game.ws_b.recv_until("turn_result")
    assert result_a["selections"][f"player{game.role_a}"] == sorted(cells_a)
    assert result_b["selections"][f"player{game.role_b}"] == sorted(cells_b)
    return result_a, result_b, cells_a, cells_b


def _receive_rest(ws: WsClient):
    state = _recv_while(
        ws,
        lambda message: message.get("type") == "room_state"
        and message.get("status") == "playing",
        "休息阶段 room_state",
    )
    rest = ws.recv_until("rest")
    return state, rest


def _next_trial(game: Game, rest_a: dict, rest_b: dict):
    expected_index = rest_a["nextTrialIndex"]
    game.ws_a.send("rest_ready")
    game.ws_b.send("rest_ready")

    def next_state(message):
        if message.get("type") != "room_state" or message.get("status") != "playing":
            return False
        game_state = message.get("game") or {}
        return game_state.get("trialIndex") == expected_index and game_state.get("phase") == "turn"

    state_a = _recv_while(game.ws_a, next_state, "下一局 room_state")
    state_b = _recv_while(game.ws_b, next_state, "下一局 room_state")
    start_a = game.ws_a.recv_until("trial_start")
    start_b = game.ws_b.recv_until("trial_start")
    turn_a = game.ws_a.recv_until("turn")
    turn_b = game.ws_b.recv_until("turn")
    return state_a, state_b, start_a, start_b, turn_a, turn_b


def _questionnaire_state(ws: WsClient) -> dict:
    return _recv_while(
        ws,
        lambda message: message.get("type") == "room_state"
        and message.get("status") == "questionnaire",
        "questionnaire room_state",
    )


def _receive_questionnaire_messages(game: Game):
    state_a = _questionnaire_state(game.ws_a)
    state_b = _questionnaire_state(game.ws_b)
    game_over_a = game.ws_a.recv_until("game_over")
    game_over_b = game.ws_b.recv_until("game_over")
    required_a = game.ws_a.recv_until("questionnaire_required")
    required_b = game.ws_b.recv_until("questionnaire_required")
    return state_a, state_b, game_over_a, game_over_b, required_a, required_b


def _play_to_questionnaire(game: Game) -> Journey:
    current = {
        "state_a": game.state_a,
        "state_b": game.state_b,
        "start_a": game.start_a,
        "start_b": game.start_b,
        "turn_a": game.turn_a,
        "turn_b": game.turn_b,
    }
    trials = [current]
    turn_a, turn_b = game.turn_a, game.turn_b
    round_number = 0
    while True:
        round_number += 1
        result_a, result_b, _cells_a, _cells_b = _submit_round(
            game, turn_a, turn_b, tag=f"play-{round_number}"
        )
        current["result_a"] = result_a
        current["result_b"] = result_b
        if result_a["trialEnded"]:
            if result_a["trialIndex"] + 1 >= game.start_a["totalTrials"]:
                state_a, state_b, game_over_a, game_over_b, required_a, required_b = (
                    _receive_questionnaire_messages(game)
                )
                return Journey(
                    trials=trials,
                    state_a=state_a,
                    state_b=state_b,
                    game_over_a=game_over_a,
                    game_over_b=game_over_b,
                    required_a=required_a,
                    required_b=required_b,
                )
            state_a, rest_a = _receive_rest(game.ws_a)
            state_b, rest_b = _receive_rest(game.ws_b)
            game.state_a, game.state_b = state_a, state_b
            (
                game.state_a,
                game.state_b,
                game.start_a,
                game.start_b,
                game.turn_a,
                game.turn_b,
            ) = _next_trial(game, rest_a, rest_b)
            turn_a, turn_b = game.turn_a, game.turn_b
            current = {
                "state_a": game.state_a,
                "state_b": game.state_b,
                "start_a": game.start_a,
                "start_b": game.start_b,
                "turn_a": game.turn_a,
                "turn_b": game.turn_b,
            }
            trials.append(current)
        else:
            turn_a = game.ws_a.recv_until("turn")
            turn_b = game.ws_b.recv_until("turn")
            game.turn_a, game.turn_b = turn_a, turn_b


def _questionnaire_token(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    token = query.get("rt", [None])[0]
    assert token, f"问卷地址缺少 token: {url}"
    return token


def _complete_questionnaire(
    server,
    token: str,
    identity: dict,
    document_type: str = "id_card",
    *,
    q1: str = "female",
    q2: str = "实验完成",
) -> dict:
    client = ApiClient(server.base_url)
    payload = client.json(
        "POST",
        "/api/jatos/questionnaire/complete",
        json={
            "token": token,
            "answers": questionnaire_answers(
                identity, document_type=document_type, q1=q1, q2=q2
            ),
            "jatosWorkerId": f"worker-{uuid.uuid4().hex[:8]}",
            "jatosStudyResultId": f"study-{uuid.uuid4().hex[:8]}",
            "jatosComponentResultId": f"component-{uuid.uuid4().hex[:8]}",
        },
    )
    client.close()
    return payload


def _seconds_until(value: str) -> float:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (moment - datetime.now(timezone.utc)).total_seconds()


def _monitor(admin: ApiClient, room_id: str) -> dict:
    return admin.json("GET", f"/admin/api/rooms/{room_id}/monitor")


def _assert_trial_parameters(payload: dict, row: dict, source_index: int) -> None:
    assert payload["initialSoldiersA"] == row["soldiersA"]
    assert payload["initialSoldiersB"] == row["soldiersB"]
    assert payload["reinforcementA"] == row["soldiersA"]
    assert payload["reinforcementB"] == row["soldiersB"]
    assert payload["sourceIndex"] == source_index


def _assert_initial_board(board: dict, row: dict, spawns: dict) -> None:
    assert board["owners"][spawns["A"]] == 1
    assert board["soldiers"][spawns["A"]] == row["soldiersA"]
    assert board["owners"][spawns["B"]] == 2
    assert board["soldiers"][spawns["B"]] == row["soldiersB"]
    assert board["owners"].count(1) == 1
    assert board["owners"].count(2) == 1


def _png_bytes(color) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _webp_bytes(color) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buffer, format="WEBP")
    return buffer.getvalue()


def _json_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def _game_trials(room_id: str) -> list[dict]:
    return fetch_all(
        "SELECT * FROM game_trials WHERE room_id = %s ORDER BY trial_index", (room_id,)
    )


def test_practice_and_formal_turn_settings(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=2,
        practice_seconds=2,
        formal_cap=2,
        formal_seconds=1,
        rest_seconds=1,
    )
    game = _start_game(server, setup, participant_a, participant_b)

    assert game.start_a["isPractice"] is True
    assert game.start_a["trialIndex"] == 0
    assert game.start_a["gameNumber"] == 1
    assert game.start_a["formalTrial"] == 0
    assert game.start_a["practiceTrials"] == 1
    assert game.start_a["formalTrials"] == 2
    assert game.start_a["totalTrials"] == 3
    assert game.start_a["turnCount"] == 2
    assert game.start_a["turnSeconds"] == 2
    assert game.start_a["round"] == 1
    _assert_trial_parameters(game.start_a, STAY_ROWS[0], 0)
    _assert_initial_board(game.start_a["board"], STAY_ROWS[0], SPAWNS_2X2)
    assert game.state_a["game"]["phase"] == "turn"
    assert game.state_a["game"]["isPractice"] is True
    assert game.state_a["game"]["turnCount"] == 2
    assert game.state_a["game"]["turnSeconds"] == 2
    _assert_trial_parameters(game.state_a["game"], STAY_ROWS[0], 0)
    assert game.turn_a["round"] == 1
    assert game.turn_a["turnCount"] == 2
    assert game.turn_a["turnSeconds"] == 2
    _assert_trial_parameters(game.turn_a, STAY_ROWS[0], 0)
    assert 1.5 <= _seconds_until(game.turn_a["deadline"]) <= 2.6

    result_a, result_b, _cells_a, _cells_b = _submit_round(
        game, game.turn_a, game.turn_b, tag="practice-1"
    )
    assert result_a["round"] == 1
    assert result_a["trialEnded"] is False
    assert result_a["resultDisplayMs"] == 0
    assert result_a["nextRound"] == 2
    _assert_trial_parameters(result_a, STAY_ROWS[0], 0)
    assert 1.5 <= _seconds_until(result_a["deadline"]) <= 2.6
    assert result_b["nextRound"] == 2
    turn_a = game.ws_a.recv_until("turn")
    turn_b = game.ws_b.recv_until("turn")
    assert turn_a["round"] == 2
    assert turn_a["turnSeconds"] == 2

    result_a, result_b, _cells_a, _cells_b = _submit_round(
        game, turn_a, turn_b, tag="practice-2"
    )
    assert result_a["trialEnded"] is True
    assert result_a["trialIndex"] == 0
    _assert_trial_parameters(result_a, STAY_ROWS[0], 0)
    state_a, rest_a = _receive_rest(game.ws_a)
    state_b, rest_b = _receive_rest(game.ws_b)
    assert state_a["game"]["phase"] == "rest"
    assert state_a["game"]["finalSoldiers"]["player1"] > STAY_ROWS[0]["soldiersA"]
    _assert_trial_parameters(state_a["game"], STAY_ROWS[0], 0)
    assert rest_a["completedTrialIndex"] == 0
    assert rest_a["completedIsPractice"] is True
    assert rest_a["completedFormalTrial"] == 0
    assert rest_a["nextTrialIndex"] == 1
    assert rest_a["nextIsPractice"] is False
    assert rest_a["nextFormalTrial"] == 1
    assert rest_a["nextSourceIndex"] in (1, 2)
    assert 0.5 <= _seconds_until(rest_a["deadline"]) <= 1.6

    (
        state_1_a,
        _state_1_b,
        start_1_a,
        start_1_b,
        turn_1_a,
        _turn_1_b,
    ) = _next_trial(game, rest_a, rest_b)
    assert start_1_a["trialIndex"] == 1
    assert start_1_a["isPractice"] is False
    assert start_1_a["formalTrial"] == 1
    assert start_1_a["turnCount"] == 2
    assert start_1_a["turnSeconds"] == 1
    assert start_1_a["sourceIndex"] in (1, 2)
    assert start_1_a["sourceIndex"] == rest_a["nextSourceIndex"]
    source_row = STAY_ROWS[start_1_a["sourceIndex"]]
    _assert_trial_parameters(start_1_a, source_row, start_1_a["sourceIndex"])
    _assert_trial_parameters(state_1_a["game"], source_row, start_1_a["sourceIndex"])
    _assert_trial_parameters(turn_1_a, source_row, start_1_a["sourceIndex"])
    _assert_initial_board(start_1_a["board"], source_row, SPAWNS_2X2)
    assert 0.5 <= _seconds_until(turn_1_a["deadline"]) <= 1.6
    assert start_1_b["trialIndex"] == 1

    trials = [
        trial
        for trial in _game_trials(setup.room["id"])
        if trial["trial_index"] == 0
    ]
    assert len(trials) == 1
    assert bool(trials[0]["is_practice"]) is True
    assert trials[0]["completed_rounds"] == 2
    assert trials[0]["forced_rounds"] == 0
    assert trials[0]["end_reason"] == "turn_limit"
    assert trials[0]["end_turn"] == 2


def test_dual_submit_flags_and_animation_deadline(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=DUEL_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=3,
        practice_seconds=1,
        formal_cap=1,
        formal_seconds=1,
        rest_seconds=1,
    )
    game = _start_game(server, setup, participant_a, participant_b)

    cells_a = _selection(game.turn_a["board"], game.role_a, False)
    _send_selection(game.ws_a, game.turn_a, cells_a, "partial")
    ack_a = game.ws_a.recv_until("turn")
    ack_b = game.ws_b.recv_until("turn")
    assert ack_a["submitted"] is True
    assert ack_a["partnerSubmitted"] is False
    assert ack_b["submitted"] is False
    assert ack_b["partnerSubmitted"] is True
    assert ack_a["round"] == 1

    cells_b = _selection(ack_b["board"], game.role_b, False)
    _send_selection(game.ws_b, ack_b, cells_b, "partial-partner")
    result_a = game.ws_a.recv_until("turn_result")
    result_b = game.ws_b.recv_until("turn_result")
    assert result_a["warLocation"] == []
    assert result_a["resultDisplayMs"] == 0
    assert result_a["nextRound"] == 2
    assert 0.5 <= _seconds_until(result_a["deadline"]) <= 1.6
    assert result_a["selections"][f"player{game.role_a}"] == sorted(cells_a)
    assert result_b["selections"][f"player{game.role_b}"] == sorted(cells_b)

    turn_a = game.ws_a.recv_until("turn")
    turn_b = game.ws_b.recv_until("turn")
    assert turn_a["round"] == 2

    result_a, result_b, _cells_a, _cells_b = _submit_round(
        game, turn_a, turn_b, attack=True, tag="duel-war"
    )
    assert result_a["warLocation"] == [SPAWNS_2X2["B"]]
    assert result_a["resultDisplayMs"] == 1000
    assert result_a["trialEnded"] is False
    assert result_a["nextRound"] == 3
    assert 1.5 <= _seconds_until(result_a["deadline"]) <= 2.6
    assert result_b["resultDisplayMs"] == 1000

    turn_a = game.ws_a.recv_until("turn")
    turn_b = game.ws_b.recv_until("turn")
    result_a, result_b, _cells_a, _cells_b = _submit_round(
        game, turn_a, turn_b, attack=True, tag="duel-final"
    )
    assert result_a["trialEnded"] is True
    assert result_a["resultDisplayMs"] == 1000
    state_a, rest_a = _receive_rest(game.ws_a)
    state_b, rest_b = _receive_rest(game.ws_b)
    assert state_a["game"]["phase"] == "rest"
    assert rest_a["nextTrialIndex"] == 1
    assert 1.5 <= _seconds_until(rest_a["deadline"]) <= 2.6

    trials = _game_trials(setup.room["id"])
    assert len(trials) == 1
    assert trials[0]["completed_rounds"] == 3
    assert trials[0]["forced_rounds"] == 0
    assert trials[0]["end_reason"] == "turn_limit"
    turns = fetch_all(
        "SELECT * FROM turns WHERE game_trial_id = %s AND round > 0 ORDER BY round",
        (trials[0]["id"],),
    )
    assert [turn["round"] for turn in turns] == [1, 2, 3]


def test_timeout_auto_selects_and_resolves(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=2,
        practice_seconds=1,
        formal_cap=1,
        formal_seconds=1,
        rest_seconds=1,
    )
    game = _start_game(server, setup, participant_a, participant_b)

    result_a = game.ws_a.recv_until("turn_result", timeout=10)
    result_b = game.ws_b.recv_until("turn_result", timeout=10)
    assert result_a["round"] == 1
    assert result_a["autoSelected"] == {"player1": True, "player2": True}
    assert result_a["selectionSources"] == {"player1": "timeout", "player2": "timeout"}
    assert result_a["selections"]["player1"] == [SPAWNS_2X2["A"]]
    assert result_a["selections"]["player2"] == [SPAWNS_2X2["B"]]
    assert result_a["warLocation"] == []
    assert result_a["resultDisplayMs"] == 0
    assert result_a["nextRound"] == 2
    assert _seconds_until(result_a["deadline"]) <= 1.6
    assert result_b["round"] == 1

    turn_a = game.ws_a.recv_until("turn")
    turn_b = game.ws_b.recv_until("turn")
    assert turn_a["round"] == 2
    assert turn_b["round"] == 2

    result_a = game.ws_a.recv_until("turn_result", timeout=10)
    result_b = game.ws_b.recv_until("turn_result", timeout=10)
    assert result_a["round"] == 2
    assert result_a["trialEnded"] is True
    assert result_a["autoSelected"] == {"player1": True, "player2": True}
    assert result_a["selectionSources"] == {"player1": "timeout", "player2": "timeout"}
    state_a, rest_a = _receive_rest(game.ws_a)
    state_b, rest_b = _receive_rest(game.ws_b)
    assert state_a["game"]["phase"] == "rest"
    assert rest_a["nextTrialIndex"] == 1

    submissions = fetch_all(
        "SELECT round, source, COUNT(*) AS count FROM turn_submissions "
        "WHERE game_trial_id IN (SELECT id FROM game_trials WHERE room_id = %s) "
        "GROUP BY round, source ORDER BY round",
        (setup.room["id"],),
    )
    assert [(row["round"], row["source"], row["count"]) for row in submissions] == [
        (1, "timeout", 2),
        (2, "timeout", 2),
    ]


def test_annihilation_forces_rounds_in_practice_and_formal(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=ANNIHILATION_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=3,
        practice_seconds=2,
        formal_cap=3,
        formal_seconds=2,
        rest_seconds=1,
    )
    game = _start_game(server, setup, participant_a, participant_b)

    result_a, result_b, _cells_a, _cells_b = _submit_round(
        game, game.turn_a, game.turn_b, attack=True, tag="practice-annihilation"
    )
    assert result_a["trialEnded"] is True
    assert result_b["trialEnded"] is True
    assert result_a["warLocation"] == [SPAWNS_2X2["B"]]
    assert result_a["resultDisplayMs"] == 1000
    assert result_a["round"] == 1
    state_a, rest_a = _receive_rest(game.ws_a)
    state_b, rest_b = _receive_rest(game.ws_b)
    assert rest_a["finalSoldiers"]["player2"] == 0
    assert rest_a["completedIsPractice"] is True
    assert rest_a["nextTrialIndex"] == 1
    assert rest_a["nextFormalTrial"] == 1
    assert state_a["game"]["finalSoldiers"]["player2"] == 0

    practice_trial = fetch_one(
        "SELECT * FROM game_trials WHERE room_id = %s AND trial_index = 0",
        (setup.room["id"],),
    )
    assert practice_trial["completed_rounds"] == 3
    assert practice_trial["forced_rounds"] == 2
    assert practice_trial["end_reason"] == "annihilation"
    assert practice_trial["end_turn"] == 1
    assert practice_trial["winner"] == 1
    summary = _json_value(practice_trial["summary_json"])
    assert summary["completedRounds"] == 3
    assert summary["forcedRounds"] == 2
    assert summary["finalSoldiers"]["player2"] == 0
    practice_turns = fetch_all(
        "SELECT * FROM turns WHERE game_trial_id = %s AND round > 0 ORDER BY round",
        (practice_trial["id"],),
    )
    assert [turn["round"] for turn in practice_turns] == [1, 2, 3]
    assert [bool(turn["forced"]) for turn in practice_turns] == [False, True, True]

    (
        _state_a,
        _state_b,
        start_a,
        start_b,
        turn_a,
        turn_b,
    ) = _next_trial(game, rest_a, rest_b)
    assert start_a["trialIndex"] == 1
    assert start_a["isPractice"] is False
    assert start_a["formalTrial"] == 1
    _assert_trial_parameters(start_a, ANNIHILATION_ROWS[1], 1)

    result_a, result_b, _cells_a, _cells_b = _submit_round(
        game, turn_a, turn_b, attack=True, tag="formal-annihilation"
    )
    assert result_a["trialEnded"] is True
    assert result_a["warLocation"] == [SPAWNS_2X2["B"]]
    state_a, state_b, _game_over_a, _game_over_b, required_a, required_b = (
        _receive_questionnaire_messages(game)
    )
    assert state_a["status"] == "questionnaire"
    assert state_a["game"]["phase"] == "questionnaire"
    assert urlparse(required_a["url"]).path == urlparse(state_a["questionnaire"]["url"]).path
    assert urlparse(required_b["url"]).path == urlparse(state_b["questionnaire"]["url"]).path
    assert _questionnaire_token(required_a["url"])
    assert _questionnaire_token(required_b["url"])

    formal_trial = fetch_one(
        "SELECT * FROM game_trials WHERE room_id = %s AND trial_index = 1",
        (setup.room["id"],),
    )
    assert formal_trial["completed_rounds"] == 3
    assert formal_trial["forced_rounds"] == 2
    assert formal_trial["end_reason"] == "annihilation"
    assert formal_trial["end_turn"] == 1
    assert formal_trial["winner"] == 1
    room = fetch_one("SELECT * FROM rooms WHERE id = %s", (setup.room["id"],))
    assert room["status"] == "questionnaire"


def test_rest_ready_immediate_and_timeout_auto_start(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=1,
        practice_seconds=1,
        formal_cap=1,
        formal_seconds=1,
        rest_seconds=3,
    )
    game = _start_game(server, setup, participant_a, participant_b)

    _result_a, _result_b, _cells_a, _cells_b = _submit_round(
        game, game.turn_a, game.turn_b, tag="rest-ready"
    )
    _state_a, rest_a = _receive_rest(game.ws_a)
    _state_b, rest_b = _receive_rest(game.ws_b)
    assert rest_a["nextTrialIndex"] == 1

    started = time.monotonic()
    game.ws_a.send("rest_ready")
    game.ws_b.send("rest_ready")
    start_a = game.ws_a.recv_until("trial_start")
    start_b = game.ws_b.recv_until("trial_start")
    elapsed = time.monotonic() - started
    assert elapsed < 2.0
    assert start_a["trialIndex"] == 1
    assert start_b["trialIndex"] == 1
    turn_a = game.ws_a.recv_until("turn")
    turn_b = game.ws_b.recv_until("turn")

    _result_a, _result_b, _cells_a, _cells_b = _submit_round(
        game, turn_a, turn_b, tag="rest-timeout"
    )
    _state_a, rest_a = _receive_rest(game.ws_a)
    _state_b, rest_b = _receive_rest(game.ws_b)
    assert rest_a["nextTrialIndex"] == 2
    received_at = time.monotonic()
    start_a = game.ws_a.recv_until("trial_start", timeout=10)
    start_b = game.ws_b.recv_until("trial_start", timeout=10)
    elapsed = time.monotonic() - received_at
    assert elapsed >= 2.5
    assert start_a["trialIndex"] == 2
    assert start_b["trialIndex"] == 2
    game.ws_a.recv_until("turn")
    game.ws_b.recv_until("turn")


def test_rest_pause_and_resume_on_disconnect(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=1,
        practice_seconds=1,
        formal_cap=1,
        formal_seconds=1,
        rest_seconds=8,
        reconnect_window=20,
    )
    game = _start_game(server, setup, participant_a, participant_b)

    _result_a, _result_b, _cells_a, _cells_b = _submit_round(
        game, game.turn_a, game.turn_b, tag="rest-pause"
    )
    _state_a, rest_a = _receive_rest(game.ws_a)
    _state_b, rest_b = _receive_rest(game.ws_b)
    assert rest_b["nextTrialIndex"] == 1
    remaining_before = _seconds_until(rest_a["deadline"])
    assert remaining_before > 6.5

    game.ws_b.close()
    wait_until(
        lambda: _monitor(context.admin, setup.room["id"])["restDeadline"] is None,
        timeout=10,
    )
    time.sleep(2.5)
    monitor = _monitor(context.admin, setup.room["id"])
    assert monitor["phase"] == "rest"
    assert monitor["trialIndex"] == 0
    assert monitor["restDeadline"] is None
    assert monitor["room"]["status"] == "playing"

    ws_b, snapshot_b = _connect(server, participant_b)
    game.ws_b = ws_b
    assert snapshot_b["game"]["phase"] == "rest"
    assert snapshot_b["game"]["restDeadline"] is not None
    rest_a = game.ws_a.recv_until("rest")
    rest_b = ws_b.recv_until("rest")
    assert rest_a["deadline"] == rest_b["deadline"]
    assert _seconds_until(rest_a["deadline"]) > 6.0
    assert rest_a["ready"] == {}

    (
        _state_a,
        _state_b,
        start_a,
        start_b,
        _turn_a,
        _turn_b,
    ) = _next_trial(game, rest_a, rest_b)
    assert start_a["trialIndex"] == 1
    assert start_b["trialIndex"] == 1


def test_turn_pause_survives_beyond_original_deadline(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=2,
        practice_seconds=4,
        formal_cap=2,
        formal_seconds=4,
        rest_seconds=1,
        reconnect_window=20,
    )
    game = _start_game(server, setup, participant_a, participant_b)
    assert _seconds_until(game.turn_a["deadline"]) <= 4.2

    game.ws_b.close()
    wait_until(
        lambda: _monitor(context.admin, setup.room["id"])["turnDeadline"] is None,
        timeout=10,
    )
    time.sleep(5.0)
    monitor = _monitor(context.admin, setup.room["id"])
    assert monitor["phase"] == "turn"
    assert monitor["round"] == 1
    assert monitor["turnDeadline"] is None
    assert monitor["room"]["status"] == "playing"
    assert len(monitor["trials"]) == 1
    assert monitor["trials"][0]["endedAt"] is None

    ws_b, snapshot_b = _connect(server, participant_b)
    game.ws_b = ws_b
    assert snapshot_b["game"]["phase"] == "turn"
    assert snapshot_b["game"]["round"] == 1
    assert snapshot_b["game"]["turnDeadline"] is not None
    resumed_a = game.ws_a.recv_until("turn")
    resumed_b = ws_b.recv_until("turn")
    assert resumed_a["deadline"] == resumed_b["deadline"]
    assert 2.5 <= _seconds_until(resumed_a["deadline"]) <= 4.6

    result_a, result_b, _cells_a, _cells_b = _submit_round(
        game, resumed_a, resumed_b, tag="resumed-round"
    )
    assert result_a["round"] == 1
    assert result_a["trialEnded"] is False
    assert result_a["nextRound"] == 2
    assert 3.5 <= _seconds_until(result_a["deadline"]) <= 4.6
    game.ws_a.recv_until("turn")
    game.ws_b.recv_until("turn")


def test_instruction_pause_on_disconnect_and_resume(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        min_reading=4,
        reconnect_window=20,
    )
    _book(setup, participant_a, participant_b)
    ws_a, ws_b, waiting_a, waiting_b = _open_room(server, participant_a, participant_b)
    assert waiting_a["status"] == "waiting"
    assert waiting_b["status"] == "waiting"
    info_a, info_b = _start_instructions(ws_a, ws_b)
    assert info_a["role"] in (1, 2)
    assert info_b["role"] == 3 - info_a["role"]
    assert info_a["minReadingSeconds"] == 4

    ws_b.close()
    wait_until(
        lambda: any(
            participant["disconnectedUntil"] is not None
            for participant in _monitor(context.admin, setup.room["id"])["participants"]
        ),
        timeout=10,
    )
    time.sleep(4.5)
    ws_a.send("instruction_complete")
    error = _recv_while(
        ws_a, lambda message: message.get("type") == "error", "指导语错误"
    )
    assert error["code"] == "reading_incomplete"
    assert "剩余" in error["message"]

    ws_b, snapshot_b = _connect(server, participant_b)
    assert snapshot_b["status"] == "instructions"
    assert snapshot_b["role"] == info_b["role"]
    assert snapshot_b["instruction"]["completed"] is False
    time.sleep(4.5)

    ws_a.send("instruction_complete")
    _wait_instruction_completed(ws_a)
    ws_b.send("instruction_complete")
    _wait_instruction_completed(ws_b)
    state_a, state_b, start_a, start_b, turn_a, turn_b = _enter_game_messages(ws_a, ws_b)
    assert state_a["status"] == "playing"
    assert state_b["status"] == "playing"
    assert start_a["isPractice"] is True
    assert turn_a["round"] == 1
    assert turn_b["round"] == 1


def test_technical_abort_payment_attended_only(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=1,
        practice_seconds=3,
        showup=500,
        reconnect_window=1,
    )
    game = _start_game(server, setup, participant_a, participant_b)
    participant_a_id = _me(participant_a)["id"]
    participant_b_id = _me(participant_b)["id"]

    context.admin.json(
        "POST",
        f"/admin/api/rooms/{setup.room['id']}/actions",
        json={"action": "mark_absent", "participantId": participant_b_id},
    )
    game.ws_b.close()
    archived = game.ws_a.recv_until("room_archived", timeout=15)
    assert archived["reason"] == "technical_abort"
    assert archived["rewardKind"] == "none"
    assert archived["canRebook"] is False
    assert archived["questionnaireRequired"] is True
    assert archived["showupPayCents"] == 500
    assert _me(participant_a)["hasShowupQuestionnaire"] is True
    assert _me(participant_a)["hasPayment"] is False
    assert _me(participant_a)["canBook"] is False
    assert _me(participant_b)["hasPayment"] is False
    assert _me(participant_b)["canBook"] is True

    detail = context.admin.json("GET", f"/admin/api/rooms/{setup.room['id']}")
    assert detail["room"]["status"] == "archived"
    assert detail["room"]["archiveReason"] == "technical_abort"
    statuses = {booking["participantId"]: booking["status"] for booking in detail["bookings"]}
    assert statuses[participant_a_id] == "attended"
    assert statuses[participant_b_id] == "no_show"

    blocked_absent = context.admin.request(
        "POST",
        f"/admin/api/rooms/{setup.room['id']}/actions",
        json={"action": "mark_absent", "participantId": participant_a_id},
    )
    assert blocked_absent.status_code == 409
    assert blocked_absent.json()["detail"] == "技术中止后不能把到场参与者标记缺席"
    blocked_completed = context.admin.request(
        "POST",
        f"/admin/api/rooms/{setup.room['id']}/actions",
        json={"action": "mark_completed", "participantId": participant_a_id},
    )
    assert blocked_completed.status_code == 409
    assert blocked_completed.json()["detail"] == "技术中止参与者请通过提交后测问卷生成到场费"
    resend_a = context.admin.json(
        "POST",
        f"/admin/api/rooms/{setup.room['id']}/actions",
        json={"action": "resend_questionnaire", "participantId": participant_a_id},
    )
    assert [link["participantId"] for link in resend_a["links"]] == [participant_a_id]
    resend_b = context.admin.request(
        "POST",
        f"/admin/api/rooms/{setup.room['id']}/actions",
        json={"action": "resend_questionnaire", "participantId": participant_b_id},
    )
    assert resend_b.status_code == 404

    assert context.admin.json("GET", "/admin/api/payments")["payments"] == []
    identity = valid_identity_answers("运行时甲", phone="13900002222")
    participant_a.json(
        "POST",
        "/api/questionnaire/complete",
        json={
            "roomId": setup.room["id"],
            "answers": questionnaire_answers(identity, q1="female", q2="技术中止"),
            "jatosWorkerId": "runtime-worker",
            "jatosStudyResultId": "runtime-study",
            "jatosComponentResultId": "runtime-component",
        },
    )
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 1
    payment = payments[0]
    assert payment["participantId"] == participant_a_id
    assert payment["basePayCents"] == 0
    assert payment["performancePayCents"] == 0
    assert payment["showupPayCents"] == 500
    assert payment["totalCents"] == 500
    assert payment["status"] == "pending"
    assert payment["deadlineAt"] is not None
    assert _me(participant_a)["hasShowupQuestionnaire"] is False
    assert _me(participant_a)["hasPayment"] is True
    assert _me(participant_a)["canBook"] is False
    assert _me(participant_b)["canBook"] is True
    resend_after = context.admin.request(
        "POST",
        f"/admin/api/rooms/{setup.room['id']}/actions",
        json={"action": "resend_questionnaire", "participantId": participant_a_id},
    )
    assert resend_after.status_code == 404
    assert fetch_one(
        "SELECT COUNT(*) AS count FROM payments WHERE room_id = %s", (setup.room["id"],)
    )["count"] == 1
    assert fetch_one(
        "SELECT COUNT(*) AS count FROM payments WHERE participant_id = %s",
        (participant_b_id,),
    )["count"] == 0


def test_restart_recovers_waiting(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        starts_in=2,
        wait_window=60,
    )
    _book(setup, participant_a, participant_b)
    ws_a, ws_b, waiting_a, waiting_b = _open_room(server, participant_a, participant_b)
    assert waiting_a["status"] == "waiting"
    assert waiting_b["status"] == "waiting"
    assert waiting_a["role"] is None
    ws_a.close()
    ws_b.close()

    server.restart()
    admin = ApiClient(server.base_url).login_admin()
    ws_a, snapshot_a = _connect(server, participant_a)
    ws_b, snapshot_b = _connect(server, participant_b)
    assert snapshot_a["status"] == "waiting"
    assert snapshot_a["phase"] == "waiting"
    assert snapshot_a["role"] is None
    assert snapshot_b["status"] == "waiting"
    assert snapshot_b["phase"] == "waiting"

    monitor = _monitor(admin, setup.room["id"])
    restarts = [
        event for event in monitor["events"] if event["type"] == "server_restart"
    ]
    assert restarts
    assert restarts[0]["payload"]["previousStatus"] == "waiting"
    assert monitor["room"]["status"] == "waiting"


def test_restart_recovers_instructions(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        starts_in=2,
        reconnect_window=60,
    )
    _book(setup, participant_a, participant_b)
    ws_a, ws_b, waiting_a, waiting_b = _open_room(server, participant_a, participant_b)
    assert waiting_a["status"] == "waiting"
    info_a, info_b = _start_instructions(ws_a, ws_b)
    ws_a.close()
    ws_b.close()

    server.restart()
    admin = ApiClient(server.base_url).login_admin()
    ws_a, snapshot_a = _connect(server, participant_a)
    ws_b, snapshot_b = _connect(server, participant_b)
    assert snapshot_a["status"] == "instructions"
    assert snapshot_a["phase"] == "instructions"
    assert snapshot_a["role"] == info_a["role"]
    assert snapshot_a["instruction"]["completed"] is False
    assert snapshot_b["status"] == "instructions"
    assert snapshot_b["role"] == info_b["role"]
    assert snapshot_b["instruction"]["completed"] is False

    _complete_instructions(ws_a, ws_b)
    state_a, state_b, start_a, start_b, turn_a, turn_b = _enter_game_messages(ws_a, ws_b)
    assert state_a["status"] == "playing"
    assert state_b["status"] == "playing"
    assert start_a["isPractice"] is True
    assert start_b["isPractice"] is True
    assert turn_a["round"] == 1
    assert turn_b["round"] == 1

    monitor = _monitor(admin, setup.room["id"])
    restarts = [
        event for event in monitor["events"] if event["type"] == "server_restart"
    ]
    assert restarts
    assert restarts[0]["payload"]["previousStatus"] == "instructions"


def test_restart_resets_playing_turn_clock(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=2,
        practice_seconds=6,
        formal_cap=2,
        formal_seconds=6,
        rest_seconds=1,
        reconnect_window=10,
    )
    game = _start_game(server, setup, participant_a, participant_b)
    cells_a = _selection(game.turn_a["board"], game.role_a, False)
    _send_selection(game.ws_a, game.turn_a, cells_a, "before-restart")
    ack_a = game.ws_a.recv_until("turn")
    ack_b = game.ws_b.recv_until("turn")
    assert ack_a["submitted"] is True
    assert ack_b["partnerSubmitted"] is True
    assert ack_b["submitted"] is False
    time.sleep(2.0)
    game.ws_a.close()
    game.ws_b.close()

    server.restart()
    admin = ApiClient(server.base_url).login_admin()
    ws_a, snapshot_a = _connect(server, participant_a)
    assert snapshot_a["status"] == "playing"
    assert snapshot_a["game"]["phase"] == "turn"
    assert snapshot_a["game"]["round"] == 1
    assert snapshot_a["game"]["submitted"] is True
    assert snapshot_a["game"]["partnerSubmitted"] is False
    assert snapshot_a["game"]["turnDeadline"] is None

    ws_b, snapshot_b = _connect(server, participant_b)
    assert snapshot_b["status"] == "playing"
    assert snapshot_b["game"]["turnDeadline"] is not None
    assert snapshot_b["game"]["submitted"] is False
    assert snapshot_b["game"]["partnerSubmitted"] is True
    resumed_a = ws_a.recv_until("turn")
    resumed_b = ws_b.recv_until("turn")
    assert resumed_a["round"] == 1
    assert resumed_a["submitted"] is True
    assert resumed_a["partnerSubmitted"] is False
    assert resumed_b["submitted"] is False
    assert resumed_b["partnerSubmitted"] is True
    assert resumed_a["deadline"] == resumed_b["deadline"]
    assert _seconds_until(resumed_a["deadline"]) >= 5.0

    cells_b = _selection(resumed_b["board"], game.role_b, False)
    _send_selection(ws_b, resumed_b, cells_b, "after-restart")
    result_a = ws_a.recv_until("turn_result")
    result_b = ws_b.recv_until("turn_result")
    assert result_a["round"] == 1
    assert result_a["trialEnded"] is False
    assert result_a["selections"][f"player{game.role_a}"] == sorted(cells_a)
    assert result_a["selections"][f"player{game.role_b}"] == sorted(cells_b)
    assert result_b["nextRound"] == 2
    ws_a.recv_until("turn")
    ws_b.recv_until("turn")

    room = fetch_one("SELECT * FROM rooms WHERE id = %s", (setup.room["id"],))
    runtime_state = _json_value(room["runtime_state"])
    assert runtime_state["recovery_count"] >= 1
    monitor = _monitor(admin, setup.room["id"])
    restarts = [
        event for event in monitor["events"] if event["type"] == "server_restart"
    ]
    assert restarts
    assert restarts[0]["payload"]["previousStatus"] == "playing"


def test_restart_recovers_questionnaire_without_abort(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=1,
        practice_seconds=1,
        formal_cap=1,
        formal_seconds=1,
        rest_seconds=1,
        reconnect_window=1,
    )
    game = _start_game(server, setup, participant_a, participant_b)
    journey = _play_to_questionnaire(game)
    assert journey.state_a["status"] == "questionnaire"
    assert journey.state_a["self"]["canExit"] is False
    assert journey.state_a["game"]["phase"] == "questionnaire"
    assert journey.state_a["game"]["turnDeadline"] is None
    assert journey.state_a["game"]["restDeadline"] is None
    assert journey.state_a["questionnaire"]["status"] == "in_progress"
    assert journey.state_a["questionnaire"]["url"]
    assert journey.state_b["status"] == "questionnaire"

    game.ws_a.send("exit_room")
    error = _recv_while(
        game.ws_a, lambda message: message.get("type") == "error", "退出错误"
    )
    assert error["code"] == "invalid_state"

    time.sleep(2.0)
    detail = context.admin.json("GET", f"/admin/api/rooms/{setup.room['id']}")
    assert detail["room"]["status"] == "questionnaire"
    assert detail["room"]["archiveReason"] is None
    assert all(
        participant["questionnaireStatus"] == "in_progress"
        for participant in detail["participants"]
    )
    game.ws_a.close()
    game.ws_b.close()

    server.restart()
    admin = ApiClient(server.base_url).login_admin()
    ws_a, snapshot_a = _connect(server, participant_a)
    ws_b, snapshot_b = _connect(server, participant_b)
    assert snapshot_a["status"] == "questionnaire"
    assert snapshot_a["game"]["phase"] == "questionnaire"
    assert snapshot_a["questionnaire"]["status"] == "in_progress"
    assert snapshot_a["self"]["canExit"] is False
    assert snapshot_b["status"] == "questionnaire"
    assert snapshot_b["questionnaire"]["status"] == "in_progress"

    monitor = _monitor(admin, setup.room["id"])
    assert all(
        participant["disconnectedUntil"] is None
        for participant in monitor["participants"]
    )
    restarts = [
        event for event in monitor["events"] if event["type"] == "server_restart"
    ]
    assert restarts
    assert restarts[0]["payload"]["previousStatus"] == "questionnaire"

    time.sleep(2.0)
    detail = admin.json("GET", f"/admin/api/rooms/{setup.room['id']}")
    assert detail["room"]["status"] == "questionnaire"
    assert detail["room"]["archiveReason"] is None


def test_random_formal_order_parameters_and_reproducibility(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    troop_rows = [
        {"soldiersA": 3, "soldiersB": 4},
        {"soldiersA": 5, "soldiersB": 6},
        {"soldiersA": 7, "soldiersB": 8},
        {"soldiersA": 9, "soldiersB": 10},
    ]
    setup = context.make_room(
        troop_rows=troop_rows,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=1,
        practice_seconds=1,
        formal_cap=1,
        formal_seconds=1,
        rest_seconds=1,
        randomize=True,
    )
    game = _start_game(server, setup, participant_a, participant_b)
    journey = _play_to_questionnaire(game)

    assert len(journey.trials) == 4
    practice = journey.trials[0]
    assert practice["start_a"]["trialIndex"] == 0
    assert practice["start_a"]["isPractice"] is True
    assert practice["start_a"]["formalTrial"] == 0
    assert practice["start_a"]["sourceIndex"] == 0
    _assert_trial_parameters(practice["start_a"], troop_rows[0], 0)
    _assert_initial_board(practice["start_a"]["board"], troop_rows[0], SPAWNS_2X2)

    formal_sources = []
    for position, trial in enumerate(journey.trials[1:], start=1):
        start_a = trial["start_a"]
        start_b = trial["start_b"]
        source_index = start_a["sourceIndex"]
        formal_sources.append(source_index)
        assert start_a["trialIndex"] == position
        assert start_a["gameNumber"] == position + 1
        assert start_a["isPractice"] is False
        assert start_a["formalTrial"] == position
        assert start_b["formalTrial"] == position
        assert start_a["totalTrials"] == 4
        source_row = troop_rows[source_index]
        _assert_trial_parameters(start_a, source_row, source_index)
        _assert_trial_parameters(start_b, source_row, source_index)
        _assert_initial_board(start_a["board"], source_row, SPAWNS_2X2)
        _assert_trial_parameters(trial["state_a"]["game"], source_row, source_index)
        _assert_trial_parameters(trial["turn_a"], source_row, source_index)
        _assert_trial_parameters(trial["result_a"], source_row, source_index)
        assert trial["result_a"]["trialIndex"] == position
        assert trial["result_a"]["sourceIndex"] == source_index
    assert sorted(formal_sources) == [1, 2, 3]
    assert len(set(formal_sources)) == 3

    export = context.admin.json(
        "GET", f"/admin/api/rooms/{setup.room['id']}/export.json"
    )
    assert export["schemaVersion"] == 5
    plan_order = [entry["sourceIndex"] for entry in export["trialPlan"]["order"]]
    assert plan_order == [0] + formal_sources
    assert export["trialPlan"]["seed"]
    assert [trial["sourceIndex"] for trial in export["trials"]] == [0] + formal_sources
    stored = _game_trials(setup.room["id"])
    assert [trial["source_index"] for trial in stored] == [0] + formal_sources

    first = generate_trial_plan(troop_rows, 1, 3, True, 123456789)
    second = generate_trial_plan(troop_rows, 1, 3, True, 123456789)
    first_signature = [
        (entry.trial_index, entry.source_index, entry.is_practice, entry.formal_trial, entry.params)
        for entry in first
    ]
    second_signature = [
        (entry.trial_index, entry.source_index, entry.is_practice, entry.formal_trial, entry.params)
        for entry in second
    ]
    assert first_signature == second_signature
    assert first_signature[0][1] == 0
    assert first_signature[0][2] is True
    assert {entry.source_index for entry in first[1:]} == {1, 2, 3}
    for entry in first[1:]:
        assert entry.params == troop_rows[entry.source_index]


def test_visuals_both_mode(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    asset = upload_media(context.admin, _png_bytes((220, 80, 60)), filename="both-map.png")
    assets = [asset["id"], None, None, None]
    setup = context.make_room(
        troop_rows=STAY_ROWS[:2],
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        mode="both",
        assets=assets,
        colors=["#112233", None, None, None],
    )
    game = _start_game(server, setup, participant_a, participant_b)
    assert game.start_a["visuals"] == game.start_b["visuals"]
    assert len(game.start_a["visuals"]) == 4
    assert game.start_a["visuals"][0]["backgroundAssetId"] == asset["id"]
    assert game.start_a["visuals"][0]["color"] == "#112233"
    assert game.start_a["visuals"][1]["backgroundAssetId"] is None
    assert game.state_a["game"]["visuals"] == game.start_a["visuals"]
    assert game.state_b["game"]["visuals"] == game.start_a["visuals"]


def test_visuals_ab_mode(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    asset_a = upload_media(
        context.admin, _png_bytes((220, 80, 60)), filename="ab-map-a.png"
    )
    asset_b = upload_media(
        context.admin, _png_bytes((60, 80, 220)), filename="ab-map-b.png"
    )
    assets = {
        "A": [asset_a["id"], None, None, None],
        "B": [asset_b["id"], None, None, None],
    }
    setup = context.make_room(
        troop_rows=STAY_ROWS[:2],
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        mode="ab",
        assets=assets,
        colors={
            "A": ["#112233", None, None, None],
            "B": ["#445566", None, None, None],
        },
    )
    game = _start_game(server, setup, participant_a, participant_b)

    visuals_a = game.start_a["visuals"] if game.role_a == 1 else game.start_b["visuals"]
    visuals_b = game.start_a["visuals"] if game.role_a == 2 else game.start_b["visuals"]
    assert visuals_a[0]["backgroundAssetId"] == asset_a["id"]
    assert visuals_a[0]["color"] == "#112233"
    assert visuals_b[0]["backgroundAssetId"] == asset_b["id"]
    assert visuals_b[0]["color"] == "#445566"
    assert visuals_a != visuals_b

    state_visuals_a = (
        game.state_a["game"]["visuals"] if game.role_a == 1 else game.state_b["game"]["visuals"]
    )
    state_visuals_b = (
        game.state_a["game"]["visuals"] if game.role_a == 2 else game.state_b["game"]["visuals"]
    )
    assert state_visuals_a[0]["backgroundAssetId"] == asset_a["id"]
    assert state_visuals_b[0]["backgroundAssetId"] == asset_b["id"]


def test_idempotent_and_stale_submissions(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS[:2],
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=2,
        practice_seconds=10,
        formal_cap=2,
        formal_seconds=10,
        rest_seconds=1,
    )
    game = _start_game(server, setup, participant_a, participant_b)

    cells_a = _selection(game.turn_a["board"], game.role_a, False)
    message_id = "dup-message-1"
    game.ws_a.send(
        "submit_selection",
        roomId=game.room_id,
        trialIndex=game.turn_a["trialIndex"],
        round=game.turn_a["round"],
        cells=cells_a,
        clientMsgId=message_id,
    )
    ack_a = game.ws_a.recv_until("turn")
    ack_b = game.ws_b.recv_until("turn")
    assert ack_a["submitted"] is True
    assert ack_b["partnerSubmitted"] is True

    game.ws_a.send(
        "submit_selection",
        roomId=game.room_id,
        trialIndex=ack_a["trialIndex"],
        round=ack_a["round"],
        cells=cells_a,
        clientMsgId=message_id,
    )
    duplicate_state = game.ws_a.recv_until("room_state")
    assert duplicate_state["game"]["submitted"] is True
    assert duplicate_state["game"]["partnerSubmitted"] is False
    assert fetch_one(
        "SELECT COUNT(*) AS count FROM turn_submissions "
        "WHERE game_trial_id IN (SELECT id FROM game_trials WHERE room_id = %s) AND round = 1",
        (setup.room["id"],),
    )["count"] == 1

    game.ws_a.send(
        "submit_selection",
        roomId=game.room_id,
        trialIndex=ack_a["trialIndex"],
        round=ack_a["round"],
        cells=cells_a,
        clientMsgId="dup-message-2",
    )
    error = _recv_while(
        game.ws_a, lambda message: message.get("type") == "error", "重复提交错误"
    )
    assert error["code"] == "already_submitted"

    cells_b = _selection(ack_b["board"], game.role_b, False)
    _send_selection(game.ws_b, ack_b, cells_b, "normal-submit")
    result_a = game.ws_a.recv_until("turn_result")
    result_b = game.ws_b.recv_until("turn_result")
    assert result_b["round"] == result_a["round"]
    assert result_a["selections"][f"player{game.role_a}"] == sorted(cells_a)
    assert result_a["selections"][f"player{game.role_b}"] == sorted(cells_b)
    assert result_a["trialEnded"] is False
    next_turn_a = game.ws_a.recv_until("turn")
    next_turn_b = game.ws_b.recv_until("turn")
    assert next_turn_a["round"] == 2
    assert next_turn_b["round"] == 2

    game.ws_b.send(
        "submit_selection",
        roomId=game.room_id,
        trialIndex=next_turn_b["trialIndex"],
        round=1,
        cells=cells_b,
        clientMsgId="stale-round",
    )
    stale = _recv_while(
        game.ws_b, lambda message: message.get("type") == "error", "过期回合错误"
    )
    assert stale["code"] == "stale_round"
    assert fetch_one(
        "SELECT COUNT(*) AS count FROM turn_submissions "
        "WHERE game_trial_id IN (SELECT id FROM game_trials WHERE room_id = %s) AND round = 1",
        (setup.room["id"],),
    )["count"] == 2


def test_dashboard_attention_includes_instructions(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        practice_cap=1,
        practice_seconds=2,
        formal_cap=1,
        formal_seconds=2,
        starts_in=2,
        reconnect_window=10,
    )
    _book(setup, participant_a, participant_b)
    ws_a, ws_b, _waiting_a, _waiting_b = _open_room(
        server, participant_a, participant_b
    )
    _start_instructions(ws_a, ws_b)

    dashboard = context.admin.json("GET", "/admin/api/dashboard")
    attention_ids = {room["id"] for room in dashboard["attentionRooms"]}
    assert setup.room["id"] in attention_ids
    assert dashboard["roomCounts"]["instructions"] == 1

    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


def test_duplicate_connection_does_not_log_asgi_exception(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns=SPAWNS_2X2,
        starts_in=120,
        wait_window=600,
        reconnect_window=10,
    )
    _book(setup, participant_a)

    old = WsClient(server, participant_a.cookie_value("moyo_participant"))
    old.recv_until("room_state")
    new = WsClient(server, participant_a.cookie_value("moyo_participant"))
    new.recv_until("room_state")
    time.sleep(1.5)

    log = server.log_tail(300)
    assert "WebSocketDisconnected" not in log
    assert "Exception in ASGI application" not in log

    for socket in (old, new):
        try:
            socket.close()
        except Exception:
            pass
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_inactivity_archives_abandoned_without_payment():
    reset_database()
    server = ServerHandle(
        env_overrides={
            "INACTIVITY_TIMEOUT_SECONDS": "6",
            "INACTIVITY_WARNING_SECONDS": "2",
        }
    )
    server.start()
    try:
        context = Context(server)
        participant_a, participant_b = context.participants()
        setup = context.make_room(
            troop_rows=STAY_ROWS,
            grid=(2, 2),
            spawns=SPAWNS_2X2,
            practice_cap=1,
            practice_seconds=30,
        )
        game = _start_game(server, setup, participant_a, participant_b)
        warning = game.ws_a.recv_until("inactivity_warning", timeout=12)
        assert warning["remainingSeconds"] >= 1
        archived = game.ws_a.recv_until("room_archived", timeout=12)
        assert archived["reason"] == "abandoned"
        assert archived["canRebook"] is True
        assert archived["rewardKind"] == "none"
        assert context.admin.json("GET", "/admin/api/payments")["payments"] == []
        assert _me(participant_a)["canBook"] is True
        assert _me(participant_b)["canBook"] is True
        game.ws_a.close()
        participant_a.close()
        participant_b.close()
        context.admin.close()
    finally:
        server.stop()


@pytest.mark.integration
def test_hidden_page_pauses_inactivity():
    reset_database()
    server = ServerHandle(
        env_overrides={
            "INACTIVITY_TIMEOUT_SECONDS": "3",
            "INACTIVITY_WARNING_SECONDS": "1",
        }
    )
    server.start()
    try:
        context = Context(server)
        participant_a, participant_b = context.participants()
        setup = context.make_room(
            troop_rows=STAY_ROWS,
            grid=(2, 2),
            spawns=SPAWNS_2X2,
            practice_cap=1,
            practice_seconds=30,
        )
        game = _start_game(server, setup, participant_a, participant_b)
        game.ws_a.send("visibility", roomId=setup.room["id"], visible=False)
        game.ws_b.send("visibility", roomId=setup.room["id"], visible=False)
        time.sleep(6)
        detail = context.admin.json("GET", f"/admin/api/rooms/{setup.room['id']}")
        assert detail["room"]["status"] != "archived"
        game.ws_a.send("visibility", roomId=setup.room["id"], visible=True)
        game.ws_b.send("visibility", roomId=setup.room["id"], visible=True)
        archived = game.ws_a.recv_until("room_archived", timeout=12)
        assert archived["reason"] == "abandoned"
        game.ws_a.close()
        participant_a.close()
        participant_b.close()
        context.admin.close()
    finally:
        server.stop()


@pytest.mark.integration
def test_disconnect_prefers_technical_abort_over_inactivity():
    reset_database()
    server = ServerHandle(
        env_overrides={
            "INACTIVITY_TIMEOUT_SECONDS": "4",
            "INACTIVITY_WARNING_SECONDS": "1",
        }
    )
    server.start()
    try:
        context = Context(server)
        participant_a, participant_b = context.participants()
        setup = context.make_room(
            troop_rows=STAY_ROWS,
            grid=(2, 2),
            spawns=SPAWNS_2X2,
            practice_cap=1,
            practice_seconds=30,
            reconnect_window=1,
        )
        game = _start_game(server, setup, participant_a, participant_b)
        game.ws_a.close()
        archived = game.ws_b.recv_until("room_archived", timeout=12)
        assert archived["reason"] == "technical_abort"
        game.ws_b.close()
        participant_a.close()
        participant_b.close()
        context.admin.close()
    finally:
        server.stop()


@pytest.mark.integration
def test_activity_messages_prevent_inactivity_archive():
    reset_database()
    server = ServerHandle(
        env_overrides={
            "INACTIVITY_TIMEOUT_SECONDS": "4",
            "INACTIVITY_WARNING_SECONDS": "1",
        }
    )
    server.start()
    try:
        context = Context(server)
        participant_a, participant_b = context.participants()
        setup = context.make_room(
            troop_rows=STAY_ROWS,
            grid=(2, 2),
            spawns=SPAWNS_2X2,
            practice_cap=1,
            practice_seconds=30,
        )
        game = _start_game(server, setup, participant_a, participant_b)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            game.ws_a.send("activity", roomId=setup.room["id"])
            game.ws_b.send("activity", roomId=setup.room["id"])
            time.sleep(0.5)
        detail = context.admin.json("GET", f"/admin/api/rooms/{setup.room['id']}")
        assert detail["room"]["status"] != "archived"
        assert detail["room"]["archiveReason"] is None
        game.ws_a.close()
        participant_a.close()
        participant_b.close()
        context.admin.close()
    finally:
        server.stop()
