import hashlib
import io
import json
import uuid
import zipfile

import httpx
import pytest
from PIL import Image

from conftest import (
    ApiClient,
    create_instruction,
    create_map_group,
    create_questionnaire,
    create_room,
    create_troop_profile,
)

OVERSIZED_BYTES = 10 * 1024 * 1024 + 1


def _image_bytes(fmt, *, size, color=(31, 119, 180), exif_orientation=None):
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    if fmt == "JPEG" and exif_orientation is not None:
        exif = Image.Exif()
        exif[274] = exif_orientation
        image.save(buffer, format=fmt, quality=90, exif=exif)
    else:
        image.save(buffer, format=fmt)
    return buffer.getvalue()


def _animated_gif_bytes(*, size=(8, 8), durations=(40, 80, 120)):
    frames = [
        Image.new("RGB", size, (index * 60, 10, 10))
        for index in range(len(durations))
    ]
    buffer = io.BytesIO()
    frames[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=list(durations),
        loop=0,
    )
    return buffer.getvalue()


def _upload(admin, data, *, filename, content_type="image/png", kind="map"):
    return admin.request(
        "POST",
        "/admin/api/media",
        files={"file": (filename, data, content_type)},
        data={"kind": kind},
    )


def _asset(admin, data, *, filename, content_type="image/png", kind="map"):
    response = _upload(admin, data, filename=filename, content_type=content_type, kind=kind)
    assert response.status_code == 200, response.text
    return response.json()["asset"]


def _map_maps(version, cells_by_slot):
    return [
        {
            "slot": item["slot"],
            "description": item["description"],
            "factorLevel": item["factorLevel"],
            "cells": cells_by_slot.get(item["slot"], item["cells"]),
        }
        for item in version["maps"]
    ]


def _create_payload(version, cells_by_slot):
    return {
        "mode": version["mode"],
        "rows": version["rows"],
        "cols": version["cols"],
        "spawns": version["spawns"],
        "troopProfileVersionId": version["profile"]["versionId"],
        "practiceTrials": version["practiceTrials"],
        "formalTrials": version["formalTrials"],
        "practiceTurnCap": version["practiceTurnCap"],
        "practiceTurnSeconds": version["practiceTurnSeconds"],
        "formalTurnCap": version["formalTurnCap"],
        "formalTurnSeconds": version["formalTurnSeconds"],
        "restSeconds": version["restSeconds"],
        "randomizeFormal": version["randomizeFormal"],
        "payment": version["payment"],
        "maps": _map_maps(version, cells_by_slot),
    }


def _entry_by_id(export):
    return {entry["assetId"]: entry for entry in export["media"]}


def _zip_entries(response):
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    media_manifest = json.loads(archive.read("media/manifest.json"))
    manifest = json.loads(archive.read("manifest.json"))
    for entry in media_manifest["assets"]:
        assert entry["path"] in names
        digest = hashlib.sha256(archive.read(entry["path"])).hexdigest()
        assert entry["sha256"] == "sha256:" + digest
    manifest_files = {item["path"]: item for item in manifest["files"]}
    for entry in media_manifest["assets"]:
        assert manifest_files[entry["path"]]["sha256"] == entry["sha256"]
    archive.close()
    return media_manifest


@pytest.mark.integration
def test_media_upload_formats_exif_and_limits(server):
    admin = ApiClient(server.base_url).login_admin()
    png_data = _image_bytes("PNG", size=(37, 19))
    png = _asset(admin, png_data, filename="narrow.png")
    assert png["contentType"] == "image/png"
    assert (png["width"], png["height"]) == (37, 19)
    assert png["sha256"].startswith("sha256:")
    assert png["url"] == f"/media/{png['id']}"

    download = admin.request("GET", f"/media/{png['id']}")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("image/png")
    assert png["sizeBytes"] == len(download.content)
    assert (
        "sha256:" + hashlib.sha256(download.content).hexdigest() == png["sha256"]
    )
    with Image.open(io.BytesIO(download.content)) as stored:
        assert stored.size == (37, 19)

    jpeg = _asset(
        admin,
        _image_bytes("JPEG", size=(60, 30), exif_orientation=6),
        filename="turned.jpg",
        content_type="image/jpeg",
    )
    assert jpeg["contentType"] == "image/jpeg"
    assert (jpeg["width"], jpeg["height"]) == (30, 60)
    jpeg_download = admin.request("GET", f"/media/{jpeg['id']}")
    assert jpeg_download.status_code == 200
    with Image.open(io.BytesIO(jpeg_download.content)) as stored:
        assert stored.size == (30, 60)
        assert len(stored.getexif()) == 0

    webp = _asset(
        admin,
        _image_bytes("WEBP", size=(41, 23)),
        filename="wide.webp",
        content_type="image/webp",
    )
    assert webp["contentType"] == "image/webp"
    assert (webp["width"], webp["height"]) == (41, 23)

    duplicate = _asset(admin, png_data, filename="copy.png")
    assert duplicate["id"] == png["id"]

    anonymous = httpx.get(f"{server.base_url}/media/{png['id']}", timeout=30)
    assert anonymous.status_code == 401
    missing = admin.request("GET", f"/media/{uuid.uuid4()}")
    assert missing.status_code == 404

    participant = ApiClient(server.base_url).login_participant("媒体参与者", "13700002001")
    permitted = participant.request("GET", f"/media/{png['id']}")
    assert permitted.status_code == 200

    invalid = _upload(admin, b"definitely-not-an-image", filename="broken.png")
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "文件不是有效图片"
    empty = _upload(admin, b"", filename="empty.png")
    assert empty.status_code == 400
    assert empty.json()["detail"] == "上传文件为空"
    gif_data = _animated_gif_bytes()
    gif = _asset(
        admin,
        gif_data,
        filename="anim.gif",
        content_type="image/gif",
        kind="instruction-image",
    )
    assert gif["contentType"] == "image/gif"
    assert (gif["width"], gif["height"]) == (8, 8)
    assert gif["sizeBytes"] == len(gif_data)
    gif_download = admin.request("GET", f"/media/{gif['id']}")
    assert gif_download.status_code == 200
    assert gif_download.headers["content-type"].startswith("image/gif")
    assert gif_download.content == gif_data
    with Image.open(io.BytesIO(gif_download.content)) as stored:
        assert stored.n_frames == 3
        assert stored.info.get("loop") == 0
        frame_durations = []
        for index in range(stored.n_frames):
            stored.seek(index)
            frame_durations.append(stored.info.get("duration"))
        assert frame_durations == [40, 80, 120]
    gif_duplicate = _asset(
        admin,
        gif_data,
        filename="copy.gif",
        content_type="image/gif",
        kind="instruction-image",
    )
    assert gif_duplicate["id"] == gif["id"]
    oversized = _upload(
        admin, b"0" * OVERSIZED_BYTES, filename="huge.png", content_type="image/png"
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"] == "图片超过大小限制"

    participant.close()
    admin.close()


@pytest.mark.integration
def test_instruction_accepts_gif_and_renders_media_source(server):
    admin = ApiClient(server.base_url).login_admin()
    gif = _asset(
        admin,
        _animated_gif_bytes(),
        filename="guide.gif",
        content_type="image/gif",
        kind="instruction-image",
    )
    profile = create_troop_profile(admin)
    group = create_map_group(admin, profile["id"])
    instruction = create_instruction(
        admin,
        group["id"],
        1,
        f"# 玩家一\n\n![演示动图](asset://{gif['id']})\n",
        0,
    )
    rendered = admin.json("GET", f"/admin/api/instructions/{instruction['id']}")[
        "instruction"
    ]
    assert f'src="/media/{gif["id"]}"' in rendered["contentHtml"]
    assert "asset://" not in rendered["contentHtml"]
    assert f"asset://{gif['id']}" in rendered["contentMarkdown"]
    admin.close()


@pytest.mark.integration
def test_map_group_rejects_webp_and_missing_assets(server):
    admin = ApiClient(server.base_url).login_admin()
    profile = create_troop_profile(admin)
    draft = create_map_group(admin, profile["id"], rows=2, cols=2, publish=False)
    total = draft["rows"] * draft["cols"]

    webp = _asset(
        admin,
        _image_bytes("WEBP", size=(41, 23)),
        filename="cell.webp",
        content_type="image/webp",
    )
    webp_cells = [webp["id"]] + [None] * (total - 1)
    create_response = admin.request(
        "POST", "/admin/api/map-groups", json=_create_payload(draft, {"Both": webp_cells})
    )
    assert create_response.status_code == 400
    assert create_response.json()["detail"] == "地图单元格仅支持 PNG/JPG 图片"
    patch_response = admin.request(
        "PATCH",
        f"/admin/api/map-groups/{draft['id']}",
        json={"maps": _map_maps(draft, {"Both": webp_cells})},
    )
    assert patch_response.status_code == 400
    assert patch_response.json()["detail"] == "地图单元格仅支持 PNG/JPG 图片"

    missing_id = str(uuid.uuid4())
    missing_cells = [missing_id] + [None] * (total - 1)
    missing_create = admin.request(
        "POST", "/admin/api/map-groups", json=_create_payload(draft, {"Both": missing_cells})
    )
    assert missing_create.status_code == 400
    assert missing_create.json()["detail"] == "地图单元格引用的图片资源不存在"
    missing_patch = admin.request(
        "PATCH",
        f"/admin/api/map-groups/{draft['id']}",
        json={"maps": _map_maps(draft, {"Both": missing_cells})},
    )
    assert missing_patch.status_code == 400
    assert missing_patch.json()["detail"] == "地图单元格引用的图片资源不存在"

    unchanged = admin.json("GET", f"/admin/api/map-groups/{draft['id']}")["mapGroup"]
    assert unchanged["maps"][0]["cells"] == [None] * total
    assert unchanged["contentHash"] == draft["contentHash"]

    admin.close()


@pytest.mark.integration
def test_map_group_colors_round_trip_and_validation(server):
    admin = ApiClient(server.base_url).login_admin()
    profile = create_troop_profile(admin)
    draft = create_map_group(
        admin,
        profile["id"],
        rows=2,
        cols=2,
        colors=["#aabbcc", None, None, None],
        publish=False,
    )
    assert draft["maps"][0]["colors"] == ["#AABBCC", None, None, None]

    base_maps = [
        {
            "slot": item["slot"],
            "description": item["description"],
            "factorLevel": item["factorLevel"],
            "cells": item["cells"],
            "colors": item["colors"],
        }
        for item in draft["maps"]
    ]
    too_short = [dict(item) for item in base_maps]
    too_short[0]["colors"] = ["#AABBCC", None, None]
    response = admin.request(
        "PATCH", f"/admin/api/map-groups/{draft['id']}", json={"maps": too_short}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "地图单元格颜色数量必须为 4"

    invalid = [dict(item) for item in base_maps]
    invalid[0]["colors"] = ["red", None, None, None]
    response = admin.request(
        "PATCH", f"/admin/api/map-groups/{draft['id']}", json={"maps": invalid}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "地图单元格背景颜色必须为 #RRGGBB"

    updated_maps = [dict(item) for item in base_maps]
    updated_maps[0]["colors"] = ["#112233", None, None, None]
    response = admin.request(
        "PATCH",
        f"/admin/api/map-groups/{draft['id']}",
        json={"maps": updated_maps},
    )
    assert response.status_code == 200, response.text
    updated = response.json()["mapGroup"]
    assert updated["maps"][0]["colors"] == ["#112233", None, None, None]
    assert updated["contentHash"] != draft["contentHash"]

    admin.close()


@pytest.mark.integration
def test_room_media_export_and_instruction_asset_rendering(server):
    admin = ApiClient(server.base_url).login_admin()
    profile = create_troop_profile(admin)
    questionnaire = create_questionnaire(admin)

    both_image = _asset(
        admin, _image_bytes("PNG", size=(37, 19)), filename="both-cell.png"
    )
    instruction_image = _asset(
        admin,
        _image_bytes("PNG", size=(33, 17), color=(20, 90, 44)),
        filename="instruction.png",
        kind="instruction_image",
    )
    both_group = create_map_group(
        admin,
        profile["id"],
        rows=2,
        cols=2,
        description="合成地图",
        assets=[both_image["id"], None, None, None],
    )
    instruction_markdown = (
        f"# 玩家一\n\n请阅读示意图：\n\n![示意图](asset://{instruction_image['id']})\n"
    )
    both_instruction_a = create_instruction(
        admin, both_group["id"], 1, instruction_markdown, 0
    )
    both_instruction_b = create_instruction(admin, both_group["id"], 2, "# 玩家二", 0)
    both_room = create_room(
        admin,
        both_group["id"],
        both_instruction_a["id"],
        both_instruction_b["id"],
        questionnaire["id"],
        starts_in_seconds=600,
        label="媒体导出房间",
    )

    rendered = admin.json(
        "GET", f"/admin/api/instructions/{both_instruction_a['id']}"
    )["instruction"]
    assert f'src="/media/{instruction_image["id"]}"' in rendered["contentHtml"]
    assert "asset://" not in rendered["contentHtml"]
    assert f"asset://{instruction_image['id']}" in rendered["contentMarkdown"]

    missing_instruction = admin.request(
        "POST",
        "/admin/api/instructions",
        json={
            "mapGroupVersionId": both_group["id"],
            "role": 1,
            "markdown": f"![缺失](asset://{uuid.uuid4()})",
            "minReadingSeconds": 0,
        },
    )
    assert missing_instruction.status_code == 400
    assert "指导语引用了不存在的图片资产" in missing_instruction.json()["detail"]

    export = admin.json("GET", f"/admin/api/rooms/{both_room['id']}/export.json")
    assert export["schemaVersion"] == 6
    both_entries = _entry_by_id(export)
    assert set(both_entries) == {both_image["id"], instruction_image["id"]}
    both_entry = both_entries[both_image["id"]]
    assert (both_entry["width"], both_entry["height"]) == (37, 19)
    assert both_entry["contentType"] == "image/png"
    assert both_entry["sha256"] == both_image["sha256"]
    assert both_entry["path"] == f"media/{both_image['id']}.png"
    assert export["mapGroup"]["maps"][0]["cells"][0] == both_image["id"]
    assert (
        f"asset://{instruction_image['id']}"
        in export["instructions"]["player1"]["contentMarkdown"]
    )
    zip_response = admin.request("GET", f"/admin/api/rooms/{both_room['id']}/analysis.zip")
    assert zip_response.status_code == 200
    both_manifest = _zip_entries(zip_response)
    assert {entry["assetId"] for entry in both_manifest["assets"]} == set(both_entries)

    a_image = _asset(
        admin, _image_bytes("PNG", size=(48, 16), color=(200, 80, 10)), filename="a.png"
    )
    b_image = _asset(
        admin,
        _image_bytes("JPEG", size=(24, 32), color=(10, 60, 200)),
        filename="b.jpg",
        content_type="image/jpeg",
    )
    ab_group = create_map_group(
        admin,
        profile["id"],
        mode="ab",
        rows=2,
        cols=2,
        description="对照地图",
        assets={
            "A": [a_image["id"], None, None, None],
            "B": [b_image["id"], None, None, None],
        },
    )
    ab_instruction_a = create_instruction(
        admin,
        ab_group["id"],
        1,
        f"![示意](asset://{instruction_image['id']})",
        0,
    )
    ab_instruction_b = create_instruction(admin, ab_group["id"], 2, "## 玩家二", 0)
    ab_room = create_room(
        admin,
        ab_group["id"],
        ab_instruction_a["id"],
        ab_instruction_b["id"],
        questionnaire["id"],
        starts_in_seconds=600,
        label="AB 媒体导出房间",
    )
    ab_export = admin.json("GET", f"/admin/api/rooms/{ab_room['id']}/export.json")
    ab_entries = _entry_by_id(ab_export)
    assert set(ab_entries) == {a_image["id"], b_image["id"], instruction_image["id"]}
    maps = {item["slot"]: item for item in ab_export["mapGroup"]["maps"]}
    assert maps["A"]["cells"][0] == a_image["id"]
    assert maps["B"]["cells"][0] == b_image["id"]
    assert ab_entries[a_image["id"]]["contentType"] == "image/png"
    assert ab_entries[b_image["id"]]["contentType"] == "image/jpeg"
    assert ab_entries[a_image["id"]]["path"] == f"media/{a_image['id']}.png"
    assert ab_entries[b_image["id"]]["path"] == f"media/{b_image['id']}.jpg"
    ab_zip = admin.request("GET", f"/admin/api/rooms/{ab_room['id']}/analysis.zip")
    assert ab_zip.status_code == 200
    ab_manifest = _zip_entries(ab_zip)
    assert {entry["assetId"] for entry in ab_manifest["assets"]} == set(ab_entries)

    admin.close()
