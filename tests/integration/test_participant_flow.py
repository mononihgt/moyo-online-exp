import time
import uuid

import httpx
import pytest
from conftest import WsClient, import_roster, wait_until
from test_review_regressions import (
    _completion_payload,
    _reach_instructions,
    _reach_questionnaire,
)
from test_runtime_flows import Context, _book, _enter_both, _start_game

COMPLETED_MESSAGE = "你已完成全部实验，无法再预约新的场次。"
PENDING_QUESTIONNAIRE_MESSAGE = (
    "你已完成本次正式实验，但后测问卷尚未提交。请先继续填写并提交问卷，目前无法预约新的场次。"
)


def _owned_cell(board: dict, role: int) -> int:
    owned = [index for index, owner in enumerate(board["owners"]) if owner == role]
    return owned[0] if owned else 0


@pytest.mark.integration
def test_exit_during_instructions_archives_abandoned_for_both(server):
    context = Context(server)
    import_roster(context.admin, [("指导甲", "13700000301"), ("指导乙", "13700000302")])
    room = context.room(starts_in_seconds=2, reconnect_window_seconds=30)
    participant_a = context.participant("指导甲", "13700000301")
    participant_b = context.participant("指导乙", "13700000302")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    _enter_both(ws_a, ws_b, room["id"], context.admin)
    ws_a.send("start_matching", roomId=room["id"])
    ws_b.send("start_matching", roomId=room["id"])
    ws_a.recv_until("instruction_state")
    ws_b.recv_until("instruction_state")
    ws_a.send("instruction_complete", roomId=room["id"])
    ws_b.send("instruction_complete", roomId=room["id"])
    state_a = ws_a.recv_until("room_state")
    assert state_a["self"]["canExit"] is True
    ws_a.send("exit_room", roomId=room["id"])
    archived_a = ws_a.recv_until("room_archived")
    assert archived_a["reason"] == "abandoned"
    assert archived_a["selfExited"] is True
    assert archived_a["selfQuestionnaireStatus"] == "not_started"
    assert archived_a["selfCompleted"] is False
    assert archived_a["canRebook"] is True
    assert archived_a["rewardKind"] == "none"
    archived_b = ws_b.recv_until("room_archived")
    assert archived_b["reason"] == "abandoned"
    assert archived_b["selfExited"] is False
    assert archived_b["canRebook"] is True
    assert archived_b["rewardKind"] == "none"
    state_a = ws_a.recv_until("room_state")
    assert state_a["archive"]["reason"] == "abandoned"
    assert state_a["archive"]["selfExited"] is True
    assert state_a["archive"]["canRebook"] is True
    assert state_a["archive"]["rewardKind"] == "none"
    assert state_a["self"]["canExit"] is False
    state_b = ws_b.recv_until("room_state")
    assert state_b["archive"]["selfExited"] is False
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert payments == []
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["status"] == "archived"
    assert detail["room"]["archiveReason"] == "abandoned"
    assert all(item["completedAt"] is None for item in detail["participants"])
    experiment_a = participant_a.json("GET", "/api/my-experiments")["experiments"][0]
    assert experiment_a["selfAttended"] is True
    assert experiment_a["selfExited"] is True
    assert experiment_a["canRebook"] is True
    assert experiment_a["rewardKind"] == "none"
    experiment_b = participant_b.json("GET", "/api/my-experiments")["experiments"][0]
    assert experiment_b["selfExited"] is False
    assert experiment_b["canRebook"] is True
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_exit_during_playing_archives_abandoned_and_archived_reconnect_views(server):
    context = Context(server)
    import_roster(context.admin, [("对局甲", "13700000311"), ("对局乙", "13700000312")])
    room = context.room(starts_in_seconds=2, turn_seconds=30, reconnect_window_seconds=30)
    participant_a = context.participant("对局甲", "13700000311")
    participant_b = context.participant("对局乙", "13700000312")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a, ws_b, _role_a, _role_b, _turn_a, _turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    ws_a.send("exit_room", roomId=room["id"])
    archived_a = ws_a.recv_until("room_archived")
    assert archived_a["reason"] == "abandoned"
    assert archived_a["selfExited"] is True
    archived_b = ws_b.recv_until("room_archived")
    assert archived_b["selfExited"] is False
    assert context.admin.json("GET", "/admin/api/payments")["payments"] == []

    new_room = context.room(starts_in_seconds=60, label="Rebook room")
    participant_a.json("POST", f"/api/rooms/{new_room['id']}/book")
    ws_a.close()
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    state_a = ws_a.recv_until("room_state")
    assert state_a["roomId"] == new_room["id"]
    assert state_a["status"] == "open"

    ws_b.close()
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    state_b = ws_b.recv_until("room_state")
    assert state_b["roomId"] == room["id"]
    assert state_b["status"] == "archived"
    assert state_b["archive"]["reason"] == "abandoned"
    assert state_b["archive"]["selfExited"] is False
    assert state_b["archive"]["selfQuestionnaireStatus"] == "not_started"
    assert state_b["archive"]["selfCompleted"] is False
    assert state_b["archive"]["canRebook"] is True
    assert state_b["archive"]["rewardKind"] == "none"
    archived_b = ws_b.recv_until("room_archived")
    assert archived_b["selfExited"] is False
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_exit_during_rest_archives_abandoned_without_payment(server):
    context = Context(server)
    import_roster(context.admin, [("休息甲", "13700000321"), ("休息乙", "13700000322")])
    room = context.room(
        starts_in_seconds=2,
        practice=0,
        formal=2,
        turn_count=1,
        turn_seconds=3,
        rest_seconds=30,
        reconnect_window_seconds=30,
    )
    participant_a = context.participant("休息甲", "13700000321")
    participant_b = context.participant("休息乙", "13700000322")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
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
            clientMsgId=f"rest-exit-{role}-{uuid.uuid4().hex[:6]}",
        )
    rest_a = ws_a.recv_until("rest")
    rest_b = ws_b.recv_until("rest")
    assert rest_a["trialIndex"] == 0
    assert rest_a["round"] == 1
    assert rest_b["trialIndex"] == 0
    assert rest_b["round"] == 1
    ws_b.send("exit_room", roomId=room["id"])
    archived_b = ws_b.recv_until("room_archived")
    assert archived_b["reason"] == "abandoned"
    assert archived_b["selfExited"] is True
    archived_a = ws_a.recv_until("room_archived")
    assert archived_a["selfExited"] is False
    assert context.admin.json("GET", "/admin/api/payments")["payments"] == []
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["archiveReason"] == "abandoned"
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_rest_messages_carry_trial_round_and_complete(server):
    context = Context(server)
    import_roster(context.admin, [("休息甲", "13700000801"), ("休息乙", "13700000802")])
    room = context.room(
        starts_in_seconds=2,
        practice=0,
        formal=2,
        turn_count=1,
        turn_seconds=3,
        rest_seconds=30,
    )
    participant_a = context.participant("休息甲", "13700000801")
    participant_b = context.participant("休息乙", "13700000802")
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
            clientMsgId=f"rest-complete-{role}-{uuid.uuid4().hex[:6]}",
        )
    rest_a = ws_a.recv_until("rest")
    rest_b = ws_b.recv_until("rest")
    assert rest_a["trialIndex"] == 0
    assert rest_a["round"] == 1
    assert rest_b["trialIndex"] == 0
    assert rest_b["round"] == 1
    ws_a.send("rest_ready", roomId=room["id"])
    ws_b.send("rest_ready", roomId=room["id"])
    complete_a = ws_a.recv_until("rest_complete")
    complete_b = ws_b.recv_until("rest_complete")
    assert complete_a["trialIndex"] == 0
    assert complete_a["round"] == 1
    assert complete_b["trialIndex"] == 0
    assert complete_b["round"] == 1
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_wait_expiry_no_start_when_both_attended(server):
    context = Context(server)
    import_roster(context.admin, [("未启甲", "13700000331"), ("未启乙", "13700000332")])
    room = context.room(starts_in_seconds=2, wait_window_seconds=5)
    participant_a = context.participant("未启甲", "13700000331")
    participant_b = context.participant("未启乙", "13700000332")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    my_room = participant_a.json("GET", "/api/my-room")
    assert my_room["room"]["bookingStatus"] == "booked"
    assert my_room["room"]["canCancel"] is False
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    _enter_both(ws_a, ws_b, room["id"], context.admin)
    my_room = participant_a.json("GET", "/api/my-room")
    assert my_room["room"]["bookingStatus"] == "attended"
    assert my_room["room"]["canCancel"] is False
    archived = ws_a.recv_until("room_archived", timeout=25)
    assert archived["reason"] == "no_start"
    assert archived["rewardKind"] == "none"
    assert archived["canRebook"] is True
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["archiveReason"] == "no_start"
    statuses = {booking["name"]: booking["status"] for booking in detail["bookings"]}
    assert statuses == {"未启甲": "attended", "未启乙": "attended"}
    assert context.admin.json("GET", "/admin/api/payments")["payments"] == []
    experiment = participant_a.json("GET", "/api/my-experiments")["experiments"][0]
    assert experiment["rewardKind"] == "none"
    assert experiment["canRebook"] is True
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_technical_abort_with_zero_showup_creates_no_payment(server):
    context = Context(server)
    import_roster(context.admin, [("零补甲", "13700000341"), ("零补乙", "13700000342")])
    room = context.room(
        starts_in_seconds=2,
        turn_seconds=30,
        reconnect_window_seconds=2,
        showup_pay_cents=0,
    )
    participant_a = context.participant("零补甲", "13700000341")
    participant_b = context.participant("零补乙", "13700000342")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a, ws_b, _role_a, _role_b, _turn_a, _turn_b = _start_game(
        context, room, participant_a, participant_b
    )
    ws_b.close()
    archived = ws_a.recv_until("room_archived", timeout=20)
    assert archived["reason"] == "technical_abort"
    assert archived["rewardKind"] == "none"
    assert archived["canRebook"] is True
    assert context.admin.json("GET", "/admin/api/payments")["payments"] == []
    experiment = participant_a.json("GET", "/api/my-experiments")["experiments"][0]
    assert experiment["rewardKind"] == "none"
    assert experiment["canRebook"] is True
    assert experiment["payment"] is None
    ws_a.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_admin_archive_reason_policy_by_stage(server):
    context = Context(server)
    room_before_start = context.room(starts_in_seconds=60, label="Before start")
    for reason in ("technical_abort", "admin_aborted", "completed", "not_full", "abandoned", "no_start", "no_show"):
        rejected = context.admin.request(
            "POST",
            f"/admin/api/rooms/{room_before_start['id']}/archive",
            json={"reason": reason},
        )
        assert rejected.status_code == 400, reason
    archived = context.admin.json(
        "POST", f"/admin/api/rooms/{room_before_start['id']}/archive", json={}
    )
    assert archived["room"]["archiveReason"] == "admin_cancelled"

    cancelled_room = context.room(starts_in_seconds=60, label="Cancel room")
    cancelled = context.admin.json("POST", f"/admin/api/rooms/{cancelled_room['id']}/cancel")
    assert cancelled["room"]["archiveReason"] == "admin_cancelled"

    started_room = context.room(starts_in_seconds=2, wait_window_seconds=60, label="After start")
    wait_until(
        lambda: context.admin.json("GET", f"/admin/api/rooms/{started_room['id']}")["room"]["status"]
        == "waiting",
        timeout=20,
    )
    late_cancel = context.admin.request("POST", f"/admin/api/rooms/{started_room['id']}/cancel")
    assert late_cancel.status_code == 409
    for reason in ("admin_cancelled", "technical_abort", "not_full"):
        rejected = context.admin.request(
            "POST",
            f"/admin/api/rooms/{started_room['id']}/archive",
            json={"reason": reason},
        )
        assert rejected.status_code == 400, reason
    started = context.admin.json(
        "POST",
        f"/admin/api/rooms/{started_room['id']}/archive",
        json={},
    )
    assert started["room"]["archiveReason"] == "admin_aborted"
    assert context.admin.json("GET", "/admin/api/payments")["payments"] == []
    context.admin.close()


@pytest.mark.integration
def test_admin_cancelled_room_enters_history_and_self_cancel_does_not(server):
    context = Context(server)
    import_roster(context.admin, [("取消甲", "13700000351")])
    participant = context.participant("取消甲", "13700000351")
    cancelled_room = context.room(starts_in_seconds=60, label="Admin cancelled")
    booking = participant.json("POST", f"/api/rooms/{cancelled_room['id']}/book")
    my_room = participant.json("GET", "/api/my-room")
    assert my_room["room"]["bookingStatus"] == "booked"
    assert my_room["room"]["canCancel"] is True
    assert my_room["room"]["canEnter"] is False
    context.admin.json("POST", f"/admin/api/rooms/{cancelled_room['id']}/cancel")
    experiments = participant.json("GET", "/api/my-experiments")["experiments"]
    assert len(experiments) == 1
    record = experiments[0]
    assert record["roomId"] == cancelled_room["id"]
    assert record["archiveReason"] == "admin_cancelled"
    assert record["bookingStatus"] == "canceled"
    assert record["selfAttended"] is False
    assert record["selfExited"] is False
    assert record["canRebook"] is True
    assert record["rewardKind"] == "none"
    assert record["payment"] is None
    ws = WsClient(server, participant.cookie_value("moyo_participant"))
    error = ws.recv_until("error")
    assert error["code"] == "no_active_room"
    ws.close()

    self_cancel_room = context.room(starts_in_seconds=60, label="Self cancel")
    self_booking = participant.json("POST", f"/api/rooms/{self_cancel_room['id']}/book")
    participant.json("POST", f"/api/bookings/{self_booking['booking']['id']}/cancel")
    experiments = participant.json("GET", "/api/my-experiments")["experiments"]
    assert [item["roomId"] for item in experiments] == [cancelled_room["id"]]
    assert booking["booking"]["roomId"] == cancelled_room["id"]

    rebook_room = context.room(starts_in_seconds=60, label="Rebook")
    participant.json("POST", f"/api/rooms/{rebook_room['id']}/book")
    my_room = participant.json("GET", "/api/my-room")
    assert my_room["room"]["roomId"] == rebook_room["id"]
    participant.close()
    context.admin.close()


@pytest.mark.integration
def test_questionnaire_incomplete_late_submission_and_lock(server):
    context = Context(server)
    import_roster(context.admin, [("补交甲", "13700000361"), ("补交乙", "13700000362")])
    room = context.room(
        starts_in_seconds=2,
        practice=0,
        formal=1,
        turn_count=1,
        turn_seconds=3,
    )
    participant_a = context.participant("补交甲", "13700000361")
    participant_b = context.participant("补交乙", "13700000362")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a, ws_b, token_a, token_b = _reach_questionnaire(
        context, room, participant_a, participant_b
    )
    assert token_a and token_b
    ws_a.close()
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    questionnaire_state = ws_a.recv_until("room_state")
    assert questionnaire_state["roomId"] == room["id"]
    assert questionnaire_state["status"] == "questionnaire"
    assert questionnaire_state["self"]["canExit"] is False
    ws_a.send("exit_room", roomId=room["id"])
    exit_error = ws_a.recv_until("error")
    assert exit_error["code"] == "invalid_state"
    context.admin.json(
        "POST",
        f"/admin/api/rooms/{room['id']}/actions",
        json={"action": "force_archive", "reason": "questionnaire_incomplete"},
    )
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["status"] == "archived"
    assert detail["room"]["archiveReason"] == "questionnaire_incomplete"
    assert all(item["completedAt"] is None for item in detail["participants"])
    assert context.admin.json("GET", "/admin/api/payments")["payments"] == []

    draft = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/draft",
        json={"token": token_a, "answers": {"q1": "female"}},
        timeout=30,
    )
    assert draft.status_code == 200
    payload_a = _completion_payload(token_a)
    complete_a = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/complete",
        json=payload_a,
        timeout=30,
    )
    assert complete_a.status_code == 200
    assert complete_a.json()["canonical"] is True
    repeated = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/complete",
        json=payload_a,
        timeout=30,
    )
    assert repeated.status_code == 200
    assert repeated.json()["saved"] is True

    me_a = participant_a.json("GET", "/api/me")["me"]
    assert me_a["status"] == "completed"
    assert me_a["isCompleted"] is True
    assert me_a["canBook"] is False
    assert me_a["hasPendingQuestionnaire"] is False
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["archiveReason"] == "questionnaire_incomplete"
    completed_by_name = {item["name"]: item["completedAt"] for item in detail["participants"]}
    assert completed_by_name["补交甲"] is not None
    assert completed_by_name["补交乙"] is None
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 1
    payment_a = payments[0]
    assert payment_a["name"] == "补交甲"
    assert payment_a["basePayCents"] == 1000
    assert payment_a["showupPayCents"] == 0
    assert payment_a["totalCents"] == payment_a["basePayCents"] + payment_a["performancePayCents"]
    assert payment_a["status"] == "pending"
    assert payment_a["deadlineAt"] is not None
    context_a = participant_a.json("GET", f"/api/questionnaire/context?roomId={room['id']}")
    assert context_a["submitted"] is True
    assert context_a["roomStatus"] == "archived"
    assert context_a["archiveReason"] == "questionnaire_incomplete"
    experiment_a = participant_a.json("GET", "/api/my-experiments")["experiments"][0]
    assert experiment_a["rewardKind"] == "completion"
    assert experiment_a["canRebook"] is False
    assert experiment_a["questionnaireStatus"] == "completed"
    assert experiment_a["payment"]["totalCents"] == payment_a["totalCents"]
    assert participant_a.json("GET", "/api/my-room")["pendingQuestionnaires"] == []
    blocked = participant_a.request("POST", f"/api/rooms/{room['id']}/book")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == COMPLETED_MESSAGE
    other_room = context.room(starts_in_seconds=60, label="Locked room")
    blocked = participant_a.request("POST", f"/api/rooms/{other_room['id']}/book")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == COMPLETED_MESSAGE
    admin_blocked = context.admin.request(
        "POST",
        f"/admin/api/rooms/{other_room['id']}/bookings",
        json={"participantId": me_a["id"]},
    )
    assert admin_blocked.status_code == 409
    assert admin_blocked.json()["detail"] == COMPLETED_MESSAGE

    me_b = participant_b.json("GET", "/api/me")["me"]
    assert me_b["status"] == "eligible"
    assert me_b["canBook"] is False
    assert me_b["hasPendingQuestionnaire"] is True
    pending_room = participant_b.json("GET", "/api/my-room")["pendingQuestionnaires"][0]
    assert pending_room["roomId"] == room["id"]
    assert pending_room["archiveReason"] == "questionnaire_incomplete"
    assert pending_room["canContinue"] is True
    blocked_b = participant_b.request("POST", f"/api/rooms/{other_room['id']}/book")
    assert blocked_b.status_code == 409
    assert blocked_b.json()["detail"] == PENDING_QUESTIONNAIRE_MESSAGE
    draft_b = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/draft",
        json={"token": token_b, "answers": {"q2": 5}},
        timeout=30,
    )
    assert draft_b.status_code == 200
    complete_b = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/complete",
        json=_completion_payload(token_b, answer="male"),
        timeout=30,
    )
    assert complete_b.status_code == 200
    assert complete_b.json()["canonical"] is True
    me_b = participant_b.json("GET", "/api/me")["me"]
    assert me_b["status"] == "completed"
    assert me_b["canBook"] is False
    detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["status"] == "archived"
    assert detail["room"]["archiveReason"] == "questionnaire_incomplete"
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 2
    assert {item["name"] for item in payments} == {"补交甲", "补交乙"}
    experiment_b = participant_b.json("GET", "/api/my-experiments")["experiments"][0]
    assert experiment_b["rewardKind"] == "completion"
    assert experiment_b["canRebook"] is False
    blocked_b = participant_b.request("POST", f"/api/rooms/{other_room['id']}/book")
    assert blocked_b.status_code == 409
    assert blocked_b.json()["detail"] == COMPLETED_MESSAGE
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_completed_questionnaire_creates_zero_payment_and_archives_completed(server):
    context = Context(server)
    import_roster(context.admin, [("零元甲", "13700000371"), ("零元乙", "13700000372")])
    room = context.room(
        starts_in_seconds=2,
        practice=0,
        formal=1,
        turn_count=1,
        turn_seconds=3,
        base_pay_cents=0,
        performance_rate_cents=0,
        showup_pay_cents=500,
    )
    participant_a = context.participant("零元甲", "13700000371")
    participant_b = context.participant("零元乙", "13700000372")
    _book(context, room, participant_a, participant_b)
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
    ws_a, ws_b, token_a, token_b = _reach_questionnaire(
        context, room, participant_a, participant_b
    )
    complete_a = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/complete",
        json=_completion_payload(token_a),
        timeout=30,
    )
    assert complete_a.status_code == 200
    assert complete_a.json()["canonical"] is True
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 1
    assert payments[0]["totalCents"] == 0
    assert payments[0]["basePayCents"] == 0
    assert payments[0]["performancePayCents"] == 0
    assert payments[0]["showupPayCents"] == 0
    complete_b = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/complete",
        json=_completion_payload(token_b, answer="male"),
        timeout=30,
    )
    assert complete_b.status_code == 200
    assert complete_b.json()["canonical"] is True
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
    payments = context.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 2
    assert {item["name"] for item in payments} == {"零元甲", "零元乙"}
    assert all(item["totalCents"] == 0 for item in payments)
    me = participant_b.json("GET", "/api/me")["me"]
    assert me["status"] == "completed"
    assert me["isCompleted"] is True
    assert me["canBook"] is False
    experiment = participant_a.json("GET", "/api/my-experiments")["experiments"][0]
    assert experiment["archiveReason"] == "completed"
    assert experiment["rewardKind"] == "completion"
    assert experiment["canRebook"] is False
    assert experiment["payment"]["totalCents"] == 0
    archived = ws_a.recv_until("room_archived", timeout=20)
    assert archived["reason"] == "completed"
    assert archived["selfCompleted"] is True
    assert archived["canRebook"] is False
    assert archived["rewardKind"] == "completion"
    export = context.admin.request("GET", "/admin/api/payments/export.csv")
    assert export.status_code == 200
    text = export.content.decode("utf-8-sig")
    assert "零元甲" in text and "零元乙" in text
    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()


@pytest.mark.integration
def test_instruction_clock_pauses_while_partner_disconnected(server):
    context = Context(server)
    import_roster(context.admin, [("暂停甲", "13700000901"), ("暂停乙", "13700000902")])
    room = context.room(
        starts_in_seconds=2,
        reconnect_window_seconds=30,
        min_reading_seconds=30,
    )
    participant_a = context.participant("暂停甲", "13700000901")
    participant_b = context.participant("暂停乙", "13700000902")
    _book(context, room, participant_a, participant_b)
    wait_until(
        lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting",
        timeout=20,
    )
    ws_a, ws_b = _reach_instructions(context, room, participant_a, participant_b)
    time.sleep(2)

    def seconds_for(name: str) -> int:
        detail = context.admin.json("GET", f"/admin/api/rooms/{room['id']}")
        return next(
            item["instructionConnectedSeconds"]
            for item in detail["participants"]
            if item["name"] == name
        )

    ws_b.close()
    wait_until(
        lambda: next(
            (
                item["disconnectedUntil"]
                for item in context.admin.json(
                    "GET", f"/admin/api/rooms/{room['id']}/monitor"
                )["participants"]
                if item["name"] == "暂停乙"
            ),
            None,
        ),
        timeout=10,
    )
    time.sleep(6)
    paused = seconds_for("暂停甲")
    assert paused >= 1
    time.sleep(3)
    assert seconds_for("暂停甲") <= paused + 1

    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    ws_b.send("enter_room", roomId=room["id"])
    ws_b.recv_until("room_state")
    time.sleep(6)
    assert seconds_for("暂停甲") >= paused + 2

    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    context.admin.close()
