from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    public_base_url: str = "http://127.0.0.1:8000"
    secret_key: str = "dev-secret-key-change-in-production"
    phone_hmac_key: str = "dev-phone-hmac-key-change-in-production"
    phone_encryption_key: str = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    database_url: str = "mysql+aiomysql://moyo:moyo_dev_password@127.0.0.1:3307/moyo?charset=utf8mb4"
    admin_username: str = "admin"
    admin_initial_password: str = "admin-initial-password"
    jatos_base_url: str = "http://127.0.0.1:9000"
    jatos_study_code: str = ""
    jatos_api_token: str = ""
    timezone: str = "Asia/Shanghai"
    media_dir: str = str(PROJECT_DIR / "data" / "media")
    cookie_secure: bool | None = None
    session_participant_max_age: int = 60 * 60 * 24 * 30
    session_admin_max_age: int = 60 * 60 * 8
    login_rate_limit_attempts: int = 10
    login_rate_limit_seconds: int = 300
    questionnaire_rate_limit_attempts: int = 240
    questionnaire_rate_limit_seconds: int = 60
    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 4096 * 4096
    trust_proxy_headers: bool = False
    serve_frontend: bool = True
    log_level: str = "INFO"

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.public_base_url.lower().startswith("https://")

    @property
    def jatos_origin(self) -> str | None:
        if not self.jatos_base_url:
            return None
        from urllib.parse import urlsplit

        parts = urlsplit(self.jatos_base_url)
        if not parts.scheme or not parts.netloc:
            return None
        return f"{parts.scheme}://{parts.netloc}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
