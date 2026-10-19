import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from conftest import (
    ApiClient,
    WsClient,
    create_consent,
    create_instruction,
    create_map_group,
    create_questionnaire,
    create_room,
    create_troop_profile,
    import_roster,
    questionnaire_answers,
    valid_identity_answers,
    wait_until,
)

COMPLETED_MESSAGE = "你已完成全部实验，无法再预约新的场次。"
PENDING_QUESTIONNAIRE_MESSAGE = (
    "你已完成本次正式实验，但后测问卷尚未提交。请先继续填写并提交问卷，目前无法预约新的场次。"
)
FAST_PROFILE_ROWS = [
    {"soldiersA": 5, "soldiersB": 5},
    {"soldiersA": 3, "soldiersB": 4},
]
IDENTITY_A = valid_identity_answers("流程甲", phone="13900002001")
IDENTITY_B = valid_identity_answers("流程乙", phone="13900002002")


class Setup:
    def __init__(self, server, *, rest_seconds=1):
        self.server = server
        self.admin = ApiClient(server.base_url).login_admin()
        create_consent(self.admin)
        self.profile = create_troop_profile(self.admin, FAST_PROFILE_ROWS)
        self.questionnaire = create_questionnaire(self.admin)
        self.map_group = create_map_group(
            self.admin,
            self.profile["id"],
            rows=2,
            cols=2,
            formal_trials=1,
            description="流程地图",
            practice_turn_cap=1,
            practice_turn_seconds=2,
            formal_turn_cap=1,
            formal_turn_seconds=2,
            rest_seconds=rest_seconds,
        )
        self.instruction_a = create_instruction(
            self.admin, self.map_group["id"], 1, "# 玩家一\n\n测试指导语", 0
        )
        self.instruction_b = create_instruction(
            self.admin, self.map_group["id"], 2, "# 玩家二\n\n测试指导语", 0
        )

    def room(
        self,
        *,
        starts_in_seconds=3,
        wait_window_seconds=60,
        reconnect_window_seconds=5,
        publish=True,
        label="流程房间",
    ):
        return create_room(
            self.admin,
            self.map_group["id"],
            self.instruction_a["id"],
            self.instruction_b["id"],
            self.questionnaire["id"],
            starts_in_seconds=starts_in_seconds,
            wait_window_seconds=wait_window_seconds,
            reconnect_window_seconds=reconnect_window_seconds,
            label=label,
            publish=publish,
        )

    def close(self):
        self.admin.close()


def _login(server, admin, accounts):
    import_roster(admin, accounts)
    clients = []
    for name, phone in accounts:
        client = ApiClient(server.base_url).login_participant(name, phone)
        client.consent()
        clients.append(client)
    return clients


def _my_room(client):
    return client.json("GET", "/api/my-room")["room"]


def _wait_my_room_status(client, status, timeout=30):
    wait_until(lambda: (_my_room(client) or {}).get("status") == status, timeout=timeout)
    return _my_room(client)


def _owned_cell(board, role):
    for index, owner in enumerate(board["owners"]):
        if owner == role:
            return index
    raise AssertionError(f"玩家 {role} 在棋盘上没有领地")


def _wait_instruction_completed(ws):
    for _ in range(80):
        message = ws.recv()
        if message.get("type") == "error":
            raise AssertionError(f"websocket error: {message}")
        if message.get("type") == "instruction_state" and message["instruction"]["completed"]:
            return message
    raise AssertionError("指导语未完成")


def _enter_both(ws_a, ws_b, admin, room_id):
    ws_a.send("enter_room", roomId=room_id)
    ws_b.send("enter_room", roomId=room_id)
    ws_a.recv_until("room_state")
    ws_b.recv_until("room_state")
    wait_until(
        lambda: all(
            booking["status"] == "attended"
            for booking in admin.json("GET", f"/admin/api/rooms/{room_id}")["bookings"]
        ),
        timeout=10,
    )


def _start_instructions(ws_a, ws_b, room_id):
    ws_a.send("start_matching", roomId=room_id)
    ws_b.send("start_matching", roomId=room_id)
    state_a = ws_a.recv_until("instruction_state")
    state_b = ws_b.recv_until("instruction_state")
    return state_a["instruction"]["role"], state_b["instruction"]["role"]


def _complete_instructions(ws_a, ws_b, room_id):
    ws_a.send("instruction_complete", roomId=room_id)
    ws_b.send("instruction_complete", roomId=room_id)
    _wait_instruction_completed(ws_a)
    _wait_instruction_completed(ws_b)


def _reach_questionnaire(ws_a, ws_b, room_id, role_a, role_b, total_trials=2):
    ws_a.send("enter_game", roomId=room_id)
    ws_b.send("enter_game", roomId=room_id)
    for trial_index in range(total_trials):
        ws_a.recv_until("trial_start")
        ws_b.recv_until("trial_start")
        turn_a = ws_a.recv_until("turn")
        turn_b = ws_b.recv_until("turn")
        for ws, role, turn in ((ws_a, role_a, turn_a), (ws_b, role_b, turn_b)):
            ws.send(
                "submit_selection",
                roomId=room_id,
                trialIndex=turn["trialIndex"],
                round=turn["round"],
                cells=[_owned_cell(turn["board"], role)],
                clientMsgId=f"flow-{trial_index}-{role}-{uuid.uuid4().hex[:8]}",
            )
        result_a = ws_a.recv_until("turn_result")
        ws_b.recv_until("turn_result")
        assert result_a["trialEnded"] is True
        if trial_index + 1 < total_trials:
            ws_a.recv_until("rest")
            ws_b.recv_until("rest")
            ws_a.send("rest_ready", roomId=room_id)
            ws_b.send("rest_ready", roomId=room_id)
            ws_a.recv_until("rest_complete")
            ws_b.recv_until("rest_complete")
    questionnaire_a = ws_a.recv_until("questionnaire_required")
    questionnaire_b = ws_b.recv_until("questionnaire_required")
    return questionnaire_a, questionnaire_b


def _play_to_questionnaire(server, setup, room, participant_a, participant_b):
    _wait_my_room_status(participant_a, "waiting")
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    _enter_both(ws_a, ws_b, setup.admin, room["id"])
    role_a, role_b = _start_instructions(ws_a, ws_b, room["id"])
    _complete_instructions(ws_a, ws_b, room["id"])
    questionnaire_a, questionnaire_b = _reach_questionnaire(
        ws_a, ws_b, room["id"], role_a, role_b
    )
    return ws_a, ws_b, questionnaire_a, questionnaire_b


def _token(url):
    return parse_qs(urlparse(url).query)["rt"][0]


def _complete_payload(room_id, identity, **answers):
    return {
        "roomId": room_id,
        "answers": questionnaire_answers(identity, **answers),
        "jatosWorkerId": f"worker-{uuid.uuid4().hex[:8]}",
        "jatosStudyResultId": f"study-{uuid.uuid4()}",
        "jatosComponentResultId": f"component-{uuid.uuid4()}",
    }


def _section_counts(admin):
    return admin.json("GET", "/admin/api/rooms")["counts"]


def _section_room_ids(admin, section):
    rooms = admin.json("GET", "/admin/api/rooms", params={"section": section})["rooms"]
    return {item["id"] for item in rooms}


def _assert_counts(admin, **expected):
    counts = _section_counts(admin)
    assert set(counts) == {"draft", "open", "in_progress", "unpaid", "archived"}
    for key, value in expected.items():
        assert counts[key] == value, f"分区 {key} 期望 {value}，实际 {counts[key]}"


@pytest.mark.integration
def test_booking_capacity_and_bookable_rules(server):
    setup = Setup(server)
    participant_a, participant_b, participant_c = _login(
        server,
        setup.admin,
        [("预约甲", "13700001011"), ("预约乙", "13700001012"), ("预约丙", "13700001013")],
    )
    draft = setup.room(starts_in_seconds=180, publish=False, label="草稿房间")
    first = setup.room(starts_in_seconds=60, label="第一场")
    second = setup.room(starts_in_seconds=120, label="第二场")
    started = setup.room(starts_in_seconds=3, label="已开始房间")

    bookable = participant_a.json("GET", "/api/rooms/bookable")
    listed_ids = {item["id"] for item in bookable["rooms"]}
    assert draft["id"] not in listed_ids
    assert {first["id"], second["id"]} <= listed_ids
    first_item = next(item for item in bookable["rooms"] if item["id"] == first["id"])
    assert first_item["capacity"] == 2
    assert first_item["bookedCount"] == 0
    assert first_item["canBook"] is True
    assert first_item["full"] is False
    assert "internalLabel" not in first_item
    assert bookable["canBook"] is True
    assert bookable["serverNow"]
    assert bookable["timezone"]

    wait_until(
        lambda: started["id"]
        not in {item["id"] for item in participant_a.json("GET", "/api/rooms/bookable")["rooms"]},
        timeout=15,
    )

    booking_a = participant_a.json("POST", f"/api/rooms/{first['id']}/book")
    assert booking_a["bookedCount"] == 1
    assert booking_a["roomStatus"] == "open"
    assert booking_a["capacity"] == 2
    repeat = participant_a.request("POST", f"/api/rooms/{first['id']}/book")
    assert repeat.status_code == 409

    booking_b = participant_b.json("POST", f"/api/rooms/{first['id']}/book")
    assert booking_b["bookedCount"] == 2
    assert booking_b["roomStatus"] == "full"
    full_item = next(
        item
        for item in participant_c.json("GET", "/api/rooms/bookable")["rooms"]
        if item["id"] == first["id"]
    )
    assert full_item["full"] is True
    assert full_item["canBook"] is False
    over_capacity = participant_c.request("POST", f"/api/rooms/{first['id']}/book")
    assert over_capacity.status_code == 409
    assert over_capacity.json()["detail"] == "该房间已满"

    other_room = participant_a.request("POST", f"/api/rooms/{second['id']}/book")
    assert other_room.status_code == 409
    assert other_room.json()["detail"] == "你已有有效预约，请先取消当前预约"

    participant_a.json("POST", f"/api/bookings/{booking_a['booking']['id']}/cancel")
    detail = setup.admin.json("GET", f"/admin/api/rooms/{first['id']}")
    assert detail["room"]["bookedCount"] == 1
    assert detail["room"]["status"] == "open"
    reopened = next(
        item
        for item in participant_c.json("GET", "/api/rooms/bookable")["rooms"]
        if item["id"] == first["id"]
    )
    assert reopened["canBook"] is True
    assert reopened["bookedCount"] == 1
    participant_c.json("POST", f"/api/rooms/{first['id']}/book")
    assert (
        setup.admin.json("GET", f"/admin/api/rooms/{first['id']}")["room"]["status"] == "full"
    )
    second_booking = participant_a.json("POST", f"/api/rooms/{second['id']}/book")
    assert second_booking["bookedCount"] == 1

    for client in (participant_a, participant_b, participant_c):
        client.close()
    setup.close()


@pytest.mark.integration
def test_room_lifecycle_publish_close_and_config_revisions(server):
    setup = Setup(server)
    participant_a, participant_b = _login(
        server, setup.admin, [("周期甲", "13700001021"), ("周期乙", "13700001022")]
    )
    room = setup.room(starts_in_seconds=180, publish=False, label="生命周期房间")
    room_id = room["id"]
    assert room["status"] == "draft"
    _assert_counts(setup.admin, draft=1, open=0, in_progress=0, unpaid=0, archived=0)
    assert room_id in _section_room_ids(setup.admin, "draft")
    assert room_id not in {
        item["id"] for item in participant_a.json("GET", "/api/rooms/bookable")["rooms"]
    }

    draft_close = setup.admin.request("POST", f"/admin/api/rooms/{room_id}/close-booking")
    assert draft_close.status_code == 409

    new_start = (datetime.now(timezone.utc) + timedelta(seconds=240)).isoformat().replace(
        "+00:00", "Z"
    )
    published = setup.admin.json("POST", f"/admin/api/rooms/{room_id}/publish")["room"]
    assert published["status"] == "open"
    _assert_counts(setup.admin, draft=0, open=1, in_progress=0, unpaid=0, archived=0)
    second_publish = setup.admin.request("POST", f"/admin/api/rooms/{room_id}/publish")
    assert second_publish.status_code == 409
    assert second_publish.json()["detail"] == "只有草稿房间可以开放预约"

    starts_locked = setup.admin.request(
        "PATCH", f"/admin/api/rooms/{room_id}", json={"startsAt": new_start}
    )
    assert starts_locked.status_code == 409
    assert starts_locked.json()["detail"] == "仅草稿房间可以修改开始时间"

    revisions_before = setup.admin.json("GET", f"/admin/api/rooms/{room_id}")["configRevisions"]
    configured = setup.admin.json(
        "PATCH", f"/admin/api/rooms/{room_id}", json={"waitWindowSeconds": 45}
    )["room"]
    assert configured["waitWindowSeconds"] == 45
    revisions_after = setup.admin.json("GET", f"/admin/api/rooms/{room_id}")["configRevisions"]
    assert len(revisions_after) == len(revisions_before) + 1
    assert revisions_after[-1]["config"]["waitWindowSeconds"] == 45

    closed = setup.admin.json("POST", f"/admin/api/rooms/{room_id}/close-booking")["room"]
    assert closed["status"] == "draft"
    _assert_counts(setup.admin, draft=1, open=0, in_progress=0, unpaid=0, archived=0)
    draft_patch = setup.admin.json(
        "PATCH", f"/admin/api/rooms/{room_id}", json={"waitWindowSeconds": 50}
    )["room"]
    assert draft_patch["waitWindowSeconds"] == 50

    setup.admin.json("POST", f"/admin/api/rooms/{room_id}/publish")
    participant_a.json("POST", f"/api/rooms/{room_id}/book")
    blocked_close = setup.admin.request("POST", f"/admin/api/rooms/{room_id}/close-booking")
    assert blocked_close.status_code == 409
    assert blocked_close.json()["detail"] == "存在有效预约，无法关闭预约"

    late_room = setup.room(starts_in_seconds=3, wait_window_seconds=600, label="开始后房间")
    wait_until(
        lambda: setup.admin.json("GET", f"/admin/api/rooms/{late_room['id']}")["room"]["status"]
        == "waiting",
        timeout=20,
    )
    late_starts = setup.admin.request(
        "PATCH", f"/admin/api/rooms/{late_room['id']}", json={"startsAt": new_start}
    )
    assert late_starts.status_code == 409
    assert late_starts.json()["detail"] == "仅草稿房间可以修改开始时间"
    late_config = setup.admin.request(
        "PATCH", f"/admin/api/rooms/{late_room['id']}", json={"waitWindowSeconds": 70}
    )
    assert late_config.status_code == 409
    assert late_config.json()["detail"] == "房间开始后不可修改配置"
    late_close = setup.admin.request(
        "POST", f"/admin/api/rooms/{late_room['id']}/close-booking"
    )
    assert late_close.status_code == 409
    assert late_close.json()["detail"] == "只有开放预约的房间可以关闭预约"
    late_publish = setup.admin.request("POST", f"/admin/api/rooms/{late_room['id']}/publish")
    assert late_publish.status_code == 409

    cancelled_room = setup.room(starts_in_seconds=120, label="管理员取消房间")
    participant_b.json("POST", f"/api/rooms/{cancelled_room['id']}/book")
    cancelled = setup.admin.json("POST", f"/admin/api/rooms/{cancelled_room['id']}/cancel")
    assert cancelled["room"]["archiveReason"] == "admin_cancelled"
    experiment = next(
        item
        for item in participant_b.json("GET", "/api/my-experiments")["experiments"]
        if item["roomId"] == cancelled_room["id"]
    )
    assert experiment["archiveReason"] == "admin_cancelled"
    assert experiment["canRebook"] is True
    assert experiment["rewardKind"] == "none"
    rebook_room = setup.room(starts_in_seconds=120, label="取消后重订房间")
    rebook = participant_b.json("POST", f"/api/rooms/{rebook_room['id']}/book")
    assert rebook["bookedCount"] == 1

    participant_a.close()
    participant_b.close()
    setup.close()


@pytest.mark.integration
def test_one_time_lock_questionnaire_wait_and_late_submission(server):
    setup = Setup(server)
    participant_a, participant_b = _login(
        server, setup.admin, [("锁定甲", "13700001031"), ("锁定乙", "13700001032")]
    )
    room = setup.room(
        starts_in_seconds=3,
        wait_window_seconds=600,
        reconnect_window_seconds=1,
        label="锁定房间",
    )
    participant_a.json("POST", f"/api/rooms/{room['id']}/book")
    participant_b.json("POST", f"/api/rooms/{room['id']}/book")
    ws_a, ws_b, questionnaire_a, questionnaire_b = _play_to_questionnaire(
        server, setup, room, participant_a, participant_b
    )
    token_a = _token(questionnaire_a["url"])
    token_b = _token(questionnaire_b["url"])
    detail = setup.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["status"] == "questionnaire"
    assert detail["payments"] == []

    other_room = setup.room(starts_in_seconds=180, label="锁定后的新房间")
    me_a = participant_a.json("GET", "/api/me")["me"]
    assert me_a["canBook"] is False
    assert me_a["hasPendingQuestionnaire"] is True
    blocked = participant_a.request("POST", f"/api/rooms/{other_room['id']}/book")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == PENDING_QUESTIONNAIRE_MESSAGE
    bookable_a = participant_a.json("GET", "/api/rooms/bookable")
    assert bookable_a["canBook"] is False
    assert all(item["canBook"] is False for item in bookable_a["rooms"])

    ws_a.send("exit_room", roomId=room["id"])
    exit_error = ws_a.recv_until("error")
    assert exit_error["code"] == "invalid_state"
    ws_a.close()
    ws_b.close()
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline:
        state = setup.admin.json("GET", f"/admin/api/rooms/{room['id']}")["room"]
        assert state["status"] == "questionnaire"
        assert state["archiveReason"] is None
        time.sleep(0.25)
    assert setup.admin.json("GET", "/admin/api/payments")["payments"] == []

    archived = setup.admin.json(
        "POST",
        f"/admin/api/rooms/{room['id']}/archive",
        json={"reason": "questionnaire_incomplete"},
    )["room"]
    assert archived["status"] == "archived"
    assert archived["archiveReason"] == "questionnaire_incomplete"
    pending_rooms = participant_a.json("GET", "/api/my-room")["pendingQuestionnaires"]
    assert [item["roomId"] for item in pending_rooms] == [room["id"]]
    assert pending_rooms[0]["canContinue"] is True
    still_blocked = participant_a.request("POST", f"/api/rooms/{other_room['id']}/book")
    assert still_blocked.status_code == 409
    assert still_blocked.json()["detail"] == PENDING_QUESTIONNAIRE_MESSAGE

    draft_a = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/draft",
        json={"token": token_a, "answers": {"q1": "female"}},
        timeout=30,
    )
    assert draft_a.status_code == 200, draft_a.text
    assert draft_a.json()["saved"] is True
    complete_a = participant_a.json(
        "POST",
        "/api/questionnaire/complete",
        json=_complete_payload(room["id"], IDENTITY_A, q1="female", q2="流程顺利"),
    )
    assert complete_a["saved"] is True
    assert complete_a["canonical"] is True

    me_a = participant_a.json("GET", "/api/me")["me"]
    assert me_a["status"] == "completed"
    assert me_a["isCompleted"] is True
    assert me_a["canBook"] is False
    assert me_a["hasPendingQuestionnaire"] is False
    blocked_after = participant_a.request("POST", f"/api/rooms/{other_room['id']}/book")
    assert blocked_after.status_code == 409
    assert blocked_after.json()["detail"] == COMPLETED_MESSAGE
    payments = setup.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 1
    assert payments[0]["status"] == "pending"
    assert payments[0]["totalCents"] >= 0
    detail = setup.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["archiveReason"] == "questionnaire_incomplete"

    me_b = participant_b.json("GET", "/api/me")["me"]
    assert me_b["hasPendingQuestionnaire"] is True
    blocked_b = participant_b.request("POST", f"/api/rooms/{other_room['id']}/book")
    assert blocked_b.status_code == 409
    assert blocked_b.json()["detail"] == PENDING_QUESTIONNAIRE_MESSAGE
    draft_b = httpx.post(
        f"{server.base_url}/api/jatos/questionnaire/draft",
        json={"token": token_b, "answers": {"q2": "补交草稿"}},
        timeout=30,
    )
    assert draft_b.status_code == 200, draft_b.text
    complete_b = participant_b.json(
        "POST",
        "/api/questionnaire/complete",
        json=_complete_payload(room["id"], IDENTITY_B, q1="male", q2="补交完成"),
    )
    assert complete_b["canonical"] is True
    me_b = participant_b.json("GET", "/api/me")["me"]
    assert me_b["status"] == "completed"
    assert me_b["canBook"] is False
    detail = setup.admin.json("GET", f"/admin/api/rooms/{room['id']}")
    assert detail["room"]["status"] == "archived"
    assert detail["room"]["archiveReason"] == "questionnaire_incomplete"
    assert all(
        item["questionnaireStatus"] == "completed" for item in detail["participants"]
    )
    payments = setup.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 2
    assert {item["status"] for item in payments} == {"pending"}
    experiment_b = next(
        item
        for item in participant_b.json("GET", "/api/my-experiments")["experiments"]
        if item["roomId"] == room["id"]
    )
    assert experiment_b["rewardKind"] == "completion"
    assert experiment_b["canRebook"] is False
    assert experiment_b["payment"]["totalCents"] == next(
        item["totalCents"] for item in payments if item["analysisCode"] == experiment_b["payment"]["analysisCode"]
    )

    participant_a.close()
    participant_b.close()
    setup.close()


@pytest.mark.integration
def test_room_sections_follow_status_and_pending_payment(server):
    setup = Setup(server)
    participant_a, participant_b, participant_c, participant_d, participant_e = _login(
        server,
        setup.admin,
        [
            ("分区甲", "13700001041"),
            ("分区乙", "13700001042"),
            ("分区丙", "13700001043"),
            ("分区丁", "13700001044"),
            ("分区戊", "13700001045"),
        ],
    )
    draft_room = setup.room(starts_in_seconds=600, publish=False, label="分区草稿")
    open_room = setup.room(starts_in_seconds=600, label="分区开放")
    full_room = setup.room(starts_in_seconds=600, label="分区满员")
    participant_c.json("POST", f"/api/rooms/{full_room['id']}/book")
    participant_d.json("POST", f"/api/rooms/{full_room['id']}/book")
    assert setup.admin.json("GET", f"/admin/api/rooms/{full_room['id']}")["room"]["status"] == "full"

    waiting_room = setup.room(starts_in_seconds=3, wait_window_seconds=600, label="分区进行中")
    participant_e.json("POST", f"/api/rooms/{waiting_room['id']}/book")
    wait_until(
        lambda: setup.admin.json("GET", f"/admin/api/rooms/{waiting_room['id']}")["room"]["status"]
        == "waiting",
        timeout=20,
    )

    _assert_counts(setup.admin, draft=1, open=2, in_progress=1, unpaid=0, archived=0)
    assert _section_room_ids(setup.admin, "draft") == {draft_room["id"]}
    assert _section_room_ids(setup.admin, "open") == {open_room["id"], full_room["id"]}
    assert _section_room_ids(setup.admin, "in_progress") == {waiting_room["id"]}
    assert _section_room_ids(setup.admin, "unpaid") == set()
    assert _section_room_ids(setup.admin, "archived") == set()

    questionnaire_room = setup.room(
        starts_in_seconds=3, wait_window_seconds=600, label="分区问卷"
    )
    participant_a.json("POST", f"/api/rooms/{questionnaire_room['id']}/book")
    participant_b.json("POST", f"/api/rooms/{questionnaire_room['id']}/book")
    ws_a, ws_b, _questionnaire_a, _questionnaire_b = _play_to_questionnaire(
        server, setup, questionnaire_room, participant_a, participant_b
    )
    _assert_counts(setup.admin, draft=1, open=2, in_progress=2, unpaid=0, archived=0)

    participant_a.json(
        "POST",
        "/api/questionnaire/complete",
        json=_complete_payload(questionnaire_room["id"], IDENTITY_A, q1="female", q2="分区甲"),
    )
    _assert_counts(setup.admin, draft=1, open=2, in_progress=2, unpaid=0, archived=0)
    participant_b.json(
        "POST",
        "/api/questionnaire/complete",
        json=_complete_payload(questionnaire_room["id"], IDENTITY_B, q1="male", q2="分区乙"),
    )
    detail = setup.admin.json("GET", f"/admin/api/rooms/{questionnaire_room['id']}")
    assert detail["room"]["status"] == "archived"
    assert detail["room"]["archiveReason"] == "completed"
    payments = detail["payments"]
    assert len(payments) == 2
    assert all(item["status"] == "pending" for item in payments)
    _assert_counts(setup.admin, draft=1, open=2, in_progress=1, unpaid=1, archived=0)
    assert _section_room_ids(setup.admin, "unpaid") == {questionnaire_room["id"]}
    assert _section_room_ids(setup.admin, "archived") == set()

    for payment in payments:
        setup.admin.json(
            "PATCH", f"/admin/api/payments/{payment['id']}", json={"status": "paid"}
        )
    _assert_counts(setup.admin, draft=1, open=2, in_progress=1, unpaid=0, archived=1)
    assert _section_room_ids(setup.admin, "unpaid") == set()
    assert _section_room_ids(setup.admin, "archived") == {questionnaire_room["id"]}

    ws_a.close()
    ws_b.close()
    for client in (participant_a, participant_b, participant_c, participant_d, participant_e):
        client.close()
    setup.close()


@pytest.mark.integration
def test_wait_expiry_not_full_no_show_no_start(server):
    setup = Setup(server)
    participant_a, participant_b = _login(
        server, setup.admin, [("等待甲", "13700001051"), ("等待乙", "13700001052")]
    )
    not_full = setup.room(
        starts_in_seconds=3, wait_window_seconds=2, label="不足两人房间"
    )
    participant_a.json("POST", f"/api/rooms/{not_full['id']}/book")
    _wait_my_room_status(participant_a, "waiting")
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_a.send("enter_room", roomId=not_full["id"])
    ws_a.recv_until("room_state")
    archived = ws_a.recv_until("room_archived", timeout=20)
    assert archived["reason"] == "not_full"
    assert archived["selfExited"] is False
    assert archived["selfCompleted"] is False
    assert archived["canRebook"] is True
    assert archived["rewardKind"] == "none"
    detail = setup.admin.json("GET", f"/admin/api/rooms/{not_full['id']}")
    assert detail["room"]["archiveReason"] == "not_full"
    assert detail["bookings"][0]["status"] == "attended"
    assert setup.admin.json("GET", "/admin/api/payments")["payments"] == []
    experiment = participant_a.json("GET", "/api/my-experiments")["experiments"][0]
    assert experiment["selfAttended"] is True
    assert experiment["payment"] is None
    assert experiment["canRebook"] is True
    ws_a.close()

    no_show = setup.room(starts_in_seconds=3, wait_window_seconds=3, label="缺席房间")
    participant_a.json("POST", f"/api/rooms/{no_show['id']}/book")
    participant_b.json("POST", f"/api/rooms/{no_show['id']}/book")
    _wait_my_room_status(participant_a, "waiting")
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_a.send("enter_room", roomId=no_show["id"])
    ws_a.recv_until("room_state")
    archived = ws_a.recv_until("room_archived", timeout=20)
    assert archived["reason"] == "no_show"
    assert archived["rewardKind"] == "none"
    detail = setup.admin.json("GET", f"/admin/api/rooms/{no_show['id']}")
    statuses = {item["name"]: item["status"] for item in detail["bookings"]}
    assert statuses == {"等待甲": "attended", "等待乙": "no_show"}
    assert setup.admin.json("GET", "/admin/api/payments")["payments"] == []
    ws_a.close()

    no_start = setup.room(starts_in_seconds=3, wait_window_seconds=3, label="未开始房间")
    participant_a.json("POST", f"/api/rooms/{no_start['id']}/book")
    participant_b.json("POST", f"/api/rooms/{no_start['id']}/book")
    _wait_my_room_status(participant_a, "waiting")
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    _enter_both(ws_a, ws_b, setup.admin, no_start["id"])
    archived_a = ws_a.recv_until("room_archived", timeout=20)
    archived_b = ws_b.recv_until("room_archived", timeout=20)
    assert archived_a["reason"] == "no_start"
    assert archived_b["reason"] == "no_start"
    assert archived_a["canRebook"] is True
    detail = setup.admin.json("GET", f"/admin/api/rooms/{no_start['id']}")
    statuses = {item["name"]: item["status"] for item in detail["bookings"]}
    assert statuses == {"等待甲": "attended", "等待乙": "attended"}
    assert setup.admin.json("GET", "/admin/api/payments")["payments"] == []
    experiment = participant_b.json("GET", "/api/my-experiments")["experiments"][0]
    assert experiment["rewardKind"] == "none"
    assert experiment["payment"] is None

    ws_a.close()
    ws_b.close()
    participant_a.close()
    participant_b.close()
    setup.close()


@pytest.mark.integration
def test_exit_rules_waiting_instructions_playing_rest(server):
    setup = Setup(server, rest_seconds=30)
    accounts = [
        ("退出甲", "13700001061"),
        ("退出乙", "13700001062"),
        ("退出丙", "13700001063"),
        ("退出丁", "13700001064"),
        ("退出戊", "13700001065"),
        ("退出己", "13700001066"),
        ("退出庚", "13700001067"),
        ("退出辛", "13700001068"),
    ]
    clients = _login(server, setup.admin, accounts)
    waiting_a, waiting_b, instructions_a, instructions_b = clients[0:4]
    playing_a, playing_b, rest_a, rest_b = clients[4:8]

    waiting_room = setup.room(
        starts_in_seconds=3, wait_window_seconds=600, label="等待退出房间"
    )
    waiting_a.json("POST", f"/api/rooms/{waiting_room['id']}/book")
    waiting_b.json("POST", f"/api/rooms/{waiting_room['id']}/book")
    _wait_my_room_status(waiting_a, "waiting")
    ws_wa = WsClient(server, waiting_a.cookie_value("moyo_participant"))
    ws_wb = WsClient(server, waiting_b.cookie_value("moyo_participant"))
    _enter_both(ws_wa, ws_wb, setup.admin, waiting_room["id"])
    ws_wa.send("exit_room", roomId=waiting_room["id"])
    partner_error = ws_wa.recv_until("error")
    assert partner_error["code"] == "partner_present"
    assert (
        setup.admin.json("GET", f"/admin/api/rooms/{waiting_room['id']}")["room"]["status"]
        == "waiting"
    )
    setup.admin.json(
        "POST",
        f"/admin/api/rooms/{waiting_room['id']}/archive",
        json={"reason": "admin_aborted"},
    )
    ws_wa.close()
    ws_wb.close()

    solo_room = setup.room(
        starts_in_seconds=3, wait_window_seconds=600, label="等待单人退出房间"
    )
    waiting_a.json("POST", f"/api/rooms/{solo_room['id']}/book")
    _wait_my_room_status(waiting_a, "waiting")
    ws_so = WsClient(server, waiting_a.cookie_value("moyo_participant"))
    ws_so.send("enter_room", roomId=solo_room["id"])
    ws_so.recv_until("room_state")
    ws_so.send("exit_room", roomId=solo_room["id"])
    solo_archived = ws_so.recv_until("room_archived")
    assert solo_archived["reason"] == "abandoned"
    assert solo_archived["selfExited"] is True
    assert solo_archived["canRebook"] is True
    assert setup.admin.json("GET", "/admin/api/payments")["payments"] == []
    ws_so.close()

    instructions_room = setup.room(
        starts_in_seconds=3, wait_window_seconds=600, label="指导语退出房间"
    )
    instructions_a.json("POST", f"/api/rooms/{instructions_room['id']}/book")
    instructions_b.json("POST", f"/api/rooms/{instructions_room['id']}/book")
    _wait_my_room_status(instructions_a, "waiting")
    ws_ia = WsClient(server, instructions_a.cookie_value("moyo_participant"))
    ws_ib = WsClient(server, instructions_b.cookie_value("moyo_participant"))
    _enter_both(ws_ia, ws_ib, setup.admin, instructions_room["id"])
    _start_instructions(ws_ia, ws_ib, instructions_room["id"])
    ws_ia.send("exit_room", roomId=instructions_room["id"])
    archived_a = ws_ia.recv_until("room_archived")
    archived_b = ws_ib.recv_until("room_archived")
    assert archived_a["reason"] == "abandoned"
    assert archived_a["selfExited"] is True
    assert archived_b["selfExited"] is False
    assert archived_a["canRebook"] is True
    assert archived_b["canRebook"] is True
    assert archived_a["rewardKind"] == "none"
    detail = setup.admin.json("GET", f"/admin/api/rooms/{instructions_room['id']}")
    assert detail["room"]["archiveReason"] == "abandoned"
    assert setup.admin.json("GET", "/admin/api/payments")["payments"] == []
    rebook_room = setup.room(starts_in_seconds=120, label="退赛后重订房间")
    rebook = instructions_a.json("POST", f"/api/rooms/{rebook_room['id']}/book")
    assert rebook["bookedCount"] == 1
    ws_ia.close()
    ws_ib.close()

    playing_room = setup.room(
        starts_in_seconds=3, wait_window_seconds=600, label="对局退出房间"
    )
    playing_a.json("POST", f"/api/rooms/{playing_room['id']}/book")
    playing_b.json("POST", f"/api/rooms/{playing_room['id']}/book")
    _wait_my_room_status(playing_a, "waiting")
    ws_pa = WsClient(server, playing_a.cookie_value("moyo_participant"))
    ws_pb = WsClient(server, playing_b.cookie_value("moyo_participant"))
    _enter_both(ws_pa, ws_pb, setup.admin, playing_room["id"])
    role_a, role_b = _start_instructions(ws_pa, ws_pb, playing_room["id"])
    _complete_instructions(ws_pa, ws_pb, playing_room["id"])
    ws_pa.send("enter_game", roomId=playing_room["id"])
    ws_pb.send("enter_game", roomId=playing_room["id"])
    ws_pa.recv_until("turn")
    ws_pb.recv_until("turn")
    ws_pa.send("exit_room", roomId=playing_room["id"])
    archived_pa = ws_pa.recv_until("room_archived")
    archived_pb = ws_pb.recv_until("room_archived")
    assert archived_pa["reason"] == "abandoned"
    assert archived_pa["selfExited"] is True
    assert archived_pb["selfExited"] is False
    assert setup.admin.json("GET", "/admin/api/payments")["payments"] == []
    ws_pa.close()
    ws_pb.close()

    rest_room = setup.room(
        starts_in_seconds=3, wait_window_seconds=600, label="休息退出房间"
    )
    rest_a.json("POST", f"/api/rooms/{rest_room['id']}/book")
    rest_b.json("POST", f"/api/rooms/{rest_room['id']}/book")
    _wait_my_room_status(rest_a, "waiting")
    ws_ra = WsClient(server, rest_a.cookie_value("moyo_participant"))
    ws_rb = WsClient(server, rest_b.cookie_value("moyo_participant"))
    _enter_both(ws_ra, ws_rb, setup.admin, rest_room["id"])
    role_ra, role_rb = _start_instructions(ws_ra, ws_rb, rest_room["id"])
    _complete_instructions(ws_ra, ws_rb, rest_room["id"])
    ws_ra.send("enter_game", roomId=rest_room["id"])
    ws_rb.send("enter_game", roomId=rest_room["id"])
    ws_ra.recv_until("trial_start")
    ws_rb.recv_until("trial_start")
    turn_ra = ws_ra.recv_until("turn")
    turn_rb = ws_rb.recv_until("turn")
    for ws, role, turn in ((ws_ra, role_ra, turn_ra), (ws_rb, role_rb, turn_rb)):
        ws.send(
            "submit_selection",
            roomId=rest_room["id"],
            trialIndex=turn["trialIndex"],
            round=turn["round"],
            cells=[_owned_cell(turn["board"], role)],
            clientMsgId=f"rest-exit-{role}-{uuid.uuid4().hex[:8]}",
        )
    rest_message_a = ws_ra.recv_until("rest")
    rest_message_b = ws_rb.recv_until("rest")
    assert rest_message_a["trialIndex"] == 0
    assert rest_message_b["trialIndex"] == 0
    ws_rb.send("exit_room", roomId=rest_room["id"])
    archived_rb = ws_rb.recv_until("room_archived")
    archived_ra = ws_ra.recv_until("room_archived")
    assert archived_rb["reason"] == "abandoned"
    assert archived_rb["selfExited"] is True
    assert archived_ra["selfExited"] is False
    assert archived_ra["rewardKind"] == "none"
    detail = setup.admin.json("GET", f"/admin/api/rooms/{rest_room['id']}")
    assert detail["room"]["archiveReason"] == "abandoned"
    assert setup.admin.json("GET", "/admin/api/payments")["payments"] == []

    ws_ra.close()
    ws_rb.close()
    for client in clients:
        client.close()
    setup.close()


@pytest.mark.integration
def test_technical_abort_showup_payment(server):
    setup = Setup(server)
    participant_a, participant_b = _login(
        server, setup.admin, [("断线甲", "13700001071"), ("断线乙", "13700001072")]
    )
    room = setup.room(
        starts_in_seconds=3, wait_window_seconds=600, reconnect_window_seconds=2, label="断线房间"
    )
    participant_a.json("POST", f"/api/rooms/{room['id']}/book")
    participant_b.json("POST", f"/api/rooms/{room['id']}/book")
    _wait_my_room_status(participant_a, "waiting")
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    _enter_both(ws_a, ws_b, setup.admin, room["id"])
    _start_instructions(ws_a, ws_b, room["id"])
    ws_b.close()
    archived = ws_a.recv_until("room_archived", timeout=20)
    assert archived["reason"] == "technical_abort"
    assert archived["rewardKind"] == "showup"
    assert archived["canRebook"] is True
    payments = setup.admin.json("GET", "/admin/api/payments")["payments"]
    assert len(payments) == 2
    assert all(item["showupPayCents"] == 1000 for item in payments)
    assert all(item["basePayCents"] == 0 for item in payments)
    assert all(item["performancePayCents"] == 0 for item in payments)
    assert all(item["totalCents"] == 1000 for item in payments)
    assert all(item["status"] == "pending" for item in payments)
    experiment_a = next(
        item
        for item in participant_a.json("GET", "/api/my-experiments")["experiments"]
        if item["roomId"] == room["id"]
    )
    assert experiment_a["rewardKind"] == "showup"
    assert experiment_a["payment"]["totalCents"] == 1000
    ws_a.close()
    participant_a.close()
    participant_b.close()
    setup.close()
