import csv
import io
import json
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

from app.constants import TIMEZONE
from app.timeutil import isoformat_utc, localize, week_deadline_utc

from conftest import (
    PASSPORT_SAMPLE,
    ID_CARD_SAMPLE,
    ApiClient,
    create_instruction,
    create_map_group,
    create_troop_profile,
    fetch_all,
    fetch_one,
    questionnaire_answers,
    upload_media,
    valid_identity_answers,
    wait_until,
)

from test_runtime_flows import (
    ANNIHILATION_ROWS,
    Context,
    STAY_ROWS,
    _book,
    _complete_questionnaire,
    _connect,
    _json_value,
    _me,
    _monitor,
    _next_trial,
    _play_to_questionnaire,
    _questionnaire_token,
    _receive_rest,
    _start_game,
    _submit_round,
    _webp_bytes,
    _seconds_until,
)


REVIEW_PLAYERS = (("复核甲", "13700002001"), ("复核乙", "13700002002"))
PAY_ROWS = [
    {"soldiersA": 1000, "soldiersB": 1000},
    {"soldiersA": 8, "soldiersB": 9},
    {"soldiersA": 8, "soldiersB": 9},
]


def _error_detail(response) -> str:
    payload = response.json()
    return payload.get("detail") or json.dumps(payload, ensure_ascii=False)


def _payments_for_room(admin: ApiClient, room_id: str) -> list[dict]:
    payments = admin.json("GET", "/admin/api/payments")["payments"]
    return [payment for payment in payments if payment["roomId"] == room_id]


def _room_detail(admin: ApiClient, room_id: str) -> dict:
    return admin.json("GET", f"/admin/api/rooms/{room_id}")


def _wait_archived(admin: ApiClient, room_id: str, reason: str | None = None, timeout: float = 20) -> dict:
    def archived():
        detail = _room_detail(admin, room_id)
        if detail["room"]["status"] != "archived":
            return False
        return reason is None or detail["room"]["archiveReason"] == reason

    wait_until(archived, timeout=timeout)
    return _room_detail(admin, room_id)


def _extra_participants(context: Context, players) -> list[ApiClient]:
    clients = []
    for name, phone in players:
        client = ApiClient(context.server.base_url).login_participant(name, phone)
        client.consent()
        clients.append(client)
    return clients


def _complete_room(
    server,
    context: Context,
    game,
    journey,
    identity_a: dict,
    identity_b: dict,
    *,
    document_a: str = "id_card",
    document_b: str = "passport",
) -> dict:
    token_a = _questionnaire_token(journey.state_a["questionnaire"]["url"])
    token_b = _questionnaire_token(journey.state_b["questionnaire"]["url"])
    _complete_questionnaire(server, token_a, identity_a, document_type=document_a)
    _complete_questionnaire(server, token_b, identity_b, document_type=document_b)
    return _wait_archived(context.admin, game.room_id, "completed")


def _start_completed_room(
    server,
    context: Context,
    participants,
    *,
    troop_rows=STAY_ROWS,
    grid=(2, 2),
    spawns=None,
    base_pay=4500,
    rate=1,
    performance_floor=0,
    performance_cap=2000,
    identity_a=None,
    identity_b=None,
):
    participant_a, participant_b = participants
    setup = context.make_room(
        troop_rows=troop_rows,
        grid=grid,
        spawns=spawns or {"A": 0, "B": 1},
        practice_cap=1,
        practice_seconds=1,
        formal_cap=1,
        formal_seconds=1,
        rest_seconds=1,
        base_pay=base_pay,
        rate=rate,
        performance_floor=performance_floor,
        performance_cap=performance_cap,
    )
    game = _start_game(server, setup, participant_a, participant_b)
    journey = _play_to_questionnaire(game)
    identity_a = identity_a or valid_identity_answers("复核甲", phone="13800002101")
    identity_b = identity_b or valid_identity_answers("复核乙", phone="13800002102")
    detail = _complete_room(
        server, context, game, journey, identity_a, identity_b
    )
    return setup, game, journey, identity_a, identity_b, detail


def _csv_rows(response) -> list[list[str]]:
    text = response.text.lstrip("﻿")
    return list(csv.reader(io.StringIO(text)))


def _yuan(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _local_date(iso_value: str) -> str:
    moment = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    return localize(moment, TIMEZONE).date().isoformat()


def _questionnaire_schema(questions: list[dict]) -> dict:
    return {
        "title": "校验问卷",
        "pages": [{"id": "page1", "questions": questions}],
    }


def _room_payload(context: Context, map_group_id: str, p1: str, p2: str) -> dict:
    starts_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    return {
        "internalLabel": f"校验房间-{uuid.uuid4().hex[:6]}",
        "startsAt": starts_at.isoformat().replace("+00:00", "Z"),
        "mapGroupVersionId": map_group_id,
        "instructionVersionP1Id": p1,
        "instructionVersionP2Id": p2,
        "questionnaireVersionId": context.questionnaire["id"],
        "waitWindowSeconds": 30,
        "reconnectWindowSeconds": 5,
    }


def test_week_deadline_and_technical_abort_payments(server):
    assert week_deadline_utc(datetime(2026, 10, 17, 12, 0), TIMEZONE) == datetime(
        2026, 10, 18, 16, 0
    )
    assert week_deadline_utc(datetime(2026, 10, 18, 2, 0), TIMEZONE) == datetime(
        2026, 10, 25, 16, 0
    )

    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns={"A": 0, "B": 1},
        practice_cap=2,
        practice_seconds=2,
        formal_cap=2,
        formal_seconds=2,
        rest_seconds=1,
        showup=500,
        reconnect_window=1,
    )
    game = _start_game(server, setup, participant_a, participant_b)
    game.ws_a.close()
    game.ws_b.close()

    detail = _wait_archived(context.admin, setup.room["id"], "technical_abort")
    booked = {booking["participantId"]: booking["status"] for booking in detail["bookings"]}
    assert set(booked.values()) == {"attended"}
    assert _payments_for_room(context.admin, setup.room["id"]) == []

    identity_a = valid_identity_answers("截止甲", phone="13900003333")
    identity_b = valid_identity_answers("截止乙", phone="13900004444")
    for client, identity, tag in (
        (participant_a, identity_a, "截止甲"),
        (participant_b, identity_b, "截止乙"),
    ):
        client.json(
            "POST",
            "/api/questionnaire/complete",
            json={
                "roomId": setup.room["id"],
                "answers": questionnaire_answers(identity, q1="female", q2=tag),
                "jatosWorkerId": f"{tag}-worker",
                "jatosStudyResultId": f"{tag}-study",
                "jatosComponentResultId": f"{tag}-component",
            },
        )

    completed_rows = fetch_all(
        "SELECT participant_id, completed_at FROM room_participants WHERE room_id = %s",
        (setup.room["id"],),
    )
    completed_by_participant = {
        row["participant_id"]: row["completed_at"] for row in completed_rows
    }
    payments = _payments_for_room(context.admin, setup.room["id"])
    assert len(payments) == 2
    for payment in payments:
        assert payment["basePayCents"] == 0
        assert payment["performancePayCents"] == 0
        assert payment["showupPayCents"] == 500
        assert payment["totalCents"] == 500
        assert payment["status"] == "pending"
        expected_deadline = isoformat_utc(
            week_deadline_utc(
                completed_by_participant[payment["participantId"]], TIMEZONE
            )
        )
        assert payment["deadlineAt"] == expected_deadline


def test_performance_floor_and_practice_excluded(server):
    context = Context(server)
    participants = context.participants(REVIEW_PLAYERS)
    setup, game, _journey, _identity_a, _identity_b, detail = _start_completed_room(
        server,
        context,
        participants,
        troop_rows=PAY_ROWS,
        base_pay=1000,
        rate=7,
        performance_cap=2000,
    )
    assert detail["room"]["archiveReason"] == "completed"
    payments = _payments_for_room(context.admin, setup.room["id"])
    assert len(payments) == 2
    for payment in payments:
        assert payment["basePayCents"] == 1000
        assert payment["performancePayCents"] == 100
        assert payment["showupPayCents"] == 0
        assert payment["totalCents"] == 1100
        assert payment["analysisCode"]
    assert {payment["analysisCode"] for payment in payments}.__len__() == 2


def test_performance_cap(server):
    context = Context(server)
    participants = context.participants(REVIEW_PLAYERS)
    setup, _game, _journey, _identity_a, _identity_b, _detail = _start_completed_room(
        server,
        context,
        participants,
        troop_rows=PAY_ROWS,
        base_pay=4500,
        rate=500,
        performance_cap=2000,
    )
    payments = _payments_for_room(context.admin, setup.room["id"])
    assert len(payments) == 2
    for payment in payments:
        assert payment["basePayCents"] == 4500
        assert payment["performancePayCents"] == 2000
        assert payment["totalCents"] == 6500


def test_performance_floor(server):
    context = Context(server)
    participants = context.participants(REVIEW_PLAYERS)
    setup, _game, _journey, _identity_a, _identity_b, _detail = _start_completed_room(
        server,
        context,
        participants,
        troop_rows=PAY_ROWS,
        base_pay=1000,
        rate=1,
        performance_floor=3500,
        performance_cap=5500,
    )
    payments = _payments_for_room(context.admin, setup.room["id"])
    assert len(payments) == 2
    for payment in payments:
        assert payment["basePayCents"] == 1000
        assert payment["performancePayCents"] == 3500
        assert payment["totalCents"] == 4500


def test_payment_override_note_and_paid_preserved(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns={"A": 0, "B": 1},
        practice_cap=2,
        practice_seconds=2,
        formal_cap=2,
        formal_seconds=2,
        rest_seconds=1,
        showup=500,
        reconnect_window=1,
    )
    game = _start_game(server, setup, participant_a, participant_b)
    game.ws_a.close()
    game.ws_b.close()
    _wait_archived(context.admin, setup.room["id"], "technical_abort")
    for client, tag, phone in (
        (participant_a, "覆盖甲", "13900005555"),
        (participant_b, "覆盖乙", "13900006666"),
    ):
        identity = valid_identity_answers(tag, phone=phone)
        client.json(
            "POST",
            "/api/questionnaire/complete",
            json={
                "roomId": setup.room["id"],
                "answers": questionnaire_answers(identity, q1="female", q2=tag),
                "jatosWorkerId": f"{tag}-worker",
                "jatosStudyResultId": f"{tag}-study",
                "jatosComponentResultId": f"{tag}-component",
            },
        )
    payments = _payments_for_room(context.admin, setup.room["id"])
    assert len(payments) == 2
    payment = payments[0]
    participant_id = payment["participantId"]

    missing_note = context.admin.request(
        "PATCH",
        f"/admin/api/payments/{payment['id']}",
        json={"overrideAmountCents": 12345},
    )
    assert missing_note.status_code == 400
    assert "覆盖金额必须填写备注" in _error_detail(missing_note)

    overridden = context.admin.json(
        "PATCH",
        f"/admin/api/payments/{payment['id']}",
        json={"overrideAmountCents": 12345, "adminNote": "线下协商调整"},
    )["payment"]
    assert overridden["overrideAmountCents"] == 12345
    assert overridden["totalCents"] == 12345
    assert overridden["note"] == "线下协商调整"
    assert overridden["status"] == "pending"

    paid = context.admin.json(
        "PATCH",
        f"/admin/api/payments/{payment['id']}",
        json={"status": "paid"},
    )["payment"]
    assert paid["status"] == "paid"
    assert paid["paidAt"] is not None

    blocked_absent = context.admin.request(
        "POST",
        f"/admin/api/rooms/{setup.room['id']}/actions",
        json={"action": "mark_absent", "participantId": participant_id},
    )
    assert blocked_absent.status_code == 409
    assert _error_detail(blocked_absent) == "技术中止后不能把到场参与者标记缺席"
    preserved = next(
        item
        for item in _payments_for_room(context.admin, setup.room["id"])
        if item["id"] == payment["id"]
    )
    assert preserved["status"] == "paid"
    assert preserved["overrideAmountCents"] == 12345
    assert preserved["totalCents"] == 12345
    assert preserved["note"] == "线下协商调整"
    assert preserved["paidAt"] == paid["paidAt"]


def test_analysis_export_and_audit_without_pii(server):
    players = (("导出甲", "13800009901"), ("导出乙", "13800009902"))
    context = Context(server)
    participants = context.participants(players)
    participant_a, participant_b = participants
    identity_a = valid_identity_answers("导出甲", phone="13800009911")
    identity_b = valid_identity_answers("导出乙", phone="13800009912")
    setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns={"A": 0, "B": 1},
        practice_cap=1,
        practice_seconds=1,
        formal_cap=1,
        formal_seconds=1,
        rest_seconds=1,
        base_pay=4500,
        rate=50,
    )
    game = _start_game(server, setup, participant_a, participant_b)
    journey = _play_to_questionnaire(game)
    _complete_room(
        server,
        context,
        game,
        journey,
        identity_a,
        identity_b,
        document_a="id_card",
        document_b="passport",
    )

    participant_ids = [_me(participant_a)["id"], _me(participant_b)["id"]]
    pii = [
        players[0][0],
        players[1][0],
        players[0][1],
        players[1][1],
        identity_a["real_name"],
        identity_b["real_name"],
        identity_a["alipay_phone"],
        identity_b["alipay_phone"],
        ID_CARD_SAMPLE,
        PASSPORT_SAMPLE,
        *participant_ids,
    ]

    export = context.admin.json("GET", f"/admin/api/rooms/{setup.room['id']}/export.json")
    assert export["schemaVersion"] == 6
    assert len(export["participants"]) == 2
    participant_keys = {
        "analysisCode",
        "role",
        "bookingStatus",
        "attendedAt",
        "instruction",
        "questionnaire",
        "completedAt",
    }
    for participant in export["participants"]:
        assert set(participant) == participant_keys
        assert participant["analysisCode"]
        assert participant["role"] in (1, 2)
        answers = participant["questionnaire"]["answers"]
        assert set(answers) == {"q1", "q2"}
        assert "real_name" not in answers
        assert "alipay_phone" not in answers
        assert "identity_document" not in answers
    export_text = json.dumps(export, ensure_ascii=False)
    for value in pii:
        assert value not in export_text

    snapshot_row = fetch_one(
        "SELECT archive_snapshot_json FROM rooms WHERE id = %s", (setup.room["id"],)
    )
    snapshot = _json_value(snapshot_row["archive_snapshot_json"])
    assert set(snapshot) == {
        "schemaVersion",
        "createdAt",
        "room",
        "mapGroup",
        "instructions",
        "questionnaire",
        "media",
    }
    snapshot_text = json.dumps(snapshot, ensure_ascii=False)
    for value in pii:
        assert value not in snapshot_text

    zip_response = context.admin.request(
        "GET", f"/admin/api/rooms/{setup.room['id']}/analysis.zip"
    )
    assert zip_response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(zip_response.content))
    names = set(archive.namelist())
    assert {
        "room.json",
        "participants.csv",
        "turns.csv",
        "trials.csv",
        "payment.csv",
        "questionnaire.json",
        "manifest.json",
    } <= names
    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    assert manifest["schemaVersion"] == 6
    assert manifest["containsPII"] is False
    assert manifest["rowCounts"]["participants"] == 2
    assert manifest["rowCounts"]["payments"] == 2
    payment_rows = list(
        csv.reader(io.StringIO(archive.read("payment.csv").decode("utf-8-sig")))
    )
    assert len(payment_rows) == 3
    for name in names:
        if not name.endswith((".json", ".csv")):
            continue
        text = archive.read(name).decode("utf-8-sig")
        for value in pii:
            assert value not in text, f"{name} 包含敏感值 {value}"

    history_name = "历史完成甲"
    history_phone = "13800005555"
    history_note = "历史备注敏感值"
    history_content = (
        "姓名,手机号,备注\n"
        f"{history_name},{history_phone},{history_note}\n"
    )
    history_report = context.admin.json(
        "POST",
        "/admin/api/participants/import-completed",
        files={"file": ("completed.csv", history_content.encode("utf-8"), "text/csv")},
    )
    assert history_report["created"] == 1
    assert history_report["matched"] == 0
    assert history_report["unmatched"] == 0

    audit = context.admin.json("GET", "/admin/api/audit?limit=500")
    entries = audit["entries"]
    assert any(entry["action"] == "participants_import_completed" for entry in entries)
    audit_text = json.dumps(entries, ensure_ascii=False)
    for value in [
        players[0][0],
        players[1][0],
        identity_a["real_name"],
        identity_b["real_name"],
        players[0][1],
        players[1][1],
        identity_a["alipay_phone"],
        identity_b["alipay_phone"],
        ID_CARD_SAMPLE,
        PASSPORT_SAMPLE,
        history_name,
        history_phone,
        history_note,
    ]:
        assert value not in audit_text


def test_payment_lists_filters_and_columns(server):
    context = Context(server)
    extra_a, extra_b = _extra_participants(
        context, (("清单丙", "13800003303"), ("清单丁", "13800004404"))
    )
    participants = context.participants(REVIEW_PLAYERS)
    participant_a, participant_b = participants

    abort_setup = context.make_room(
        troop_rows=STAY_ROWS,
        grid=(2, 2),
        spawns={"A": 0, "B": 1},
        practice_cap=2,
        practice_seconds=2,
        formal_cap=2,
        formal_seconds=2,
        rest_seconds=1,
        showup=500,
        reconnect_window=1,
    )
    abort_game = _start_game(server, abort_setup, extra_a, extra_b)
    abort_game.ws_a.close()
    abort_game.ws_b.close()
    _wait_archived(context.admin, abort_setup.room["id"], "technical_abort")
    identity_abort_a = valid_identity_answers("清单丙", phone="13800005555")
    identity_abort_b = valid_identity_answers("清单丁", phone="13800006666")
    for client, identity, tag in (
        (extra_a, identity_abort_a, "清单丙"),
        (extra_b, identity_abort_b, "清单丁"),
    ):
        client.json(
            "POST",
            "/api/questionnaire/complete",
            json={
                "roomId": abort_setup.room["id"],
                "answers": questionnaire_answers(identity, q1="female", q2=tag),
                "jatosWorkerId": f"{tag}-worker",
                "jatosStudyResultId": f"{tag}-study",
                "jatosComponentResultId": f"{tag}-component",
            },
        )

    identity_a = valid_identity_answers("清单甲", phone="13800001111")
    identity_b = valid_identity_answers("清单乙", phone="13800002222")
    setup, game, journey, _identity_a, _identity_b, _detail = _start_completed_room(
        server,
        context,
        participants,
        troop_rows=PAY_ROWS,
        base_pay=4500,
        rate=50,
        identity_a=identity_a,
        identity_b=identity_b,
    )
    payments = _payments_for_room(context.admin, setup.room["id"])
    assert len(payments) == 2
    assert sorted(payment["totalCents"] for payment in payments) == [5300, 5400]

    start_date = _local_date(_room_detail(context.admin, setup.room["id"])["room"]["startsAt"])
    abort_start_date = _local_date(
        _room_detail(context.admin, abort_setup.room["id"])["room"]["startsAt"]
    )
    params = {
        "from": min(start_date, abort_start_date),
        "to": max(start_date, abort_start_date),
    }
    pending_list = context.admin.request(
        "GET", "/admin/api/payments/export-payment-list.csv", params=params
    )
    assert pending_list.status_code == 200
    rows = _csv_rows(pending_list)
    assert rows[0] == ["序号", "玩家支付宝手机号", "玩家姓名", "金额"]
    assert len(rows) == 5
    assert {row[1] for row in rows[1:]} == {
        identity_a["alipay_phone"],
        identity_b["alipay_phone"],
        identity_abort_a["alipay_phone"],
        identity_abort_b["alipay_phone"],
    }
    assert {row[2] for row in rows[1:]} == {
        identity_a["real_name"],
        identity_b["real_name"],
        identity_abort_a["real_name"],
        identity_abort_b["real_name"],
    }
    assert sorted(row[3] for row in rows[1:]) == [
        "5.00",
        "5.00",
        "53.00",
        "54.00",
    ]

    empty = context.admin.request(
        "GET",
        "/admin/api/payments/export-payment-list.csv",
        params={"from": "2000-01-01", "to": "2000-01-02"},
    )
    assert _csv_rows(empty) == [["序号", "玩家支付宝手机号", "玩家姓名", "金额"]]

    reimbursement_before = context.admin.request(
        "GET", "/admin/api/payments/export-reimbursement-list.csv", params=params
    )
    assert _csv_rows(reimbursement_before) == [
        ["序号", "参与日期", "玩家姓名", "玩家手机号", "玩家身份证", "金额"]
    ]

    payment_ids = [
        row["id"]
        for row in fetch_all(
            "SELECT id FROM payments WHERE room_id = %s", (setup.room["id"],)
        )
    ]
    marked = context.admin.json(
        "POST",
        "/admin/api/payments/bulk-mark-paid",
        json={"paymentIds": payment_ids},
    )
    assert marked["updated"] == 2

    after_paid = context.admin.request(
        "GET", "/admin/api/payments/export-payment-list.csv", params=params
    )
    after_paid_rows = _csv_rows(after_paid)
    assert after_paid_rows[0] == ["序号", "玩家支付宝手机号", "玩家姓名", "金额"]
    assert len(after_paid_rows) == 3
    assert {row[1] for row in after_paid_rows[1:]} == {
        identity_abort_a["alipay_phone"],
        identity_abort_b["alipay_phone"],
    }
    assert {row[2] for row in after_paid_rows[1:]} == {
        identity_abort_a["real_name"],
        identity_abort_b["real_name"],
    }
    assert sorted(row[3] for row in after_paid_rows[1:]) == ["5.00", "5.00"]

    reimbursement = context.admin.request(
        "GET", "/admin/api/payments/export-reimbursement-list.csv", params=params
    )
    reimbursement_rows = _csv_rows(reimbursement)
    assert reimbursement_rows[0] == [
        "序号",
        "参与日期",
        "玩家姓名",
        "玩家手机号",
        "玩家身份证",
        "金额",
    ]
    assert len(reimbursement_rows) == 3
    payment_by_participant = {
        payment["participantId"]: payment for payment in payments
    }
    expected = {
        (
            start_date,
            identity_a["real_name"],
            REVIEW_PLAYERS[0][1],
            ID_CARD_SAMPLE,
            _yuan(payment_by_participant[_me(participant_a)["id"]]["totalCents"]),
        ),
        (
            start_date,
            identity_b["real_name"],
            REVIEW_PLAYERS[1][1],
            PASSPORT_SAMPLE,
            _yuan(payment_by_participant[_me(participant_b)["id"]]["totalCents"]),
        ),
    }
    assert {tuple(row[1:]) for row in reimbursement_rows[1:]} == expected

    abort_payments = _payments_for_room(context.admin, abort_setup.room["id"])
    assert len(abort_payments) == 2
    assert all(payment["status"] == "pending" for payment in abort_payments)


def test_room_start_and_config_limits(server):
    context = Context(server)
    participant_a, _participant_b = context.participants()
    draft_setup = context.make_room(
        troop_rows=STAY_ROWS[:2],
        grid=(2, 2),
        spawns={"A": 0, "B": 1},
        starts_in=3600,
        publish=False,
    )
    room_id = draft_setup.room["id"]
    assert draft_setup.room["status"] == "draft"
    new_start = datetime.now(timezone.utc) + timedelta(hours=2)
    patched = context.admin.json(
        "PATCH",
        f"/admin/api/rooms/{room_id}",
        json={"internalLabel": "草稿改名"},
    )
    assert patched["room"]["internalLabel"] == "草稿改名"
    context.admin.json("POST", f"/admin/api/rooms/{room_id}/publish")

    start_rejected = context.admin.request(
        "PATCH",
        f"/admin/api/rooms/{room_id}",
        json={"startsAt": new_start.isoformat().replace("+00:00", "Z")},
    )
    assert start_rejected.status_code == 409
    assert "仅草稿房间可以修改开始时间" in _error_detail(start_rejected)

    config_patched = context.admin.json(
        "PATCH",
        f"/admin/api/rooms/{room_id}",
        json={"reconnectWindowSeconds": 12},
    )
    assert config_patched["room"]["status"] == "open"

    _book(draft_setup, participant_a)
    close_with_booking = context.admin.request(
        "POST", f"/admin/api/rooms/{room_id}/close-booking"
    )
    assert close_with_booking.status_code == 409
    assert "存在有效预约，无法关闭预约" in _error_detail(close_with_booking)
    detail = _room_detail(context.admin, room_id)
    booking_id = detail["bookings"][0]["id"]
    participant_a.json("POST", f"/api/bookings/{booking_id}/cancel")
    closed = context.admin.json("POST", f"/admin/api/rooms/{room_id}/close-booking")
    assert closed["room"]["status"] == "draft"

    started_setup = context.make_room(
        troop_rows=STAY_ROWS[:2],
        grid=(2, 2),
        spawns={"A": 0, "B": 1},
        starts_in=1,
    )
    time.sleep(1.5)
    config_rejected = context.admin.request(
        "PATCH",
        f"/admin/api/rooms/{started_setup.room['id']}",
        json={"reconnectWindowSeconds": 12},
    )
    assert config_rejected.status_code == 409
    assert "房间开始后不可修改配置" in _error_detail(config_rejected)
    close_rejected = context.admin.request(
        "POST", f"/admin/api/rooms/{started_setup.room['id']}/close-booking"
    )
    assert close_rejected.status_code == 409
    # 到达开始时间后定时任务可能已把房间移出 open/full，两种提示都表示此时禁止关闭预约。
    assert "关闭预约" in _error_detail(close_rejected)

    past_setup = context.make_room(
        troop_rows=STAY_ROWS[:2],
        grid=(2, 2),
        spawns={"A": 0, "B": 1},
        starts_in=-120,
        publish=False,
    )
    publish_past = context.admin.request(
        "POST", f"/admin/api/rooms/{past_setup.room['id']}/publish"
    )
    assert publish_past.status_code == 400
    assert "开始时间必须晚于当前时间" in _error_detail(publish_past)


def test_instruction_prefix_and_role_validation(server):
    context = Context(server)
    profile = create_troop_profile(context.admin, STAY_ROWS)
    first = create_map_group(
        context.admin,
        profile["id"],
        rows=2,
        cols=2,
        formal_trials=2,
        spawns={"A": 0, "B": 1},
        description=f"校验甲{uuid.uuid4().hex[:6]}",
    )
    second = create_map_group(
        context.admin,
        profile["id"],
        rows=2,
        cols=2,
        formal_trials=2,
        spawns={"A": 0, "B": 1},
        description=f"校验乙{uuid.uuid4().hex[:6]}",
    )
    create_instruction(context.admin, first["id"], 1, "甲玩家1")
    first_role2 = create_instruction(context.admin, first["id"], 2, "甲玩家2")
    second_role1 = create_instruction(context.admin, second["id"], 1, "乙玩家1")

    role_response = context.admin.request(
        "POST",
        "/admin/api/rooms",
        json=_room_payload(context, first["id"], first_role2["id"], first_role2["id"]),
    )
    assert role_response.status_code == 400
    assert "玩家1指导语的角色必须是 1" in _error_detail(role_response)

    prefix_response = context.admin.request(
        "POST",
        "/admin/api/rooms",
        json=_room_payload(context, first["id"], second_role1["id"], first_role2["id"]),
    )
    assert prefix_response.status_code == 400
    assert "玩家1指导语的名称前缀必须与地图组名称一致" in _error_detail(prefix_response)


def test_questionnaire_protected_field_validation(server):
    context = Context(server)

    missing = _questionnaire_schema(
        [
            {"id": "real_name", "type": "real_name", "label": "真实姓名", "required": True},
            {
                "id": "alipay_phone",
                "type": "alipay_phone",
                "label": "支付宝手机号",
                "required": True,
            },
        ]
    )
    created = context.admin.json(
        "POST",
        "/admin/api/questionnaires",
        json={"name": f"缺身份-{uuid.uuid4().hex[:6]}", "schemaJson": missing},
    )
    publish_missing = context.admin.request(
        "POST",
        f"/admin/api/questionnaires/{created['questionnaire']['id']}/publish",
    )
    assert publish_missing.status_code == 400
    assert "问卷必须包含受保护题型: identity_document" in _error_detail(publish_missing)

    optional = _questionnaire_schema(
        [
            {"id": "real_name", "type": "real_name", "label": "真实姓名", "required": False},
            {
                "id": "alipay_phone",
                "type": "alipay_phone",
                "label": "支付宝手机号",
                "required": True,
            },
            {
                "id": "identity_document",
                "type": "identity_document",
                "label": "身份证件",
                "required": True,
            },
        ]
    )
    optional_response = context.admin.request(
        "POST",
        "/admin/api/questionnaires",
        json={"name": f"可选题-{uuid.uuid4().hex[:6]}", "schemaJson": optional},
    )
    assert optional_response.status_code == 400
    assert "pages[0].questions[0] 受保护题型必须设置为必填" in _error_detail(
        optional_response
    )

    duplicate = _questionnaire_schema(
        [
            {"id": "real_name", "type": "real_name", "label": "真实姓名", "required": True},
            {
                "id": "real_name_again",
                "type": "real_name",
                "label": "真实姓名再次",
                "required": True,
            },
        ]
    )
    duplicate_response = context.admin.request(
        "POST",
        "/admin/api/questionnaires",
        json={"name": f"重复题-{uuid.uuid4().hex[:6]}", "schemaJson": duplicate},
    )
    assert duplicate_response.status_code == 400
    assert "受保护题型重复: real_name" in _error_detail(duplicate_response)


def test_map_group_webp_rejected_and_builtin_profile_read_only(server):
    context = Context(server)
    profile = create_troop_profile(context.admin, STAY_ROWS)
    webp_asset = upload_media(
        context.admin, _webp_bytes((30, 60, 90)), filename="forbidden-map.webp"
    )
    assert webp_asset["contentType"] == "image/webp"
    payload = {
        "mode": "both",
        "rows": 2,
        "cols": 2,
        "spawns": {"A": 0, "B": 1},
        "troopProfileVersionId": profile["id"],
        "practiceTrials": 1,
        "formalTrials": 2,
        "payment": {
            "basePayCents": 4500,
            "performanceRateCents": 1,
            "performanceFloorCents": 0,
            "performanceCapCents": 2000,
            "showupPayCents": 1000,
        },
        "maps": [
            {
                "slot": "Both",
                "description": f"拒绝地图{uuid.uuid4().hex[:6]}",
                "factorLevel": "标准",
                "cells": [webp_asset["id"], None, None, None],
            }
        ],
    }
    webp_response = context.admin.request("POST", "/admin/api/map-groups", json=payload)
    assert webp_response.status_code == 400
    assert "地图单元格仅支持 PNG/JPG 图片" in _error_detail(webp_response)

    profiles = context.admin.json("GET", "/admin/api/troop-profiles")["profiles"]
    builtin = next(item for item in profiles if item["builtIn"])
    builtin_version = builtin["versions"][0]
    patch_builtin = context.admin.request(
        "PATCH",
        f"/admin/api/troop-profiles/{builtin_version['id']}",
        json={"rows": [{"soldiersA": 3, "soldiersB": 4}, {"soldiersA": 5, "soldiersB": 6}]},
    )
    assert patch_builtin.status_code == 409
    assert "内置方案只读，请复制后修改" in _error_detail(patch_builtin)

    create_same = context.admin.request(
        "POST",
        "/admin/api/troop-profiles",
        json={
            "name": builtin["name"],
            "rows": [{"soldiersA": 3, "soldiersB": 4}, {"soldiersA": 5, "soldiersB": 6}],
        },
    )
    assert create_same.status_code == 409
    assert "内置方案只读，请复制后修改" in _error_detail(create_same)

    copy_name = f"复制方案-{uuid.uuid4().hex[:6]}"
    copied = context.admin.json(
        "POST",
        f"/admin/api/troop-profiles/{builtin_version['id']}/copy",
        json={"name": copy_name},
    )["troopProfile"]
    assert copied["name"] == copy_name
    assert copied["builtIn"] is False
    assert copied["status"] == "draft"
    edited = context.admin.json(
        "PATCH",
        f"/admin/api/troop-profiles/{copied['id']}",
        json={"rows": [{"soldiersA": 2, "soldiersB": 3}, {"soldiersA": 4, "soldiersB": 5}]},
    )["troopProfile"]
    assert edited["status"] == "draft"
    assert edited["rows"] == [
        {"soldiersA": 2, "soldiersB": 3},
        {"soldiersA": 4, "soldiersB": 5},
    ]


def test_map_group_draft_can_switch_troop_profile(server):
    context = Context(server)
    first_profile = create_troop_profile(context.admin, STAY_ROWS)
    second_rows = [
        {"soldiersA": 4, "soldiersB": 5},
        {"soldiersA": 6, "soldiersB": 7},
        {"soldiersA": 8, "soldiersB": 9},
    ]
    second_profile = create_troop_profile(context.admin, second_rows)
    draft_profile = create_troop_profile(context.admin, STAY_ROWS, publish=False)
    map_group = create_map_group(
        context.admin,
        first_profile["id"],
        rows=2,
        cols=2,
        formal_trials=2,
        spawns={"A": 0, "B": 1},
        description=f"换方案{uuid.uuid4().hex[:6]}",
        publish=False,
    )
    map_payload = {
        "mode": "both",
        "rows": 2,
        "cols": 2,
        "spawns": {"A": 0, "B": 1},
        "practiceTrials": 1,
        "formalTrials": 2,
        "practiceTurnCap": 3,
        "practiceTurnSeconds": 3,
        "formalTurnCap": 3,
        "formalTurnSeconds": 3,
        "restSeconds": 1,
        "randomizeFormal": True,
        "payment": {
            "basePayCents": 4500,
            "performanceRateCents": 1,
            "performanceFloorCents": 0,
            "performanceCapCents": 2000,
            "showupPayCents": 1000,
        },
        "maps": [
            {
                "slot": "Both",
                "description": map_group["maps"][0]["description"],
                "factorLevel": map_group["maps"][0]["factorLevel"],
                "cells": [None, None, None, None],
            }
        ],
    }
    switched = context.admin.json(
        "PATCH",
        f"/admin/api/map-groups/{map_group['id']}",
        json={**map_payload, "troopProfileVersionId": second_profile["id"]},
    )["mapGroup"]
    assert switched["profile"]["versionId"] == second_profile["id"]
    assert switched["profile"]["rows"] == second_rows
    assert switched["contentHash"] != map_group["contentHash"]

    mismatch = context.admin.request(
        "PATCH",
        f"/admin/api/map-groups/{map_group['id']}",
        json={
            **map_payload,
            "troopProfileVersionId": second_profile["id"],
            "formalTrials": 3,
        },
    )
    assert mismatch.status_code == 400
    assert "地图组正式对局数与兵力配置不一致" in _error_detail(mismatch)

    draft_rejected = context.admin.request(
        "PATCH",
        f"/admin/api/map-groups/{map_group['id']}",
        json={**map_payload, "troopProfileVersionId": draft_profile["id"]},
    )
    assert draft_rejected.status_code == 400
    assert "兵力配置方案版本尚未发布" in _error_detail(draft_rejected)


def test_combat_boundary_and_rest_reconnect(server):
    context = Context(server)
    participant_a, participant_b = context.participants()
    setup = context.make_room(
        troop_rows=ANNIHILATION_ROWS,
        grid=(2, 2),
        spawns={"A": 0, "B": 1},
        practice_cap=3,
        practice_seconds=2,
        formal_cap=3,
        formal_seconds=2,
        rest_seconds=4,
        reconnect_window=15,
    )
    game = _start_game(server, setup, participant_a, participant_b)

    result_a, result_b, _cells_a, _cells_b = _submit_round(
        game, game.turn_a, game.turn_b, attack=True, tag="边界攻击"
    )
    assert result_a["trialEnded"] is True
    assert result_a["warLocation"] == [1]
    assert result_a["resultDisplayMs"] == 1000
    assert result_a["round"] == 1
    state_a, rest_a = _receive_rest(game.ws_a)
    _state_b, rest_b = _receive_rest(game.ws_b)
    assert state_a["game"]["phase"] == "rest"
    assert rest_a["finalSoldiers"]["player2"] == 0
    assert 4.5 <= _seconds_until(rest_a["deadline"]) <= 5.6
    assert rest_a["nextTrialIndex"] == 1

    game.ws_b.close()
    wait_until(
        lambda: _monitor(context.admin, setup.room["id"])["restDeadline"] is None,
        timeout=10,
    )
    time.sleep(1.5)
    monitor = _monitor(context.admin, setup.room["id"])
    assert monitor["phase"] == "rest"
    assert monitor["restDeadline"] is None

    ws_b, snapshot_b = _connect(server, participant_b)
    game.ws_b = ws_b
    assert snapshot_b["game"]["phase"] == "rest"
    assert snapshot_b["game"]["restDeadline"] is not None
    resumed_a = game.ws_a.recv_until("rest")
    resumed_b = ws_b.recv_until("rest")
    assert resumed_a["deadline"] == resumed_b["deadline"]
    assert _seconds_until(resumed_a["deadline"]) > 3.0

    _state_a, _state_b, start_a, start_b, _turn_a, _turn_b = _next_trial(
        game, resumed_a, resumed_b
    )
    assert start_a["trialIndex"] == 1
    assert start_b["trialIndex"] == 1
    formal_trial = fetch_one(
        "SELECT * FROM game_trials WHERE room_id = %s AND trial_index = 0",
        (setup.room["id"],),
    )
    assert formal_trial["completed_rounds"] == 3
    assert formal_trial["forced_rounds"] == 2
    assert formal_trial["end_reason"] == "annihilation"


def test_old_v4_endpoints_removed(server):
    context = Context(server)
    conditions = context.admin.request("GET", "/admin/api/conditions")
    assert conditions.status_code == 404
    legacy_export = context.admin.request("GET", "/admin/api/payments/export.csv")
    assert legacy_export.status_code in (404, 405)
    assert "序号" not in legacy_export.text
    assert "text/csv" not in legacy_export.headers.get("content-type", "")
    profiles = context.admin.json("GET", "/admin/api/troop-profiles")
    assert profiles["profiles"]
