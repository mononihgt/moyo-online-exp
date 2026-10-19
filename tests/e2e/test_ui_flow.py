import os
import re

import pytest
from playwright.sync_api import expect, sync_playwright

from conftest import (
    ApiClient,
    ServerHandle,
    create_consent,
    create_instruction,
    create_map_group,
    create_questionnaire,
    create_room,
    create_troop_profile,
    import_roster,
    questionnaire_answers,
    reset_database,
    valid_identity_answers,
    wait_until,
)

ROOM_SECTIONS = ["未开放预约", "开放预约", "进行中", "未完全支付", "已归档"]
DETAIL_TABS = ["概览", "预约", "监控", "数据", "付款"]
PHONES = {"界面甲": "13400000001", "界面乙": "13400000002"}
IDENTITIES = {
    "界面甲": valid_identity_answers("界面甲", phone="13900004441"),
    "界面乙": valid_identity_answers("界面乙", phone="13900004442"),
}


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


def _book_room(page, room_id):
    option = page.locator(
        f'[data-testid="room-option"][data-room-id="{room_id}"]'
    )
    expect(option).to_be_enabled(timeout=30000)
    option.click()
    expect(page.get_by_test_id("book-room")).to_be_enabled(timeout=15000)
    page.get_by_test_id("book-room").click()
    expect(page.get_by_test_id("current-booking")).to_contain_text(
        "开始时间", timeout=15000
    )


def _role_marker(page):
    text = page.locator(".exp-hud-role").inner_text()
    assert "○" in text or "◇" in text, text
    return "circle" if "○" in text else "diamond"


def _click_cell(page, index, rows, cols):
    canvas = page.get_by_test_id("game-canvas")
    expect(canvas).to_be_visible(timeout=30000)
    box = canvas.bounding_box()
    assert box is not None
    row, col = divmod(index, cols)
    page.mouse.click(
        box["x"] + (col + 0.5) * box["width"] / cols,
        box["y"] + (row + 0.5) * box["height"] / rows,
    )
    confirm = page.get_by_test_id("confirm-selection")
    expect(confirm).to_be_enabled(timeout=10000)
    confirm.click()


def _submit_round(page_a, page_b, marker_a, marker_b, rows, cols):
    circle_index = 1
    diamond_index = max(2, rows * cols - 2)
    _click_cell(
        page_a,
        circle_index if marker_a == "circle" else diamond_index,
        rows,
        cols,
    )
    _click_cell(
        page_b,
        circle_index if marker_b == "circle" else diamond_index,
        rows,
        cols,
    )


def _expect_hud_label(page_a, page_b, label):
    expect(page_a.locator(".exp-hud-left")).to_contain_text(label, timeout=30000)
    expect(page_b.locator(".exp-hud-left")).to_contain_text(label, timeout=30000)


def _open_nav(page, testid, title):
    page.get_by_test_id(testid).click()
    expect(page.locator("h1.admin-page-title")).to_have_text(title, timeout=15000)


def _submit_questionnaires(server, room_id):
    clients = []
    try:
        for name, phone, tag in (
            ("界面甲", "13400000001", "ui-a"),
            ("界面乙", "13400000002", "ui-b"),
        ):
            client = ApiClient(server.base_url).login_participant(name, phone)
            client.consent()
            client.json(
                "POST",
                "/api/questionnaire/complete",
                json={
                    "roomId": room_id,
                    "answers": questionnaire_answers(
                        IDENTITIES[name], q1="female", q2=f"{name}的问卷回答"
                    ),
                    "jatosWorkerId": f"ui-worker-{tag}",
                    "jatosStudyResultId": f"ui-study-{tag}",
                    "jatosComponentResultId": f"ui-component-{tag}",
                },
            )
            clients.append(client)
    finally:
        for client in clients:
            client.close()


@pytest.mark.e2e
def test_two_browser_contexts_full_participant_flow_and_admin_smoke(ui_server):
    server = ui_server
    admin = ApiClient(server.base_url).login_admin()
    import_roster(admin, [("界面甲", "13400000001"), ("界面乙", "13400000002")])
    create_consent(admin)
    profile = create_troop_profile(
        admin,
        rows=[
            {"soldiersA": 7, "soldiersB": 7},
            {"soldiersA": 8, "soldiersB": 9},
        ],
        name="界面测试兵力",
    )
    map_group = create_map_group(
        admin,
        profile["id"],
        rows=3,
        cols=4,
        formal_trials=1,
        description="界面测试地图",
        factor_level="界面条件",
        practice_turn_cap=1,
        practice_turn_seconds=15,
        formal_turn_cap=2,
        formal_turn_seconds=15,
        rest_seconds=1,
        randomize_formal=False,
    )
    instruction_1 = create_instruction(
        admin, map_group["id"], 1, "# 玩家1\n\n这是玩家1的指导语。", 0
    )
    instruction_2 = create_instruction(
        admin, map_group["id"], 2, "# 玩家2\n\n这是玩家2的指导语。", 0
    )
    questionnaire = create_questionnaire(admin)
    materials = {
        "map_group_version_id": map_group["id"],
        "instruction_p1": instruction_1["id"],
        "instruction_p2": instruction_2["id"],
        "questionnaire_id": questionnaire["id"],
    }
    create_room(
        admin,
        **materials,
        starts_in_seconds=7200,
        wait_window_seconds=90,
        reconnect_window_seconds=20,
        label="界面草稿房间",
        publish=False,
    )
    create_room(
        admin,
        **materials,
        starts_in_seconds=7200,
        wait_window_seconds=90,
        reconnect_window_seconds=20,
        label="界面关闭预约房间",
    )
    create_room(
        admin,
        **materials,
        starts_in_seconds=7200,
        wait_window_seconds=90,
        reconnect_window_seconds=20,
        label="界面开放房间",
    )
    late_room = create_room(
        admin,
        **materials,
        starts_in_seconds=3,
        wait_window_seconds=300,
        reconnect_window_seconds=20,
        label="界面开始锁定房间",
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
            **materials,
            starts_in_seconds=15,
            wait_window_seconds=90,
            reconnect_window_seconds=20,
            label="界面测试房间",
        )
        page_a.reload(wait_until="domcontentloaded")
        page_b.reload(wait_until="domcontentloaded")
        _book_room(page_a, room["id"])
        _book_room(page_b, room["id"])
        page_a.reload(wait_until="domcontentloaded")
        page_b.reload(wait_until="domcontentloaded")
        expect(page_a.get_by_test_id("current-booking")).to_contain_text(
            "2/2", timeout=15000
        )
        expect(page_b.get_by_test_id("current-booking")).to_contain_text(
            "2/2", timeout=15000
        )

        expect(page_a.get_by_test_id("enter-room")).to_be_visible(timeout=45000)
        expect(page_b.get_by_test_id("enter-room")).to_be_visible(timeout=45000)
        page_a.get_by_test_id("enter-room").click()
        page_b.get_by_test_id("enter-room").click()
        expect(page_a.get_by_test_id("start-matching")).to_be_visible(
            timeout=30000
        )
        expect(page_b.get_by_test_id("start-matching")).to_be_visible(
            timeout=30000
        )
        page_a.get_by_test_id("start-matching").click()
        page_b.get_by_test_id("start-matching").click()

        expect(page_a.get_by_test_id("instruction-content")).to_be_visible(
            timeout=30000
        )
        expect(page_b.get_by_test_id("instruction-content")).to_be_visible(
            timeout=30000
        )
        expect(page_a.get_by_test_id("instruction-content")).to_contain_text(
            "这是玩家"
        )
        expect(page_b.get_by_test_id("instruction-content")).to_contain_text(
            "这是玩家"
        )
        expect(page_a.get_by_test_id("instruction-complete")).to_be_enabled(
            timeout=10000
        )
        expect(page_b.get_by_test_id("instruction-complete")).to_be_enabled(
            timeout=10000
        )
        page_a.get_by_test_id("instruction-complete").click()
        page_b.get_by_test_id("instruction-complete").click()
        page_a.get_by_test_id("enter-game").click()
        page_b.get_by_test_id("enter-game").click()

        expect(page_a.get_by_test_id("game-canvas")).to_be_visible(timeout=30000)
        expect(page_b.get_by_test_id("game-canvas")).to_be_visible(timeout=30000)
        marker_a = _role_marker(page_a)
        marker_b = _role_marker(page_b)
        assert marker_a != marker_b

        _expect_hud_label(page_a, page_b, "练习 1/1")
        for page in (page_a, page_b):
            expect(page.get_by_test_id("trial-info-badge")).to_have_attribute(
                "aria-label",
                "本局初始兵力与每格收益：玩家 A +7，玩家 B +7",
                timeout=20000,
            )
        _submit_round(page_a, page_b, marker_a, marker_b, rows=3, cols=4)
        expect(page_a.get_by_test_id("rest-view")).to_be_visible(timeout=30000)
        expect(page_b.get_by_test_id("rest-view")).to_be_visible(timeout=30000)
        expect(page_a.get_by_test_id("rest-title")).to_have_text("练习结束")
        expect(page_a.get_by_test_id("rest-trial-chip")).to_have_text("练习局")

        expect(page_a.get_by_test_id("rest-ready")).to_be_enabled(timeout=20000)
        expect(page_b.get_by_test_id("rest-ready")).to_be_enabled(timeout=20000)
        page_a.get_by_test_id("rest-ready").click()
        page_b.get_by_test_id("rest-ready").click()

        _expect_hud_label(page_a, page_b, "正式 1/1 · 回合 1/2")
        for page in (page_a, page_b):
            expect(page.get_by_test_id("trial-info-badge")).to_have_attribute(
                "aria-label",
                "本局初始兵力与每格收益：玩家 A +8，玩家 B +9",
                timeout=30000,
            )
        _submit_round(page_a, page_b, marker_a, marker_b, rows=3, cols=4)
        _expect_hud_label(page_a, page_b, "正式 1/1 · 回合 2/2")
        _submit_round(page_a, page_b, marker_a, marker_b, rows=3, cols=4)
        expect(
            page_a.get_by_role("heading", name="请填写后测问卷", exact=True)
        ).to_be_visible(timeout=30000)
        expect(
            page_b.get_by_role("heading", name="请填写后测问卷", exact=True)
        ).to_be_visible(timeout=30000)
        expect(page_a.get_by_test_id("exit-experiment")).to_have_count(0)

        admin_context = browser.new_context(viewport={"width": 1280, "height": 900})
        admin_page = admin_context.new_page()
        admin_page.goto(
            f"{server.base_url}/admin/login", wait_until="domcontentloaded"
        )
        admin_page.get_by_test_id("admin-login-username").fill("admin")
        admin_page.get_by_test_id("admin-login-password").fill(
            "integration-admin-password"
        )
        admin_page.get_by_test_id("admin-login-submit").click()
        expect(admin_page).to_have_url(f"{server.base_url}/admin", timeout=15000)
        expect(admin_page.locator("h1.admin-page-title")).to_have_text("仪表盘")

        _open_nav(admin_page, "nav-participants", "被试名单")
        expect(admin_page.locator("table")).to_contain_text("界面甲")

        _open_nav(admin_page, "nav-troop-profiles", "兵力方案")
        expect(
            admin_page.get_by_test_id(f"troop-profile-version-{profile['id']}")
        ).to_be_visible()
        expect(admin_page.get_by_test_id("troop-profile-create")).to_be_visible()

        _open_nav(admin_page, "nav-map-groups", "地图组")
        admin_page.get_by_test_id(
            f"map-group-version-{map_group['id']}"
        ).click()
        preview_row = admin_page.get_by_test_id("map-group-preview-row")
        expect(preview_row).to_have_value("1")
        expect(preview_row.locator("option")).to_have_text(["练习", "正式 1"])
        badge = admin_page.get_by_test_id("trial-info-badge")
        expect(badge).to_have_attribute(
            "aria-label", "本局初始兵力与每格收益：玩家 A +8，玩家 B +9"
        )
        preview_row.select_option("0")
        expect(badge).to_have_attribute(
            "aria-label", "本局初始兵力与每格收益：玩家 A +7，玩家 B +7"
        )

        _open_nav(admin_page, "nav-instructions", "指导语")
        expect(
            admin_page.get_by_test_id(
                f"instruction-version-{instruction_1['id']}"
            )
        ).to_be_visible()
        admin_page.get_by_test_id(
            f"instruction-version-{instruction_1['id']}"
        ).click()
        expect(admin_page.get_by_text("已发布版本只读").first).to_be_visible()

        _open_nav(admin_page, "nav-questionnaires", "问卷")
        admin_page.get_by_test_id("questionnaire-create").click()
        protected = admin_page.get_by_test_id("questionnaire-protected-status")
        expect(protected).to_be_visible()
        expect(protected).to_contain_text("缺少受保护字段：真实姓名")
        expect(protected).to_contain_text("缺少受保护字段：支付宝手机号")
        expect(protected).to_contain_text("缺少受保护字段：身份证明")
        publish = admin_page.get_by_test_id("questionnaire-publish")
        expect(publish).to_be_disabled()
        first_type = admin_page.get_by_test_id("questionnaire-question-type-0-0")
        first_type.select_option("real_name")
        first_required = admin_page.get_by_test_id("questionnaire-required-0-0")
        expect(first_required).to_be_checked()
        expect(first_required).to_be_disabled()
        for index_text, question_type in (
            ("1", "alipay_phone"),
            ("2", "identity_document"),
        ):
            admin_page.get_by_test_id("questionnaire-add-question-0").click()
            type_select = admin_page.get_by_test_id(
                f"questionnaire-question-type-0-{index_text}"
            )
            type_select.select_option(question_type)
            required = admin_page.get_by_test_id(
                f"questionnaire-required-0-{index_text}"
            )
            expect(required).to_be_checked()
            expect(required).to_be_disabled()
        expect(admin_page.get_by_text("受保护字段 3/3")).to_be_visible()
        expect(protected).to_have_count(0)
        expect(publish).to_be_enabled()
        duplicate = first_type.locator('option[value="alipay_phone"]')
        expect(duplicate).to_be_disabled()
        expect(duplicate).to_contain_text("已使用")

        _open_nav(admin_page, "nav-rooms", "房间")
        section_filter = admin_page.get_by_test_id("room-section-filter")
        expect(section_filter).to_have_value("draft")
        section_texts = section_filter.locator("option").all_text_contents()
        assert [text.split("（")[0].strip() for text in section_texts] == ROOM_SECTIONS
        assert all(re.search(r"（\d+）$", text.strip()) for text in section_texts)
        rooms_table = admin_page.locator("table.admin-table")
        expect(
            rooms_table.get_by_role("link", name="界面草稿房间", exact=True)
        ).to_be_visible()
        expect(admin_page.get_by_test_id("room-create")).to_be_visible()
        expect(admin_page.get_by_test_id("room-batch-create")).to_be_visible()

        section_filter.select_option("open")
        expect(
            rooms_table.get_by_role("link", name="界面开放房间", exact=True)
        ).to_be_visible()
        expect(
            rooms_table.get_by_role("link", name="界面关闭预约房间", exact=True)
        ).to_be_visible()
        expect(admin_page.get_by_test_id("room-create")).to_have_count(0)
        expect(admin_page.get_by_test_id("room-batch-create")).to_have_count(0)
        close_row = admin_page.locator("table.admin-table tr").filter(
            has_text="界面关闭预约房间"
        )
        close_button = close_row.get_by_test_id("room-close-booking")
        expect(close_button).to_be_enabled()
        close_button.click()
        close_dialog = admin_page.get_by_role("dialog", name="关闭预约")
        expect(close_dialog).to_be_visible()
        close_dialog.get_by_role("button", name="关闭预约", exact=True).click()
        expect(
            admin_page.get_by_text("Room 已关闭预约并回到草稿状态")
        ).to_be_visible()
        section_filter.select_option("draft")
        expect(
            rooms_table.get_by_role("link", name="界面关闭预约房间", exact=True)
        ).to_be_visible()

        rooms_table.get_by_role("link", name="界面草稿房间", exact=True).click()
        expect(admin_page.locator("h1.admin-page-title")).to_have_text("房间详情")
        expect(
            admin_page.locator('[data-testid^="room-tab-"]')
        ).to_have_text(DETAIL_TABS)
        admin_page.get_by_test_id("room-edit").click()
        expect(admin_page.get_by_test_id("room-form-starts-at")).to_be_enabled()
        admin_page.locator("form").get_by_role(
            "button", name="取消", exact=True
        ).click()

        admin_page.goto(
            f"{server.base_url}/admin/rooms?section=open",
            wait_until="domcontentloaded",
        )
        rooms_table.get_by_role("link", name="界面开放房间", exact=True).click()
        admin_page.get_by_test_id("room-edit").click()
        expect(admin_page.get_by_test_id("room-form-starts-at")).to_be_disabled()
        expect(
            admin_page.get_by_text(
                "非草稿房间不可修改开始时间。", exact=False
            ).first
        ).to_be_visible()
        expect(admin_page.get_by_test_id("room-form-map-group")).to_be_enabled()
        expect(admin_page.get_by_test_id("room-edit-save")).to_be_enabled()
        admin_page.locator("form").get_by_role(
            "button", name="取消", exact=True
        ).click()

        wait_until(
            lambda: admin.json(
                "GET", f"/admin/api/rooms/{late_room['id']}"
            )["room"]["status"]
            != "open",
            timeout=30,
        )
        admin_page.goto(
            f"{server.base_url}/admin/rooms?section=in_progress",
            wait_until="domcontentloaded",
        )
        expect(
            rooms_table.get_by_role(
                "link", name="界面开始锁定房间", exact=True
            )
        ).to_be_visible(timeout=15000)
        rooms_table.get_by_role(
            "link", name="界面开始锁定房间", exact=True
        ).click()
        expect(admin_page.locator("h1.admin-page-title")).to_have_text("房间详情")
        expect(admin_page.get_by_test_id("room-edit")).to_have_count(0)
        expect(admin_page.get_by_test_id("room-form-starts-at")).to_have_count(0)
        expect(
            admin_page.locator('[data-testid^="room-tab-"]')
        ).to_have_text(DETAIL_TABS)

        _submit_questionnaires(server, room["id"])
        for page in (page_a, page_b):
            expect(
                page.get_by_role("heading", name="实验已完成", exact=True)
            ).to_be_visible(timeout=30000)
            expect(page.get_by_test_id("reward-info")).to_be_visible()
            expect(page.get_by_test_id("rebook")).to_have_count(0)

        _open_nav(admin_page, "nav-payments", "付款")
        expect(admin_page.get_by_test_id("payment-bulk-entry")).to_be_visible()
        expect(admin_page.get_by_test_id("payment-export-list")).to_be_visible()
        expect(
            admin_page.get_by_test_id("payment-export-reimbursement")
        ).to_be_visible()
        payments = admin.json("GET", "/admin/api/payments")["payments"]
        ours = [
            payment
            for payment in payments
            if payment["name"] in IDENTITIES
        ]
        assert len(ours) == 2
        assert all(payment["status"] == "pending" for payment in ours)

        admin_page.get_by_test_id("payment-bulk-entry").click()
        expect(admin_page.locator("h1.admin-page-title")).to_have_text("批量付款")
        expect(admin_page.get_by_test_id("bulk-summary")).to_be_visible()
        expect(admin_page.get_by_test_id("bulk-mark-paid")).to_be_enabled()
        for payment in ours:
            row = admin_page.get_by_test_id(
                f"bulk-payment-row-{payment['id']}"
            )
            checkbox = admin_page.get_by_test_id(
                f"bulk-payment-checkbox-{payment['id']}"
            )
            expect(row).to_contain_text("待支付")
            expect(checkbox).to_be_checked()
            phone = row.locator(".admin-bulk-phone")
            expect(phone).to_have_text(PHONES[payment["name"]])
            assert len(phone.inner_text()) == 11

        admin_page.get_by_test_id("bulk-invert-selection").click()
        for payment in ours:
            expect(
                admin_page.get_by_test_id(
                    f"bulk-payment-checkbox-{payment['id']}"
                )
            ).not_to_be_checked()
        admin_page.get_by_test_id("bulk-select-all-button").click()
        for payment in ours:
            expect(
                admin_page.get_by_test_id(
                    f"bulk-payment-checkbox-{payment['id']}"
                )
            ).to_be_checked()
        admin_page.get_by_test_id("bulk-mark-paid").click()
        bulk_dialog = admin_page.get_by_role("dialog", name="批量标记已支付")
        expect(bulk_dialog).to_be_visible()
        bulk_dialog.get_by_role("button", name="标记已支付", exact=True).click()
        expect(
            admin_page.get_by_text(
                re.compile(r"已标记 \d+ 笔付款为已支付，跳过 0 笔已支付记录")
            )
        ).to_be_visible(timeout=15000)
        for payment in ours:
            expect(
                admin_page.get_by_test_id(
                    f"bulk-payment-row-{payment['id']}"
                )
            ).to_contain_text("已支付")
            expect(
                admin_page.get_by_test_id(
                    f"bulk-payment-checkbox-{payment['id']}"
                )
            ).to_be_disabled()
        expect(admin_page.get_by_test_id("bulk-mark-paid")).to_be_disabled()

        context_a.close()
        context_b.close()
        admin_context.close()
        browser.close()
    admin.close()
