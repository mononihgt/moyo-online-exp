import hashlib
import io
import json
import uuid
import zipfile
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from conftest import (
    ApiClient,
    WsClient,
    create_condition,
    create_consent,
    create_instruction,
    create_questionnaire,
    create_room,
    import_roster,
    wait_until,
)


def _owned_cell(board: dict, role: int) -> int:
    owned = [index for index, owner in enumerate(board["owners"]) if owner == role]
    return owned[0] if owned else 0


def _wait_instruction_completed(ws: WsClient) -> dict:
    for _ in range(30):
        message = ws.recv()
        if message.get("type") == "instruction_state" and message["instruction"]["completed"]:
            return message
    raise AssertionError("instruction did not complete")


def _receive_next_phase(ws: WsClient, wanted: set[str]) -> dict:
    for _ in range(60):
        message = ws.recv()
        if message.get("type") in wanted:
            return message
    raise AssertionError(f"did not receive any of {wanted}")


def _play_game(ws_a: WsClient, ws_b: WsClient, role_a: int, role_b: int) -> tuple[dict, dict]:
    turn_a = ws_a.recv_until("turn")
    turn_b = ws_b.recv_until("turn")
    while True:
        trial_index = turn_a["trialIndex"]
        round_number = turn_a["round"]
        for ws, role, board in (
            (ws_a, role_a, turn_a["board"]),
            (ws_b, role_b, turn_b["board"]),
        ):
            ws.send(
                "submit_selection",
                roomId=turn_a["roomId"],
                trialIndex=trial_index,
                round=round_number,
                cells=[_owned_cell(board, role)],
                clientMsgId=f"{role}-{trial_index}-{round_number}-{uuid.uuid4().hex[:6]}",
            )
        result_a = ws_a.recv_until("turn_result")
        result_b = ws_b.recv_until("turn_result")
        assert result_a["round"] == round_number
        assert len(result_a["board"]["owners"]) == 5 * 7
        if result_a["trialEnded"]:
            next_a = _receive_next_phase(ws_a, {"rest", "game_over"})
            next_b = _receive_next_phase(ws_b, {"rest", "game_over"})
            if next_a["type"] == "game_over":
                questionnaire_a = ws_a.recv_until("questionnaire_required")
                questionnaire_b = ws_b.recv_until("questionnaire_required")
                return questionnaire_a, questionnaire_b
            ws_a.send("rest_ready", roomId=turn_a["roomId"])
            ws_b.send("rest_ready", roomId=turn_a["roomId"])
            turn_a = ws_a.recv_until("turn")
            turn_b = ws_b.recv_until("turn")
            continue
        turn_a = ws_a.recv_until("turn")
        turn_b = ws_b.recv_until("turn")


def _extract_token(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return query["rt"][0]


@pytest.mark.integration
def test_full_two_participant_flow_and_exports(server):
    admin = ApiClient(server.base_url).login_admin()
    roster = import_roster(admin, [("被试甲", "13800000001"), ("被试乙", "13800000002")])
    assert roster["imported"] == 2
    create_consent(admin)
    instruction_1 = create_instruction(admin, 1, "# 玩家1\n\n你是圆形玩家。", 0)
    instruction_2 = create_instruction(admin, 2, "# 玩家2\n\n你是菱形玩家。", 0)
    questionnaire = create_questionnaire(admin)
    condition = create_condition(admin, rows=5, cols=7, practice=1, formal=2, turn_count=3, turn_seconds=4, rest_seconds=1)
    room = create_room(
        admin,
        condition_id=condition["id"],
        instruction_p1=instruction_1["id"],
        instruction_p2=instruction_2["id"],
        questionnaire_id=questionnaire["id"],
        starts_in_seconds=6,
    )
    room_id = room["id"]

    participant_a = ApiClient(server.base_url).login_participant("被试甲", "13800000001")
    participant_b = ApiClient(server.base_url).login_participant("被试乙", "13800000002")
    participant_a.consent()
    participant_b.consent()

    bookable = participant_a.json("GET", "/api/rooms/bookable")
    bookable_room = next(item for item in bookable["rooms"] if item["id"] == room_id)
    assert bookable_room["bookedCount"] == 0
    assert "internalLabel" not in bookable_room

    participant_a.json("POST", f"/api/rooms/{room_id}/book")
    second_booking_attempt = participant_a.request("POST", f"/api/rooms/{room_id}/book")
    assert second_booking_attempt.status_code == 409
    participant_b.json("POST", f"/api/rooms/{room_id}/book")
    room_list = participant_a.json("GET", "/api/rooms/bookable")
    assert next(item for item in room_list["rooms"] if item["id"] == room_id)["bookedCount"] == 2

    current = wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]
        if participant_a.json("GET", "/api/my-room")["room"]
        and participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting"
        else None,
        timeout=30,
    )
    assert current["canEnter"] is True

    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    ws_a.send("enter_room", roomId=room_id)
    ws_b.send("enter_room", roomId=room_id)
    state_a = ws_a.recv_until("room_state")
    state_b = ws_b.recv_until("room_state")
    assert state_a["role"] is None
    assert state_b["role"] is None
    wait_until(
        lambda: all(
            booking["attendedAt"] is not None
            for booking in admin.json("GET", f"/admin/api/rooms/{room_id}")["bookings"]
        ),
        timeout=10,
    )

    ws_a.send("start_matching", roomId=room_id)
    ws_b.send("start_matching", roomId=room_id)
    instruction_a = ws_a.recv_until("instruction_state")
    instruction_b = ws_b.recv_until("instruction_state")
    assert instruction_a["instruction"]["role"] in (1, 2)
    assert instruction_b["instruction"]["role"] in (1, 2)
    assert instruction_a["instruction"]["role"] != instruction_b["instruction"]["role"]
    role_a = instruction_a["instruction"]["role"]
    role_b = instruction_b["instruction"]["role"]

    snapshot = admin.json("GET", f"/admin/api/rooms/{room_id}")["configSnapshot"]
    assert snapshot["condition"]["rows"] == 5
    assert snapshot["condition"]["cols"] == 7
    locked_attempt = admin.request(
        "PATCH",
        f"/admin/api/rooms/{room_id}",
        json={"basePayCents": 2000},
    )
    assert locked_attempt.status_code == 409

    ws_a.send("instruction_complete", roomId=room_id)
    ws_b.send("instruction_complete", roomId=room_id)
    _wait_instruction_completed(ws_a)
    _wait_instruction_completed(ws_b)

    ws_a.send("enter_game", roomId=room_id)
    ws_b.send("enter_game", roomId=room_id)
    questionnaire_a, questionnaire_b = _play_game(ws_a, ws_b, role_a, role_b)
    assert questionnaire_a["url"] and questionnaire_b["url"]

    token_a = _extract_token(questionnaire_a["url"])
    token_b = _extract_token(questionnaire_b["url"])
    context_a = httpx.get(f"{server.base_url}/api/jatos/questionnaire", params={"token": token_a})
    assert context_a.status_code == 200
    assert context_a.json()["questionnaire"]["schema"]["title"] == "后测问卷"
    draft = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/draft",
        json={"token": token_a, "answers": {"q1": "female"}},
    )
    assert draft.status_code == 200

    for token, answer, worker in (
        (token_a, "female", "worker-a"),
        (token_b, "male", "worker-b"),
    ):
        study_id = f"study-{uuid.uuid4()}"
        component_id = f"component-{uuid.uuid4()}"
        complete = httpx.post(
            f"{server.base_url}/api/jatos/questionnaire/complete",
            json={
                "token": token,
                "answers": {"q1": answer, "q2": 4},
                "jatosWorkerId": worker,
                "jatosStudyResultId": study_id,
                "jatosComponentResultId": component_id,
            },
        )
        assert complete.status_code == 200, complete.text
        assert complete.json()["canonical"] is True
        repeat = httpx.post(
            f"{server.base_url}/api/jatos/questionnaire/complete",
            json={
                "token": token,
                "answers": {"q1": answer, "q2": 4},
                "jatosWorkerId": worker,
                "jatosStudyResultId": study_id,
                "jatosComponentResultId": component_id,
            },
        )
        assert repeat.status_code == 200
        assert repeat.json()["saved"] is True

    audit_attempt = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/complete",
        json={
            "token": token_a,
            "answers": {"q1": "male", "q2": 1},
            "jatosWorkerId": "worker-audit",
            "jatosStudyResultId": f"study-audit-{uuid.uuid4()}",
            "jatosComponentResultId": f"component-audit-{uuid.uuid4()}",
        },
    )
    assert audit_attempt.status_code == 200
    assert audit_attempt.json()["canonical"] is False

    room_detail = admin.json("GET", f"/admin/api/rooms/{room_id}")
    assert room_detail["room"]["status"] == "archived"
    assert room_detail["room"]["archiveReason"] == "completed"
    assert len(room_detail["payments"]) == 2
    assert len(room_detail["participants"]) == 2
    assert all(item["questionnaireStatus"] == "completed" for item in room_detail["participants"])

    experiment_a = participant_a.json("GET", "/api/my-experiments")["experiments"][0]
    assert experiment_a["roomStatus"] == "archived"
    assert experiment_a["completedAt"] is not None
    assert experiment_a["payment"]["status"] == "pending"
    participant_a_me = participant_a.json("GET", "/api/me")["me"]
    assert participant_a_me["status"] == "completed"
    assert participant_a_me["canBook"] is False

    duplicate_booking = participant_a.request("POST", f"/api/rooms/{room_id}/book")
    assert duplicate_booking.status_code in (403, 409)

    export_response = admin.request("GET", f"/admin/api/rooms/{room_id}/analysis.zip")
    assert export_response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(export_response.content))
    names = set(archive.namelist())
    for required in (
        "manifest.json",
        "room.json",
        "participants.csv",
        "turns.csv",
        "events.csv",
        "questionnaire.json",
        "payment.csv",
        "trials/trial0.json",
        "trials/trial1.json",
        "trials/trial2.json",
        "media/manifest.json",
    ):
        assert required in names
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["schemaVersion"] == 4
    assert manifest["containsPII"] is False
    assert manifest["rowCounts"]["participants"] == 2
    assert manifest["rowCounts"]["trials"] == 3
    for entry in manifest["files"]:
        data = archive.read(entry["path"])
        assert len(data) == entry["bytes"]
        assert "sha256:" + hashlib.sha256(data).hexdigest() == entry["sha256"]
    room_json = archive.read("room.json").decode("utf-8")
    for pii in ("被试甲", "被试乙", "13800000001", "13800000002"):
        assert pii not in room_json
        assert pii not in archive.read("participants.csv").decode("utf-8")
        assert pii not in archive.read("turns.csv").decode("utf-8")
        assert pii not in archive.read("events.csv").decode("utf-8")
        assert pii not in archive.read("questionnaire.json").decode("utf-8")
        assert pii not in archive.read("payment.csv").decode("utf-8")
    exported = json.loads(room_json)
    assert exported["schemaVersion"] == 4
    assert len(exported["condition"]["cells"]) == 35
    assert exported["trialPlan"]["order"][0] == 0
    assert exported["trials"][0]["isPractice"] is True
    assert exported["trials"][0]["initialState"]["rows"] == 5
    assert exported["trials"][0]["initialState"]["cols"] == 7
    assert len(exported["trials"][0]["initialState"]["owners"]) == 35
    assert len(exported["trials"][0]["turns"]) == 4
    assert exported["trials"][0]["completedRounds"] == 3
    for participant in exported["participants"]:
        assert participant["analysisCode"].startswith("P-")
        assert participant["questionnaire"]["answers"]["q1"] in ("female", "male")
    extra_attempts = [
        participant
        for participant in exported["participants"]
        if len(participant["questionnaire"]["attempts"]) > 1
    ]
    assert len(extra_attempts) == 1
    canonical_attempts = [item for item in extra_attempts[0]["questionnaire"]["attempts"] if item["canonical"]]
    assert len(canonical_attempts) == 1
    assert extra_attempts[0]["questionnaire"]["answers"]["q1"] == "female"

    payments = admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 2
    payment = payments[0]
    updated = admin.json(
        "PATCH",
        f"/admin/api/payments/{payment['id']}",
        json={"overrideAmountCents": 12345, "adminNote": "测试调整", "status": "paid"},
    )
    assert updated["payment"]["totalCents"] == 12345
    assert updated["payment"]["status"] == "paid"
    payment_csv = admin.request("GET", "/admin/api/payments/export.csv")
    assert payment_csv.status_code == 200
    text = payment_csv.content.decode("utf-8-sig")
    assert "被试甲" in text and "13800000001" in text
    assert "12345" in text
    audit = admin.json("GET", "/admin/api/audit")
    actions = {entry["action"] for entry in audit["entries"]}
    assert {"payments_exported", "payment_updated", "room_export_zip"} <= actions

    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    admin.close()


@pytest.mark.integration
def test_cancel_before_start_reopens_slot(server):
    admin = ApiClient(server.base_url).login_admin()
    import_roster(admin, [("取消甲", "13900000001"), ("取消乙", "13900000002")])
    create_consent(admin)
    instruction_1 = create_instruction(admin, 1, "# 一", 0)
    instruction_2 = create_instruction(admin, 2, "# 二", 0)
    questionnaire = create_questionnaire(admin)
    condition = create_condition(admin)
    room = create_room(
        admin,
        condition_id=condition["id"],
        instruction_p1=instruction_1["id"],
        instruction_p2=instruction_2["id"],
        questionnaire_id=questionnaire["id"],
        starts_in_seconds=30,
    )
    participant = ApiClient(server.base_url).login_participant("取消甲", "13900000001")
    participant.consent()
    booking = participant.json("POST", f"/api/rooms/{room['id']}/book")
    room_state = admin.json("GET", f"/admin/api/rooms/{room['id']}")["room"]
    assert room_state["bookedCount"] == 1
    participant.json("POST", f"/api/bookings/{booking['booking']['id']}/cancel")
    room_state = admin.json("GET", f"/admin/api/rooms/{room['id']}")["room"]
    assert room_state["bookedCount"] == 0
    assert room_state["status"] == "open"
    participant.close()
    admin.close()
