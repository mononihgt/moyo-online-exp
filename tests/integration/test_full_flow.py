import csv
import hashlib
import io
import json
import uuid
import zipfile
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx
import pytest
from PIL import Image

from conftest import (
    ApiClient,
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
    upload_media,
    valid_identity_answers,
    wait_until,
)

LOGIN_A = ("被试甲", "13800000001")
LOGIN_B = ("被试乙", "13800000002")
IDENTITY_A = valid_identity_answers("甲", phone="13900001111")
IDENTITY_B = valid_identity_answers("乙", phone="13900001112")
PROFILE_ROWS = [
    {"soldiersA": 7, "soldiersB": 7},
    {"soldiersA": 8, "soldiersB": 9},
    {"soldiersA": 6, "soldiersB": 5},
]
PROTECTED_IDS = {"real_name", "alipay_phone", "identity_document"}
PAYMENT_TOTAL_CENTS = 5900
PERFORMANCE_PAY_CENTS = 1400


def _json_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def _owned_cell(board: dict, role: int) -> int:
    owned = [index for index, owner in enumerate(board["owners"]) if owner == role]
    assert owned, f"玩家 {role} 在棋盘上没有领地"
    return owned[0]


def _receive_next_phase(ws: WsClient, wanted: set[str]) -> dict:
    for _ in range(200):
        message = ws.recv()
        if message.get("type") in wanted:
            return message
        if message.get("type") == "error":
            raise AssertionError(f"websocket error: {message}")
    raise AssertionError(f"did not receive any of {wanted}")


def _wait_instruction_completed(ws: WsClient) -> dict:
    for _ in range(60):
        message = ws.recv()
        if message.get("type") == "instruction_state" and message["instruction"]["completed"]:
            return message
        if message.get("type") == "error":
            raise AssertionError(f"websocket error: {message}")
    raise AssertionError("instruction did not complete")


def _extract_token(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return query["rt"][0]


def _total_soldiers(board: dict, role: int) -> int:
    return sum(
        soldiers for index, soldiers in enumerate(board["soldiers"]) if board["owners"][index] == role
    )


def _assert_initial_board(board: dict, role_a: int, role_b: int, soldiers_a: int, soldiers_b: int) -> None:
    assert board["rows"] == 3
    assert board["cols"] == 3
    occupied = [(index, owner) for index, owner in enumerate(board["owners"]) if owner]
    assert len(occupied) == 2
    assert {owner for _index, owner in occupied} == {1, 2}
    positive = [index for index, soldiers in enumerate(board["soldiers"]) if soldiers > 0]
    assert len(positive) == 2
    for index, owner in occupied:
        expected = soldiers_a if owner == 1 else soldiers_b
        assert board["soldiers"][index] == expected
    assert role_a in (1, 2) and role_b in (1, 2) and role_a != role_b


def _assert_trial_parameters(message: dict, profile_rows: list[dict], source_index: int) -> None:
    row = profile_rows[source_index]
    assert message["sourceIndex"] == source_index
    assert message["initialSoldiersA"] == row["soldiersA"]
    assert message["initialSoldiersB"] == row["soldiersB"]
    assert message["reinforcementA"] == row["soldiersA"]
    assert message["reinforcementB"] == row["soldiersB"]
    assert message["initialSoldiersA"] == message["reinforcementA"]
    assert message["initialSoldiersB"] == message["reinforcementB"]


def _play_all_trials(
    ws_a: WsClient,
    ws_b: WsClient,
    room_id: str,
    role_a: int,
    role_b: int,
    profile_rows: list[dict],
    total_trials: int,
    turn_cap: int,
) -> tuple[list[dict], dict, dict]:
    summaries = []
    for trial_index in range(total_trials):
        start_a = ws_a.recv_until("trial_start")
        start_b = ws_b.recv_until("trial_start")
        assert start_a["trialIndex"] == trial_index
        assert start_b["trialIndex"] == trial_index
        source_index = start_a["sourceIndex"]
        assert start_b["sourceIndex"] == source_index
        assert start_a["isPractice"] == (trial_index == 0)
        assert start_b["isPractice"] == (trial_index == 0)
        assert start_a["formalTrial"] == (0 if trial_index == 0 else trial_index)
        assert start_a["turnCount"] == turn_cap
        assert start_a["round"] == 1
        _assert_trial_parameters(start_a, profile_rows, source_index)
        _assert_trial_parameters(start_b, profile_rows, source_index)
        soldiers_a = start_a["initialSoldiersA"]
        soldiers_b = start_a["initialSoldiersB"]
        reinforcement_by_role = {1: soldiers_a, 2: soldiers_b}

        turn_a = ws_a.recv_until("turn")
        turn_b = ws_b.recv_until("turn")
        assert turn_a["trialIndex"] == trial_index
        assert turn_a["round"] == 1
        assert turn_a["turnCount"] == turn_cap
        assert turn_b["round"] == 1
        _assert_initial_board(turn_a["board"], role_a, role_b, soldiers_a, soldiers_b)
        _assert_initial_board(turn_b["board"], role_a, role_b, soldiers_a, soldiers_b)
        _assert_trial_parameters(turn_a, profile_rows, source_index)

        final_board = None
        for round_number in range(1, turn_cap + 1):
            assert turn_a["round"] == round_number
            assert turn_b["round"] == round_number
            ws_a.send(
                "submit_selection",
                roomId=room_id,
                trialIndex=trial_index,
                round=round_number,
                cells=[_owned_cell(turn_a["board"], role_a)],
                clientMsgId=f"a-{trial_index}-{round_number}-{uuid.uuid4().hex[:8]}",
            )
            ws_b.send(
                "submit_selection",
                roomId=room_id,
                trialIndex=trial_index,
                round=round_number,
                cells=[_owned_cell(turn_b["board"], role_b)],
                clientMsgId=f"b-{trial_index}-{round_number}-{uuid.uuid4().hex[:8]}",
            )
            result_a = ws_a.recv_until("turn_result")
            result_b = ws_b.recv_until("turn_result")
            assert result_a["trialIndex"] == trial_index
            assert result_b["trialIndex"] == trial_index
            assert result_a["round"] == round_number
            assert result_b["round"] == round_number
            for result in (result_a, result_b):
                _assert_trial_parameters(result, profile_rows, source_index)
                assert result["warLocation"] == []
                assert result["warLost"] == {"player1": [], "player2": []}
            assert _total_soldiers(result_a["board"], role_a) == (
                reinforcement_by_role[role_a] * (round_number + 1)
            )
            assert _total_soldiers(result_a["board"], role_b) == (
                reinforcement_by_role[role_b] * (round_number + 1)
            )
            assert result_a["trialEnded"] == (round_number == turn_cap)
            final_board = result_a["board"]
            if round_number < turn_cap:
                turn_a = ws_a.recv_until("turn")
                turn_b = ws_b.recv_until("turn")
                assert turn_a["round"] == round_number + 1
                assert turn_a["trialIndex"] == trial_index
                assert turn_a["submitted"] is False
                assert turn_b["round"] == round_number + 1

        next_a = _receive_next_phase(ws_a, {"rest", "game_over"})
        next_b = _receive_next_phase(ws_b, {"rest", "game_over"})
        assert next_a["type"] == next_b["type"]
        summaries.append(
            {
                "trialIndex": trial_index,
                "sourceIndex": source_index,
                "isPractice": trial_index == 0,
                "board": final_board,
            }
        )
        if next_a["type"] == "rest":
            assert next_a["trialIndex"] == trial_index
            assert next_b["trialIndex"] == trial_index
            assert next_a["completedIsPractice"] == (trial_index == 0)
            assert next_a["nextTrialIndex"] == trial_index + 1
            assert next_a["finalSoldiers"]["player1"] == reinforcement_by_role[1] * (turn_cap + 1)
            assert next_a["finalSoldiers"]["player2"] == reinforcement_by_role[2] * (turn_cap + 1)
            ws_a.send("rest_ready", roomId=room_id)
            ws_b.send("rest_ready", roomId=room_id)
        else:
            questionnaire_a = ws_a.recv_until("questionnaire_required")
            questionnaire_b = ws_b.recv_until("questionnaire_required")
            assert questionnaire_a["url"] and questionnaire_b["url"]
            return summaries, questionnaire_a, questionnaire_b
    raise AssertionError("game did not reach questionnaire")


def _read_csv(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


def _section_counts(admin: ApiClient) -> dict:
    return admin.json("GET", "/admin/api/rooms")["counts"]


def _assert_sections(admin: ApiClient, **expected: int) -> None:
    counts = _section_counts(admin)
    assert set(counts) == {"draft", "open", "in_progress", "unpaid", "archived"}
    values = {
        "draft": counts["draft"],
        "open": counts["open"],
        "in_progress": counts["in_progress"],
        "unpaid": counts["unpaid"],
        "archived": counts["archived"],
    }
    for key, value in expected.items():
        assert values[key] == value, f"分区 {key} 期望 {value}，实际 {values[key]}"


def _assert_no_pii(text: str, pii_values: list[str], location: str) -> None:
    for value in pii_values:
        assert value not in text, f"{location} 包含敏感信息: {value}"


@pytest.mark.integration
def test_full_two_participant_flow_and_exports(server):
    admin = ApiClient(server.base_url).login_admin()
    create_consent(admin)

    profile = create_troop_profile(admin, PROFILE_ROWS)
    assert profile["status"] == "published"
    assert profile["practiceTrials"] == 1
    assert profile["formalTrials"] == 2
    assert profile["rows"] == PROFILE_ROWS

    image = Image.new("RGB", (4, 4), (220, 80, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    asset = upload_media(admin, buffer.getvalue(), filename="格子.png", kind="map")
    assert asset["contentType"] == "image/png"
    cells = [asset["assetId"]] + [None] * 8

    map_group = create_map_group(
        admin,
        profile["id"],
        mode="both",
        rows=3,
        cols=3,
        formal_trials=2,
        assets=cells,
        factors={"landmark": "present", "orientation": "horizontal"},
        landmark_cells=[0, 1, 2],
        practice_turn_cap=3,
        practice_turn_seconds=4,
        formal_turn_cap=3,
        formal_turn_seconds=4,
        rest_seconds=1,
        randomize_formal=True,
        base_pay_cents=4500,
        performance_rate_cents=50,
        performance_cap_cents=2000,
    )
    assert map_group["status"] == "published"
    assert map_group["practiceTrials"] == 1
    assert map_group["formalTrials"] == 2
    assert map_group["practiceTurnCap"] == 3
    assert map_group["practiceTurnSeconds"] == 4
    assert map_group["formalTurnCap"] == 3
    assert map_group["formalTurnSeconds"] == 4
    assert map_group["restSeconds"] == 1
    assert map_group["factors"] == {
        "landmark": "present",
        "orientation": "horizontal",
    }
    assert map_group["maps"][0]["landmarkCells"] == [0, 1, 2]
    assert map_group["spawns"] == {"A": 0, "B": 8}
    assert map_group["payment"] == {
        "basePayCents": 4500,
        "performanceRateCents": 50,
        "performanceFloorCents": 0,
        "performanceCapCents": 2000,
        "showupPayCents": 1000,
    }
    assert [item["slot"] for item in map_group["maps"]] == ["Both"]
    assert map_group["maps"][0]["cells"] == cells

    instruction_a = create_instruction(
        admin, map_group["id"], 1, "# 玩家一\n\n你是圆形玩家，每回合选择自己的格子。", 0
    )
    instruction_b = create_instruction(
        admin, map_group["id"], 2, "# 玩家二\n\n你是菱形玩家，每回合选择自己的格子。", 0
    )
    assert instruction_a["name"] == f"{map_group['name']}-A"
    assert instruction_b["name"] == f"{map_group['name']}-B"
    assert instruction_a["role"] == 1 and instruction_b["role"] == 2
    assert instruction_a["status"] == "published"

    questionnaire = create_questionnaire(admin)
    schema_questions = questionnaire["schema"]["pages"][0]["questions"]
    assert [item["type"] for item in schema_questions] == [
        "single_choice",
        "short_text",
        "real_name",
        "alipay_phone",
        "identity_document",
    ]
    assert set(questionnaire["protectedQuestionIds"]) == PROTECTED_IDS

    room = create_room(
        admin,
        map_group["id"],
        instruction_a["id"],
        instruction_b["id"],
        questionnaire["id"],
        starts_in_seconds=6,
        wait_window_seconds=30,
        publish=False,
    )
    room_id = room["id"]
    assert room["status"] == "draft"
    assert room["mapGroup"]["id"] == map_group["id"]
    assert room["mapGroup"]["troopProfile"]["versionId"] == profile["id"]
    _assert_sections(admin, draft=1, open=0, in_progress=0, unpaid=0, archived=0)
    draft_rooms = admin.json("GET", "/admin/api/rooms", params={"section": "draft"})["rooms"]
    assert [item["id"] for item in draft_rooms] == [room_id]

    published = admin.json("POST", f"/admin/api/rooms/{room_id}/publish")["room"]
    assert published["status"] == "open"
    _assert_sections(admin, draft=0, open=1, in_progress=0, unpaid=0, archived=0)
    open_rooms = admin.json("GET", "/admin/api/rooms", params={"section": "open"})["rooms"]
    assert [item["id"] for item in open_rooms] == [room_id]

    participant_a = ApiClient(server.base_url).login_participant(*LOGIN_A)
    participant_b = ApiClient(server.base_url).login_participant(*LOGIN_B)
    participant_a.consent()
    participant_b.consent()

    bookable = participant_a.json("GET", "/api/rooms/bookable")
    bookable_room = next(item for item in bookable["rooms"] if item["id"] == room_id)
    assert bookable["canBook"] is True
    assert bookable_room["canBook"] is True
    assert bookable_room["bookedCount"] == 0
    assert bookable_room["capacity"] == 2
    assert "internalLabel" not in bookable_room
    assert bookable["serverNow"]
    assert bookable["timezone"]

    booking_a = participant_a.json("POST", f"/api/rooms/{room_id}/book")
    assert booking_a["bookedCount"] == 1
    assert booking_a["roomStatus"] == "open"
    repeat_a = participant_a.request("POST", f"/api/rooms/{room_id}/book")
    assert repeat_a.status_code == 409
    booking_b = participant_b.json("POST", f"/api/rooms/{room_id}/book")
    assert booking_b["bookedCount"] == 2
    assert booking_b["roomStatus"] == "full"
    repeat_b = participant_b.request("POST", f"/api/rooms/{room_id}/book")
    assert repeat_b.status_code == 409
    _assert_sections(admin, draft=0, open=1, in_progress=0, unpaid=0, archived=0)

    def _my_room(client: ApiClient) -> dict | None:
        return client.json("GET", "/api/my-room")["room"]

    current = wait_until(
        lambda: _my_room(participant_a) if (_my_room(participant_a) or {}).get("status") == "waiting" else None,
        timeout=30,
    )
    assert current["canEnter"] is True
    assert current["canCancel"] is False
    _assert_sections(admin, draft=0, open=0, in_progress=1, unpaid=0, archived=0)

    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    ws_a.send("enter_room", roomId=room_id)
    ws_b.send("enter_room", roomId=room_id)
    state_a = ws_a.recv_until("room_state")
    state_b = ws_b.recv_until("room_state")
    assert state_a["status"] == "waiting"
    assert state_a["role"] is None
    assert state_b["role"] is None
    wait_until(
        lambda: all(
            item["status"] == "attended" and item["attendedAt"] is not None
            for item in admin.json("GET", f"/admin/api/rooms/{room_id}")["bookings"]
        ),
        timeout=10,
    )

    ws_a.send("start_matching", roomId=room_id)
    ws_b.send("start_matching", roomId=room_id)
    instruction_state_a = ws_a.recv_until("instruction_state")
    instruction_state_b = ws_b.recv_until("instruction_state")
    role_a = instruction_state_a["instruction"]["role"]
    role_b = instruction_state_b["instruction"]["role"]
    assert {role_a, role_b} == {1, 2}
    expected_instruction_a = instruction_a if role_a == 1 else instruction_b
    expected_instruction_b = instruction_a if role_b == 1 else instruction_b
    assert (
        instruction_state_a["instruction"]["contentMarkdown"]
        == expected_instruction_a["contentMarkdown"]
    )
    assert (
        instruction_state_b["instruction"]["contentMarkdown"]
        == expected_instruction_b["contentMarkdown"]
    )
    assert instruction_state_a["instruction"]["minReadingSeconds"] == 0
    assert instruction_state_a["instruction"]["contentHtml"]
    assert instruction_state_a["instruction"]["completed"] is False

    detail = admin.json("GET", f"/admin/api/rooms/{room_id}")
    assert detail["room"]["status"] == "instructions"
    snapshot = detail["configSnapshot"]
    assert snapshot["mapGroup"]["profile"]["rows"] == PROFILE_ROWS
    assert snapshot["mapGroup"]["payment"]["performanceRateCents"] == 50
    assert snapshot["instructions"]["player1"]["contentMarkdown"] == instruction_a["contentMarkdown"]
    assert snapshot["instructions"]["player2"]["contentMarkdown"] == instruction_b["contentMarkdown"]
    assert set(snapshot["questionnaire"]["protectedQuestionIds"]) == PROTECTED_IDS
    assert detail["room"]["configLockedAt"] is not None
    starts_at_raw = detail["room"]["startsAt"]
    locked_attempt = admin.request(
        "PATCH", f"/admin/api/rooms/{room_id}", json={"waitWindowSeconds": 60}
    )
    assert locked_attempt.status_code == 409
    assert locked_attempt.json()["detail"] == "房间开始后不可修改配置"

    ws_a.send("instruction_complete", roomId=room_id)
    ws_b.send("instruction_complete", roomId=room_id)
    _wait_instruction_completed(ws_a)
    _wait_instruction_completed(ws_b)
    detail = admin.json("GET", f"/admin/api/rooms/{room_id}")
    assert all(item["instructionCompletedAt"] is not None for item in detail["participants"])
    assert all(item["instructionConnectedSeconds"] >= 0 for item in detail["participants"])
    _assert_sections(admin, draft=0, open=0, in_progress=1, unpaid=0, archived=0)

    ws_a.send("enter_game", roomId=room_id)
    ws_b.send("enter_game", roomId=room_id)
    game_start_a = ws_a.recv_until("game_start")
    game_start_b = ws_b.recv_until("game_start")
    assert game_start_a["totalTrials"] == 3
    assert game_start_b["totalTrials"] == 3

    summaries, questionnaire_a, questionnaire_b = _play_all_trials(
        ws_a, ws_b, room_id, role_a, role_b, PROFILE_ROWS, total_trials=3, turn_cap=3
    )
    assert [item["isPractice"] for item in summaries] == [True, False, False]
    assert summaries[0]["sourceIndex"] == 0
    assert {item["sourceIndex"] for item in summaries[1:]} == {1, 2}

    detail = admin.json("GET", f"/admin/api/rooms/{room_id}")
    assert detail["room"]["status"] == "questionnaire"
    assert len(detail["payments"]) == 0
    participant_rows = {item["role"]: item for item in detail["participants"]}
    by_name = {item["name"]: item for item in detail["bookings"]}
    participant_ids = {
        LOGIN_A[0]: by_name[LOGIN_A[0]]["participantId"],
        LOGIN_B[0]: by_name[LOGIN_B[0]]["participantId"],
    }
    role_by_name = {LOGIN_A[0]: role_a, LOGIN_B[0]: role_b}
    analysis_code_by_name = {
        name: participant_rows[role_by_name[name]]["analysisCode"] for name in (LOGIN_A[0], LOGIN_B[0])
    }
    starts_at = datetime.fromisoformat(starts_at_raw.replace("Z", "+00:00"))
    local_date = starts_at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    _assert_sections(admin, draft=0, open=0, in_progress=1, unpaid=0, archived=0)

    token_a = _extract_token(questionnaire_a["url"])
    token_b = _extract_token(questionnaire_b["url"])
    parsed_questionnaire_url = urlparse(questionnaire_a["url"])
    assert "/publix/" in parsed_questionnaire_url.path
    assert parsed_questionnaire_url.query.count("rt=") == 1
    assert parsed_questionnaire_url.query.count("pid=") == 1

    context_a = httpx.get(
        f"{server.base_url}/api/jatos/questionnaire", params={"token": token_a}, timeout=30
    )
    assert context_a.status_code == 200
    context_a_payload = context_a.json()
    assert context_a_payload["analysisCode"] == analysis_code_by_name[LOGIN_A[0]]
    assert context_a_payload["completed"] is False
    assert context_a_payload["draftAnswers"] is None
    assert context_a_payload["existingAnswers"] is None
    assert set(context_a_payload["questionnaire"]["protectedQuestionIds"]) == PROTECTED_IDS
    assert context_a_payload["redirectUrl"].endswith(f"/complete?room={room_id}")
    assert context_a_payload["platformBaseUrl"] == server.base_url

    draft_answers = questionnaire_answers(IDENTITY_A, q1="female")
    draft = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/draft",
        json={"token": token_a, "answers": draft_answers},
        timeout=30,
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["saved"] is True
    draft_row = fetch_one(
        "SELECT answers_json FROM questionnaire_drafts WHERE room_id = %s AND participant_id = %s",
        (room_id, participant_ids[LOGIN_A[0]]),
    )
    assert draft_row is not None
    assert _json_value(draft_row["answers_json"]) == {"q1": "female"}

    context_a = httpx.get(
        f"{server.base_url}/api/jatos/questionnaire", params={"token": token_a}, timeout=30
    ).json()
    assert context_a["draftAnswers"] == {"q1": "female"}
    assert context_a["existingAnswers"] is None
    assert PROTECTED_IDS.isdisjoint(context_a["draftAnswers"])
    _assert_no_pii(
        json.dumps(context_a, ensure_ascii=False),
        [IDENTITY_A["real_name"], IDENTITY_A["alipay_phone"], IDENTITY_A["id_card"]],
        "问卷上下文",
    )

    complete_a = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/complete",
        json={
            "token": token_a,
            "answers": questionnaire_answers(IDENTITY_A, document_type="id_card", q1="female", q2="体验顺畅"),
            "jatosWorkerId": "worker-a",
            "jatosStudyResultId": f"study-a-{uuid.uuid4()}",
            "jatosComponentResultId": f"component-a-{uuid.uuid4()}",
        },
        timeout=30,
    )
    assert complete_a.status_code == 200, complete_a.text
    assert complete_a.json()["saved"] is True
    assert complete_a.json()["canonical"] is True

    detail = admin.json("GET", f"/admin/api/rooms/{room_id}")
    assert detail["room"]["status"] == "questionnaire"
    assert len(detail["payments"]) == 1
    status_by_name = {
        item["name"]: item["questionnaireStatus"] for item in detail["participants"]
    }
    assert status_by_name[LOGIN_A[0]] == "completed"
    assert status_by_name[LOGIN_B[0]] == "in_progress"
    assert fetch_one(
        "SELECT id FROM questionnaire_drafts WHERE room_id = %s AND participant_id = %s",
        (room_id, participant_ids[LOGIN_A[0]]),
    ) is None
    _assert_sections(admin, draft=0, open=0, in_progress=1, unpaid=0, archived=0)

    context_a = httpx.get(
        f"{server.base_url}/api/jatos/questionnaire", params={"token": token_a}, timeout=30
    ).json()
    assert context_a["completed"] is True
    assert context_a["draftAnswers"] is None
    assert context_a["existingAnswers"] == {"q1": "female", "q2": "体验顺畅"}
    assert PROTECTED_IDS.isdisjoint(context_a["existingAnswers"])

    complete_b = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/complete",
        json={
            "token": token_b,
            "answers": questionnaire_answers(
                IDENTITY_B, document_type="passport", q1="male", q2="规则清楚"
            ),
            "jatosWorkerId": "worker-b",
            "jatosStudyResultId": f"study-b-{uuid.uuid4()}",
            "jatosComponentResultId": f"component-b-{uuid.uuid4()}",
        },
        timeout=30,
    )
    assert complete_b.status_code == 200, complete_b.text
    assert complete_b.json()["canonical"] is True

    detail = admin.json("GET", f"/admin/api/rooms/{room_id}")
    assert detail["room"]["status"] == "archived"
    assert detail["room"]["archiveReason"] == "completed"
    assert len(detail["payments"]) == 2
    assert all(item["questionnaireStatus"] == "completed" for item in detail["participants"])
    assert all(item["completedAt"] is not None for item in detail["participants"])
    _assert_sections(admin, draft=0, open=0, in_progress=0, unpaid=1, archived=0)
    archived_rooms = admin.json("GET", "/admin/api/rooms", params={"section": "unpaid"})["rooms"]
    assert [item["id"] for item in archived_rooms] == [room_id]

    identities = fetch_all(
        "SELECT participant_id, real_name_encrypted, alipay_phone_encrypted, document_type, "
        "document_number_encrypted FROM participant_identities WHERE room_id = %s",
        (room_id,),
    )
    assert len(identities) == 2
    identity_by_pid = {row["participant_id"]: row for row in identities}
    identity_a_row = identity_by_pid[participant_ids[LOGIN_A[0]]]
    identity_b_row = identity_by_pid[participant_ids[LOGIN_B[0]]]
    assert identity_a_row["document_type"] == "id_card"
    assert identity_b_row["document_type"] == "passport"
    for column in ("real_name_encrypted", "alipay_phone_encrypted", "document_number_encrypted"):
        assert identity_a_row[column].startswith("gAAAA")
        assert identity_b_row[column].startswith("gAAAA")
    assert identity_a_row["real_name_encrypted"] != IDENTITY_A["real_name"]
    assert identity_a_row["alipay_phone_encrypted"] != IDENTITY_A["alipay_phone"]
    assert identity_a_row["document_number_encrypted"] != IDENTITY_A["id_card"]
    assert identity_b_row["document_number_encrypted"] != IDENTITY_B["passport"]

    responses = fetch_all(
        "SELECT participant_id, answers_json, canonical, source FROM questionnaire_responses "
        "WHERE room_id = %s",
        (room_id,),
    )
    assert len(responses) == 2
    for response in responses:
        assert bool(response["canonical"]) is True
        assert response["source"] == "jatos"
        answers = _json_value(response["answers_json"])
        assert set(answers) <= {"q1", "q2"}
        assert PROTECTED_IDS.isdisjoint(answers)
        _assert_no_pii(
            json.dumps(answers, ensure_ascii=False),
            [
                IDENTITY_A["real_name"],
                IDENTITY_A["alipay_phone"],
                IDENTITY_A["id_card"],
                IDENTITY_B["real_name"],
                IDENTITY_B["alipay_phone"],
                IDENTITY_B["passport"],
            ],
            "问卷答案",
        )
    assert fetch_all(
        "SELECT id FROM questionnaire_drafts WHERE room_id = %s", (room_id,)
    ) == []

    me_a = participant_a.json("GET", "/api/me")["me"]
    assert me_a["status"] == "completed"
    assert me_a["isCompleted"] is True
    assert me_a["canBook"] is False
    assert me_a["hasPendingQuestionnaire"] is False
    experiments_a = participant_a.json("GET", "/api/my-experiments")["experiments"]
    experiment_a = next(item for item in experiments_a if item["roomId"] == room_id)
    assert experiment_a["roomStatus"] == "archived"
    assert experiment_a["archiveReason"] == "completed"
    assert experiment_a["canRebook"] is False
    assert experiment_a["rewardKind"] == "completion"
    assert experiment_a["payment"]["status"] == "pending"
    assert experiment_a["payment"]["totalCents"] == PAYMENT_TOTAL_CENTS
    payments_a = participant_a.json("GET", "/api/my-payments")["payments"]
    assert [item["totalCents"] for item in payments_a] == [PAYMENT_TOTAL_CENTS]

    admin_payments = admin.json("GET", "/admin/api/payments")["payments"]
    assert len(admin_payments) == 2
    assert {item["analysisCode"] for item in admin_payments} == set(analysis_code_by_name.values())
    assert "13800000001" not in json.dumps(admin_payments, ensure_ascii=False)
    assert "13800000002" not in json.dumps(admin_payments, ensure_ascii=False)
    payment_by_name = {item["name"]: item for item in admin_payments}
    for name in (LOGIN_A[0], LOGIN_B[0]):
        payment = payment_by_name[name]
        assert payment["basePayCents"] == 4500
        assert payment["performancePayCents"] == PERFORMANCE_PAY_CENTS
        assert payment["showupPayCents"] == 0
        assert payment["totalCents"] == PAYMENT_TOTAL_CENTS
        assert payment["status"] == "pending"
        assert payment["deadlineAt"] is not None
        assert payment["roomStartsAt"] == starts_at_raw
        assert "****" in payment["phoneMasked"]

    filtered_payments = admin.json(
        "GET",
        "/admin/api/payments",
        params={"status": "pending", "from": local_date, "to": local_date},
    )["payments"]
    assert len(filtered_payments) == 2
    outside_payments = admin.json(
        "GET",
        "/admin/api/payments",
        params={"status": "pending", "from": "2000-01-01", "to": "2000-01-02"},
    )["payments"]
    assert outside_payments == []
    missing_to = admin.request(
        "GET", "/admin/api/payments", params={"from": local_date}
    )
    assert missing_to.status_code == 400
    assert missing_to.json()["detail"] == "开始日期和结束日期必须同时提供"

    payment_list = admin.request(
        "GET",
        "/admin/api/payments/export-payment-list.csv",
        params={"from": local_date, "to": local_date},
    )
    assert payment_list.status_code == 200
    assert payment_list.content.startswith(b"\xef\xbb\xbf")
    payment_rows = _read_csv(payment_list.content)
    assert payment_rows[0] == ["序号", "玩家支付宝手机号", "玩家姓名", "金额"]
    assert len(payment_rows) == 3
    payment_text = payment_list.content.decode("utf-8-sig")
    for identity in (IDENTITY_A, IDENTITY_B):
        assert identity["real_name"] in payment_text
        assert identity["alipay_phone"] in payment_text
    assert payment_text.count("59.00") == 2
    assert LOGIN_A[1] not in payment_text
    assert LOGIN_B[1] not in payment_text
    assert IDENTITY_A["id_card"] not in payment_text
    assert IDENTITY_B["passport"] not in payment_text

    bulk = admin.json(
        "GET", "/admin/api/payments/bulk", params={"from": local_date, "to": local_date}
    )
    assert bulk["from"] == local_date and bulk["to"] == local_date
    assert len(bulk["payments"]) == 2
    bulk_by_name = {item["name"]: item for item in bulk["payments"]}
    assert bulk_by_name[IDENTITY_A["real_name"]]["phone"] == LOGIN_A[1]
    assert bulk_by_name[IDENTITY_B["real_name"]]["phone"] == LOGIN_B[1]
    assert all("*" not in item["phone"] for item in bulk["payments"])
    assert all(item["status"] == "pending" for item in bulk["payments"])
    assert all(item["archiveReason"] == "completed" for item in bulk["payments"])
    assert all(item["totalCents"] == PAYMENT_TOTAL_CENTS for item in bulk["payments"])

    payment_ids = sorted(item["id"] for item in admin_payments)
    marked = admin.json(
        "POST", "/admin/api/payments/bulk-mark-paid", json={"paymentIds": payment_ids}
    )
    assert marked["updated"] == 2
    assert marked["skipped"] == 0
    assert all(item["status"] == "paid" for item in marked["payments"])
    assert {item["paymentId"] for item in marked["payments"]} == set(payment_ids)
    _assert_sections(admin, draft=0, open=0, in_progress=0, unpaid=0, archived=1)
    archived_rooms = admin.json("GET", "/admin/api/rooms", params={"section": "archived"})["rooms"]
    assert [item["id"] for item in archived_rooms] == [room_id]
    assert participant_a.json("GET", "/api/my-payments")["payments"][0]["status"] == "paid"
    assert (
        admin.json("GET", "/admin/api/payments", params={"status": "paid"})["payments"][0]["status"]
        == "paid"
    )

    reimbursement = admin.request(
        "GET",
        "/admin/api/payments/export-reimbursement-list.csv",
        params={"from": local_date, "to": local_date},
    )
    assert reimbursement.status_code == 200
    assert reimbursement.content.startswith(b"\xef\xbb\xbf")
    reimbursement_rows = _read_csv(reimbursement.content)
    assert reimbursement_rows[0] == [
        "序号",
        "参与日期",
        "玩家姓名",
        "玩家手机号",
        "玩家身份证",
        "金额",
    ]
    assert len(reimbursement_rows) == 3
    reimbursement_by_name = {row[2]: row for row in reimbursement_rows[1:]}
    assert reimbursement_by_name[IDENTITY_A["real_name"]][1] == local_date
    assert reimbursement_by_name[IDENTITY_A["real_name"]][3] == LOGIN_A[1]
    assert reimbursement_by_name[IDENTITY_A["real_name"]][4] == IDENTITY_A["id_card"]
    assert reimbursement_by_name[IDENTITY_A["real_name"]][5] == "59.00"
    assert reimbursement_by_name[IDENTITY_B["real_name"]][3] == LOGIN_B[1]
    assert reimbursement_by_name[IDENTITY_B["real_name"]][4] == IDENTITY_B["passport"]
    assert reimbursement_by_name[IDENTITY_B["real_name"]][5] == "59.00"

    audit_entries = admin.json("GET", "/admin/api/audit", params={"limit": 500})
    actions = {entry["action"] for entry in audit_entries["entries"]}
    assert {
        "room_created",
        "room_published",
        "payments_bulk_viewed",
        "payments_bulk_marked_paid",
        "payments_payment_list_exported",
        "payments_reimbursement_list_exported",
    } <= actions
    audit_text = json.dumps(audit_entries, ensure_ascii=False)
    _assert_no_pii(
        audit_text,
        [
            LOGIN_A[0],
            LOGIN_B[0],
            LOGIN_A[1],
            LOGIN_B[1],
            IDENTITY_A["real_name"],
            IDENTITY_A["alipay_phone"],
            IDENTITY_A["id_card"],
            IDENTITY_B["real_name"],
            IDENTITY_B["alipay_phone"],
            IDENTITY_B["passport"],
        ],
        "审计日志",
    )

    export_response = admin.request("GET", f"/admin/api/rooms/{room_id}/export.json")
    assert export_response.status_code == 200
    exported = export_response.json()
    assert exported["schemaVersion"] == 6
    assert "condition" not in exported
    assert exported["room"]["status"] == "archived"
    assert exported["room"]["archiveReason"] == "completed"
    assert exported["mapGroup"]["name"] == map_group["name"]
    assert exported["mapGroup"]["factors"] == {
        "landmark": "present",
        "orientation": "horizontal",
    }
    assert [item["slot"] for item in exported["mapGroup"]["maps"]] == ["Both"]
    assert exported["mapGroup"]["maps"][0]["cells"] == cells
    assert exported["mapGroup"]["maps"][0]["landmarkCells"] == [0, 1, 2]
    assert exported["mapGroup"]["profile"]["rows"] == PROFILE_ROWS
    assert set(exported["questionnaire"]["protectedQuestionIds"]) == PROTECTED_IDS
    assert exported["trialPlan"]["order"][0] == {"trialIndex": 0, "sourceIndex": 0}
    assert {item["sourceIndex"] for item in exported["trialPlan"]["order"][1:]} == {1, 2}
    assert len(exported["participants"]) == 2
    assert len(exported["trials"]) == 3
    assert len(exported["payments"]) == 2
    analysis_codes = {item["analysisCode"] for item in exported["participants"]}
    assert analysis_codes == set(analysis_code_by_name.values())
    for participant in exported["participants"]:
        assert participant["analysisCode"].startswith("P-")
        assert participant["role"] in (1, 2)
        answers = participant["questionnaire"]["answers"]
        assert set(answers) == {"q1", "q2"}
        assert PROTECTED_IDS.isdisjoint(answers)
    for trial in exported["trials"]:
        assert trial["completedRounds"] == 3
        assert trial["forcedRounds"] == 0
        assert trial["endReason"] == "turn_limit"
        assert trial["engineVersion"] == "1"
        assert trial["mechanics"]["logistics"] == "none"
        assert trial["mechanics"]["movement"] == "equalSplit"
        assert len(trial["turns"]) == 4
        for turn in trial["turns"]:
            assert set(turn["preCombatPolicies"]) == {"player1", "player2"}
            assert set(turn["movements"]) == {"player1", "player2"}
            assert set(turn["submittedAt"]) == {"player1", "player2"}
            assert len(turn["preCombatPolicies"]["player1"]) in (0, 9)
        assert any(
            turn["submittedAt"]["player1"] for turn in trial["turns"] if turn["round"] > 0
        )
        assert any(
            turn["submittedAt"]["player2"] for turn in trial["turns"] if turn["round"] > 0
        )
        assert trial["initialState"]["rows"] == 3
        assert trial["initialState"]["cols"] == 3
        assert len(trial["initialState"]["owners"]) == 9
        assert sum(1 for owner in trial["initialState"]["owners"] if owner) == 2
        expected_row = PROFILE_ROWS[trial["sourceIndex"]]
        assert trial["params"] == {
            "soldiersA": expected_row["soldiersA"],
            "soldiersB": expected_row["soldiersB"],
        }
    for payment in exported["payments"]:
        assert payment["analysisCode"] in analysis_codes
        assert payment["basePayCents"] == 4500
        assert payment["performancePayCents"] == PERFORMANCE_PAY_CENTS
        assert payment["totalCents"] == PAYMENT_TOTAL_CENTS
        assert payment["status"] == "paid"
        assert "name" not in payment
    _assert_no_pii(
        export_response.text,
        [
            LOGIN_A[0],
            LOGIN_B[0],
            LOGIN_A[1],
            LOGIN_B[1],
            IDENTITY_A["real_name"],
            IDENTITY_A["alipay_phone"],
            IDENTITY_A["id_card"],
            IDENTITY_B["real_name"],
            IDENTITY_B["alipay_phone"],
            IDENTITY_B["passport"],
        ],
        "room 导出",
    )

    zip_response = admin.request("GET", f"/admin/api/rooms/{room_id}/analysis.zip")
    assert zip_response.status_code == 200
    assert zip_response.headers["content-type"].startswith("application/zip")
    archive = zipfile.ZipFile(io.BytesIO(zip_response.content))
    names = set(archive.namelist())
    for required in (
        "manifest.json",
        "room.json",
        "participants.csv",
        "turns.csv",
        "trials.csv",
        "events.csv",
        "questionnaire.json",
        "payment.csv",
        "trials/trial0.json",
        "trials/trial1.json",
        "trials/trial2.json",
        "media/manifest.json",
    ):
        assert required in names
    turns_header = _read_csv(archive.read("turns.csv"))[0]
    for column in (
        "preCombatPolicyPlayer1",
        "preCombatPolicyPlayer2",
        "movementPlayer1",
        "movementPlayer2",
        "submittedAtPlayer1",
        "submittedAtPlayer2",
    ):
        assert column in turns_header
    trial_rows = _read_csv(archive.read("trials.csv"))
    assert trial_rows[0] == [
        "roomId",
        "trialIndex",
        "gameNumber",
        "sourceIndex",
        "isPractice",
        "formalTrial",
        "seed",
        "engineVersion",
        "mechanics",
        "params",
        "startedAt",
        "endedAt",
        "winner",
        "endReason",
        "endTurn",
        "completedRounds",
        "forcedRounds",
        "finalSoldiersPlayer1",
        "finalSoldiersPlayer2",
    ]
    assert len(trial_rows) == 4
    assert trial_rows[1][7] == "1"
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["schemaVersion"] == 6
    assert manifest["containsPII"] is False
    assert manifest["mediaIncluded"] is True
    assert manifest["rowCounts"] == {
        "participants": 2,
        "trials": 3,
        "turns": 12,
        "events": manifest["rowCounts"]["events"],
        "payments": 2,
    }
    assert manifest["rowCounts"]["events"] > 0
    manifest_paths = {entry["path"] for entry in manifest["files"]}
    assert manifest_paths == names - {"manifest.json"}
    for entry in manifest["files"]:
        data = archive.read(entry["path"])
        assert len(data) == entry["bytes"]
        assert "sha256:" + hashlib.sha256(data).hexdigest() == entry["sha256"]

    media_manifest = json.loads(archive.read("media/manifest.json"))
    assert len(media_manifest["assets"]) == 1
    media_entry = media_manifest["assets"][0]
    assert media_entry["assetId"] == asset["assetId"]
    assert media_entry["sha256"] == asset["sha256"]
    assert media_entry["width"] == 4 and media_entry["height"] == 4
    assert media_entry["path"] == f"media/{asset['assetId']}.png"
    assert media_entry["path"] in names
    media_bytes = archive.read(media_entry["path"])
    assert "sha256:" + hashlib.sha256(media_bytes).hexdigest() == media_entry["sha256"]

    room_export = json.loads(archive.read("room.json"))
    assert room_export["schemaVersion"] == 6
    assert "condition" not in room_export
    assert room_export["mapGroup"]["name"] == map_group["name"]
    assert room_export["room"]["archiveReason"] == "completed"
    assert {item["sourceIndex"] for item in room_export["trialPlan"]["order"]} == {0, 1, 2}
    assert room_export["trialPlan"]["order"][0]["sourceIndex"] == 0

    questionnaire_export = json.loads(archive.read("questionnaire.json"))
    assert set(questionnaire_export["protectedQuestionIds"]) == PROTECTED_IDS
    assert len(questionnaire_export["responses"]) == 2
    for response in questionnaire_export["responses"]:
        assert set(response["answers"]) == {"q1", "q2"}
        assert PROTECTED_IDS.isdisjoint(response["answers"])

    payment_rows_zip = _read_csv(archive.read("payment.csv"))
    assert payment_rows_zip[0] == [
        "analysisCode",
        "basePayCents",
        "performancePayCents",
        "showupPayCents",
        "overrideAmountCents",
        "totalCents",
        "status",
        "computedAt",
        "deadlineAt",
        "paidAt",
        "note",
    ]
    assert len(payment_rows_zip) == 3
    assert {row[0] for row in payment_rows_zip[1:]} == analysis_codes
    for row in payment_rows_zip[1:]:
        assert row[1] == "4500"
        assert row[2] == str(PERFORMANCE_PAY_CENTS)
        assert row[5] == str(PAYMENT_TOTAL_CENTS)
        assert row[6] == "paid"

    for path in sorted(names):
        text = archive.read(path).decode("utf-8", errors="ignore")
        _assert_no_pii(
            text,
            [
                LOGIN_A[0],
                LOGIN_B[0],
                LOGIN_A[1],
                LOGIN_B[1],
                IDENTITY_A["real_name"],
                IDENTITY_A["alipay_phone"],
                IDENTITY_A["id_card"],
                IDENTITY_B["real_name"],
                IDENTITY_B["alipay_phone"],
                IDENTITY_B["passport"],
            ],
            f"分析压缩包文件 {path}",
        )

    second_room = create_room(
        admin,
        map_group["id"],
        instruction_a["id"],
        instruction_b["id"],
        questionnaire["id"],
        starts_in_seconds=60,
        label="复预约测试房间",
    )
    assert second_room["status"] == "open"
    rebook = participant_a.request("POST", f"/api/rooms/{second_room['id']}/book")
    assert rebook.status_code == 409
    assert rebook.json()["detail"] == "你已完成全部实验，无法再预约新的场次。"
    bookable_after = participant_a.json("GET", "/api/rooms/bookable")
    assert bookable_after["canBook"] is False
    assert all(item["canBook"] is False for item in bookable_after["rooms"])
    _assert_sections(admin, draft=0, open=1, in_progress=0, unpaid=0, archived=1)

    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    admin.close()


@pytest.mark.integration
def test_cancel_before_start_reopens_slot(server):
    admin = ApiClient(server.base_url).login_admin()
    create_consent(admin)
    profile = create_troop_profile(admin)
    map_group = create_map_group(admin, profile["id"])
    instruction_a = create_instruction(admin, map_group["id"], 1, "# 一", 0)
    instruction_b = create_instruction(admin, map_group["id"], 2, "# 二", 0)
    questionnaire = create_questionnaire(admin)
    room = create_room(
        admin,
        map_group["id"],
        instruction_a["id"],
        instruction_b["id"],
        questionnaire["id"],
        starts_in_seconds=30,
    )
    participant = ApiClient(server.base_url).login_participant("取消甲", "13900000001")
    participant.consent()
    booking = participant.json("POST", f"/api/rooms/{room['id']}/book")
    room_state = admin.json("GET", f"/admin/api/rooms/{room['id']}")["room"]
    assert room_state["bookedCount"] == 1
    assert room_state["status"] == "open"
    participant.json("POST", f"/api/bookings/{booking['booking']['id']}/cancel")
    room_state = admin.json("GET", f"/admin/api/rooms/{room['id']}")["room"]
    assert room_state["bookedCount"] == 0
    assert room_state["status"] == "open"
    bookable = participant.json("GET", "/api/rooms/bookable")
    bookable_room = next(item for item in bookable["rooms"] if item["id"] == room["id"])
    assert bookable_room["bookedCount"] == 0
    assert bookable_room["canBook"] is True
    _assert_sections(admin, draft=0, open=1, in_progress=0, unpaid=0, archived=0)
    participant.close()
    admin.close()
