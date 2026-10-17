import os
import time
import uuid
from urllib.parse import parse_qs, quote, urlparse

import pytest
from playwright.sync_api import sync_playwright

from conftest import (
    ApiClient,
    ServerHandle,
    WsClient,
    create_condition,
    create_consent,
    create_instruction,
    create_questionnaire,
    create_room,
    import_roster,
    reset_database,
    wait_until,
)
from jatos_support import JatosClient, create_test_study, jatos_base_url


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


def _submit_questionnaire(browser, url: str, option_index: int) -> None:
    context = browser.new_context()
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    frame = _frame_with_title(page)
    assert "后测问卷" in frame.locator('[data-testid="questionnaire-title"]').inner_text()
    frame.locator(f"#q-question-0-option-{option_index}").check()
    frame.locator('[data-testid="questionnaire-submit"]').click()
    _wait_redirect(page)
    context.close()


def _advance_to_questionnaire(server, admin, room, participant_a, participant_b):
    wait_until(lambda: participant_a.json("GET", "/api/my-room")["room"]["status"] == "waiting", timeout=20)
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
    ws_a.send("instruction_complete", roomId=room["id"])
    ws_b.send("instruction_complete", roomId=room["id"])
    for ws in (ws_a, ws_b):
        for _ in range(20):
            message = ws.recv()
            if message.get("type") == "instruction_state" and message["instruction"]["completed"]:
                break
        else:
            raise AssertionError("instruction did not complete")
    ws_a.send("enter_game", roomId=room["id"])
    ws_b.send("enter_game", roomId=room["id"])
    turn_a = ws_a.recv_until("turn")
    turn_b = ws_b.recv_until("turn")
    while True:
        for ws, role, board in (
            (ws_a, role_a, turn_a["board"]),
            (ws_b, role_b, turn_b["board"]),
        ):
            owned = [index for index, owner in enumerate(board["owners"]) if owner == role]
            ws.send(
                "submit_selection",
                roomId=room["id"],
                trialIndex=turn_a["trialIndex"],
                round=turn_a["round"],
                cells=[owned[0] if owned else 0],
                clientMsgId=f"jatos-{role}-{turn_a['round']}-{uuid.uuid4().hex[:6]}",
            )
        result = ws_a.recv_until("turn_result")
        ws_b.recv_until("turn_result")
        if result["trialEnded"]:
            break
        turn_a = ws_a.recv_until("turn")
        turn_b = ws_b.recv_until("turn")
    game_over_a = ws_a.recv_until("game_over")
    game_over_b = ws_b.recv_until("game_over")
    questionnaire_a = ws_a.recv_until("questionnaire_required")
    questionnaire_b = ws_b.recv_until("questionnaire_required")
    ws_a.close()
    ws_b.close()
    return game_over_a, game_over_b, questionnaire_a, questionnaire_b


@pytest.mark.jatos
@pytest.mark.integration
def test_real_jatos_component_double_write_and_redirect():
    jatos = JatosClient()
    study = create_test_study(jatos)
    reset_database()
    server = ServerHandle(
        env_overrides={
            "JATOS_BASE_URL": jatos_base_url(),
            "JATOS_STUDY_CODE": study["code"],
        }
    )
    server.start()
    try:
        admin = ApiClient(server.base_url).login_admin()
        import_roster(admin, [("JATOS甲", "13500000001"), ("JATOS乙", "13500000002")])
        create_consent(admin)
        instruction_1 = create_instruction(admin, 1, "# 玩家1", 0)
        instruction_2 = create_instruction(admin, 2, "# 玩家2", 0)
        questionnaire = create_questionnaire(admin)
        condition = create_condition(
            admin, rows=3, cols=4, practice=0, formal=1, turn_count=2, turn_seconds=6, rest_seconds=1
        )
        room = create_room(
            admin,
            condition_id=condition["id"],
            instruction_p1=instruction_1["id"],
            instruction_p2=instruction_2["id"],
            questionnaire_id=questionnaire["id"],
            starts_in_seconds=2,
            reconnect_window_seconds=10,
        )
        participant_a = ApiClient(server.base_url).login_participant("JATOS甲", "13500000001")
        participant_b = ApiClient(server.base_url).login_participant("JATOS乙", "13500000002")
        participant_a.consent()
        participant_b.consent()
        participant_a.json("POST", f"/api/rooms/{room['id']}/book")
        participant_b.json("POST", f"/api/rooms/{room['id']}/book")
        game_over_a, game_over_b, questionnaire_a, questionnaire_b = _advance_to_questionnaire(
            server, admin, room, participant_a, participant_b
        )
        assert game_over_a["questionnaireUrl"]
        assert game_over_b["questionnaireUrl"]
        assert questionnaire_a["url"] == game_over_a["questionnaireUrl"]
        url_a = questionnaire_a["url"]
        url_b = questionnaire_b["url"]
        token_a = parse_qs(urlparse(url_a).query)["rt"][0]
        token_b = parse_qs(urlparse(url_b).query)["rt"][0]
        pid_a = parse_qs(urlparse(url_a).query)["pid"][0]
        pid_b = parse_qs(urlparse(url_b).query)["pid"][0]
        component_url_a = (
            f"{jatos_base_url()}/publix/{study['code']}?rt={quote(token_a)}"
            f"&pid={quote(pid_a)}&base={quote(server.base_url)}"
        )
        component_url_b = (
            f"{jatos_base_url()}/publix/{study['code']}?rt={quote(token_b)}"
            f"&pid={quote(pid_b)}&base={quote(server.base_url)}"
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome")
            )
            _submit_questionnaire(browser, component_url_a, 0)
            _submit_questionnaire(browser, component_url_b, 1)
            browser.close()

        wait_until(
            lambda: admin.json("GET", f"/admin/api/rooms/{room['id']}")["room"]["status"] == "archived",
            timeout=20,
        )
        detail = admin.json("GET", f"/admin/api/rooms/{room['id']}")
        assert detail["room"]["archiveReason"] == "completed"
        assert all(item["questionnaireStatus"] == "completed" for item in detail["participants"])

        exports = admin.json("GET", f"/admin/api/rooms/{room['id']}/export.json")
        assert len(exports["participants"]) == 2
        assert all(
            participant["questionnaire"]["jatosStudyResultId"]
            and participant["questionnaire"]["jatosComponentResultId"]
            for participant in exports["participants"]
        )
        platform_pairs = {
            (attempt["jatosStudyResultId"], attempt["jatosComponentResultId"])
            for participant in exports["participants"]
            for attempt in participant["questionnaire"]["attempts"]
        }

        metadata = jatos.results_metadata(study["study_id"])
        data = metadata["data"][0]
        study_results = data["studyResults"]
        assert len(study_results) == 2
        for result in study_results:
            assert result["studyState"] == "FINISHED"
            for component_result in result["componentResults"]:
                assert component_result["componentState"] == "FINISHED"
        jatos_pairs = {
            (str(result["id"]), str(component["id"]))
            for result in study_results
            for component in result["componentResults"]
        }
        assert jatos_pairs == platform_pairs

        answers = jatos.results_data(study["study_id"])
        assert len(answers) == 2
        answer_values = sorted(entry["answers"]["q1"] for entry in answers)
        assert answer_values == ["female", "male"]
        for entry in answers:
            assert entry["analysisCode"] in (pid_a, pid_b)
            assert entry["questionnaireVersionId"] == questionnaire["id"]
        payments = admin.json("GET", "/admin/api/payments")["payments"]
        assert len(payments) == 2
        assert all(item["status"] == "pending" for item in payments)
    finally:
        server.stop()
        jatos.close()
