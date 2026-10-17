import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

WORKER_TYPES = ["GeneralMultiple", "PersonalSingle", "PersonalMultiple"]


def _client(base_url: str, token: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )


def _request(client: httpx.Client, method: str, path: str, **kwargs):
    client.cookies.clear()
    response = client.request(method, path, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text}")
    return response


def _create_study(client: httpx.Client, title: str, description: str) -> dict:
    response = _request(
        client,
        "POST",
        "/jatos/api/v1/studies",
        json={
            "title": title,
            "description": description,
            "active": True,
            "groupStudy": False,
            "linearStudy": False,
            "allowPreview": False,
        },
    )
    return response.json()["data"]


def _enable_general_multiple(client: httpx.Client, study_uuid: str) -> int:
    response = _request(client, "GET", f"/jatos/api/v1/studies/{study_uuid}/batches")
    batches = response.json()["data"]
    if not batches:
        raise RuntimeError("study 没有默认 batch")
    batch_id = batches[0]["id"]
    _request(
        client,
        "PATCH",
        f"/jatos/api/v1/batches/{batch_id}",
        json={"allowedWorkerTypes": WORKER_TYPES},
    )
    return batch_id


def _upload_assets(client: httpx.Client, study_uuid: str, asset_dir: Path) -> None:
    files = sorted(path for path in asset_dir.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError(f"构建目录为空: {asset_dir}")
    for path in files:
        relative = path.relative_to(asset_dir).as_posix()
        content_type = mimetypes.guess_type(relative)[0] or "application/octet-stream"
        _request(
            client,
            "POST",
            f"/jatos/api/v1/studies/{study_uuid}/assets/{quote(relative, safe='/')}",
            files={"studyAssetsFile": (path.name, path.read_bytes(), content_type)},
        )


def _create_component(client: httpx.Client, study_uuid: str, title: str, html_path: str) -> dict:
    response = _request(
        client,
        "POST",
        f"/jatos/api/v1/studies/{study_uuid}/components",
        json={
            "title": title,
            "active": True,
            "reloadable": False,
            "htmlFilePath": html_path,
            "comments": "Moyo 平台问卷组件",
        },
    )
    return response.json()["data"]


def _create_code(client: httpx.Client, study_uuid: str, batch_id: int) -> str:
    response = _request(
        client,
        "POST",
        f"/jatos/api/v1/studies/{study_uuid}/studyCodes",
        json={"type": "GeneralMultiple", "amount": 1000, "batchId": batch_id},
    )
    return response.json()["data"][0]


def main() -> int:
    parser = argparse.ArgumentParser(description="创建 JATOS study 并上传平台问卷组件")
    parser.add_argument("--title", default="Moyo 后测问卷")
    parser.add_argument("--description", default="Moyo 在线实验平台后测问卷")
    parser.add_argument("--assets", default=str(Path(__file__).resolve().parents[1] / "frontend" / "dist-questionnaire"))
    parser.add_argument("--html", default="questionnaire.html")
    parser.add_argument("--component-title", default="后测问卷")
    parser.add_argument("--study", help="使用已有 study 的 id 或 uuid；省略时创建新 study")
    args = parser.parse_args()

    base_url = os.environ.get("JATOS_BASE_URL", "").strip()
    token = os.environ.get("JATOS_API_TOKEN", "").strip()
    if not base_url or not token:
        print("需要设置 JATOS_BASE_URL 和 JATOS_API_TOKEN", file=sys.stderr)
        return 2
    asset_dir = Path(args.assets)
    if not (asset_dir / args.html).is_file():
        print(f"找不到问卷入口: {asset_dir / args.html}", file=sys.stderr)
        return 2

    client = _client(base_url, token)
    try:
        if args.study:
            study_uuid = args.study
            study_id = None
        else:
            study = _create_study(client, args.title, args.description)
            study_uuid = study["uuid"]
            study_id = study["id"]
        batch_id = _enable_general_multiple(client, study_uuid)
        _upload_assets(client, study_uuid, asset_dir)
        component = _create_component(client, study_uuid, args.component_title, args.html)
        code = _create_code(client, study_uuid, batch_id)
    finally:
        client.close()

    print(
        json.dumps(
            {
                "studyId": study_id,
                "studyUuid": study_uuid,
                "batchId": batch_id,
                "componentId": component["id"],
                "componentUuid": component["uuid"],
                "studyCode": code,
                "next": "把 studyCode 填入平台的 JATOS_STUDY_CODE 或管理端设置，然后重启应用。",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
