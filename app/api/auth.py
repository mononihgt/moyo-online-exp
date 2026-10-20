from fastapi import APIRouter, Request, Response, status

from ..config import get_settings
from ..schemas import AdminLoginRequest, LoginRequest
from ..security import (
    ADMIN_COOKIE,
    CSRF_COOKIE,
    PARTICIPANT_COOKIE,
    client_ip,
    issue_admin_session,
    issue_participant_session,
    new_csrf_token,
    normalize_phone,
    phone_hash,
    rate_limiter,
    verify_password,
)
from ..services.participants import authenticate_participant, participant_me
from ..timeutil import isoformat_utc, utcnow
from .deps import DbSession, ParticipantDep

router = APIRouter()


def _set_cookie(response: Response, name: str, value: str, max_age: int, *, httponly: bool) -> None:
    settings = get_settings()
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=httponly,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def set_participant_cookies(response: Response, participant_id: str, csrf_token: str) -> None:
    settings = get_settings()
    _set_cookie(
        response,
        PARTICIPANT_COOKIE,
        issue_participant_session(participant_id),
        settings.session_participant_max_age,
        httponly=True,
    )
    _set_cookie(response, CSRF_COOKIE, csrf_token, settings.session_participant_max_age, httponly=False)


def clear_participant_cookies(response: Response) -> None:
    response.delete_cookie(PARTICIPANT_COOKIE, path="/")


@router.post("/api/login")
async def participant_login(payload: LoginRequest, request: Request, response: Response, db: DbSession):
    settings = get_settings()
    raw_phone = payload.phone.strip()
    try:
        account_key = normalize_phone(raw_phone)
    except ValueError:
        account_key = raw_phone
    rate_limiter.check(
        f"participant-login:{phone_hash(account_key)}",
        settings.login_rate_limit_attempts,
        settings.login_rate_limit_seconds,
    )
    participant = await authenticate_participant(db, payload.name, payload.phone)
    csrf_token = request.cookies.get(CSRF_COOKIE) or new_csrf_token()
    set_participant_cookies(response, participant.id, csrf_token)
    return {"me": await participant_me(db, participant), "csrfToken": csrf_token}


@router.post("/api/logout")
async def participant_logout(response: Response):
    clear_participant_cookies(response)
    return {"loggedOut": True}


@router.get("/api/me")
async def participant_profile(participant: ParticipantDep, db: DbSession, request: Request):
    return {
        "me": await participant_me(db, participant),
        "csrfToken": request.cookies.get(CSRF_COOKIE),
        "serverNow": isoformat_utc(utcnow()),
    }


@router.post("/admin/api/login")
async def admin_login(payload: AdminLoginRequest, request: Request, response: Response, db: DbSession):
    from sqlalchemy import select

    from ..models import AdminUser

    settings = get_settings()
    rate_limiter.check(
        f"admin-login:{client_ip(request, settings)}",
        settings.login_rate_limit_attempts,
        settings.login_rate_limit_seconds,
    )
    result = await db.execute(select(AdminUser).where(AdminUser.username == payload.username))
    admin = result.scalars().first()
    if admin is None or not verify_password(payload.password, admin.password_hash):
        from fastapi import HTTPException

        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码不正确")
    admin.last_login_at = utcnow()
    await db.commit()
    csrf_token = new_csrf_token()
    _set_cookie(
        response,
        ADMIN_COOKIE,
        issue_admin_session(admin.id),
        settings.session_admin_max_age,
        httponly=True,
    )
    _set_cookie(response, CSRF_COOKIE, csrf_token, settings.session_admin_max_age, httponly=False)
    return {"admin": {"id": admin.id, "username": admin.username}, "csrfToken": csrf_token}


@router.post("/admin/api/logout")
async def admin_logout(response: Response):
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return {"loggedOut": True}


@router.get("/admin/api/me")
async def admin_me(request: Request, db: DbSession):
    from ..security import current_admin

    admin = await current_admin(request, db)
    return {
        "admin": {"id": admin.id, "username": admin.username, "lastLoginAt": isoformat_utc(admin.last_login_at)},
        "csrfToken": request.cookies.get(CSRF_COOKIE),
    }
