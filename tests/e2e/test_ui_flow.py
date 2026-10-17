import os

import pytest
from playwright.sync_api import expect, sync_playwright

from conftest import (
    ApiClient,
    ServerHandle,
    create_condition,
    create_consent,
    create_instruction,
    create_questionnaire,
    create_room,
    import_roster,
    reset_database,
)


@pytest.fixture
def ui_server():
    reset_database()
    server = ServerHandle(
        env_overrides={
            "SERVE_FRONTEND": "true",
            "JATOS_BASE_URL": "http://127.0.0.1:9000",
            "JATOS_STUDY_CODE": "ui-test",
        }
    )
    server.start()
    yield server
    server.stop()


def _login_and_consent(page, base_url, name, phone):
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")
    page.get_by_test_id("login-name").fill(name)
    page.get_by_test_id("login-phone").fill(phone)
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("consent-agree")).to_be_visible(timeout=15000)
    page.get_by_test_id("consent-agree").click()
    expect(page.get_by_text("可预约场次")).to_be_visible(timeout=15000)


def _book_room(page):
    room_option = page.get_by_test_id("room-option").first
    expect(room_option).to_be_enabled(timeout=15000)
    room_option.click()
    page.get_by_test_id("book-room").click()
    expect(page.get_by_test_id("current-booking")).to_be_visible(timeout=15000)


def _click_board_cell(page, circle: bool, cols=4, rows=3):
    wrapper = page.get_by_test_id("game-canvas-wrap")
    expect(wrapper).to_be_visible(timeout=15000)
    box = wrapper.bounding_box()
    assert box is not None
    if circle:
        x = box["x"] + box["width"] / (cols * 2)
        y = box["y"] + box["height"] / (rows * 2)
    else:
        x = box["x"] + box["width"] * (1 - 1 / (cols * 2))
        y = box["y"] + box["height"] * (1 - 1 / (rows * 2))
    page.mouse.click(x, y)


@pytest.mark.e2e
def test_two_browser_contexts_full_participant_flow_and_admin_smoke(ui_server):
    server = ui_server
    admin = ApiClient(server.base_url).login_admin()
    import_roster(admin, [("界面甲", "13400000001"), ("界面乙", "13400000002")])
    create_consent(admin)
    instruction_1 = create_instruction(admin, 1, "# 玩家1\n\n这是玩家1的指导语。", 0)
    instruction_2 = create_instruction(admin, 2, "# 玩家2\n\n这是玩家2的指导语。", 0)
    questionnaire = create_questionnaire(admin)
    condition = create_condition(
        admin, rows=3, cols=4, practice=0, formal=1, turn_count=2, turn_seconds=15, rest_seconds=1
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome")
        )
        context_a = browser.new_context(viewport={"width": 1280, "height": 900})
        context_b = browser.new_context(viewport={"width": 1280, "height": 900})
        page_a = context_a.new_page()
        page_b = context_b.new_page()
        _login_and_consent(page_a, server.base_url, "界面甲", "13400000001")
        _login_and_consent(page_b, server.base_url, "界面乙", "13400000002")
        room = create_room(
            admin,
            condition_id=condition["id"],
            instruction_p1=instruction_1["id"],
            instruction_p2=instruction_2["id"],
            questionnaire_id=questionnaire["id"],
            starts_in_seconds=15,
            wait_window_seconds=60,
            reconnect_window_seconds=20,
        )
        page_a.reload(wait_until="domcontentloaded")
        page_b.reload(wait_until="domcontentloaded")
        _book_room(page_a)
        _book_room(page_b)
        expect(page_a.get_by_test_id("enter-room")).to_be_visible(timeout=30000)
        expect(page_b.get_by_test_id("enter-room")).to_be_visible(timeout=30000)

        page_a.get_by_test_id("enter-room").click()
        page_b.get_by_test_id("enter-room").click()
        expect(page_a.get_by_test_id("start-matching")).to_be_visible(timeout=15000)
        expect(page_b.get_by_test_id("start-matching")).to_be_visible(timeout=15000)
        page_a.get_by_test_id("start-matching").click()
        page_b.get_by_test_id("start-matching").click()

        expect(page_a.get_by_test_id("instruction-content")).to_be_visible(timeout=15000)
        expect(page_b.get_by_test_id("instruction-content")).to_be_visible(timeout=15000)
        expect(page_a.get_by_test_id("instruction-content")).to_contain_text("玩家")
        expect(page_a.get_by_test_id("instruction-complete")).to_be_enabled(timeout=10000)
        expect(page_b.get_by_test_id("instruction-complete")).to_be_enabled(timeout=10000)
        page_a.get_by_test_id("instruction-complete").click()
        page_b.get_by_test_id("instruction-complete").click()
        expect(page_a.get_by_test_id("enter-game")).to_be_enabled(timeout=15000)
        expect(page_b.get_by_test_id("enter-game")).to_be_enabled(timeout=15000)
        page_a.get_by_test_id("enter-game").click()
        page_b.get_by_test_id("enter-game").click()

        for page in (page_a, page_b):
            expect(page.get_by_test_id("game-canvas")).to_be_visible(timeout=20000)
        role_a_circle = "圆形" in page_a.locator(".exp-hud-role").inner_text()
        role_b_circle = "圆形" in page_b.locator(".exp-hud-role").inner_text()
        assert role_a_circle != role_b_circle
        for round_number in (1, 2):
            for page, circle in (
                (page_a, role_a_circle),
                (page_b, role_b_circle),
            ):
                if round_number == 2:
                    expect(page.locator(".exp-hud-left")).to_contain_text("回合 2/2", timeout=20000)
                _click_board_cell(page, circle)
                expect(page.get_by_test_id("confirm-selection")).to_be_enabled(timeout=5000)
            page_a.get_by_test_id("confirm-selection").click()
            page_b.get_by_test_id("confirm-selection").click()

        expect(page_a.get_by_test_id("questionnaire-button")).to_be_visible(timeout=30000)
        expect(page_b.get_by_test_id("questionnaire-button")).to_be_visible(timeout=30000)
        assert page_a.get_by_test_id("questionnaire-button").is_enabled()

        monitor = admin.json("GET", f"/admin/api/rooms/{room['id']}/monitor")
        assert monitor["phase"] == "questionnaire"
        assert len(monitor["participants"]) == 2

        admin_context = browser.new_context(viewport={"width": 1280, "height": 900})
        admin_page = admin_context.new_page()
        admin_page.goto(f"{server.base_url}/admin/login", wait_until="domcontentloaded")
        admin_page.get_by_test_id("admin-login-username").fill("admin")
        admin_page.get_by_test_id("admin-login-password").fill("integration-admin-password")
        admin_page.get_by_test_id("admin-login-submit").click()
        expect(admin_page).to_have_url(f"{server.base_url}/admin", timeout=15000)
        expect(admin_page.locator("h1.admin-page-title")).to_contain_text("仪表盘", timeout=15000)
        admin_page.get_by_test_id("nav-participants").click()
        expect(admin_page.locator("table")).to_contain_text("界面甲", timeout=15000)
        admin_page.get_by_test_id("nav-rooms").click()
        expect(admin_page.locator("table")).to_contain_text(room["internalLabel"], timeout=15000)
        admin_page.get_by_test_id("nav-conditions").click()
        expect(admin_page.locator("body")).to_contain_text("ref0", timeout=15000)

        context_a.close()
        context_b.close()
        admin_context.close()
        browser.close()
    admin.close()
