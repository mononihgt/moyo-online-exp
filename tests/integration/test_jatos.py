import io
import json
import os
import time
import uuid
import zipfile
from urllib.parse import parse_qs, quote, urlparse

import pytest
from playwright.sync_api import sync_playwright

from conftest import (
    ID_CARD_SAMPLE,
    PASSPORT_SAMPLE,
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
    reset_database,
    wait_until,
)
from jatos_support import JatosClient, create_test_study, jatos_base_url

LOGIN_A = ("JATOS甲", "13500000001")
LOGIN_B = ("JATOS乙", "13500000002")
LOGIN_C = ("导入丙", "13500000003")
LOGIN_D = ("导入丁", "13500000004")
IDENTITY_A = {
    "real_name": "身份甲",
    "alipay_phone": "13900001111",
    "document_type": "id_card",
    "number": ID_CARD_SAMPLE,
}
IDENTITY_B = {
    "real_name": "身份乙",
    "alipay_phone": "13900001112",
    "document_type": "passport",
    "number": PASSPORT_SAMPLE,
}
PROTECTED_IDS = {"real_name", "alipay_phone", "identity_document"}
PROFILE_ROWS = [
    {"soldiersA": 7, "soldiersB": 7},
    {"soldiersA": 8, "soldiersB": 9},
]
FORMAL_TRIALS = 1
TURN_CAP = 2


def _frame_with_title(page):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        for frame in page.frames:
            try:
                if frame.locator('[data-testid="questionnaire-title"]').count() > 0:
                    return frame
            except Exception:
                continue
        page.wait_for_timeout(200)
    raise AssertionError("问卷组件未加载")


def _wait_redirect(page):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if "/complete?room=" in page.url:
            return
        for frame in page.frames:
            if "/complete?room=" in frame.url:
                return
        page.wait_for_timeout(200)
    raise AssertionError(f"问卷提交后未返回平台: {page.url}")


def _submit_questionnaire(browser, url: str, option_index: int, identity: dict) -> None:
    context = browser.new_context()
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    frame = _frame_with_title(page)
    assert "后测问卷" in frame.locator('[data-testid="questionnaire-title"]').inner_text()
    frame.locator(f"#q-question-0-option-{option_index}").check()
    frame.locator("#q-question-1-input").fill("体验顺畅")
    frame.locator("#q-question-2-input").fill(identity["real_name"])
    frame.locator("#q-question-3-input").fill(identity["alipay_phone"])
    frame.locator("#q-question-4-type").select_option(identity["document_type"])
    frame.locator("#q-question-4-input").fill(identity["number"])
    frame.locator('[data-testid="questionnaire-submit"]').click()
    _wait_redirect(page)
    context.close()


def _component_url(platform_url: str, server_base_url: str) -> str:
    parsed = urlparse(platform_url)
    assert parsed.path.startswith("/publix/")
    assert "base=" not in parsed.query
    return f"{platform_url}&base={quote(server_base_url, safe='')}"


def _owned_cell(board: dict, role: int) -> int:
    owned = [index for index, owner in enumerate(board["owners"]) if owner == role]
    assert owned, f"玩家 {role} 在棋盘上没有领地"
    return owned[0]


def _receive_phase(ws: WsClient, wanted: set[str]) -> dict:
    for _ in range(300):
        message = ws.recv()
        if message.get("type") in wanted:
            return message
        if message.get("type") == "error":
            raise AssertionError(f"websocket error: {message}")
    raise AssertionError(f"did not receive any of {wanted}")


def _wait_instruction_completed(ws: WsClient) -> None:
    for _ in range(60):
        message = ws.recv()
        if message.get("type") == "instruction_state" and message["instruction"]["completed"]:
            return
        if message.get("type") == "error":
            raise AssertionError(f"websocket error: {message}")
    raise AssertionError("instruction did not complete")


def _advance_to_questionnaire(
    server, admin, room, participant_a, participant_b
) -> tuple[str, str]:
    for participant in (participant_a, participant_b):
        wait_until(
            lambda participant=participant: (
                participant.json("GET", "/api/my-room")["room"] or {}
            ).get("status") == "waiting",
            timeout=20,
        )
    ws_a = WsClient(server, participant_a.cookie_value("moyo_participant"))
    ws_b = WsClient(server, participant_b.cookie_value("moyo_participant"))
    ws_a.send("enter_room", roomId=room["id"])
    ws_b.send("enter_room", roomId=room["id"])
    ws_a.recv_until("room_state")
    ws_b.recv_until("room_state")
    wait_until(
        lambda: all(
            booking["attendedAt"] is not None
            for booking in admin.json("GET", f"/admin/api/rooms/{room['id']}")["bookings"]
        ),
        timeout=10,
    )
    ws_a.send("start_matching", roomId=room["id"])
    ws_b.send("start_matching", roomId=room["id"])
    instruction_a = ws_a.recv_until("instruction_state")
    instruction_b = ws_b.recv_until("instruction_state")
    role_a = instruction_a["instruction"]["role"]
    role_b = instruction_b["instruction"]["role"]
    assert {role_a, role_b} == {1, 2}
    ws_a.send("instruction_complete", roomId=room["id"])
    ws_b.send("instruction_complete", roomId=room["id"])
    _wait_instruction_completed(ws_a)
    _wait_instruction_completed(ws_b)
    ws_a.send("enter_game", roomId=room["id"])
    ws_b.send("enter_game", roomId=room["id"])
    ws_a.recv_until("game_start")
    ws_b.recv_until("game_start")
    total_trials = 1 + FORMAL_TRIALS
    for trial_index in range(total_trials):
        start_a = ws_a.recv_until("trial_start")
        start_b = ws_b.recv_until("trial_start")
        assert start_a["trialIndex"] == trial_index
        assert start_b["trialIndex"] == trial_index
        turn_a = ws_a.recv_until("turn")
        turn_b = ws_b.recv_until("turn")
        for round_number in range(1, TURN_CAP + 1):
            assert turn_a["round"] == round_number
            assert turn_b["round"] == round_number
            ws_a.send(
                "submit_selection",
                roomId=room["id"],
                trialIndex=trial_index,
                round=round_number,
                cells=[_owned_cell(turn_a["board"], role_a)],
                clientMsgId=f"a-{trial_index}-{round_number}-{uuid.uuid4().hex[:8]}",
            )
            ws_b.send(
                "submit_selection",
                roomId=room["id"],
                trialIndex=trial_index,
                round=round_number,
                cells=[_owned_cell(turn_b["board"], role_b)],
                clientMsgId=f"b-{trial_index}-{round_number}-{uuid.uuid4().hex[:8]}",
            )
            result_a = ws_a.recv_until("turn_result")
            result_b = ws_b.recv_until("turn_result")
            assert result_a["round"] == round_number
            assert result_b["round"] == round_number
            if round_number < TURN_CAP:
                turn_a = ws_a.recv_until("turn")
                turn_b = ws_b.recv_until("turn")
        next_a = _receive_phase(ws_a, {"rest", "game_over"})
        next_b = _receive_phase(ws_b, {"rest", "game_over"})
        assert next_a["type"] == next_b["type"]
        if next_a["type"] == "rest":
            ws_a.send("rest_ready", roomId=room["id"])
            ws_b.send("rest_ready", roomId=room["id"])
            continue
        questionnaire_a = ws_a.recv_until("questionnaire_required")
        questionnaire_b = ws_b.recv_until("questionnaire_required")
        ws_a.close()
        ws_b.close()
        return questionnaire_a["url"], questionnaire_b["url"]
    raise AssertionError("对局未进入问卷阶段")


def _room_participant_ids(admin: ApiClient, room_id: str) -> dict[str, str]:
    detail = admin.json("GET", f"/admin/api/rooms/{room_id}")
    return {booking["name"]: booking["participantId"] for booking in detail["bookings"]}


def _json_value(value):
    return json.loads(value) if isinstance(value, str) else value


def _study_results(jatos: JatosClient, study_id: int, expected: int) -> list[dict]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        metadata = jatos.results_metadata(study_id)
        results = metadata["data"][0]["studyResults"]
        if len(results) == expected and all(
            result["studyState"] == "FINISHED" for result in results
        ):
            return results
        time.sleep(0.5)
    raise AssertionError("JATOS study result 未按时完成")


def _raw_answers(jatos: JatosClient, study_id: int, expected: int) -> list[dict]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        entries = jatos.results_data(study_id)
        if len(entries) == expected:
            return entries
        time.sleep(0.5)
    raise AssertionError("JATOS 原始结果数量不符")


def _assert_no_pii(text: str, values: list[str], location: str) -> None:
    for value in values:
        assert value not in text, f"{location} 包含敏感信息: {value}"


def _assert_export_boundary(admin: ApiClient, room_id: str, pii_values: list[str]) -> dict:
    export = admin.json("GET", f"/admin/api/rooms/{room_id}/export.json")
    _assert_no_pii(json.dumps(export, ensure_ascii=False), pii_values, "export.json")
    for participant in export["participants"]:
        questionnaire = participant.get("questionnaire") or {}
        answers = questionnaire.get("answers")
        if answers is not None:
            assert PROTECTED_IDS.isdisjoint(answers)
    zip_response = admin.request("GET", f"/admin/api/rooms/{room_id}/analysis.zip")
    assert zip_response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(zip_response.content))
    for name in archive.namelist():
        content = archive.read(name).decode("utf-8", errors="ignore")
        _assert_no_pii(content, pii_values, f"analysis.zip:{name}")
    return export


def _assert_canonical_answers(room_id: str, participant_id: str, source: str) -> dict:
    rows = fetch_all(
        "SELECT answers_json, canonical, source, jatos_study_result_id, "
        "jatos_component_result_id FROM questionnaire_responses "
        "WHERE room_id = %s AND participant_id = %s",
        (room_id, participant_id),
    )
    assert len(rows) == 1
    row = rows[0]
    assert bool(row["canonical"]) is True
    assert row["source"] == source
    answers = _json_value(row["answers_json"])
    assert PROTECTED_IDS.isdisjoint(answers)
    return answers


def _assert_identity_encrypted(room_id: str) -> dict[str, dict]:
    rows = fetch_all(
        "SELECT participant_id, real_name_encrypted, alipay_phone_encrypted, "
        "document_type, document_number_encrypted FROM participant_identities WHERE room_id = %s",
        (room_id,),
    )
    assert rows
    by_pid = {row["participant_id"]: row for row in rows}
    for row in rows:
        for column in ("real_name_encrypted", "alipay_phone_encrypted", "document_number_encrypted"):
            assert row[column].startswith("gAAAA")
        assert row["document_type"] in ("id_card", "passport")
    return by_pid


@pytest.mark.jatos
@pytest.mark.integration
def test_real_jatos_protected_answers_and_manual_import():
    jatos = JatosClient()
    study = create_test_study(jatos)
    server = None
    try:
        reset_database()
        server = ServerHandle(
            env_overrides={
                "JATOS_BASE_URL": jatos_base_url(),
                "JATOS_STUDY_CODE": study["code"],
            }
        )
        server.start()
        admin = ApiClient(server.base_url).login_admin()
        create_consent(admin)
        profile = create_troop_profile(admin, PROFILE_ROWS)
        map_group = create_map_group(
            admin,
            profile["id"],
            rows=3,
            cols=3,
            formal_trials=FORMAL_TRIALS,
            practice_turn_cap=TURN_CAP,
            practice_turn_seconds=3,
            formal_turn_cap=TURN_CAP,
            formal_turn_seconds=3,
            rest_seconds=1,
        )
        instruction_a = create_instruction(admin, map_group["id"], 1, "# 玩家1", 0)
        instruction_b = create_instruction(admin, map_group["id"], 2, "# 玩家2", 0)
        questionnaire = create_questionnaire(admin)
        room_real = create_room(
            admin,
            map_group["id"],
            instruction_a["id"],
            instruction_b["id"],
            questionnaire["id"],
            starts_in_seconds=10,
            wait_window_seconds=600,
            reconnect_window_seconds=10,
        )
        room_import = create_room(
            admin,
            map_group["id"],
            instruction_a["id"],
            instruction_b["id"],
            questionnaire["id"],
            starts_in_seconds=10,
            wait_window_seconds=600,
            reconnect_window_seconds=10,
        )

        participant_a = ApiClient(server.base_url).login_participant(*LOGIN_A)
        participant_b = ApiClient(server.base_url).login_participant(*LOGIN_B)
        participant_c = ApiClient(server.base_url).login_participant(*LOGIN_C)
        participant_d = ApiClient(server.base_url).login_participant(*LOGIN_D)
        for participant in (participant_a, participant_b, participant_c, participant_d):
            participant.consent()
        participant_a.json("POST", f"/api/rooms/{room_real['id']}/book")
        participant_b.json("POST", f"/api/rooms/{room_real['id']}/book")
        participant_c.json("POST", f"/api/rooms/{room_import['id']}/book")
        participant_d.json("POST", f"/api/rooms/{room_import['id']}/book")

        url_a, url_b = _advance_to_questionnaire(
            server, admin, room_real, participant_a, participant_b
        )
        parsed_a = urlparse(url_a)
        parsed_b = urlparse(url_b)
        assert parsed_a.path == f"/publix/{study['code']}"
        assert parsed_b.path == f"/publix/{study['code']}"
        query_a = parse_qs(parsed_a.query)
        query_b = parse_qs(parsed_b.query)
        assert query_a["rt"] and query_a["pid"]
        assert query_b["rt"] and query_b["pid"]
        analysis_code_a = query_a["pid"][0]
        analysis_code_b = query_b["pid"][0]

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome")
            )
            _submit_questionnaire(
                browser, _component_url(url_a, server.base_url), 0, IDENTITY_A
            )
            _submit_questionnaire(
                browser, _component_url(url_b, server.base_url), 1, IDENTITY_B
            )
            browser.close()

        wait_until(
            lambda: admin.json("GET", f"/admin/api/rooms/{room_real['id']}")["room"]["status"]
            == "archived",
            timeout=30,
        )
        detail_real = admin.json("GET", f"/admin/api/rooms/{room_real['id']}")
        assert detail_real["room"]["archiveReason"] == "completed"
        assert all(
            item["questionnaireStatus"] == "completed" for item in detail_real["participants"]
        )
        assert len(detail_real["payments"]) == 2
        assert all(item["status"] == "pending" for item in detail_real["payments"])
        real_pids = _room_participant_ids(admin, room_real["id"])

        answers_a = _assert_canonical_answers(
            room_real["id"], real_pids[LOGIN_A[0]], "jatos"
        )
        answers_b = _assert_canonical_answers(
            room_real["id"], real_pids[LOGIN_B[0]], "jatos"
        )
        assert answers_a["q1"] == "female"
        assert answers_b["q1"] == "male"
        identity_rows = _assert_identity_encrypted(room_real["id"])
        assert set(identity_rows) == {real_pids[LOGIN_A[0]], real_pids[LOGIN_B[0]]}
        assert identity_rows[real_pids[LOGIN_A[0]]]["document_type"] == "id_card"
        assert identity_rows[real_pids[LOGIN_B[0]]]["document_type"] == "passport"
        assert (
            identity_rows[real_pids[LOGIN_A[0]]]["real_name_encrypted"]
            != IDENTITY_A["real_name"]
        )
        assert (
            identity_rows[real_pids[LOGIN_A[0]]]["document_number_encrypted"]
            != IDENTITY_A["number"]
        )

        participant_names = {
            row["name"]
            for row in fetch_all(
                "SELECT name FROM participants WHERE id IN (%s, %s)",
                (real_pids[LOGIN_A[0]], real_pids[LOGIN_B[0]]),
            )
        }
        assert participant_names == {LOGIN_A[0], LOGIN_B[0]}
        assert IDENTITY_A["real_name"] not in participant_names
        assert IDENTITY_B["real_name"] not in participant_names

        pii_room_real = [
            IDENTITY_A["real_name"],
            IDENTITY_A["alipay_phone"],
            IDENTITY_A["number"],
            IDENTITY_B["real_name"],
            IDENTITY_B["alipay_phone"],
            IDENTITY_B["number"],
        ]
        export_real = _assert_export_boundary(admin, room_real["id"], pii_room_real)
        platform_pairs = {
            (
                str(participant["questionnaire"]["jatosStudyResultId"]),
                str(participant["questionnaire"]["jatosComponentResultId"]),
            )
            for participant in export_real["participants"]
        }
        assert len(platform_pairs) == 2

        study_results = _study_results(jatos, study["study_id"], 2)
        jatos_pairs = {
            (str(result["id"]), str(component["id"]))
            for result in study_results
            for component in result["componentResults"]
            if component["componentState"] == "FINISHED"
        }
        assert jatos_pairs == platform_pairs

        raw_entries = _raw_answers(jatos, study["study_id"], 2)
        assert sorted(entry["answers"]["q1"] for entry in raw_entries) == ["female", "male"]
        assert {entry["analysisCode"] for entry in raw_entries} == {
            analysis_code_a,
            analysis_code_b,
        }
        raw_a = next(
            entry["answers"] for entry in raw_entries if entry["analysisCode"] == analysis_code_a
        )
        # 导入载荷来自 JATOS 原始结果；平台侧保存与导出边界在下方断言。
        assert PROTECTED_IDS <= set(raw_a)

        export_a = next(
            participant
            for participant in export_real["participants"]
            if participant["analysisCode"] == analysis_code_a
        )
        jatos_ids = {
            "jatosWorkerId": export_a["questionnaire"]["jatosWorkerId"],
            "jatosStudyResultId": export_a["questionnaire"]["jatosStudyResultId"],
            "jatosComponentResultId": export_a["questionnaire"]["jatosComponentResultId"],
        }

        url_c, url_d = _advance_to_questionnaire(
            server, admin, room_import, participant_c, participant_d
        )
        assert "/publix/" in urlparse(url_c).path
        assert "/publix/" in urlparse(url_d).path
        import_pids = _room_participant_ids(admin, room_import["id"])
        missing_protected = {
            key: value for key, value in raw_a.items() if key not in PROTECTED_IDS
        }
        missing_payload = {
            "action": "import_jatos_result",
            "participantId": import_pids[LOGIN_D[0]],
            "answers": missing_protected,
            **jatos_ids,
        }
        missing_response = admin.request(
            "POST", f"/admin/api/rooms/{room_import['id']}/actions", json=missing_payload
        )
        assert missing_response.status_code == 400, missing_response.text
        assert "必填题未作答" in missing_response.json()["detail"]
        assert fetch_all(
            "SELECT id FROM payments WHERE room_id = %s AND participant_id = %s",
            (room_import["id"], import_pids[LOGIN_D[0]]),
        ) == []
        assert fetch_all(
            "SELECT id FROM questionnaire_responses WHERE room_id = %s AND participant_id = %s",
            (room_import["id"], import_pids[LOGIN_D[0]]),
        ) == []
        assert (
            admin.json("GET", f"/admin/api/rooms/{room_import['id']}")["room"]["status"]
            == "questionnaire"
        )

        import_payload = {
            "action": "import_jatos_result",
            "participantId": import_pids[LOGIN_C[0]],
            "answers": raw_a,
            **jatos_ids,
        }
        imported = admin.json(
            "POST", f"/admin/api/rooms/{room_import['id']}/actions", json=import_payload
        )
        assert imported["saved"] is True
        assert imported["canonical"] is True
        duplicate = admin.json(
            "POST", f"/admin/api/rooms/{room_import['id']}/actions", json=import_payload
        )
        assert duplicate["saved"] is True
        assert len(
            fetch_all(
                "SELECT id FROM questionnaire_responses WHERE room_id = %s AND participant_id = %s",
                (room_import["id"], import_pids[LOGIN_C[0]]),
            )
        ) == 1
        assert len(
            fetch_all(
                "SELECT id FROM payments WHERE room_id = %s AND participant_id = %s",
                (room_import["id"], import_pids[LOGIN_C[0]]),
            )
        ) == 1
        assert len(
            fetch_all(
                "SELECT id FROM participant_identities WHERE room_id = %s AND participant_id = %s",
                (room_import["id"], import_pids[LOGIN_C[0]]),
            )
        ) == 1
        _assert_canonical_answers(room_import["id"], import_pids[LOGIN_C[0]], "admin")

        imported_d = admin.json(
            "POST",
            f"/admin/api/rooms/{room_import['id']}/actions",
            json={**import_payload, "participantId": import_pids[LOGIN_D[0]]},
        )
        assert imported_d["saved"] is True
        assert imported_d["canonical"] is True
        wait_until(
            lambda: admin.json("GET", f"/admin/api/rooms/{room_import['id']}")["room"]["status"]
            == "archived",
            timeout=30,
        )
        detail_import = admin.json("GET", f"/admin/api/rooms/{room_import['id']}")
        assert detail_import["room"]["archiveReason"] == "completed"
        assert len(detail_import["payments"]) == 2
        _assert_canonical_answers(room_import["id"], import_pids[LOGIN_D[0]], "admin")
        _assert_identity_encrypted(room_import["id"])
        _assert_export_boundary(admin, room_import["id"], pii_room_real)

        all_names = {row["name"] for row in fetch_all("SELECT name FROM participants")}
        assert all_names == {LOGIN_A[0], LOGIN_B[0], LOGIN_C[0], LOGIN_D[0]}
        payment_rows = fetch_all(
            "SELECT room_id, participant_id, status FROM payments ORDER BY room_id"
        )
        assert len(payment_rows) == 4
        assert all(row["status"] == "pending" for row in payment_rows)
    finally:
        if server is not None:
            server.stop()
        jatos.close()
