import hashlib
import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import VERSION_DRAFT, VERSION_PUBLISHED
from ..models import TroopProfile, TroopProfileVersion
from ..presets import default_troop_profile_payload
from ..timeutil import isoformat_utc, utcnow


class TroopProfileValidationError(ValueError):
    pass


def normalize_profile_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise TroopProfileValidationError("方案名称不能为空")
    normalized = name.strip()
    if len(normalized) > 200:
        raise TroopProfileValidationError("方案名称不能超过 200 个字符")
    return normalized


def validate_troop_profile_rows(rows: Any) -> int:
    if not isinstance(rows, list) or len(rows) < 2:
        raise TroopProfileValidationError("兵力配置方案必须包含 1 行练习和至少 1 行正式")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TroopProfileValidationError(f"第 {index} 行配置必须是对象")
        for key, player in (("soldiersA", "A"), ("soldiersB", "B")):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise TroopProfileValidationError(f"第 {index} 行玩家 {player} 兵力必须是正整数")
    return len(rows) - 1


def normalize_rows(rows: list[dict]) -> list[dict]:
    return [
        {"soldiersA": int(row["soldiersA"]), "soldiersB": int(row["soldiersB"])}
        for row in rows
    ]


def troop_profile_content_hash(name: str, rows: list[dict], formal_trials: int) -> str:
    canonical = {
        "name": name,
        "rows": normalize_rows(rows),
        "formalTrials": formal_trials,
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def ensure_troop_profile_editable(version: TroopProfileVersion) -> None:
    if version.troop_profile.built_in:
        raise HTTPException(status.HTTP_409_CONFLICT, "内置方案只读，请复制后修改")
    if version.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "已发布的版本不可修改，请创建新版本")


def serialize_troop_profile_version(version: TroopProfileVersion) -> dict:
    profile = version.troop_profile
    return {
        "id": version.id,
        "profileId": profile.id,
        "name": profile.name,
        "builtIn": profile.built_in,
        "version": version.version,
        "rows": version.rows_json,
        "practiceTrials": version.practice_trials,
        "formalTrials": version.formal_trials,
        "status": version.status,
        "contentHash": version.content_hash,
        "publishedAt": isoformat_utc(version.published_at),
        "createdAt": isoformat_utc(version.created_at),
    }


def serialize_troop_profile(profile: TroopProfile, versions: list[TroopProfileVersion]) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "builtIn": profile.built_in,
        "createdAt": isoformat_utc(profile.created_at),
        "versions": [serialize_troop_profile_version(version) for version in versions],
    }


async def _next_version_number(db: AsyncSession, troop_profile_id: str) -> int:
    current = (
        await db.execute(
            select(func.max(TroopProfileVersion.version)).where(
                TroopProfileVersion.troop_profile_id == troop_profile_id
            )
        )
    ).scalar_one_or_none()
    return (current or 0) + 1


async def _find_profile(db: AsyncSession, name: str) -> TroopProfile | None:
    rows = await db.execute(select(TroopProfile).where(TroopProfile.name == name))
    return rows.scalars().first()


async def get_troop_profile_version(db: AsyncSession, version_id: str) -> TroopProfileVersion:
    version = await db.get(TroopProfileVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "兵力配置方案版本不存在")
    return version


async def list_troop_profiles(db: AsyncSession) -> list[dict]:
    profiles = list(
        (await db.execute(select(TroopProfile).order_by(TroopProfile.name))).scalars().all()
    )
    versions = list(
        (
            await db.execute(
                select(TroopProfileVersion).order_by(
                    TroopProfileVersion.troop_profile_id, TroopProfileVersion.version.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[str, list[TroopProfileVersion]] = {}
    for version in versions:
        grouped.setdefault(version.troop_profile_id, []).append(version)
    return [serialize_troop_profile(profile, grouped.get(profile.id, [])) for profile in profiles]


async def create_troop_profile(db: AsyncSession, name: Any, rows: Any) -> TroopProfileVersion:
    normalized_name = normalize_profile_name(name)
    formal_trials = validate_troop_profile_rows(rows)
    normalized_rows = normalize_rows(rows)
    profile = await _find_profile(db, normalized_name)
    if profile is not None and profile.built_in:
        raise HTTPException(status.HTTP_409_CONFLICT, "内置方案只读，请复制后修改")
    if profile is None:
        profile = TroopProfile(name=normalized_name, built_in=False)
        db.add(profile)
        await db.flush()
    version = TroopProfileVersion(
        troop_profile=profile,
        version=await _next_version_number(db, profile.id),
        rows_json=normalized_rows,
        practice_trials=1,
        formal_trials=formal_trials,
        status=VERSION_DRAFT,
        content_hash=troop_profile_content_hash(normalized_name, normalized_rows, formal_trials),
    )
    db.add(version)
    await db.flush()
    return version


async def update_troop_profile(
    db: AsyncSession, version: TroopProfileVersion, rows: Any
) -> TroopProfileVersion:
    ensure_troop_profile_editable(version)
    formal_trials = validate_troop_profile_rows(rows)
    normalized_rows = normalize_rows(rows)
    version.rows_json = normalized_rows
    version.formal_trials = formal_trials
    version.practice_trials = 1
    version.content_hash = troop_profile_content_hash(
        version.troop_profile.name, normalized_rows, formal_trials
    )
    await db.flush()
    return version


async def publish_troop_profile(db: AsyncSession, version: TroopProfileVersion) -> TroopProfileVersion:
    if version.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有草稿版本可以发布")
    formal_trials = validate_troop_profile_rows(version.rows_json)
    previous = await db.execute(
        select(TroopProfileVersion).where(
            TroopProfileVersion.troop_profile_id == version.troop_profile_id,
            TroopProfileVersion.status == VERSION_PUBLISHED,
            TroopProfileVersion.id != version.id,
        )
    )
    for row in previous.scalars().all():
        row.status = "archived"
    version.practice_trials = 1
    version.formal_trials = formal_trials
    version.status = VERSION_PUBLISHED
    version.published_at = utcnow()
    version.content_hash = troop_profile_content_hash(
        version.troop_profile.name, version.rows_json, formal_trials
    )
    await db.flush()
    return version


async def copy_troop_profile(db: AsyncSession, version: TroopProfileVersion, name: Any) -> TroopProfileVersion:
    normalized_name = normalize_profile_name(name)
    existing = await _find_profile(db, normalized_name)
    if existing is not None:
        raise TroopProfileValidationError("方案名称已存在")
    profile = TroopProfile(name=normalized_name, built_in=False)
    db.add(profile)
    await db.flush()
    copied = TroopProfileVersion(
        troop_profile=profile,
        version=1,
        rows_json=normalize_rows(version.rows_json),
        practice_trials=1,
        formal_trials=version.formal_trials,
        status=VERSION_DRAFT,
        content_hash=troop_profile_content_hash(
            normalized_name, version.rows_json, version.formal_trials
        ),
    )
    db.add(copied)
    await db.flush()
    return copied


async def seed_built_in_troop_profile(db: AsyncSession) -> None:
    payload = default_troop_profile_payload()
    existing = await _find_profile(db, payload["name"])
    if existing is not None:
        return
    formal_trials = validate_troop_profile_rows(payload["rows"])
    rows = normalize_rows(payload["rows"])
    profile = TroopProfile(name=payload["name"], built_in=True)
    db.add(profile)
    await db.flush()
    version = TroopProfileVersion(
        troop_profile=profile,
        version=1,
        rows_json=rows,
        practice_trials=1,
        formal_trials=formal_trials,
        status=VERSION_PUBLISHED,
        content_hash=troop_profile_content_hash(payload["name"], rows, formal_trials),
        published_at=utcnow(),
    )
    db.add(version)
    await db.commit()
