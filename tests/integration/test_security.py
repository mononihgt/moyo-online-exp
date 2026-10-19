import pytest

from conftest import ApiClient, create_consent, import_roster


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
