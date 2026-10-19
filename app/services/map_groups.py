import hashlib
import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    MAP_MODE_AB,
    MAP_MODE_BOTH,
    MAP_MODES,
    MAP_SLOT_A,
    MAP_SLOT_B,
    MAP_SLOT_BOTH,
    MAP_SLOT_BY_ROLE,
    MAP_SLOTS,
    VERSION_ARCHIVED,
    VERSION_DRAFT,
    VERSION_PUBLISHED,
)
from ..models import Map, MapGroupVersion, MediaAsset, TroopProfileVersion
from ..timeutil import isoformat_utc, utcnow

ALLOWED_MAP_CONTENT_TYPES = ("image/png", "image/jpeg")
NAME_PARTS_ERROR = "地图名称必须是四段：内容描述-尺寸-因素水平-玩家后缀"
PAYMENT_FIELDS = (
    ("base_pay_cents", "basePayCents"),
    ("performance_rate_cents", "performanceRateCents"),
    ("performance_cap_cents", "performanceCapCents"),
    ("showup_pay_cents", "showupPayCents"),
)


class MapGroupValidationError(ValueError):
    pass


def _require_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MapGroupValidationError(f"{label} 必须是整数")
    return value


def normalize_name_segment(value: Any) -> str:
    if not isinstance(value, str):
        raise MapGroupValidationError(NAME_PARTS_ERROR)
    normalized = value.strip()
    if not normalized or "-" in normalized:
        raise MapGroupValidationError(NAME_PARTS_ERROR)
    if len(normalized) > 200:
        raise MapGroupValidationError("地图名称每段不能超过 200 个字符")
    return normalized


def map_size_token(rows: int, cols: int) -> str:
    return f"{rows}*{cols}"


def validate_size_token(size_token: str, rows: int, cols: int) -> str:
    expected = map_size_token(rows, cols)
    if size_token != expected:
        raise MapGroupValidationError(f"地图尺寸标识必须为 {expected}")
    return expected


def build_map_name(
    description: str, rows: int, cols: int, factor_level: str, player_suffix: str
) -> dict:
    if player_suffix not in MAP_SLOTS:
        raise MapGroupValidationError("地图玩家后缀必须为 A、B 或 Both")
    description_value = normalize_name_segment(description)
    factor_value = normalize_name_segment(factor_level)
    size_value = validate_size_token(map_size_token(rows, cols), rows, cols)
    name = "-".join((description_value, size_value, factor_value, player_suffix))
    prefix = "-".join((description_value, size_value, factor_value))
    if len(name) > 300:
        raise MapGroupValidationError("地图完整名称不能超过 300 个字符")
    if len(prefix) > 200:
        raise MapGroupValidationError("地图组名称不能超过 200 个字符")
    return {
        "name": name,
        "prefix": prefix,
        "description": description_value,
        "sizeToken": size_value,
        "factorLevel": factor_value,
        "playerSuffix": player_suffix,
    }


def parse_map_name(name: Any, rows: int, cols: int) -> dict:
    if not isinstance(name, str):
        raise MapGroupValidationError(NAME_PARTS_ERROR)
    parts = name.split("-")
    if len(parts) != 4 or any(not part or part != part.strip() for part in parts):
        raise MapGroupValidationError(NAME_PARTS_ERROR)
    description, size_token, factor_level, player_suffix = parts
    validate_size_token(size_token, rows, cols)
    return build_map_name(description, rows, cols, factor_level, player_suffix)


def _map_slot_error(mode: str) -> str:
    if mode == MAP_MODE_BOTH:
        return "both 模式必须恰好包含一张 Both 地图"
    return "ab 模式必须恰好包含 A、B 各一张地图"


def _validate_dimensions(rows: Any, cols: Any) -> tuple[int, int]:
    row_count = _require_int(rows, "rows")
    col_count = _require_int(cols, "cols")
    if row_count < 2 or col_count < 2:
        raise MapGroupValidationError("地图行数和列数必须至少为 2")
    if row_count * col_count > 100:
        raise MapGroupValidationError("地图总格数不能超过 100")
    return row_count, col_count


def _validate_map_cells(cells: Any, total: int, asset_types: dict[str, str]) -> list:
    if not isinstance(cells, list) or len(cells) != total:
        raise MapGroupValidationError(f"地图单元格数量必须为 {total}")
    normalized = []
    for cell in cells:
        if cell is None:
            normalized.append(None)
            continue
        if not isinstance(cell, str) or not cell:
            raise MapGroupValidationError(f"地图单元格数量必须为 {total}")
        content_type = asset_types.get(cell)
        if content_type is None:
            raise MapGroupValidationError("地图单元格引用的图片资源不存在")
        if content_type not in ALLOWED_MAP_CONTENT_TYPES:
            raise MapGroupValidationError("地图单元格仅支持 PNG/JPG 图片")
        normalized.append(cell)
    return normalized


def _validate_payment(payment: Any) -> dict:
    if not isinstance(payment, dict):
        raise MapGroupValidationError("费用参数必须是对象")
    normalized = {}
    for field, _camel in PAYMENT_FIELDS:
        value = _require_int(payment.get(field), field)
        if value <= 0:
            raise MapGroupValidationError("回合上限、倒计时、休息和费用必须为正数")
        normalized[field] = value
    return normalized


def _validate_timing(payload: dict) -> dict:
    normalized = {}
    for field in (
        "practice_turn_cap",
        "practice_turn_seconds",
        "formal_turn_cap",
        "formal_turn_seconds",
        "rest_seconds",
    ):
        value = _require_int(payload.get(field), field)
        if value <= 0:
            raise MapGroupValidationError("回合上限、倒计时、休息和费用必须为正数")
        normalized[field] = value
    return normalized


def validate_map_group_payload(
    payload: dict, asset_types: dict[str, str], profile_formal_trials: int
) -> dict:
    mode = payload.get("mode")
    if mode not in MAP_MODES:
        raise MapGroupValidationError("地图组模式必须为 both 或 ab")
    rows, cols = _validate_dimensions(payload.get("rows"), payload.get("cols"))
    total = rows * cols

    practice_trials = _require_int(payload.get("practice_trials", 1), "practice_trials")
    if practice_trials != 1:
        raise MapGroupValidationError("练习对局数固定为 1")
    formal_trials = _require_int(payload.get("formal_trials"), "formal_trials")
    if formal_trials < 1:
        raise MapGroupValidationError("正式对局数至少为 1")
    if formal_trials != profile_formal_trials:
        raise MapGroupValidationError("地图组正式对局数与兵力配置不一致")

    maps = payload.get("maps")
    if not isinstance(maps, list):
        raise MapGroupValidationError("地图组必须包含地图")
    slots = [item.get("slot") for item in maps if isinstance(item, dict)]
    valid_slots = all(isinstance(item, dict) for item in maps)
    if mode == MAP_MODE_BOTH:
        if not valid_slots or len(slots) != 1 or slots[0] != MAP_SLOT_BOTH:
            raise MapGroupValidationError(_map_slot_error(mode))
    else:
        if not valid_slots or len(maps) != 2 or sorted(slots) != sorted((MAP_SLOT_A, MAP_SLOT_B)):
            raise MapGroupValidationError(_map_slot_error(mode))

    normalized_maps = []
    for item in maps:
        slot = item["slot"]
        description = item.get("description")
        factor_level = item.get("factor_level", item.get("factorLevel"))
        built = build_map_name(description, rows, cols, factor_level, slot)
        cells = _validate_map_cells(item.get("cells"), total, asset_types)
        normalized_maps.append(
            {
                "slot": slot,
                "name": built["name"],
                "description": built["description"],
                "sizeToken": built["sizeToken"],
                "factorLevel": built["factorLevel"],
                "playerSuffix": built["playerSuffix"],
                "cells": cells,
                "prefix": built["prefix"],
            }
        )

    if mode == MAP_MODE_AB:
        prefixes = {item["prefix"] for item in normalized_maps}
        if len(prefixes) != 1:
            raise MapGroupValidationError("A/B 地图的前三段必须一致")

    spawns = payload.get("spawns")
    if not isinstance(spawns, dict):
        raise MapGroupValidationError("出生格 A 和 B 必须在范围内且不能重合")
    spawn_a = _require_int(spawns.get(MAP_SLOT_A), "出生格 A")
    spawn_b = _require_int(spawns.get(MAP_SLOT_B), "出生格 B")
    if not (0 <= spawn_a < total) or not (0 <= spawn_b < total) or spawn_a == spawn_b:
        raise MapGroupValidationError("出生格 A 和 B 必须在范围内且不能重合")

    timing = _validate_timing(payload)
    payment = _validate_payment(payload.get("payment"))
    randomize_formal = payload.get("randomize_formal")
    if not isinstance(randomize_formal, bool):
        raise MapGroupValidationError("randomize_formal 必须是布尔值")

    first = normalized_maps[0]
    return {
        "mode": mode,
        "rows": rows,
        "cols": cols,
        "spawn_a_index": spawn_a,
        "spawn_b_index": spawn_b,
        "practice_trials": 1,
        "formal_trials": formal_trials,
        "randomize_formal": randomize_formal,
        "name": first["prefix"],
        "maps": normalized_maps,
        "payment": payment,
        **timing,
    }


def map_group_content_hash(data: dict) -> str:
    canonical = {
        "name": data["name"],
        "mode": data["mode"],
        "rows": data["rows"],
        "cols": data["cols"],
        "spawns": {"A": data["spawn_a_index"], "B": data["spawn_b_index"]},
        "troopProfileVersionId": data["troop_profile_version_id"],
        "practiceTrials": 1,
        "formalTrials": data["formal_trials"],
        "practiceTurnCap": data["practice_turn_cap"],
        "practiceTurnSeconds": data["practice_turn_seconds"],
        "formalTurnCap": data["formal_turn_cap"],
        "formalTurnSeconds": data["formal_turn_seconds"],
        "restSeconds": data["rest_seconds"],
        "randomizeFormal": data["randomize_formal"],
        "payment": {camel: data["payment"][field] for field, camel in PAYMENT_FIELDS},
        "maps": [
            {
                "slot": item["slot"],
                "name": item["name"],
                "description": item["description"],
                "sizeToken": item["sizeToken"],
                "factorLevel": item["factorLevel"],
                "playerSuffix": item["playerSuffix"],
                "cells": item["cells"],
            }
            for item in data["maps"]
        ],
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def map_group_payment(version: MapGroupVersion) -> dict:
    return {
        "basePayCents": version.base_pay_cents,
        "performanceRateCents": version.performance_rate_cents,
        "performanceCapCents": version.performance_cap_cents,
        "showupPayCents": version.showup_pay_cents,
    }


def _sorted_maps(version: MapGroupVersion) -> list[Map]:
    order = {MAP_SLOT_A: 0, MAP_SLOT_B: 1, MAP_SLOT_BOTH: 0}
    return sorted(version.maps, key=lambda item: (order.get(item.slot, 9), item.slot))


def serialize_map(version: MapGroupVersion) -> list[dict]:
    return [
        {
            "slot": item.slot,
            "name": item.name,
            "description": item.description,
            "sizeToken": item.size_token,
            "factorLevel": item.factor_level,
            "playerSuffix": item.player_suffix,
            "cells": item.cells_json,
        }
        for item in _sorted_maps(version)
    ]


def serialize_map_group_version(version: MapGroupVersion) -> dict:
    profile_version = version.troop_profile_version
    profile = profile_version.troop_profile
    return {
        "id": version.id,
        "versionId": version.id,
        "name": version.name,
        "version": version.version,
        "mode": version.mode,
        "rows": version.rows,
        "cols": version.cols,
        "spawns": {"A": version.spawn_a_index, "B": version.spawn_b_index},
        "practiceTrials": version.practice_trials,
        "formalTrials": version.formal_trials,
        "practiceTurnCap": version.practice_turn_cap,
        "practiceTurnSeconds": version.practice_turn_seconds,
        "formalTurnCap": version.formal_turn_cap,
        "formalTurnSeconds": version.formal_turn_seconds,
        "restSeconds": version.rest_seconds,
        "randomizeFormal": version.randomize_formal,
        "payment": map_group_payment(version),
        "profile": {
            "profileId": profile.id,
            "versionId": profile_version.id,
            "name": profile.name,
            "version": profile_version.version,
            "builtIn": profile.built_in,
            "rows": profile_version.rows_json,
        },
        "maps": serialize_map(version),
        "status": version.status,
        "contentHash": version.content_hash,
        "publishedAt": isoformat_utc(version.published_at),
        "createdAt": isoformat_utc(version.created_at),
    }


def serialize_map_group_snapshot(version: MapGroupVersion) -> dict:
    data = serialize_map_group_version(version)
    data.pop("status", None)
    data.pop("createdAt", None)
    return data


def build_role_visuals(version: MapGroupVersion, role: int) -> list[dict]:
    if role not in MAP_SLOT_BY_ROLE:
        raise ValueError("role 必须是 1 或 2")
    slot = MAP_SLOT_BOTH if version.mode == MAP_MODE_BOTH else MAP_SLOT_BY_ROLE[role]
    selected = next((item for item in version.maps if item.slot == slot), None)
    if selected is None:
        raise ValueError("地图组缺少角色对应的地图")
    return [{"color": None, "backgroundAssetId": cell} for cell in selected.cells_json]


async def collect_asset_types(db: AsyncSession, asset_ids: set[str]) -> dict[str, str]:
    if not asset_ids:
        return {}
    rows = await db.execute(select(MediaAsset).where(MediaAsset.id.in_(asset_ids)))
    return {asset.id: asset.content_type for asset in rows.scalars().all()}


def _payload_asset_ids(maps: list) -> set[str]:
    ids: set[str] = set()
    for item in maps:
        if not isinstance(item, dict):
            continue
        cells = item.get("cells")
        if not isinstance(cells, list):
            continue
        for cell in cells:
            if isinstance(cell, str) and cell:
                ids.add(cell)
    return ids


async def _get_profile_version(db: AsyncSession, version_id: str) -> TroopProfileVersion:
    version = await db.get(TroopProfileVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "兵力配置方案版本不存在")
    if version.status != VERSION_PUBLISHED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "兵力配置方案版本尚未发布")
    return version


async def _next_group_version(db: AsyncSession, name: str) -> int:
    current = (
        await db.execute(select(func.max(MapGroupVersion.version)).where(MapGroupVersion.name == name))
    ).scalar_one_or_none()
    return (current or 0) + 1


def _version_payload(version: MapGroupVersion) -> dict:
    return {
        "mode": version.mode,
        "rows": version.rows,
        "cols": version.cols,
        "spawns": {"A": version.spawn_a_index, "B": version.spawn_b_index},
        "troop_profile_version_id": version.troop_profile_version_id,
        "practice_trials": version.practice_trials,
        "formal_trials": version.formal_trials,
        "practice_turn_cap": version.practice_turn_cap,
        "practice_turn_seconds": version.practice_turn_seconds,
        "formal_turn_cap": version.formal_turn_cap,
        "formal_turn_seconds": version.formal_turn_seconds,
        "rest_seconds": version.rest_seconds,
        "randomize_formal": version.randomize_formal,
        "payment": {
            "base_pay_cents": version.base_pay_cents,
            "performance_rate_cents": version.performance_rate_cents,
            "performance_cap_cents": version.performance_cap_cents,
            "showup_pay_cents": version.showup_pay_cents,
        },
        "maps": [
            {
                "slot": item.slot,
                "description": item.description,
                "factor_level": item.factor_level,
                "cells": item.cells_json,
            }
            for item in _sorted_maps(version)
        ],
    }


def _apply_validated(version: MapGroupVersion, data: dict) -> None:
    version.name = data["name"]
    version.mode = data["mode"]
    version.rows = data["rows"]
    version.cols = data["cols"]
    version.spawn_a_index = data["spawn_a_index"]
    version.spawn_b_index = data["spawn_b_index"]
    version.practice_trials = 1
    version.formal_trials = data["formal_trials"]
    version.practice_turn_cap = data["practice_turn_cap"]
    version.practice_turn_seconds = data["practice_turn_seconds"]
    version.formal_turn_cap = data["formal_turn_cap"]
    version.formal_turn_seconds = data["formal_turn_seconds"]
    version.rest_seconds = data["rest_seconds"]
    version.randomize_formal = data["randomize_formal"]
    version.base_pay_cents = data["payment"]["base_pay_cents"]
    version.performance_rate_cents = data["payment"]["performance_rate_cents"]
    version.performance_cap_cents = data["payment"]["performance_cap_cents"]
    version.showup_pay_cents = data["payment"]["showup_pay_cents"]
    version.content_hash = map_group_content_hash(data)


def _replace_maps(version: MapGroupVersion, maps: list[dict]) -> None:
    existing = {item.slot: item for item in version.maps}
    kept_slots: set[str] = set()
    for item in maps:
        kept_slots.add(item["slot"])
        row = existing.get(item["slot"])
        if row is None:
            version.maps.append(
                Map(
                    slot=item["slot"],
                    name=item["name"],
                    description=item["description"],
                    size_token=item["sizeToken"],
                    factor_level=item["factorLevel"],
                    player_suffix=item["playerSuffix"],
                    cells_json=item["cells"],
                )
            )
            continue
        row.name = item["name"]
        row.description = item["description"]
        row.size_token = item["sizeToken"]
        row.factor_level = item["factorLevel"]
        row.player_suffix = item["playerSuffix"]
        row.cells_json = item["cells"]
    for slot, row in existing.items():
        if slot not in kept_slots:
            version.maps.remove(row)


async def create_map_group(db: AsyncSession, payload: dict) -> MapGroupVersion:
    profile_version = await _get_profile_version(db, payload.get("troop_profile_version_id"))
    asset_types = await collect_asset_types(db, _payload_asset_ids(payload.get("maps") or []))
    data = validate_map_group_payload(payload, asset_types, profile_version.formal_trials)
    data["troop_profile_version_id"] = profile_version.id
    version = MapGroupVersion(
        name=data["name"],
        version=await _next_group_version(db, data["name"]),
        troop_profile_version=profile_version,
        status=VERSION_DRAFT,
    )
    _apply_validated(version, data)
    _replace_maps(version, data["maps"])
    db.add(version)
    await db.flush()
    return version


async def update_map_group(db: AsyncSession, version: MapGroupVersion, patch: dict) -> MapGroupVersion:
    if version.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "已发布的版本不可修改，请创建新版本")
    payload = _version_payload(version)
    for key, value in patch.items():
        if value is not None:
            payload[key] = value
    profile_version = version.troop_profile_version
    if patch.get("troop_profile_version_id") is not None:
        profile_version = await _get_profile_version(db, patch["troop_profile_version_id"])
    payload["troop_profile_version_id"] = profile_version.id
    asset_types = await collect_asset_types(db, _payload_asset_ids(payload["maps"]))
    data = validate_map_group_payload(payload, asset_types, profile_version.formal_trials)
    data["troop_profile_version_id"] = profile_version.id
    conflict = await db.execute(
        select(MapGroupVersion.id).where(
            MapGroupVersion.name == data["name"],
            MapGroupVersion.version == version.version,
            MapGroupVersion.id != version.id,
        )
    )
    if conflict.scalars().first() is not None:
        raise MapGroupValidationError("地图组名称与已有版本冲突")
    _apply_validated(version, data)
    version.troop_profile_version = profile_version
    _replace_maps(version, data["maps"])
    await db.flush()
    return version


async def publish_map_group(db: AsyncSession, version: MapGroupVersion) -> MapGroupVersion:
    if version.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "已发布的版本不可修改，请创建新版本")
    payload = _version_payload(version)
    asset_types = await collect_asset_types(db, _payload_asset_ids(payload["maps"]))
    data = validate_map_group_payload(
        payload, asset_types, version.troop_profile_version.formal_trials
    )
    data["troop_profile_version_id"] = version.troop_profile_version_id
    previous = await db.execute(
        select(MapGroupVersion).where(
            MapGroupVersion.name == version.name,
            MapGroupVersion.status == VERSION_PUBLISHED,
            MapGroupVersion.id != version.id,
        )
    )
    for row in previous.scalars().all():
        row.status = VERSION_ARCHIVED
    _apply_validated(version, data)
    version.status = VERSION_PUBLISHED
    version.published_at = utcnow()
    await db.flush()
    return version


async def get_map_group_version(db: AsyncSession, version_id: str) -> MapGroupVersion:
    version = await db.get(MapGroupVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "地图组版本不存在")
    return version


async def list_map_groups(db: AsyncSession) -> list[dict]:
    rows = await db.execute(
        select(MapGroupVersion).order_by(MapGroupVersion.name, MapGroupVersion.version.desc())
    )
    return [serialize_map_group_version(version) for version in rows.scalars().all()]
