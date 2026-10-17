import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pymysql
import pytest
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
ARTIFACTS = PROJECT_ROOT / ".review"
ARTIFACTS.mkdir(parents=True, exist_ok=True)

DB_HOST = os.environ.get("TEST_MYSQL_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("TEST_MYSQL_PORT", "3307"))
DB_USER = os.environ.get("TEST_MYSQL_USER", "moyo")
DB_PASSWORD = os.environ.get("TEST_MYSQL_PASSWORD", "moyo_dev_password")
DB_NAME = os.environ.get("TEST_MYSQL_DATABASE", "moyo_test")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    f"mysql+aiomysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4",
)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "integration-admin-password"
FERNET_KEY = "WbHjoN9iR54PDbJDatQC0i2G-ow1XNn2_AzRpfdo3_0="


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _mysql_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=True,
    )


@pytest.fixture(scope="session", autouse=True)
def migrate_database():
    env = os.environ.copy()
    env["DATABASE_URL"] = TEST_DATABASE_URL
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("alembic upgrade failed:\n" + result.stdout + result.stderr)


def reset_database() -> None:
    from app import models  # noqa: F401
    from app.db import Base

    connection = _mysql_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
            for table in reversed(Base.metadata.sorted_tables):
                cursor.execute(f"TRUNCATE TABLE `{table.name}`")
            cursor.execute("SET FOREIGN_KEY_CHECKS=1")
    finally:
        connection.close()


class ServerHandle:
    def __init__(self, env_overrides: dict | None = None) -> None:
        self.env_overrides = env_overrides or {}
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.ws_url = f"ws://127.0.0.1:{self.port}/ws/room"
        self.process: subprocess.Popen | None = None
        self.log_path = ARTIFACTS / f"integration-uvicorn-{self.port}.log"
        self._log_handle = None

    def env(self) -> dict:
        env = os.environ.copy()
        env.update(
            {
                "PUBLIC_BASE_URL": self.base_url,
                "DATABASE_URL": TEST_DATABASE_URL,
                "SECRET_KEY": "integration-secret-key",
                "PHONE_HMAC_KEY": "integration-phone-hmac-key",
                "PHONE_ENCRYPTION_KEY": FERNET_KEY,
                "ADMIN_USERNAME": ADMIN_USERNAME,
                "ADMIN_INITIAL_PASSWORD": ADMIN_PASSWORD,
                "JATOS_BASE_URL": os.environ.get("TEST_JATOS_BASE_URL", "http://127.0.0.1:9000"),
                "JATOS_STUDY_CODE": os.environ.get("TEST_JATOS_STUDY_CODE", "moyo-test"),
                "JATOS_API_TOKEN": os.environ.get("TEST_JATOS_API_TOKEN", ""),
                "COOKIE_SECURE": "false",
                "SERVE_FRONTEND": "false",
                "LOGIN_RATE_LIMIT_ATTEMPTS": "1000",
                "QUESTIONNAIRE_RATE_LIMIT_ATTEMPTS": "10000",
                "PYTHONUNBUFFERED": "1",
            }
        )
        env.update(self.env_overrides)
        return env

    def start(self) -> None:
        self._log_handle = self.log_path.open("ab")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--workers",
                "1",
            ],
            cwd=ROOT,
            env=self.env(),
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"{self.base_url}/healthz", timeout=1)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if self.process.poll() is not None:
                raise RuntimeError("uvicorn exited early:\n" + self.log_tail())
            time.sleep(0.1)
        raise RuntimeError("uvicorn did not become healthy:\n" + self.log_tail())

    def log_tail(self, lines: int = 80) -> str:
        if not self.log_path.exists():
            return "(no log)"
        content = self.log_path.read_text(errors="replace").splitlines()
        return "\n".join(content[-lines:])

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                self.process.wait(timeout=5)
        self.process = None
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def restart(self) -> None:
        self.stop()
        self.start()


@pytest.fixture
def server():
    reset_database()
    instance = ServerHandle()
    instance.start()
    yield instance
    instance.stop()


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=30)

    def request(self, method: str, path: str, **kwargs):
        csrf = self.client.cookies.get("moyo_csrf")
        headers = kwargs.pop("headers", {})
        if csrf:
            headers["X-CSRF-Token"] = csrf
        response = self.client.request(method, path, headers=headers, **kwargs)
        return response

    def json(self, method: str, path: str, expected: int = 200, **kwargs):
        response = self.request(method, path, **kwargs)
        if response.status_code != expected:
            raise AssertionError(f"{method} {path} -> {response.status_code}: {response.text}")
        return response.json()

    def login_admin(self) -> "ApiClient":
        payload = self.json(
            "POST",
            "/admin/api/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        assert payload["admin"]["username"] == ADMIN_USERNAME
        return self

    def login_participant(self, name: str, phone: str) -> "ApiClient":
        payload = self.json("POST", "/api/login", json={"name": name, "phone": phone})
        assert payload["me"]["name"] == name
        return self

    def consent(self) -> None:
        document = self.json("GET", "/api/consent")
        self.json("POST", "/api/consent", json={"versionId": document["versionId"], "agree": True})

    def cookie_value(self, name: str) -> str:
        value = self.client.cookies.get(name)
        if not value:
            raise AssertionError(f"cookie {name} missing")
        return value

    def close(self) -> None:
        self.client.close()


class WsClient:
    def __init__(self, server: ServerHandle, cookie: str) -> None:
        self.ws = connect(
            server.ws_url,
            additional_headers={"Cookie": f"moyo_participant={cookie}"},
            open_timeout=15,
            close_timeout=5,
        )

    def send(self, message_type: str, **fields) -> None:
        self.ws.send(json.dumps({"type": message_type, **fields}))

    def recv(self, timeout: float = 20) -> dict:
        return json.loads(self.ws.recv(timeout=timeout))

    def recv_until(self, message_type: str, timeout: float = 20, limit: int = 200) -> dict:
        for _ in range(limit):
            message = self.recv(timeout=timeout)
            if message.get("type") == message_type:
                return message
            if message.get("type") == "error":
                raise AssertionError(f"websocket error: {message}")
        raise AssertionError(f"did not receive {message_type}")

    def close(self) -> None:
        self.ws.close()


def wait_until(predicate, timeout: float = 30, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s; last={last!r}")


def create_consent(admin: ApiClient) -> dict:
    created = admin.json("POST", "/admin/api/consent-versions", json={"markdown": "# 知情同意\n\n测试同意书。"})
    admin.json("POST", f"/admin/api/consent-versions/{created['id']}/publish")
    return created


def create_instruction(admin: ApiClient, role: int, markdown: str, min_seconds: int = 0) -> dict:
    created = admin.json(
        "POST",
        "/admin/api/instructions",
        json={
            "name": f"role-{role}-instructions",
            "role": role,
            "markdown": markdown,
            "minReadingSeconds": min_seconds,
        },
    )
    admin.json("POST", f"/admin/api/instructions/{created['instruction']['id']}/publish")
    return created["instruction"]


def create_questionnaire(admin: ApiClient) -> dict:
    schema = {
        "title": "后测问卷",
        "pages": [
            {
                "id": "page1",
                "questions": [
                    {
                        "id": "q1",
                        "type": "single_choice",
                        "label": "你的性别",
                        "required": True,
                        "options": [{"value": "female", "label": "女"}, {"value": "male", "label": "男"}],
                    },
                    {
                        "id": "q2",
                        "type": "likert",
                        "label": "满意度",
                        "required": False,
                        "min": 1,
                        "max": 5,
                    },
                ],
            }
        ],
    }
    created = admin.json(
        "POST", "/admin/api/questionnaires", json={"name": "post-questionnaire", "schemaJson": schema}
    )
    admin.json("POST", f"/admin/api/questionnaires/{created['questionnaire']['id']}/publish")
    return created["questionnaire"]


def create_condition(
    admin: ApiClient,
    *,
    rows: int = 5,
    cols: int = 7,
    practice: int = 1,
    formal: int = 2,
    turn_count: int = 3,
    turn_seconds: int = 3,
    rest_seconds: int = 1,
) -> dict:
    total = rows * cols
    cells = []
    for index in range(total):
        owner = 1 if index == 0 else (2 if index == total - 1 else 0)
        cells.append(
            {
                "row": index // cols,
                "col": index % cols,
                "initialOwner": owner,
                "initialSoldiers": 0,
                "reinforcementA": 2,
                "reinforcementB": 2,
            }
        )
    layer = [{"color": "#DCEBFF", "backgroundAssetId": None} for _ in range(total)]
    trial_params = []
    for index in range(practice + formal):
        is_practice = index < practice
        trial_params.append(
            {
                "sourceIndex": index,
                "isPractice": is_practice,
                "formalTrial": 0 if is_practice else index - practice + 1,
                "baseSoldiersA": 8,
                "baseSoldiersB": 8,
                "reinforcementOverrides": None,
            }
        )
    payload = {
        "name": f"condition-{rows}x{cols}-{practice}-{formal}",
        "description": "集成测试条件",
        "rows": rows,
        "cols": cols,
        "cells": cells,
        "visuals": {"player1": layer, "player2": [dict(item) for item in layer]},
        "baseAIndex": 0,
        "baseBIndex": total - 1,
        "practiceTrials": practice,
        "formalTrials": formal,
        "turnCount": turn_count,
        "turnSeconds": turn_seconds,
        "restSeconds": rest_seconds,
        "randomizeFormal": True,
        "trialParams": trial_params,
        "metadata": {"test": True},
    }
    created = admin.json("POST", "/admin/api/conditions", json=payload)
    admin.json("POST", f"/admin/api/conditions/{created['condition']['id']}/publish")
    return created["condition"]


def import_roster(admin: ApiClient, participants: list[tuple[str, str]]) -> dict:
    content = "姓名,手机号\n" + "\n".join(f"{name},{phone}" for name, phone in participants) + "\n"
    return admin.json(
        "POST",
        "/admin/api/participants/import",
        files={"file": ("roster.csv", content.encode("utf-8"), "text/csv")},
    )


def create_room(
    admin: ApiClient,
    *,
    condition_id: str,
    instruction_p1: str,
    instruction_p2: str,
    questionnaire_id: str,
    starts_in_seconds: float = 2,
    wait_window_seconds: int = 30,
    reconnect_window_seconds: int = 5,
    base_pay_cents: int = 1000,
    performance_rate_cents: int = 1,
    showup_pay_cents: int = 500,
    label: str = "Integration Room",
) -> dict:
    from datetime import datetime, timedelta, timezone

    starts_at = datetime.now(timezone.utc) + timedelta(seconds=starts_in_seconds)
    created = admin.json(
        "POST",
        "/admin/api/rooms",
        json={
            "internalLabel": label,
            "startsAt": starts_at.isoformat().replace("+00:00", "Z"),
            "conditionVersionId": condition_id,
            "instructionVersionP1Id": instruction_p1,
            "instructionVersionP2Id": instruction_p2,
            "questionnaireVersionId": questionnaire_id,
            "basePayCents": base_pay_cents,
            "performanceRateCents": performance_rate_cents,
            "showupPayCents": showup_pay_cents,
            "waitWindowSeconds": wait_window_seconds,
            "reconnectWindowSeconds": reconnect_window_seconds,
        },
    )
    admin.json("POST", f"/admin/api/rooms/{created['room']['id']}/publish")
    return created["room"]
