import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
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
IDENTITY_FERNET_KEY = "odEQ9io8t2uipKkgvVyIY3UXIYGua3wrE8fnS3662sE="
ID_CARD_SAMPLE = "11010519491231002X"
PASSPORT_SAMPLE = "E12345678"
DEFAULT_TROOP_ROWS = [
    {"soldiersA": 7, "soldiersB": 7},
    {"soldiersA": 8, "soldiersB": 9},
    {"soldiersA": 6, "soldiersB": 5},
]


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


def execute_sql(sql: str, params: tuple = ()) -> None:
    connection = _mysql_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
    finally:
        connection.close()


def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    connection = _mysql_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        connection.close()


def fetch_one(sql: str, params: tuple = ()) -> dict | None:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


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
                "IDENTITY_ENCRYPTION_KEY": IDENTITY_FERNET_KEY,
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


def create_troop_profile(
    admin: ApiClient,
    rows: list[dict] | None = None,
    *,
    publish: bool = True,
    name: str | None = None,
) -> dict:
    normalized = [
        {"soldiersA": int(row["soldiersA"]), "soldiersB": int(row["soldiersB"])}
        for row in (rows if rows is not None else DEFAULT_TROOP_ROWS)
    ]
    profile_name = name or f"测试兵力-{uuid.uuid4().hex[:8]}"
    created = admin.json(
        "POST",
        "/admin/api/troop-profiles",
        json={"name": profile_name, "rows": normalized},
    )
    version = created["troopProfile"]
    if publish:
        version = admin.json(
            "POST", f"/admin/api/troop-profiles/{version['id']}/publish"
        )["troopProfile"]
    return version


def _asset_cells(assets, slot: str, total: int) -> list:
    if assets is None:
        return [None] * total
    cells = assets.get(slot) if isinstance(assets, dict) else assets
    if cells is None:
        return [None] * total
    if len(cells) != total:
        raise ValueError(f"{slot} 地图单元格数量必须为 {total}")
    return list(cells)


def _landmark_indexes(value, slot: str) -> list[int]:
    if value is None:
        return []
    indexes = value.get(slot) if isinstance(value, dict) else value
    return list(indexes or [])


def create_map_group(
    admin: ApiClient,
    troop_profile_version_id: str,
    *,
    mode: str = "both",
    rows: int = 3,
    cols: int = 3,
    formal_trials: int = 2,
    assets: list[str | None] | dict[str, list[str | None]] | None = None,
    colors: list[str | None] | dict[str, list[str | None]] | None = None,
    landmark_cells: list[int] | dict[str, list[int]] | None = None,
    factors: dict[str, str] | None = None,
    spawns: dict[str, int] | None = None,
    description: str = "测试地图",
    factor_level: str = "标准",
    practice_turn_cap: int = 3,
    practice_turn_seconds: int = 3,
    formal_turn_cap: int = 3,
    formal_turn_seconds: int = 3,
    rest_seconds: int = 1,
    randomize_formal: bool = True,
    base_pay_cents: int = 4500,
    performance_rate_cents: int = 1,
    performance_floor_cents: int = 0,
    performance_cap_cents: int = 2000,
    showup_pay_cents: int = 1000,
    publish: bool = True,
) -> dict:
    total = rows * cols
    slots = ("Both",) if mode == "both" else ("A", "B")
    maps = [
        {
            "slot": slot,
            "description": description,
            "factorLevel": factor_level,
            "cells": _asset_cells(assets, slot, total),
            "colors": _asset_cells(colors, slot, total),
            "landmarkCells": _landmark_indexes(landmark_cells, slot),
        }
        for slot in slots
    ]
    payload = {
        "mode": mode,
        "factors": factors or {},
        "rows": rows,
        "cols": cols,
        "spawns": spawns or {"A": 0, "B": total - 1},
        "troopProfileVersionId": troop_profile_version_id,
        "practiceTrials": 1,
        "formalTrials": formal_trials,
        "practiceTurnCap": practice_turn_cap,
        "practiceTurnSeconds": practice_turn_seconds,
        "formalTurnCap": formal_turn_cap,
        "formalTurnSeconds": formal_turn_seconds,
        "restSeconds": rest_seconds,
        "randomizeFormal": randomize_formal,
        "payment": {
            "basePayCents": base_pay_cents,
            "performanceRateCents": performance_rate_cents,
            "performanceFloorCents": performance_floor_cents,
            "performanceCapCents": performance_cap_cents,
            "showupPayCents": showup_pay_cents,
        },
        "maps": maps,
    }
    created = admin.json("POST", "/admin/api/map-groups", json=payload)
    version = created["mapGroup"]
    if publish:
        version = admin.json(
            "POST", f"/admin/api/map-groups/{version['id']}/publish"
        )["mapGroup"]
    return version


def create_instruction(
    admin: ApiClient,
    map_group_version_id: str,
    role: int,
    markdown: str,
    min_seconds: int = 0,
    *,
    publish: bool = True,
) -> dict:
    created = admin.json(
        "POST",
        "/admin/api/instructions",
        json={
            "mapGroupVersionId": map_group_version_id,
            "role": role,
            "markdown": markdown,
            "minReadingSeconds": min_seconds,
        },
    )
    instruction = created["instruction"]
    if publish:
        instruction = admin.json(
            "POST", f"/admin/api/instructions/{instruction['id']}/publish"
        )["instruction"]
    return instruction


def create_questionnaire(
    admin: ApiClient,
    *,
    publish: bool = True,
    name: str | None = None,
) -> dict:
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
                        "type": "short_text",
                        "label": "实验感受",
                        "required": True,
                        "maxLength": 200,
                    },
                    {"id": "real_name", "type": "real_name", "label": "真实姓名", "required": True},
                    {
                        "id": "alipay_phone",
                        "type": "alipay_phone",
                        "label": "支付宝手机号",
                        "required": True,
                    },
                    {
                        "id": "identity_document",
                        "type": "identity_document",
                        "label": "身份证件",
                        "required": True,
                    },
                ],
            }
        ],
    }
    questionnaire_name = name or f"测试问卷-{uuid.uuid4().hex[:8]}"
    created = admin.json(
        "POST",
        "/admin/api/questionnaires",
        json={"name": questionnaire_name, "schemaJson": schema},
    )
    questionnaire = created["questionnaire"]
    if publish:
        questionnaire = admin.json(
            "POST", f"/admin/api/questionnaires/{questionnaire['id']}/publish"
        )["questionnaire"]
    return questionnaire


def create_room(
    admin: ApiClient,
    map_group_version_id: str,
    instruction_p1: str,
    instruction_p2: str,
    questionnaire_id: str,
    starts_in_seconds: float = 6,
    wait_window_seconds: int = 30,
    reconnect_window_seconds: int = 5,
    label: str = "集成测试房间",
    *,
    publish: bool = True,
) -> dict:
    starts_at = datetime.now(timezone.utc) + timedelta(seconds=starts_in_seconds)
    created = admin.json(
        "POST",
        "/admin/api/rooms",
        json={
            "internalLabel": label,
            "startsAt": starts_at.isoformat().replace("+00:00", "Z"),
            "mapGroupVersionId": map_group_version_id,
            "instructionVersionP1Id": instruction_p1,
            "instructionVersionP2Id": instruction_p2,
            "questionnaireVersionId": questionnaire_id,
            "waitWindowSeconds": wait_window_seconds,
            "reconnectWindowSeconds": reconnect_window_seconds,
        },
    )
    room = created["room"]
    if publish:
        room = admin.json("POST", f"/admin/api/rooms/{room['id']}/publish")["room"]
    return room


def upload_media(
    admin: ApiClient,
    data: bytes,
    *,
    filename: str = "asset.png",
    kind: str = "map",
) -> dict:
    response = admin.request(
        "POST",
        "/admin/api/media",
        files={"file": (filename, data, "image/png")},
        data={"kind": kind},
    )
    if response.status_code != 200:
        raise AssertionError(f"media upload failed: {response.status_code}: {response.text}")
    return response.json()["asset"]


def valid_identity_answers(
    prefix: str,
    *,
    phone: str = "13900001111",
    id_card: str = ID_CARD_SAMPLE,
    passport: str = PASSPORT_SAMPLE,
) -> dict:
    return {
        "real_name": f"测试{prefix}",
        "alipay_phone": phone,
        "id_card": id_card,
        "passport": passport,
    }


def questionnaire_protected_answers(identity: dict, *, document_type: str = "id_card") -> dict:
    if document_type not in ("id_card", "passport"):
        raise ValueError("document_type 必须为 id_card 或 passport")
    return {
        "real_name": identity["real_name"],
        "alipay_phone": identity["alipay_phone"],
        "identity_document": {
            "documentType": document_type,
            "number": identity[document_type],
        },
    }


def questionnaire_answers(identity: dict, *, document_type: str = "id_card", **answers) -> dict:
    return {**answers, **questionnaire_protected_answers(identity, document_type=document_type)}
