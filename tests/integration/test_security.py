import pytest

from conftest import ApiClient, ServerHandle, create_consent, reset_database


@pytest.mark.integration
def test_admin_auth_csrf_and_openapi_disabled(server):
    anonymous = ApiClient(server.base_url)
    assert anonymous.request("GET", "/admin/api/rooms").status_code == 401
    assert anonymous.request("GET", "/openapi.json").status_code == 404
    assert anonymous.request("GET", "/docs").status_code == 404

    admin = ApiClient(server.base_url).login_admin()
    without_csrf = admin.client.request(
        "POST",
        "/admin/api/troop-profiles",
        json={
            "name": "csrf-test",
            "rows": [{"soldiersA": 5, "soldiersB": 5}, {"soldiersA": 6, "soldiersB": 6}],
        },
    )
    assert without_csrf.status_code == 403
    assert without_csrf.json()["detail"] == "CSRF 校验失败"
    admin.close()
    anonymous.close()


@pytest.mark.integration
def test_participant_csrf_and_login_errors(server):
    admin = ApiClient(server.base_url).login_admin()
    create_consent(admin)
    client = ApiClient(server.base_url)
    created = client.request(
        "POST", "/api/login", json={"name": "安全甲", "phone": "13200000001"}
    )
    assert created.status_code == 200
    wrong_name = client.request(
        "POST", "/api/login", json={"name": "安全乙", "phone": "13200000001"}
    )
    assert wrong_name.status_code == 401
    assert wrong_name.json()["detail"] == "姓名或手机号不正确"
    invalid_phone = client.request(
        "POST", "/api/login", json={"name": "安全甲", "phone": "12345"}
    )
    assert invalid_phone.status_code == 401
    assert invalid_phone.json()["detail"] == "姓名或手机号不正确"
    client.consent()
    login_response = client.request(
        "POST", "/api/login", json={"name": "安全甲", "phone": "13200000001"}
    )
    assert login_response.status_code == 200
    set_cookie = login_response.headers.get_list("set-cookie")
    participant_cookie = next(item for item in set_cookie if item.startswith("moyo_participant="))
    assert "HttpOnly" in participant_cookie
    assert "SameSite=lax" in participant_cookie

    csrf_response = client.client.request(
        "POST",
        "/api/consent",
        json={"versionId": "00000000-0000-0000-0000-000000000000", "agree": True},
    )
    assert csrf_response.status_code == 403
    admin.close()
    client.close()


@pytest.mark.integration
def test_participant_login_limit_is_per_account():
    reset_database()
    server = ServerHandle(env_overrides={"LOGIN_RATE_LIMIT_ATTEMPTS": "2"})
    server.start()
    participant_a = None
    participant_b = None
    try:
        participant_a = ApiClient(server.base_url)
        for _ in range(2):
            allowed = participant_a.request(
                "POST",
                "/api/login",
                json={"name": "限制甲", "phone": "13800000001"},
            )
            assert allowed.status_code == 200
        blocked = participant_a.request(
            "POST",
            "/api/login",
            json={"name": "限制甲", "phone": "13800000001"},
        )
        assert blocked.status_code == 429

        participant_b = ApiClient(server.base_url)
        other_account = participant_b.request(
            "POST",
            "/api/login",
            json={"name": "限制乙", "phone": "13800000002"},
        )
        assert other_account.status_code == 200
    finally:
        for client in (participant_a, participant_b):
            if client is not None:
                client.close()
        server.stop()
