import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from .api import admin as admin_api
from .api import auth as auth_api
from .api import jatos as jatos_api
from .api import media as media_api
from .api import participant as participant_api
from .api import ws as ws_api
from .config import PROJECT_DIR, get_settings
from .db import dispose_engine, get_session_factory, init_engine
from .logging_config import configure_logging
from .models import AdminUser
from .security import CSRF_COOKIE, hash_password, new_csrf_token
from .services.conditions import seed_presets
from .services.runtime import runtime_manager

logger = logging.getLogger(__name__)


async def _seed_admin() -> None:
    settings = get_settings()
    async with get_session_factory()() as db:
        existing = (await db.execute(select(AdminUser).limit(1))).scalars().first()
        if existing is not None:
            return
        db.add(
            AdminUser(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_initial_password),
            )
        )
        await db.commit()


async def _seed_data() -> None:
    async with get_session_factory()() as db:
        await seed_presets(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine()
    await _seed_admin()
    await _seed_data()
    await runtime_manager.start()
    try:
        yield
    finally:
        await runtime_manager.stop()
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="在线双人战争游戏实验平台",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    allowed_origins = []
    for candidate in (settings.public_base_url, settings.jatos_base_url):
        if not candidate:
            continue
        parts = urlsplit(candidate)
        if parts.scheme and parts.netloc:
            allowed_origins.append(f"{parts.scheme}://{parts.netloc}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(set(allowed_origins)),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
        max_age=600,
    )

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        response = await call_next(request)
        if (
            request.method in ("GET", "HEAD")
            and CSRF_COOKIE not in request.cookies
            and not request.url.path.startswith("/media/")
        ):
            response.set_cookie(
                CSRF_COOKIE,
                new_csrf_token(),
                max_age=settings.session_participant_max_age,
                httponly=False,
                secure=settings.secure_cookies,
                samesite="lax",
                path="/",
            )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
        )
        if settings.secure_cookies:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    app.include_router(auth_api.router)
    app.include_router(participant_api.router)
    app.include_router(jatos_api.router)
    app.include_router(admin_api.router)
    app.include_router(media_api.router)
    app.include_router(ws_api.router)

    @app.get("/healthz")
    async def healthz():
        try:
            async with get_session_factory()() as db:
                await db.execute(text("SELECT 1"))
        except Exception:
            logger.exception("health check failed")
            return JSONResponse({"status": "error", "database": "unavailable"}, status_code=503)
        return {"status": "ok", "database": "ok"}

    dist_dir = PROJECT_DIR / "frontend" / "dist"
    if settings.serve_frontend and dist_dir.exists():
        assets_dir = dist_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}")
        async def spa(full_path: str):
            if full_path.startswith(("api/", "admin/api/", "media/", "ws/")):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = (dist_dir / full_path).resolve()
            if full_path and candidate.is_file() and dist_dir.resolve() in candidate.parents:
                return FileResponse(candidate)
            index = dist_dir / "index.html"
            if index.exists():
                return FileResponse(index)
            return JSONResponse({"detail": "前端尚未构建"}, status_code=503)

    return app


app = create_app()
