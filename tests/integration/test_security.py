import pytest

from conftest import (
    ApiClient,
    ServerHandle,
    create_consent,
    import_roster,
    reset_database,
)


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
    import_roster(admin, [("安全甲", "13200000001")])
    create_consent(admin)
    client = ApiClient(server.base_url)
    wrong = client.request("POST", "/api/login", json={"name": "安全甲", "phone": "13200000009"})
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "姓名或手机号不正确"
    client.login_participant("安全甲", "13200000001")
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
    admin = None
    participant_a = None
    participant_b = None
    try:
        admin = ApiClient(server.base_url).login_admin()
        import_roster(
            admin,
            [("限制甲", "13800000001"), ("限制乙", "13800000002")],
        )
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
        for client in (participant_a, participant_b, admin):
            if client is not None:
                client.close()
        server.stop()
