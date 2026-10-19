from datetime import datetime, timedelta, timezone

import pytest

from conftest import (
    ApiClient,
    create_instruction,
    create_map_group,
    create_questionnaire,
    create_troop_profile,
)


def _setup_materials(admin: ApiClient) -> dict:
    profile = create_troop_profile(admin)
    map_group = create_map_group(admin, profile["id"])
    instruction_p1 = create_instruction(admin, map_group["id"], 1, "# 玩家 A\n\n测试指导语。")
    instruction_p2 = create_instruction(admin, map_group["id"], 2, "# 玩家 B\n\n测试指导语。")
    questionnaire = create_questionnaire(admin)
    return {
        "mapGroupVersionId": map_group["id"],
        "instructionVersionP1Id": instruction_p1["id"],
        "instructionVersionP2Id": instruction_p2["id"],
        "questionnaireVersionId": questionnaire["id"],
    }


def _create_draft_room(
    admin: ApiClient, materials: dict, label: str, starts_at: str
) -> dict:
    return admin.json(
        "POST",
        "/admin/api/rooms",
        json={
            "internalLabel": label,
            "startsAt": starts_at,
            **materials,
            "waitWindowSeconds": 60,
            "reconnectWindowSeconds": 30,
        },
    )["room"]


@pytest.mark.integration
def test_room_list_pagination(server):
    admin = ApiClient(server.base_url).login_admin()
    materials = _setup_materials(admin)
    starts_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace(
        "+00:00", "Z"
    )
    room_ids = [
        _create_draft_room(admin, materials, f"分页草稿 {index}", starts_at)["id"]
        for index in range(3)
    ]

    first = admin.json("GET", "/admin/api/rooms?section=draft&limit=2&offset=0")
    first_ids = [room["id"] for room in first["rooms"]]
    assert len(first_ids) == 2
    assert first["counts"]["draft"] == 3

    second = admin.json("GET", "/admin/api/rooms?section=draft&limit=2&offset=2")
    second_ids = [room["id"] for room in second["rooms"]]
    assert len(second_ids) == 1
    assert second["counts"]["draft"] == 3

    assert set(first_ids).isdisjoint(second_ids)
    assert set(first_ids) | set(second_ids) == set(room_ids)

    repeated_first = admin.json("GET", "/admin/api/rooms?section=draft&limit=2&offset=0")
    assert [room["id"] for room in repeated_first["rooms"]] == first_ids
    repeated_second = admin.json("GET", "/admin/api/rooms?section=draft&limit=2&offset=2")
    assert [room["id"] for room in repeated_second["rooms"]] == second_ids

    empty = admin.json("GET", "/admin/api/rooms?section=draft&limit=2&offset=3")
    assert empty["rooms"] == []
    assert empty["counts"]["draft"] == 3

    invalid = admin.request("GET", "/admin/api/rooms?section=draft&offset=-1")
    assert invalid.status_code == 422

    admin.close()
