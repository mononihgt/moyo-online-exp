import io
import json
import zipfile

import pytest
from openpyxl import Workbook
from PIL import Image

from conftest import (
    ApiClient,
    create_condition,
    create_consent,
    create_instruction,
    create_questionnaire,
    create_room,
    import_roster,
)


def _jpeg_with_exif() -> bytes:
    image = Image.new("RGB", (64, 48), (20, 40, 60))
    exif = Image.Exif()
    exif[0x010F] = "TestCamera"
    exif[0x0110] = "TestModel"
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


@pytest.mark.integration
def test_media_upload_requires_auth_strips_exif_and_exports_snapshot(server):
    admin = ApiClient(server.base_url).login_admin()
    original = _jpeg_with_exif()
    upload = admin.request(
        "POST",
        "/admin/api/media",
        files={"file": ("background.jpg", original, "image/jpeg")},
        data={"kind": "condition_background"},
    )
    assert upload.status_code == 200, upload.text
    asset = upload.json()["asset"]
    assert asset["contentType"] == "image/jpeg"
    assert asset["width"] == 64 and asset["height"] == 48
    assert asset["sha256"].startswith("sha256:")

    anonymous = ApiClient(server.base_url)
    assert anonymous.request("GET", f"/media/{asset['assetId']}").status_code == 401
    downloaded = admin.request("GET", f"/media/{asset['assetId']}")
    assert downloaded.status_code == 200
    clean = Image.open(io.BytesIO(downloaded.content))
    assert len(clean.getexif()) == 0
    assert clean.size == (64, 48)

    svg_upload = admin.request(
        "POST",
        "/admin/api/media",
        files={"file": ("evil.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml")},
        data={"kind": "instruction_image"},
    )
    assert svg_upload.status_code == 400

    import_roster(admin, [("媒体被试", "13600000001")])
    create_consent(admin)
    instruction_1 = create_instruction(
        admin, 1, f"# 玩家1\n\n![示意图](asset://{asset['assetId']})", 0
    )
    instruction_2 = create_instruction(admin, 2, "# 玩家2", 0)
    questionnaire = create_questionnaire(admin)
    condition = create_condition(admin)
    detail = admin.json("GET", f"/admin/api/conditions/{condition['id']}")["condition"]
    payload = {
        key: detail[key]
        for key in (
            "name",
            "description",
            "rows",
            "cols",
            "cells",
            "visuals",
            "baseAIndex",
            "baseBIndex",
            "trialParams",
            "practiceTrials",
            "formalTrials",
            "turnCount",
            "turnSeconds",
            "restSeconds",
            "randomizeFormal",
            "metadata",
        )
    }
    payload["visuals"]["player1"][1]["backgroundAssetId"] = asset["assetId"]
    payload["visuals"]["player2"][1]["backgroundAssetId"] = asset["assetId"]
    conditional = admin.json("POST", "/admin/api/conditions", json=payload)["condition"]
    admin.json("POST", f"/admin/api/conditions/{conditional['id']}/publish")

    invalid_payload = json.loads(json.dumps(payload))
    invalid_payload["name"] = "missing-asset"
    invalid_payload["visuals"]["player1"][2]["backgroundAssetId"] = "00000000-0000-0000-0000-000000000000"
    invalid = admin.request("POST", "/admin/api/conditions", json=invalid_payload)
    assert invalid.status_code == 400

    room = create_room(
        admin,
        condition_id=conditional["id"],
        instruction_p1=instruction_1["id"],
        instruction_p2=instruction_2["id"],
        questionnaire_id=questionnaire["id"],
        starts_in_seconds=300,
    )
    exported = admin.json("GET", f"/admin/api/rooms/{room['id']}/export.json")
    assert exported["schemaVersion"] == 4
    assert len(exported["media"]) == 1
    media_entry = exported["media"][0]
    assert media_entry["assetId"] == asset["assetId"]
    assert media_entry["sha256"] == asset["sha256"]
    assert exported["instructions"]["player1"]["contentMarkdown"].find(f"asset://{asset['assetId']}") >= 0

    zip_response = admin.request("GET", f"/admin/api/rooms/{room['id']}/analysis.zip")
    assert zip_response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(zip_response.content))
    assert media_entry["path"] in archive.namelist()
    assert archive.read(media_entry["path"]) == downloaded.content
    media_manifest = json.loads(archive.read("media/manifest.json"))
    assert media_manifest["assets"][0]["assetId"] == asset["assetId"]
    room_json = json.loads(archive.read("room.json"))
    assert room_json["condition"]["visuals"]["player1"][1]["backgroundAssetId"] == asset["assetId"]

    participant = ApiClient(server.base_url).login_participant("媒体被试", "13600000001")
    participant.consent()
    assert participant.request("GET", f"/media/{asset['assetId']}").status_code == 200
    admin.close()
    participant.close()


@pytest.mark.integration
def test_import_completed_and_participant_status_changes(server):
    admin = ApiClient(server.base_url).login_admin()
    import_roster(admin, [("历史甲", "13600000011"), ("历史乙", "13600000012")])
    completed_csv = "姓名,手机号\n历史甲,13600000011\n不存在丙,13600000013\n"
    report = admin.json(
        "POST",
        "/admin/api/participants/import-completed",
        files={"file": ("completed.csv", completed_csv.encode("utf-8"), "text/csv")},
    )
    assert report["matched"] == 1
    assert report["unmatched"] == 1
    participant = ApiClient(server.base_url).login_participant("历史甲", "13600000011")
    me = participant.json("GET", "/api/me")["me"]
    assert me["isCompleted"] is True
    assert me["canBook"] is False
    participants = admin.json("GET", "/admin/api/participants")["participants"]
    record = next(item for item in participants if item["name"] == "历史甲")
    admin.json("PATCH", f"/admin/api/participants/{record['id']}", json={"status": "disabled", "notes": "测试停用"})
    me = participant.json("GET", "/api/me")["me"]
    assert me["isDisabled"] is True
    assert me["status"] == "disabled"
    admin.json("PATCH", f"/admin/api/participants/{record['id']}", json={"status": "eligible"})
    me = participant.json("GET", "/api/me")["me"]
    assert me["status"] == "eligible"
    audit = admin.json("GET", "/admin/api/audit")["entries"]
    actions = {entry["action"] for entry in audit}
    assert "participants_import_completed" in actions
    assert "participant_updated" in actions
    admin.close()
    participant.close()


@pytest.mark.integration
def test_xlsx_roster_import_with_numeric_phone(server):
    admin = ApiClient(server.base_url).login_admin()
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["姓名", "手机号", "备注"])
    sheet.append(["表格甲", 13600000021, "XLSX 导入"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    report = admin.json(
        "POST",
        "/admin/api/participants/import",
        files={
            "file": (
                "roster.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert report["imported"] == 1
    participant = ApiClient(server.base_url).login_participant("表格甲", "13600000021")
    assert participant.json("GET", "/api/me")["me"]["name"] == "表格甲"
    admin.close()
    participant.close()
