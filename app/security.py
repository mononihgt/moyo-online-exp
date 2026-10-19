import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import Settings, get_settings
from .models import AdminUser, Participant

PARTICIPANT_COOKIE = "moyo_participant"
ADMIN_COOKIE = "moyo_admin"
CSRF_COOKIE = "moyo_csrf"
CSRF_HEADER = "X-CSRF-Token"

_PASSWORD_HASHER = PasswordHasher()
_PHONE_DIGITS = re.compile(r"\D")
_SENSITIVE_QUERY = re.compile(r"(token|rt|auth|password)=([^&\s\"]+)", re.IGNORECASE)


def normalize_phone(raw: str) -> str:
    digits = _PHONE_DIGITS.sub("", raw or "")
    if digits.startswith("0086"):
        digits = digits[4:]
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    if not re.fullmatch(r"1[3-9]\d{9}", digits):
        raise ValueError("手机号格式不正确")
    return digits


def mask_phone(phone: str) -> str:
    if len(phone) < 7:
        return "****"
    return f"{phone[:3]}****{phone[-4:]}"


def phone_hash(phone: str, settings: Settings | None = None) -> str:
    key = (settings or get_settings()).phone_hmac_key.encode("utf-8")
    return hmac.new(key, phone.encode("utf-8"), hashlib.sha256).hexdigest()


def _fernet(settings: Settings | None = None) -> Fernet:
    return Fernet((settings or get_settings()).phone_encryption_key.encode("utf-8"))


def encrypt_phone(phone: str, settings: Settings | None = None) -> str:
    return _fernet(settings).encrypt(phone.encode("utf-8")).decode("utf-8")


def decrypt_phone(value: str, settings: Settings | None = None) -> str:
    try:
        return _fernet(settings).decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("手机号密文无法解密") from exc


def _identity_fernet(settings: Settings | None = None) -> Fernet:
    return Fernet((settings or get_settings()).identity_encryption_key.encode("utf-8"))


def encrypt_identity(value: str, settings: Settings | None = None) -> str:
    return _identity_fernet(settings).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_identity(value: str, settings: Settings | None = None) -> str:
    try:
        return _identity_fernet(settings).decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("身份信息密文无法解密") from exc


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _serializer(settings: Settings, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=salt)


def issue_participant_session(participant_id: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return _serializer(settings, "participant-session").dumps({"sub": participant_id})


def read_participant_session(token: str, settings: Settings) -> str:
    try:
        payload = _serializer(settings, "participant-session").loads(
            token, max_age=settings.session_participant_max_age
        )
    except SignatureExpired as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "会话已过期，请重新登录") from exc
    except BadSignature as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "会话无效，请重新登录") from exc
    participant_id = payload.get("sub") if isinstance(payload, dict) else None
    if not participant_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "会话无效，请重新登录")
    return participant_id


def issue_admin_session(admin_id: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return _serializer(settings, "admin-session").dumps({"sub": admin_id})


def read_admin_session(token: str, settings: Settings) -> str:
    try:
        payload = _serializer(settings, "admin-session").loads(token, max_age=settings.session_admin_max_age)
    except SignatureExpired as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "管理员会话已过期") from exc
    except BadSignature as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "管理员会话无效") from exc
    admin_id = payload.get("sub") if isinstance(payload, dict) else None
    if not admin_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "管理员会话无效")
    return admin_id


def sign_payload(payload: dict, salt: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    data = dict(payload)
    data.setdefault("nonce", secrets.token_hex(8))
    return _serializer(settings, salt).dumps(data)


def verify_signed_payload(token: str, salt: str, max_age: int, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    try:
        payload = _serializer(settings, salt).loads(token, max_age=max_age)
    except SignatureExpired as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "链接已过期，请向主试申请新的问卷链接") from exc
    except BadSignature as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "链接无效") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "链接无效")
    return payload


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def assert_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF 校验失败")


async def current_participant(request: Request, db) -> Participant:
    token = request.cookies.get(PARTICIPANT_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")
    participant_id = read_participant_session(token, get_settings())
    participant = await db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在")
    return participant


async def current_admin(request: Request, db) -> AdminUser:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录管理员账号")
    admin_id = read_admin_session(token, get_settings())
    admin = await db.get(AdminUser, admin_id)
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "管理员账号不存在")
    return admin


def client_ip(request: Request, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, attempts: int, window_seconds: int) -> None:
        now = time.monotonic()
        events = self._events[key]
        while events and now - events[0] > window_seconds:
            events.popleft()
        if len(events) >= attempts:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试")
        events.append(now)

    def reset(self) -> None:
        self._events.clear()


rate_limiter = RateLimiter()


def redact_sensitive(value: str) -> str:
    return _SENSITIVE_QUERY.sub(lambda match: f"{match.group(1)}=[redacted]", value)
