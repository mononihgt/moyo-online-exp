import io
import json
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from conftest import (
    ApiClient,
    WsClient,
    create_condition,
    execute_sql,
    import_roster,
    wait_until,
)
from test_runtime_flows import Context, _book, _enter_both, _start_game


def _owned_cell(board: dict, role: int) -> int:
    owned = [index for index, owner in enumerate(board["owners"]) if owner == role]
    return owned[0] if owned else 0


def _iso_to_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _wait_instruction_completed(ws: WsClient) -> dict:
    for _ in range(40):
        message = ws.recv()
        if message.get("type") == "instruction_state" and message["instruction"]["completed"]:
            return message
    raise AssertionError("instruction did not complete")


def _wait_partner_online(ws: WsClient, online: bool) -> dict:
    for _ in range(60):
        message = ws.recv()
        if message.get("type") == "partner_state" and message["partner"]["online"] is online:
            return message
    raise AssertionError(f"partner online state {online} did not arrive")


def _reach_instructions(context: Context, room, participant_a, participant_b):
    ws_a = WsClient(context.server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(context.server, participant_b.cookie_value("moyo_participant"))
    _enter_both(ws_a, ws_b, room["id"], context.admin)
    ws_a.send("start_matching", roomId=room["id"])
    ws_b.send("start_matching", roomId=room["id"])
    ws_a.recv_until("instruction_state")
    ws_b.recv_until("instruction_state")
    return ws_a, ws_b


def _token_from_url(url: str) -> str:
    return parse_qs(urlparse(url).query)["rt"][0]


def _reach_questionnaire(context: Context, room, participant_a, participant_b):
    ws_a, ws_b, role_a, role_b, turn_a, turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    for ws, role, turn in ((ws_a, role_a, turn_a), (ws_b, role_b, turn_b)):
        ws.send(
            "submit_selection",
            roomId=room["id"],
            trialIndex=turn["trialIndex"],
            round=turn["round"],
            cells=[_owned_cell(turn["board"], role)],
            clientMsgId=f"questionnaire-{role}-{uuid.uuid4().hex[:8]}",
        )
    questionnaire_a = ws_a.recv_until("questionnaire_required")
    questionnaire_b = ws_b.recv_until("questionnaire_required")
    return (
        ws_a,
        ws_b,
        _token_from_url(questionnaire_a["url"]),
        _token_from_url(questionnaire_b["url"]),
    )


def _completion_payload(token: str, *, answer: str = "female") -> dict:
    return {
        "token": token,
        "answers": {"q1": answer, "q2": 4},
        "jatosWorkerId": f"worker-{uuid.uuid4().hex[:8]}",
        "jatosStudyResultId": f"study-{uuid.uuid4()}",
        "jatosComponentResultId": f"component-{uuid.uuid4()}",
    }


@pytest.mark.integration
def test_concurrent_booking_respects_capacity(server):
    context = Context(server)
    import_roster(
        context.admin,
        [("已报甲", "13700000101"), ("抢位乙", "13700000102"), ("抢位丙", "13700000103")],
    )
    room = context.room(starts_in_seconds=60)
    participant_a = context.participant("已报甲", "13700000101")
    participant_b = context.participant("抢位乙", "13700000102")
    participant_c = context.participant("抢位丙", "13700000103")
    _book(context, room, participant_a)

    barrier = threading.Barrier(2)

    def book(client: ApiClient):
        barrier.wait()
        return client.request("POST", f"/api/rooms/{room['id']}/book")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(book, participant_b), pool.submit(book, participant_c)]
        responses = [future.result() for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 409]
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["bookedCount"] == 2
    assert detail["room"]["status"] == "full"

    for client in (participant_a, participant_b, participant_c):
        client.close()
    context.admin.close()


@pytest.mark.integration
def test_mark_absent_while_waiting_archives_no_show(server):
    context = Context(server)
    import_roster(context.admin, [("到场甲", "13700000111"), ("标记乙", "13700000112")])
    room = context.room(starts_in_seconds=2, wait_window_seconds=3)
    participant_a = context.participant("到场甲", "13700000111")
    participant_b = context.participant("标记乙", "13700000112")
    _book(context, room, participant_a, participant_b)
    wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting",
        timeout=20,
    )
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    _enter_both(ws_a, ws_b, room["id"], context.admin)
    booking_b = next(
        booking
        for booking in context.admin.json("GET", f"/admin/api/rooms/{room['id']}")["bookings"]
        if booking["name"] == "标记乙"
    )
    context.admin.json(
        "POST",
        f"/admin/api/rooms/{room['id']}/actions",
        json={"action": "mark_absent", "participantId": booking_b["participantId"]},
    )
    archived = ws_a.recv_until("room_archived", timeout=20)
    assert archived["reason"] == "no_show"
    assert archived["rewardKind"] == "none"
    assert context.admin.json("GET", "/admin/api/payments")["payments"] == []
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    statuses = {booking["name"]: booking["status"] for booking in detail["bookings"]}
    assert statuses["标记乙"] == "no_show"
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_mark_absent_after_technical_abort_keeps_existing_payment(server):
    context = Context(server)
    import_roster(context.admin, [("到场丙", "13700000121"), ("标记丁", "13700000122")])
    room = context.room(
        starts_in_seconds=2,
        turn_seconds=30,
        reconnect_window_seconds=2,
    )
    participant_a = context.participant("到场丙", "13700000121")
    participant_b = context.participant("标记丁", "13700000122")
    _book(context, room, participant_a, participant_b)
    wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting",
        timeout=20,
    )
    ws_a, ws_b, _role_a, _role_b, _turn_a, _turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    ws_b.close()
    archived = ws_a.recv_until("room_archived", timeout=20)
    assert archived["reason"] == "technical_abort"
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 2
    assert all(item["showupPayCents"] == 500 for item in payments)
    booking_b = next(
        booking
        for booking in context.admin.json("GET", f"/admin/api/rooms/{room['id']}")["bookings"]
        if booking["name"] == "标记丁"
    )
    result = context.admin.json(
        "POST",
        f"/admin/api/rooms/{room['id']}/actions",
        json={"action": "mark_absent", "participantId": booking_b["participantId"]},
    )
    assert result == {"ok": True}
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["archiveReason"] == "technical_abort"
    statuses = {booking["name"]: booking["status"] for booking in detail["bookings"]}
    assert statuses["标记丁"] == "no_show"
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 2
    by_name = {item["name"]: item for item in payments}
    assert by_name["到场丙"]["totalCents"] == 500
    assert by_name["标记丁"]["totalCents"] == 500
    assert by_name["标记丁"]["showupPayCents"] == 500
    ws_a.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_archived_condition_can_still_be_updated_and_copied(server):
    context = Context(server)
    condition = create_condition(context.admin, rows=3, cols=4, practice=0, formal=1)
    starts_at = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    room = context.admin.json(
        "POST",
        "/admin/api/rooms",
        json={
            "internalLabel": "Archived version room",
            "startsAt": starts_at,
            "conditionVersionId": condition["id"],
            "instructionVersionP1Id": context.instruction_1["id"],
            "instructionVersionP2Id": context.instruction_2["id"],
            "questionnaireVersionId": context.questionnaire["id"],
            "basePayCents": 1000,
            "performanceRateCents": 1,
            "showupPayCents": 500,
            "waitWindowSeconds": 900,
            "reconnectWindowSeconds": 600,
        },
    )["room"]
    create_condition(context.admin, rows=3, cols=4, practice=0, formal=1)
    patched = context.admin.request(
        "PATCH", f"/admin/api/rooms/{room['id']}", json={"internalLabel": "Updated room"}
    )
    assert patched.status_code == 200, patched.text
    published = context.admin.request("POST", f"/admin/api/rooms/{room['id']}/publish")
    assert published.status_code == 200, published.text
    copied = context.admin.request("POST", f"/admin/api/rooms/{room['id']}/copy", json={})
    assert copied.status_code == 200, copied.text
    assert copied.json()["room"]["condition"]["id"] == condition["id"]
    context.admin.close()


@pytest.mark.integration
def test_payment_status_patch_preserves_override_and_note(server):
    context = Context(server)
    import_roster(context.admin, [("付款甲", "13700000131"), ("付款乙", "13700000132")])
    room = context.room(starts_in_seconds=2, turn_seconds=30, reconnect_window_seconds=2)
    participant_a = context.participant("付款甲", "13700000131")
    participant_b = context.participant("付款乙", "13700000132")
    _book(context, room, participant_a, participant_b)
    wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting",
        timeout=20,
    )
    ws_a, ws_b, _role_a, _role_b, _turn_a, _turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    ws_b.close()
    ws_a.recv_until("room_archived", timeout=20)
    payment = next(
        item
        for item in context.admin.json("GET", "/admin/api/payments")["payments"]
        if item["roomId"] == room["id"]
    )
    updated = context.admin.json(
        "PATCH",
        f"/admin/api/payments/{payment['id']}",
        json={"overrideAmountCents": 12345, "adminNote": "调整金额", "status": "paid"},
    )["payment"]
    assert updated["totalCents"] == 12345
    status_only = context.admin.json(
        "PATCH", f"/admin/api/payments/{payment['id']}", json={"status": "paid"}
    )["payment"]
    assert status_only["overrideAmountCents"] == 12345
    assert status_only["note"] == "调整金额"
    assert status_only["totalCents"] == 12345
    note_only = context.admin.json(
        "PATCH", f"/admin/api/payments/{payment['id']}", json={"adminNote": "新备注"}
    )["payment"]
    assert note_only["overrideAmountCents"] == 12345
    assert note_only["note"] == "新备注"
    assert note_only["totalCents"] == 12345
    cleared = context.admin.json(
        "PATCH",
        f"/admin/api/payments/{payment['id']}",
        json={"overrideAmountCents": None, "adminNote": None},
    )["payment"]
    assert cleared["overrideAmountCents"] is None
    assert cleared["note"] is None
    assert cleared["totalCents"] == 500
    ws_a.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_import_reports_are_audited_without_names(server):
    context = Context(server)
    import_roster(context.admin, [("审计甲", "13700000141"), ("审计乙", "13700000142")])
    duplicate = context.admin.json(
        "POST",
        "/admin/api/participants/import",
        files={"file": ("roster.csv", "姓名,手机号\n审计甲,13700000141\n".encode(), "text/csv")},
    )
    assert duplicate["errors"][0]["name"] == "审计甲"
    completed = context.admin.json(
        "POST",
        "/admin/api/participants/import-completed",
        files={"file": ("completed.csv", "姓名,手机号\n审计乙,13700000142\n".encode(), "text/csv")},
    )
    assert completed["rows"][0]["name"] == "审计乙"
    audit = context.admin.json("GET", "/admin/api/audit?limit=500")["entries"]
    entries = [
        entry
        for entry in audit
        if entry["action"] in ("participants_import", "participants_import_completed")
    ]
    assert entries
    for entry in entries:
        payload_text = json.dumps(entry["payload"], ensure_ascii=False)
        assert "审计甲" not in payload_text
        assert "审计乙" not in payload_text
        for key in ("rows", "errors"):
            for row in entry["payload"].get(key, []):
                assert "name" not in row
    context.admin.close()


@pytest.mark.integration
def test_room_detail_exposes_jatos_admin_url(server):
    context = Context(server)
    room = context.room(starts_in_seconds=60)
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["jatosAdminUrl"] == "http://127.0.0.1:9000/jatos"
    assert detail["jatosStudyCode"] == "moyo-test"
    context.admin.close()


@pytest.mark.integration
def test_round_resolution_keeps_clock_paused_while_partner_offline(server):
    context = Context(server)
    import_roster(context.admin, [("结算甲", "13700000151"), ("离线乙", "13700000152")])
    room = context.room(
        starts_in_seconds=2, turn_seconds=3, turn_count=3, reconnect_window_seconds=30
    )
    participant_a = context.participant("结算甲", "13700000151")
    participant_b = context.participant("离线乙", "13700000152")
    _book(context, room, participant_a, participant_b)
    wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting",
        timeout=20,
    )
    ws_a, ws_b, role_a, role_b, turn_a, turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    ws_b.send(
        "submit_selection",
        roomId=room["id"],
        trialIndex=turn_b["trialIndex"],
        round=turn_b["round"],
        cells=[_owned_cell(turn_b["board"], role_b)],
        clientMsgId="offline-b-1",
    )
    ws_b.recv_until("turn")
    ws_b.close()
    wait_until(
        lambda: context.admin.json("GET", f"/admin/api/rooms/{room['id']}/monitor")["turnDeadline"]
        is None,
        timeout=10,
    )
    ws_a.send(
        "submit_selection",
        roomId=room["id"],
        trialIndex=turn_a["trialIndex"],
        round=turn_a["round"],
        cells=[_owned_cell(turn_a["board"], role_a)],
        clientMsgId="offline-a-1",
    )
    result = ws_a.recv_until("turn_result")
    assert result["nextRound"] == 2
    time.sleep(4)
    monitor = context.admin.json("GET", f"/admin/api/rooms/{room['id']}/monitor")
    assert monitor["round"] == 2
    assert monitor["turnDeadline"] is None
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    ws_b.send("enter_room", roomId=room["id"])
    state_b = ws_b.recv_until("room_state")
    assert state_b["game"]["turnDeadline"] is not None
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_game_start_keeps_disconnected_partner_paused(server):
    context = Context(server)
    import_roster(context.admin, [("入场甲", "13700000161"), ("入场乙", "13700000162")])
    room = context.room(starts_in_seconds=2, turn_seconds=30, reconnect_window_seconds=30)
    participant_a = context.participant("入场甲", "13700000161")
    participant_b = context.participant("入场乙", "13700000162")
    _book(context, room, participant_a, participant_b)
    wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting",
        timeout=20,
    )
    ws_a, ws_b = _reach_instructions(context, room, participant_a, participant_b)
    ws_a.send("instruction_complete", roomId=room["id"])
    ws_b.send("instruction_complete", roomId=room["id"])
    _wait_instruction_completed(ws_a)
    _wait_instruction_completed(ws_b)
    ws_a.send("enter_game", roomId=room["id"])
    time.sleep(0.5)
    ws_a.close()
    _wait_partner_online(ws_b, False)
    ws_b.send("enter_game", roomId=room["id"])
    turn_b = ws_b.recv_until("turn")
    assert turn_b["deadline"] is None
    monitor = context.admin.json("GET", f"/admin/api/rooms/{room['id']}/monitor")
    assert monitor["turnDeadline"] is None
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_a.send("enter_room", roomId=room["id"])
    state_a = ws_a.recv_until("room_state")
    assert state_a["game"]["turnDeadline"] is not None
    resumed_turn = ws_b.recv_until("turn")
    assert resumed_turn["deadline"] is not None
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_reconnect_during_rest_does_not_receive_turn(server):
    context = Context(server)
    import_roster(context.admin, [("休息甲", "13700000171"), ("重连乙", "13700000172")])
    room = context.room(
        starts_in_seconds=2,
        practice=0,
        formal=2,
        turn_count=1,
        turn_seconds=3,
        rest_seconds=5,
        reconnect_window_seconds=30,
    )
    participant_a = context.participant("休息甲", "13700000171")
    participant_b = context.participant("重连乙", "13700000172")
    _book(context, room, participant_a, participant_b)
    wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting",
        timeout=20,
    )
    ws_a, ws_b, role_a, role_b, turn_a, turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    for ws, role, turn in ((ws_a, role_a, turn_a), (ws_b, role_b, turn_b)):
        ws.send(
            "submit_selection",
            roomId=room["id"],
            trialIndex=turn["trialIndex"],
            round=turn["round"],
            cells=[_owned_cell(turn["board"], role)],
            clientMsgId=f"rest-{role}",
        )
    ws_a.recv_until("rest")
    rest_b = ws_b.recv_until("rest")
    ws_b.close()
    wait_until(
        lambda: context.admin.json("GET", f"/admin/api/rooms/{room['id']}/monitor")["restDeadline"]
        is None,
        timeout=10,
    )
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    ws_b.send("enter_room", roomId=room["id"])
    state_b = ws_b.recv_until("room_state")
    assert state_b["game"]["phase"] == "rest"
    assert state_b["game"]["restDeadline"] is not None
    assert state_b["game"]["finalSoldiers"] == rest_b["finalSoldiers"]
    assert set(state_b["game"]["finalSoldiers"]) == {"player1", "player2"}
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            message = ws_b.recv(timeout=0.3)
        except TimeoutError:
            break
        assert message.get("type") != "turn"
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_restart_preserves_instruction_seconds_and_reconnect_deadline(server):
    context = Context(server)
    import_roster(context.admin, [("重启甲", "13700000181"), ("重启乙", "13700000182")])
    room = context.room(starts_in_seconds=2, reconnect_window_seconds=30)
    participant_a = context.participant("重启甲", "13700000181")
    participant_b = context.participant("重启乙", "13700000182")
    _book(context, room, participant_a, participant_b)
    wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting",
        timeout=20,
    )
    ws_a, ws_b = _reach_instructions(context, room, participant_a, participant_b)
    time.sleep(6.5)
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    seconds_before = next(
        item["instructionConnectedSeconds"]
        for item in detail["participants"]
        if item["name"] == "重启甲"
    )
    assert seconds_before >= 5
    ws_b.close()
    due_before = wait_until(
        lambda: next(
            (
                item["disconnectedUntil"]
                for item in context.admin.json(
                    "GET", f"/admin/api/rooms/{room['id']}/monitor"
                )["participants"]
                if item["name"] == "重启乙"
            ),
            None,
        ),
        timeout=10,
    )
    time.sleep(2)
    ws_a.close()
    server.restart()
    admin = ApiClient(server.base_url).login_admin()
    monitor = admin.json("GET", f"/admin/api/rooms/{room['id']}/monitor")
    due_after = next(
        item["disconnectedUntil"]
        for item in monitor["participants"]
        if item["name"] == "重启乙"
    )
    assert abs((_iso_to_datetime(due_after) - _iso_to_datetime(due_before)).total_seconds()) < 1.5
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_a.send("enter_room", roomId=room["id"])
    ws_a.recv_until("room_state")
    detail = admin.json("GET", f"/admin/api/rooms/{room['id']}")
    seconds_after = next(
        item["instructionConnectedSeconds"]
        for item in detail["participants"]
        if item["name"] == "重启甲"
    )
    assert seconds_after >= seconds_before
    ws_a.close()
    participant_a.close()
    participant_b.close()
    admin.close()


@pytest.mark.integration
def test_concurrent_questionnaire_completion_keeps_single_canonical(server):
    context = Context(server)
    import_roster(context.admin, [("问卷甲", "13700000191"), ("问卷乙", "13700000192")])
    room = context.room(
        starts_in_seconds=2,
        practice=0,
        formal=1,
        turn_count=1,
        turn_seconds=3,
    )
    participant_a = context.participant("问卷甲", "13700000191")
    participant_b = context.participant("问卷乙", "13700000192")
    _book(context, room, participant_a, participant_b)
    wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting",
        timeout=20,
    )
    ws_a, ws_b, token_a, token_b = _reach_questionnaire(
        context, room, participant_a, participant_b
    )
    payloads = [_completion_payload(token_a), _completion_payload(token_a, answer="male")]

    def complete(payload: dict):
        return httpx.post(
            f"{server.base_url}/api/jatos/questionnaire/complete", json=payload, timeout=30
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(complete, payload) for payload in payloads]
        responses = [future.result() for future in futures]
    assert all(response.status_code == 200 for response in responses)
    assert sorted(response.json()["canonical"] for response in responses) == [False, True]
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["status"] == "questionnaire"
    complete_b = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/complete",
        json=_completion_payload(token_b),
        timeout=30,
    )
    assert complete_b.status_code == 200
    wait_until(
        lambda: context.admin.json("GET", f"/admin/api/rooms/{room['id']}")["room"]["status"]
        == "archived",
        timeout=20,
    )
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["archiveReason"] == "completed"
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_payment_export_filters_and_analysis_zip_keeps_all(server):
    context = Context(server)
    import_roster(
        context.admin, [("导出甲", "13700000211"), ("导出乙", "13700000212")]
    )
    room = context.room(starts_in_seconds=2, turn_seconds=30, reconnect_window_seconds=2)
    participant_a = context.participant("导出甲", "13700000211")
    participant_b = context.participant("导出乙", "13700000212")
    _book(context, room, participant_a, participant_b)
    wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting",
        timeout=20,
    )
    ws_a, ws_b, _role_a, _role_b, _turn_a, _turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    ws_b.close()
    archived = ws_a.recv_until("room_archived", timeout=20)
    assert archived["reason"] == "technical_abort"
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 2
    assert all(item["showupPayCents"] == 500 for item in payments)

    export = context.admin.request("GET", "/admin/api/payments/export.csv")
    assert export.status_code == 200
    text = export.content.decode("utf-8-sig")
    for value in ("导出甲", "13700000211", "导出乙", "13700000212"):
        assert value in text

    zip_response = context.admin.request(
        "GET", f"/admin/api/rooms/{room['id']}/analysis.zip"
    )
    assert zip_response.status_code == 200
    analysis = zipfile.ZipFile(io.BytesIO(zip_response.content))
    payment_csv = analysis.read("payment.csv").decode("utf-8-sig")
    assert len(payment_csv.strip().splitlines()) == 3

    execute_sql(
        "UPDATE rooms SET archive_reason = %s WHERE id = %s",
        ("admin_aborted", room["id"]),
    )
    filtered = context.admin.request("GET", "/admin/api/payments/export.csv")
    assert filtered.status_code == 200
    filtered_text = filtered.content.decode("utf-8-sig")
    assert "导出甲" not in filtered_text
    assert "13700000211" not in filtered_text
    assert len(filtered_text.strip().splitlines()) == 1

    zip_after = context.admin.request(
        "GET", f"/admin/api/rooms/{room['id']}/analysis.zip"
    )
    assert zip_after.status_code == 200
    analysis_after = zipfile.ZipFile(io.BytesIO(zip_after.content))
    payment_csv_after = analysis_after.read("payment.csv").decode("utf-8-sig")
    assert len(payment_csv_after.strip().splitlines()) == 3
    ws_a.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_concurrent_questionnaire_completion_archives_room(server):
    context = Context(server)
    import_roster(context.admin, [("并发甲", "13700000201"), ("并发乙", "13700000202")])
    room = context.room(
        starts_in_seconds=2,
        practice=0,
        formal=1,
        turn_count=1,
        turn_seconds=3,
    )
    participant_a = context.participant("并发甲", "13700000201")
    participant_b = context.participant("并发乙", "13700000202")
    _book(context, room, participant_a, participant_b)
    wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting",
        timeout=20,
    )
    ws_a, ws_b, token_a, token_b = _reach_questionnaire(
        context, room, participant_a, participant_b
    )

    def complete(payload: dict):
        return httpx.post(
            f"{server.base_url}/api/jatos/questionnaire/complete", json=payload, timeout=30
        )

    payloads = [_completion_payload(token_a), _completion_payload(token_b, answer="male")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(complete, payload) for payload in payloads]
        responses = [future.result() for future in futures]
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["canonical"] is True for response in responses)
    wait_until(
        lambda: context.admin.json("GET", f"/admin/api/rooms/{room['id']}")["room"]["status"]
        == "archived",
        timeout=20,
    )
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["archiveReason"] == "completed"
    assert all(
        item["questionnaireStatus"] == "completed" for item in detail["participants"]
    )
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()
