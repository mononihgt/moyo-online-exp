import time
import uuid
from datetime import datetime, timezone

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


class Context:
    def __init__(self, server):
        self.server = server
        self.admin = ApiClient(server.base_url).login_admin()
        create_consent(self.admin)
        self.instruction_1 = create_instruction(self.admin, 1, "# 玩家1", 0)
        self.instruction_2 = create_instruction(self.admin, 2, "# 玩家2", 0)
        self.questionnaire = create_questionnaire(self.admin)

    def room(
        self,
        *,
        practice=0,
        formal=1,
        turn_count=3,
        turn_seconds=4,
        rest_seconds=1,
        starts_in_seconds=3,
        wait_window_seconds=30,
        reconnect_window_seconds=5,
        rows=3,
        cols=4,
        min_reading_seconds=None,
        label="Integration Room",
    ):
        if min_reading_seconds is not None:
            self.instruction_1 = create_instruction(self.admin, 1, "# 玩家1", min_reading_seconds)
            self.instruction_2 = create_instruction(self.admin, 2, "# 玩家2", min_reading_seconds)
        condition = create_condition(
            self.admin,
            rows=rows,
            cols=cols,
            practice=practice,
            formal=formal,
            turn_count=turn_count,
            turn_seconds=turn_seconds,
            rest_seconds=rest_seconds,
        )
        return create_room(
            self.admin,
            condition_id=condition["id"],
            instruction_p1=self.instruction_1["id"],
            instruction_p2=self.instruction_2["id"],
            questionnaire_id=self.questionnaire["id"],
            starts_in_seconds=starts_in_seconds,
            wait_window_seconds=wait_window_seconds,
            reconnect_window_seconds=reconnect_window_seconds,
            label=label,
        )

    def participant(self, name, phone, *, consent=True):
        client = ApiClient(self.server.base_url).login_participant(name, phone)
        if consent:
            client.consent()
        return client


def _enter_both(ws_a, ws_b, room_id, admin):
    ws_a.send("enter_room", roomId=room_id)
    ws_b.send("enter_room", roomId=room_id)
    ws_a.recv_until("room_state")
    ws_b.recv_until("room_state")
    wait_until(
        lambda: all(
            booking["attendedAt"] is not None
            for booking in admin.json("GET", f"/admin/api/rooms/{room_id}")["bookings"]
        ),
        timeout=10,
    )


def _start_game(context: Context, room, participant_a, participant_b, *, min_reading_seconds=0):
    ws_a = WsClient(context.server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(context.server, participant_b.cookie_value("moyo_participant"))
    _enter_both(ws_a, ws_b, room["id"], context.admin)
    ws_a.send("start_matching", roomId=room["id"])
    ws_b.send("start_matching", roomId=room["id"])
    instruction_a = ws_a.recv_until("instruction_state")
    instruction_b = ws_b.recv_until("instruction_state")
    if min_reading_seconds:
        ws_a.send("instruction_complete", roomId=room["id"])
        ws_b.send("instruction_complete", roomId=room["id"])
        error_a = ws_a.recv_until("error")
        error_b = ws_b.recv_until("error")
        assert error_a["code"] == "reading_incomplete"
        assert error_b["code"] == "reading_incomplete"
        time.sleep(min_reading_seconds + 0.2)
        ws_a.send("instruction_complete", roomId=room["id"])
        ws_b.send("instruction_complete", roomId=room["id"])
        for ws in (ws_a, ws_b):
            for _ in range(20):
                message = ws.recv()
                if message.get("type") == "instruction_state" and message["instruction"]["completed"]:
                    break
            else:
                raise AssertionError("instruction completion did not arrive")
    else:
        ws_a.send("instruction_complete", roomId=room["id"])
        ws_b.send("instruction_complete", roomId=room["id"])
        for ws in (ws_a, ws_b):
            for _ in range(20):
                message = ws.recv()
                if message.get("type") == "instruction_state" and message["instruction"]["completed"]:
                    break
            else:
                raise AssertionError("instruction completion did not arrive")
    ws_a.send("enter_game", roomId=room["id"])
    ws_b.send("enter_game", roomId=room["id"])
    turn_a = ws_a.recv_until("turn")
    turn_b = ws_b.recv_until("turn")
    return ws_a, ws_b, instruction_a["instruction"]["role"], instruction_b["instruction"]["role"], turn_a, turn_b


def _book(context: Context, room, *participants):
    for participant in participants:
        participant.json("POST", f"/api/rooms/{room['id']}/book")


def _close_participants(admin, *clients):
    for client in clients:
        client.close()
    admin.close()


@pytest.mark.integration
def test_wait_window_archives_not_full_and_showup_payment(server):
    context = Context(server)
    import_roster(context.admin, [("独行者", "13700000001")])
    room = context.room(starts_in_seconds=2, wait_window_seconds=2)
    participant = context.participant("独行者", "13700000001")
    _book(context, room, participant)
    wait_until(lambda: participant.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws = WsClient(server, participant.cookie_value("moyo_participant"))
    ws.send("enter_room", roomId=room["id"])
    state = ws.recv_until("room_state")
    assert state["bookedCount"] == 1
    archived = ws.recv_until("room_archived", timeout=20)
    assert archived["reason"] == "not_full"
    wait_until(
        lambda: context.admin.json("GET", f"/admin/api/rooms/{room['id']}")["room"]["status"] == "archived",
        timeout=10,
    )
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 1
    assert payments[0]["showupPayCents"] == 500
    assert payments[0]["totalCents"] == 500
    me = participant.json("GET", "/api/me")["me"]
    assert me["status"] == "eligible"
    new_room = context.room(starts_in_seconds=60)
    bookable = participant.json("GET", "/api/rooms/bookable")
    assert any(item["id"] == new_room["id"] and item["canBook"] for item in bookable["rooms"])
    participant.json("POST", f"/api/rooms/{new_room['id']}/book")
    ws.close()
    _close_participants(context.admin, participant)


@pytest.mark.integration
def test_two_bookings_one_absent_archives_no_show(server):
    context = Context(server)
    import_roster(context.admin, [("到场甲", "13700000011"), ("缺席乙", "13700000012")])
    room = context.room(starts_in_seconds=2, wait_window_seconds=2)
    participant_a = context.participant("到场甲", "13700000011")
    participant_b = context.participant("缺席乙", "13700000012")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws.send("enter_room", roomId=room["id"])
    ws.recv_until("room_state")
    ws.send("start_matching", roomId=room["id"])
    error = ws.recv_until("error")
    assert error["code"] == "partner_absent"
    archived = ws.recv_until("room_archived", timeout=20)
    assert archived["reason"] == "no_show"
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    by_name = {(item["name"]): item for item in payments}
    assert by_name["到场甲"]["showupPayCents"] == 500
    assert by_name["缺席乙"]["showupPayCents"] == 0
    assert by_name["缺席乙"]["totalCents"] == 0
    bookings = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")["bookings"]
    statuses = {booking["name"]: booking["status"] for booking in bookings}
    assert statuses["到场甲"] == "attended"
    assert statuses["缺席乙"] == "no_show"
    ws.close()
    _close_participants(context.admin, participant_a, participant_b)


@pytest.mark.integration
def test_participant_cannot_exit_when_partner_present(server):
    context = Context(server)
    import_roster(context.admin, [("退出甲", "13700000021"), ("搭档乙", "13700000022")])
    room = context.room(starts_in_seconds=2)
    participant_a = context.participant("退出甲", "13700000021")
    participant_b = context.participant("搭档乙", "13700000022")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    _enter_both(ws_a, ws_b, room["id"], context.admin)
    ws_a.send("exit_room", roomId=room["id"])
    error = ws_a.recv_until("error", timeout=10)
    assert error["code"] == "partner_present"
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["status"] == "waiting"
    assert participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting"
    ws_a.close()
    ws_b.close()
    _close_participants(context.admin, participant_a, participant_b)


@pytest.mark.integration
def test_participant_exit_with_absent_partner_archives_abandoned(server):
    context = Context(server)
    import_roster(context.admin, [("退出丙", "13700000023"), ("缺席丁", "13700000024")])
    room = context.room(starts_in_seconds=2)
    participant_a = context.participant("退出丙", "13700000023")
    participant_b = context.participant("缺席丁", "13700000024")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_a.send("enter_room", roomId=room["id"])
    state = ws_a.recv_until("room_state", timeout=10)
    assert state["partner"]["entered"] is False
    ws_a.send("exit_room", roomId=room["id"])
    archived = ws_a.recv_until("room_archived", timeout=10)
    assert archived["reason"] == "abandoned"
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    by_name = {item["name"]: item for item in payments}
    assert by_name["退出丙"]["showupPayCents"] == 500
    assert by_name["缺席丁"]["showupPayCents"] == 0
    assert participant_a.json("GET", "/api/my-room")["room"] is None
    ws_a.close()
    _close_participants(context.admin, participant_a, participant_b)


@pytest.mark.integration
def test_instruction_minimum_reading_and_config_lock(server):
    context = Context(server)
    import_roster(context.admin, [("阅读甲", "13700000031"), ("阅读乙", "13700000032")])
    room = context.room(starts_in_seconds=2, min_reading_seconds=2)
    participant_a = context.participant("阅读甲", "13700000031")
    participant_b = context.participant("阅读乙", "13700000032")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a, ws_b, role_a, role_b, turn_a, _turn_b = _start_game(
        context, room, participant_a, participant_b, min_reading_seconds=2
    )
    assert role_a != role_b
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["status"] == "playing"
    assert detail["configSnapshot"]["condition"]["turnCount"] == 3
    assert detail["configRevisions"]
    lock_attempt = context.admin.request(
        "PATCH", f"/admin/api/rooms/{room['id']}", json={"showupPayCents": 1}
    )
    assert lock_attempt.status_code == 409
    ws_a.close()
    ws_b.close()
    _close_participants(context.admin, participant_a, participant_b)


@pytest.mark.integration
def test_disconnect_pauses_turn_and_reconnect_resumes(server):
    context = Context(server)
    import_roster(context.admin, [("断线甲", "13700000041"), ("重连乙", "13700000042")])
    room = context.room(starts_in_seconds=2, turn_seconds=6, reconnect_window_seconds=10)
    participant_a = context.participant("断线甲", "13700000041")
    participant_b = context.participant("重连乙", "13700000042")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a, ws_b, role_a, role_b, turn_a, turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    owned = [index for index, owner in enumerate(turn_a["board"]["owners"]) if owner == role_a]
    ws_a.send(
        "submit_selection",
        roomId=room["id"],
        trialIndex=turn_a["trialIndex"],
        round=turn_a["round"],
        cells=[owned[0]],
        clientMsgId="disconnect-a-1",
    )
    ws_a.recv_until("turn")
    ws_b.close()
    wait_until(
        lambda: context.admin.json("GET", f"/admin/api/rooms/{room['id']}/monitor")["turnDeadline"] is None,
        timeout=10,
    )
    monitor = context.admin.json("GET", f"/admin/api/rooms/{room['id']}/monitor")
    assert any(entry["type"] == "disconnect" for entry in monitor["events"])
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    ws_b.send("enter_room", roomId=room["id"])
    state_b = ws_b.recv_until("room_state")
    assert state_b["game"]["turnDeadline"] is not None
    assert state_b["game"]["partnerSubmitted"] is True
    owned_b = [index for index, owner in enumerate(state_b["game"]["board"]["owners"]) if owner == role_b]
    ws_b.send(
        "submit_selection",
        roomId=room["id"],
        trialIndex=state_b["game"]["trialIndex"],
        round=state_b["game"]["round"],
        cells=[owned_b[0]],
        clientMsgId="disconnect-b-1",
    )
    result_a = ws_a.recv_until("turn_result")
    result_b = ws_b.recv_until("turn_result")
    assert result_a["round"] == result_b["round"] == 1
    ws_a.close()
    ws_b.close()
    _close_participants(context.admin, participant_a, participant_b)


@pytest.mark.integration
def test_reconnect_timeout_archives_technical_abort(server):
    context = Context(server)
    import_roster(context.admin, [("在线甲", "13700000051"), ("超时乙", "13700000052")])
    room = context.room(starts_in_seconds=2, turn_seconds=30, reconnect_window_seconds=2)
    participant_a = context.participant("在线甲", "13700000051")
    participant_b = context.participant("超时乙", "13700000052")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a, ws_b, _role_a, _role_b, _turn_a, _turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    ws_b.close()
    archived = ws_a.recv_until("room_archived", timeout=15)
    assert archived["reason"] == "technical_abort"
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["status"] == "archived"
    assert detail["room"]["archiveReason"] == "technical_abort"
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 2
    assert all(item["showupPayCents"] == 500 for item in payments)
    ws_a.close()
    _close_participants(context.admin, participant_a, participant_b)


@pytest.mark.integration
def test_server_restart_recovers_playing_room(server):
    context = Context(server)
    import_roster(context.admin, [("重启甲", "13700000061"), ("重启乙", "13700000062")])
    room = context.room(starts_in_seconds=2, turn_seconds=6, reconnect_window_seconds=30)
    participant_a = context.participant("重启甲", "13700000061")
    participant_b = context.participant("重启乙", "13700000062")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a, ws_b, role_a, role_b, turn_a, _turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    owned = [index for index, owner in enumerate(turn_a["board"]["owners"]) if owner == role_a]
    ws_a.send(
        "submit_selection",
        roomId=room["id"],
        trialIndex=turn_a["trialIndex"],
        round=turn_a["round"],
        cells=[owned[0]],
        clientMsgId="restart-a-1",
    )
    ws_a.send("ping")
    assert ws_a.recv_until("pong")["type"] == "pong"
    ws_a.close()
    ws_b.close()
    server.restart()

    admin = ApiClient(server.base_url).login_admin()
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    ws_a.send("enter_room", roomId=room["id"])
    ws_b.send("enter_room", roomId=room["id"])
    state_a = ws_a.recv_until("room_state")
    state_b = ws_b.recv_until("room_state")
    assert state_a["status"] == "playing"
    assert state_a["game"]["submitted"] is True
    assert state_b["game"]["partnerSubmitted"] is True
    assert state_b["game"]["turnDeadline"] is not None
    deadline = datetime.fromisoformat(state_b["game"]["turnDeadline"].replace("Z", "+00:00"))
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
    assert 3 <= remaining <= 7
    owned_b = [index for index, owner in enumerate(state_b["game"]["board"]["owners"]) if owner == role_b]
    ws_b.send(
        "submit_selection",
        roomId=room["id"],
        trialIndex=state_b["game"]["trialIndex"],
        round=state_b["game"]["round"],
        cells=[owned_b[0]],
        clientMsgId="restart-b-1",
    )
    result_a = ws_a.recv_until("turn_result")
    result_b = ws_b.recv_until("turn_result")
    assert result_a["round"] == result_b["round"] == 1
    monitor = admin.json("GET", f"/admin/api/rooms/{room['id']}/monitor")
    assert any(entry["type"] == "server_restart" for entry in monitor["events"])
    ws_a.close()
    ws_b.close()
    _close_participants(admin, participant_a, participant_b)


@pytest.mark.integration
def test_questionnaire_pending_allows_new_booking_and_manual_archive(server):
    context = Context(server)
    import_roster(context.admin, [("问卷甲", "13700000071"), ("问卷乙", "13700000072")])
    room = context.room(starts_in_seconds=2, turn_seconds=3)
    participant_a = context.participant("问卷甲", "13700000071")
    participant_b = context.participant("问卷乙", "13700000072")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a, ws_b, role_a, role_b, turn_a, turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    for _ in range(10):
        owned_a = [index for index, owner in enumerate(turn_a["board"]["owners"]) if owner == role_a]
        owned_b = [index for index, owner in enumerate(turn_b["board"]["owners"]) if owner == role_b]
        for ws, cells, role in ((ws_a, owned_a, role_a), (ws_b, owned_b, role_b)):
            ws.send(
                "submit_selection",
                roomId=room["id"],
                trialIndex=turn_a["trialIndex"],
                round=turn_a["round"],
                cells=[cells[0]],
                clientMsgId=f"manual-{role}-{turn_a['round']}-{uuid.uuid4().hex[:4]}",
            )
        result = ws_a.recv_until("turn_result")
        ws_b.recv_until("turn_result")
        if result["trialEnded"]:
            break
        turn_a = ws_a.recv_until("turn")
        turn_b = ws_b.recv_until("turn")
    ws_a.recv_until("questionnaire_required")
    ws_b.recv_until("questionnaire_required")
    room_state = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")["room"]
    assert room_state["status"] == "questionnaire"

    new_room = context.room(starts_in_seconds=60, label="Second room")
    participant_a.json("POST", f"/api/rooms/{new_room['id']}/book")
    my_room = participant_a.json("GET", "/api/my-room")
    assert my_room["room"]["roomId"] == new_room["id"]
    assert my_room["pendingQuestionnaires"][0]["roomId"] == room["id"]
    links = context.admin.json(
        "POST", f"/admin/api/rooms/{room['id']}/actions", json={"action": "resend_questionnaire"}
    )
    assert len(links["links"]) == 2
    old_context = participant_a.json("GET", f"/api/questionnaire/context?roomId={room['id']}")
    assert old_context["roomId"] == room["id"]
    assert old_context["url"]
    participant_me = participant_a.json("GET", "/api/me")["me"]
    assert participant_me["status"] == "eligible"

    context.admin.json(
        "POST",
        f"/admin/api/rooms/{room['id']}/actions",
        json={"action": "force_archive", "reason": "questionnaire_incomplete"},
    )
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["status"] == "archived"
    assert detail["room"]["archiveReason"] == "questionnaire_incomplete"
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert all(item["status"] == "pending" for item in payments)
    assert all(item["showupPayCents"] == 500 for item in payments)
    participant_me = participant_a.json("GET", "/api/me")["me"]
    assert participant_me["status"] == "eligible"
    ws_a.close()
    ws_b.close()
    _close_participants(context.admin, participant_a, participant_b)


@pytest.mark.integration
def test_admin_extend_wait_add_remove_booking_and_force_archive(server):
    context = Context(server)
    import_roster(context.admin, [("等待甲", "13700000081"), ("等待乙", "13700000082")])
    room = context.room(starts_in_seconds=2, wait_window_seconds=2)
    participant_a = context.participant("等待甲", "13700000081")
    participant_b = context.participant("等待乙", "13700000082")
    participant_a.json("POST", f"/api/rooms/{room['id']}/book")
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    context.admin.json(
        "POST",
        f"/admin/api/rooms/{room['id']}/actions",
        json={"action": "extend_wait", "minutes": 2},
    )
    time.sleep(2.2)
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")["room"]
    assert detail["status"] == "waiting"

    context.admin.json(
        "POST",
        f"/admin/api/rooms/{room['id']}/bookings",
        json={"participantId": participant_b.json("GET", "/api/me")["me"]["id"]},
    )
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["bookedCount"] == 2
    booking_b = next(item for item in detail["bookings"] if item["name"] == "等待乙")
    context.admin.json(
        "DELETE", f"/admin/api/rooms/{room['id']}/bookings/{booking_b['id']}"
    )
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["bookedCount"] == 1
    context.admin.json(
        "POST",
        f"/admin/api/rooms/{room['id']}/actions",
        json={"action": "force_archive", "reason": "technical_abort"},
    )
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["status"] == "archived"
    assert detail["room"]["archiveReason"] == "technical_abort"
    _close_participants(context.admin, participant_a, participant_b)


@pytest.mark.integration
def test_turn_timeout_auto_selects_for_both_players(server):
    context = Context(server)
    import_roster(context.admin, [("超时甲", "13700000091"), ("超时乙", "13700000092")])
    room = context.room(starts_in_seconds=2, turn_seconds=1, reconnect_window_seconds=10)
    participant_a = context.participant("超时甲", "13700000091")
    participant_b = context.participant("超时乙", "13700000092")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a, ws_b, _role_a, _role_b, _turn_a, _turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    result_a = ws_a.recv_until("turn_result", timeout=15)
    result_b = ws_b.recv_until("turn_result", timeout=15)
    assert result_a["autoSelected"] == {"player1": True, "player2": True}
    assert result_b["autoSelected"] == {"player1": True, "player2": True}
    assert result_a["selectionSources"] == {"player1": "timeout", "player2": "timeout"}
    assert len(result_a["selections"]["player1"]) == 1
    assert len(result_a["selections"]["player2"]) == 1
    assert result_a["round"] == 1
    ws_a.close()
    ws_b.close()
    _close_participants(context.admin, participant_a, participant_b)
