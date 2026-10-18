import io
import json
import mimetypes
import os
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.parent
COMPONENT_DIR = ROOT / "frontend" / "dist-questionnaire"
TOKEN_FILE = PROJECT_ROOT / ".review" / "jatos" / "api_token.env"


def jatos_base_url() -> str:
    return os.environ.get("TEST_JATOS_BASE_URL", "http://127.0.0.1:9000").rstrip("/")


def jatos_api_token() -> str:
    token = os.environ.get("TEST_JATOS_API_TOKEN", "").strip()
    if token:
        return token
    if TOKEN_FILE.exists():
        for line in TOKEN_FILE.read_text().splitlines():
            if line.startswith("JATOS_API_TOKEN="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(
        "缺少 JATOS API token。先运行 scripts/jatos_dev_setup.sh，或设置 TEST_JATOS_API_TOKEN。"
    )


def ensure_questionnaire_build() -> Path:
    html = COMPONENT_DIR / "questionnaire.html"
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("缺少 npm，无法构建问卷组件")
    env = os.environ.copy()
    env["VITE_ALLOW_BASE_OVERRIDE"] = "true"
    result = subprocess.run(
        [npm, "run", "build"],
        cwd=ROOT / "frontend",
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not html.exists():
        raise RuntimeError("问卷组件构建失败:\n" + result.stdout + result.stderr)
    return html


class JatosClient:
    def __init__(self) -> None:
        self.base = jatos_base_url()
        self.client = httpx.Client(
            base_url=self.base,
            headers={"Authorization": f"Bearer {jatos_api_token()}"},
            timeout=120,
        )

    def create_study(self) -> dict:
        self.client.cookies.clear()
        response = self.client.post(
            "/jatos/api/v1/studies",
            json={
                "title": f"Moyo Test {uuid.uuid4().hex[:10]}",
                "description": "Integration test study",
                "active": True,
                "groupStudy": False,
                "linearStudy": False,
                "allowPreview": False,
            },
        )
        response.raise_for_status()
        return response.json()["data"]

    def batches(self, study_uuid: str) -> list[dict]:
        self.client.cookies.clear()
        response = self.client.get(f"/jatos/api/v1/studies/{study_uuid}/batches")
        response.raise_for_status()
        return response.json()["data"]

    def enable_general_multiple(self, batch_id: int) -> None:
        self.client.cookies.clear()
        response = self.client.patch(
            f"/jatos/api/v1/batches/{batch_id}",
            json={"allowedWorkerTypes": ["GeneralMultiple", "PersonalSingle", "PersonalMultiple"]},
        )
        response.raise_for_status()

    def upload_asset(self, study_uuid: str, relative_path: str, data: bytes) -> None:
        self.client.cookies.clear()
        content_type = mimetypes.guess_type(relative_path)[0] or "application/octet-stream"
        path = f"/jatos/api/v1/studies/{study_uuid}/assets/{quote(relative_path, safe='/')}"
        response = self.client.post(
            path,
            files={"studyAssetsFile": (Path(relative_path).name, data, content_type)},
        )
        response.raise_for_status()

    def create_component(self, study_uuid: str, html_path: str) -> dict:
        self.client.cookies.clear()
        response = self.client.post(
            f"/jatos/api/v1/studies/{study_uuid}/components",
            json={
                "title": "Questionnaire",
                "active": True,
                "reloadable": False,
                "htmlFilePath": html_path,
                "comments": "Moyo questionnaire component",
            },
        )
        response.raise_for_status()
        return response.json()["data"]

    def create_code(self, study_uuid: str, batch_id: int) -> str:
        self.client.cookies.clear()
        response = self.client.post(
            f"/jatos/api/v1/studies/{study_uuid}/studyCodes",
            json={"type": "GeneralMultiple", "amount": 10, "batchId": batch_id},
        )
        response.raise_for_status()
        return response.json()["data"][0]

    def results_metadata(self, study_id: int) -> dict:
        self.client.cookies.clear()
        response = self.client.get("/jatos/api/v1/results", params={"studyId": study_id})
        response.raise_for_status()
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        return json.loads(archive.read("metadata.json"))

    def results_data(self, study_id: int) -> list[dict]:
        self.client.cookies.clear()
        response = self.client.get("/jatos/api/v1/results", params={"studyId": study_id})
        response.raise_for_status()
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        data_entries = []
        for name in archive.namelist():
            if name.endswith("/data.txt") or name == "data.txt":
                content = archive.read(name).decode("utf-8").strip()
                if content:
                    data_entries.append(json.loads(content))
        return data_entries

    def close(self) -> None:
        self.client.close()


def create_test_study(jatos: JatosClient) -> dict:
    html = ensure_questionnaire_build()
    study = jatos.create_study()
    uuid_value = study["uuid"]
    batches = jatos.batches(uuid_value)
    if not batches:
        raise RuntimeError("JATOS study 没有默认 batch")
    batch_id = batches[0]["id"]
    jatos.enable_general_multiple(batch_id)
    for path in sorted(COMPONENT_DIR.rglob("*")):
        if path.is_file():
            relative = path.relative_to(COMPONENT_DIR).as_posix()
            jatos.upload_asset(uuid_value, relative, path.read_bytes())
    component = jatos.create_component(uuid_value, "questionnaire.html")
    code = jatos.create_code(uuid_value, batch_id)
    return {
        "study_id": study["id"],
        "study_uuid": uuid_value,
        "batch_id": batch_id,
        "component_id": component["id"],
        "component_uuid": component["uuid"],
        "code": code,
        "html_path": html,
    }
