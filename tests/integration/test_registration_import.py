import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from conftest import (
    ApiClient,
    create_consent,
    create_instruction,
    create_map_group,
    create_questionnaire,
    create_room,
    create_troop_profile,
    fetch_one,
)


def _import_completed(admin: ApiClient, content: str) -> dict:
    return admin.json(
        "POST",
        "/admin/api/participants/import-completed",
        files={"file": ("completed.csv", content.encode("utf-8"), "text/csv")},
    )


def _create_room(admin: ApiClient) -> dict:
    profile = create_troop_profile(admin)
    map_group = create_map_group(admin, profile["id"])
    instruction_a = create_instruction(admin, map_group["id"], 1, "# 一", 0)
    instruction_b = create_instruction(admin, map_group["id"], 2, "# 二", 0)
    questionnaire = create_questionnaire(admin)
    return create_room(
        admin,
        map_group["id"],
        instruction_a["id"],
        instruction_b["id"],
        questionnaire["id"],
        starts_in_seconds=30,
    )


@pytest.mark.integration
def test_admin_can_change_participant_phone(server):
    admin = ApiClient(server.base_url).login_admin()
    create_consent(admin)
    participant = ApiClient(server.base_url).login_participant(
        "手机更正", "13800001010"
    )
    participant.consent()
    participant_id = participant.json("GET", "/api/me")["me"]["id"]
    admin.json(
        "PATCH",
        f"/admin/api/participants/{participant_id}",
        json={"phone": "13800001011"},
    )
    search = admin.json(
        "GET", "/admin/api/participants?query=13800001011&limit=20"
    )
    assert search["total"] == 1
    assert search["participants"][0]["id"] == participant_id
    relogged = ApiClient(server.base_url).login_participant(
        "手机更正", "13800001011"
    )
    assert relogged.json("GET", "/api/me")["me"]["id"] == participant_id
    old_phone_account = ApiClient(server.base_url).login_participant(
        "手机更正", "13800001010"
    )
    assert old_phone_account.json("GET", "/api/me")["me"]["id"] != participant_id
    other = ApiClient(server.base_url).login_participant(
        "手机冲突", "13800001012"
    )
    other.consent()
    other_id = other.json("GET", "/api/me")["me"]["id"]
    conflict = admin.request(
        "PATCH",
        f"/admin/api/participants/{other_id}",
        json={"phone": "13800001011"},
    )
    assert conflict.status_code == 409
    audit_entries = admin.json("GET", "/admin/api/audit?limit=50")["entries"]
    phone_audit = next(
        entry
        for entry in audit_entries
        if entry["action"] == "participant_phone_updated"
    )
    audit_text = json.dumps(phone_audit["payload"], ensure_ascii=False)
    assert "13800001011" not in audit_text
    assert "13800001010" not in audit_text
    assert "138****1011" in audit_text
    participant.close()
    relogged.close()
    old_phone_account.close()
    other.close()
    admin.close()


@pytest.mark.integration
def test_login_registers_new_participant(server):
    admin = ApiClient(server.base_url).login_admin()
    create_consent(admin)
    client = ApiClient(server.base_url)
    first = client.request(
        "POST", "/api/login", json={"name": "新被试", "phone": "13800001001"}
    )
    assert first.status_code == 200
    me = first.json()["me"]
    assert me["name"] == "新被试"
    assert me["status"] == "eligible"
    assert me["consentRequired"] is True
    assert me["hasPayment"] is False
    assert me["canBook"] is False

    client.consent()
    after_consent = client.json("GET", "/api/me")["me"]
    assert after_consent["canBook"] is True

    second = client.request(
        "POST", "/api/login", json={"name": "新被试", "phone": "13800001001"}
    )
    assert second.status_code == 200
    assert second.json()["me"]["id"] == me["id"]
    count = fetch_one("SELECT COUNT(*) AS count FROM participants")["count"]
    assert count == 1
    admin.close()
    client.close()


@pytest.mark.integration
def test_phone_normalization_resolves_same_participant(server):
    client = ApiClient(server.base_url)
    first = client.request(
        "POST", "/api/login", json={"name": "号码甲", "phone": "13800001002"}
    )
    assert first.status_code == 200
    participant_id = first.json()["me"]["id"]
    for raw_phone in ("+86 138-0000-1002", "008613800001002", "8613800001002"):
        response = client.request(
            "POST", "/api/login", json={"name": "号码甲", "phone": raw_phone}
        )
        assert response.status_code == 200
        assert response.json()["me"]["id"] == participant_id
    count = fetch_one("SELECT COUNT(*) AS count FROM participants")["count"]
    assert count == 1
    client.close()


@pytest.mark.integration
def test_login_requires_matching_name_and_valid_phone(server):
    client = ApiClient(server.base_url)
    created = client.request(
        "POST", "/api/login", json={"name": "姓名甲", "phone": "13800001003"}
    )
    assert created.status_code == 200

    wrong_name = client.request(
        "POST", "/api/login", json={"name": "姓名乙", "phone": "13800001003"}
    )
    assert wrong_name.status_code == 401
    assert wrong_name.json()["detail"] == "姓名或手机号不正确"

    invalid_phone = client.request(
        "POST", "/api/login", json={"name": "姓名甲", "phone": "12345"}
    )
    assert invalid_phone.status_code == 401
    assert invalid_phone.json()["detail"] == "姓名或手机号不正确"

    blank_name = client.request(
        "POST", "/api/login", json={"name": "   ", "phone": "13800001004"}
    )
    assert blank_name.status_code == 401
    assert blank_name.json()["detail"] == "姓名或手机号不正确"

    count = fetch_one("SELECT COUNT(*) AS count FROM participants")["count"]
    assert count == 1
    client.close()


@pytest.mark.integration
def test_completed_and_disabled_participants_can_login(server):
    admin = ApiClient(server.base_url).login_admin()
    client = ApiClient(server.base_url)
    created = client.json(
        "POST", "/api/login", json={"name": "状态甲", "phone": "13800001005"}
    )
    participant_id = created["me"]["id"]
    admin.json("PATCH", f"/admin/api/participants/{participant_id}", json={"status": "completed"})
    completed = client.json(
        "POST", "/api/login", json={"name": "状态甲", "phone": "13800001005"}
    )
    assert completed["me"]["isCompleted"] is True
    assert completed["me"]["canBook"] is False

    admin.json("PATCH", f"/admin/api/participants/{participant_id}", json={"status": "disabled"})
    disabled = client.json(
        "POST", "/api/login", json={"name": "状态甲", "phone": "13800001005"}
    )
    assert disabled["me"]["isDisabled"] is True
    assert disabled["me"]["canBook"] is False
    admin.close()
    client.close()


@pytest.mark.integration
def test_concurrent_first_login_creates_one_participant(server):
    def login():
        with httpx.Client(base_url=server.base_url, timeout=30) as client:
            return client.post(
                "/api/login", json={"name": "并发甲", "phone": "13800001006"}
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: login(), range(2)))
    assert all(response.status_code == 200 for response in responses)
    ids = {response.json()["me"]["id"] for response in responses}
    assert len(ids) == 1
    count = fetch_one("SELECT COUNT(*) AS count FROM participants")["count"]
    assert count == 1


@pytest.mark.integration
def test_completed_import_creates_matches_and_reports(server):
    admin = ApiClient(server.base_url).login_admin()
    existing_client = ApiClient(server.base_url).login_participant("已注册", "13800002002")
    existing = existing_client.json("GET", "/api/me")["me"]
    admin.json(
        "PATCH",
        f"/admin/api/participants/{existing['id']}",
        json={"notes": "原备注"},
    )
    other_client = ApiClient(server.base_url).login_participant("已注册乙", "13800002005")
    long_name = "长" * 121
    content = (
        "姓名,手机号,备注\n"
        "历史新建,13800002001,历史备注\n"
        "已注册,13800002002,新备注\n"
        "历史新建,13800002001,重复行\n"
        "错名,13800002005,名称不一致\n"
        ",13800002004,空姓名\n"
        "坏手机,12345,无效手机号\n"
        f"{long_name},13800002003,姓名过长\n"
    )
    report = _import_completed(admin, content)
    assert report["total"] == 7
    assert report["created"] == 1
    assert report["matched"] == 1
    assert report["unmatched"] == 5
    assert report["created"] + report["matched"] + report["unmatched"] == report["total"]
    statuses = [row["status"] for row in report["rows"]]
    assert statuses == [
        "created",
        "matched",
        "unmatched",
        "unmatched",
        "unmatched",
        "unmatched",
        "unmatched",
    ]
    assert report["rows"][2]["error"] == "名单内手机号重复"
    assert report["rows"][3]["error"] == "姓名与已有记录不一致"
    assert report["rows"][4]["error"] == "姓名为空"
    assert report["rows"][5]["error"] == "手机号格式不正确"
    assert report["rows"][6]["error"] == "姓名过长"

    created = fetch_one(
        "SELECT name, status, notes FROM participants WHERE name = %s", ("历史新建",)
    )
    assert created == {"name": "历史新建", "status": "completed", "notes": "历史备注"}
    matched = fetch_one(
        "SELECT status, notes FROM participants WHERE id = %s", (existing["id"],)
    )
    assert matched == {"status": "completed", "notes": "原备注"}
    invalid = fetch_one(
        "SELECT COUNT(*) AS count FROM participants WHERE name IN (%s, %s)",
        ("坏手机", long_name),
    )
    assert invalid["count"] == 0

    second = _import_completed(admin, content)
    assert second["created"] == 0
    assert second["matched"] == 2
    assert second["unmatched"] == 5

    amount = fetch_one("SELECT COUNT(*) AS count FROM payments")
    assert amount["count"] == 0
    rooms = fetch_one("SELECT COUNT(*) AS count FROM rooms")
    assert rooms["count"] == 0
    identities = fetch_one("SELECT COUNT(*) AS count FROM participant_identities")
    assert identities["count"] == 0

    audit = admin.json("GET", "/admin/api/audit?limit=500")
    assert any(
        entry["action"] == "participants_import_completed" for entry in audit["entries"]
    )
    audit_text = json.dumps(audit["entries"], ensure_ascii=False)
    for value in (
        "历史新建",
        "13800002001",
        "历史备注",
        "已注册",
        "13800002002",
        "13800002005",
    ):
        assert value not in audit_text

    admin.close()
    existing_client.close()
    other_client.close()


@pytest.mark.integration
def test_completed_import_participant_cannot_book(server):
    admin = ApiClient(server.base_url).login_admin()
    create_consent(admin)
    content = "姓名,手机号\n历史锁定,13800002003\n"
    report = _import_completed(admin, content)
    assert report["created"] == 1
    client = ApiClient(server.base_url)
    logged_in = client.json(
        "POST", "/api/login", json={"name": "历史锁定", "phone": "13800002003"}
    )
    assert logged_in["me"]["isCompleted"] is True
    assert logged_in["me"]["canBook"] is False
    assert logged_in["me"]["hasPayment"] is False
    room = _create_room(admin)
    blocked = client.request("POST", f"/api/rooms/{room['id']}/book")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "你已完成全部实验，无法再预约新的场次。"
    admin.close()
    client.close()
