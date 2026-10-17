import json
import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import CONDITION_SCHEMA_VERSION, VERSION_ARCHIVED, VERSION_DRAFT, VERSION_PUBLISHED
from ..models import ConditionVersion, MediaAsset
from ..presets import PRESET_DEFINITIONS, preset_payload
from ..timeutil import isoformat_utc, utcnow

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ConditionValidationError(ValueError):
    pass


def _require_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConditionValidationError(f"{label} 必须是整数")
    return value


def _require_non_negative(value: Any, label: str) -> int:
    number = _require_int(value, label)
    if number < 0:
        raise ConditionValidationError(f"{label} 必须大于等于 0")
    return number


def _validate_overrides(overrides: Any, total_cells: int, label: str) -> None:
    if overrides is None:
        return
    if not isinstance(overrides, dict):
        raise ConditionValidationError(f"{label} 必须是对象或 null")
    for key in ("player1", "player2"):
        entries = overrides.get(key)
        if entries is None:
            continue
        if not isinstance(entries, list):
            raise ConditionValidationError(f"{label}.{key} 必须是数组")
        seen: set[int] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ConditionValidationError(f"{label}.{key} 的条目必须是对象")
            cell_index = _require_int(entry.get("cellIndex"), f"{label}.{key}.cellIndex")
            if not 0 <= cell_index < total_cells:
                raise ConditionValidationError(f"{label}.{key}.cellIndex 超出网格范围")
            if cell_index in seen:
                raise ConditionValidationError(f"{label}.{key} 存在重复 cellIndex")
            seen.add(cell_index)
            _require_non_negative(entry.get("value"), f"{label}.{key}.value")


def validate_condition_payload(payload: dict, asset_ids: set[str]) -> None:
    rows = _require_int(payload.get("rows"), "rows")
    cols = _require_int(payload.get("cols"), "cols")
    if not 2 <= rows <= 20 or not 2 <= cols <= 20:
        raise ConditionValidationError("rows 和 cols 必须在 2 到 20 之间")
    total = rows * cols
    if total > 100:
        raise ConditionValidationError("网格总格数不能超过 100")

    cells = payload.get("cells")
    if not isinstance(cells, list) or len(cells) != total:
        raise ConditionValidationError(f"cells 长度必须等于 rows * cols = {total}")
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            raise ConditionValidationError("cells 的每一项必须是对象")
        if cell.get("row") != index // cols or cell.get("col") != index % cols:
            raise ConditionValidationError(f"cells[{index}] 的 row/col 与行优先索引不一致")
        owner = _require_int(cell.get("initialOwner"), f"cells[{index}].initialOwner")
        if owner not in (0, 1, 2):
            raise ConditionValidationError(f"cells[{index}].initialOwner 必须是 0、1 或 2")
        _require_non_negative(cell.get("initialSoldiers"), f"cells[{index}].initialSoldiers")
        _require_non_negative(cell.get("reinforcementA"), f"cells[{index}].reinforcementA")
        _require_non_negative(cell.get("reinforcementB"), f"cells[{index}].reinforcementB")

    visuals = payload.get("visuals")
    if not isinstance(visuals, dict):
        raise ConditionValidationError("visuals 必须是对象")
    for player_key in ("player1", "player2"):
        layer = visuals.get(player_key)
        if not isinstance(layer, list) or len(layer) != total:
            raise ConditionValidationError(f"visuals.{player_key} 长度必须等于 {total}")
        for index, item in enumerate(layer):
            if not isinstance(item, dict):
                raise ConditionValidationError(f"visuals.{player_key}[{index}] 必须是对象")
            color = item.get("color")
            if color is not None and not _HEX_COLOR.fullmatch(str(color)):
                raise ConditionValidationError(f"visuals.{player_key}[{index}].color 必须是十六进制颜色")
            asset_id = item.get("backgroundAssetId")
            if asset_id is not None and asset_id not in asset_ids:
                raise ConditionValidationError(f"visuals.{player_key}[{index}] 引用的背景资产不存在")
        if all(item.get("color") is None and item.get("backgroundAssetId") is None for item in layer):
            raise ConditionValidationError(f"visuals.{player_key} 不能全部为空")

    base_a = _require_int(payload.get("base_a_index"), "base_a_index")
    base_b = _require_int(payload.get("base_b_index"), "base_b_index")
    if not 0 <= base_a < total or not 0 <= base_b < total:
        raise ConditionValidationError("基地索引超出网格范围")
    if base_a == base_b:
        raise ConditionValidationError("两个基地不能重合")
    if cells[base_a]["initialOwner"] != 1:
        raise ConditionValidationError("基地 A 的初始归属必须是玩家1")
    if cells[base_b]["initialOwner"] != 2:
        raise ConditionValidationError("基地 B 的初始归属必须是玩家2")
    owners = {cell["initialOwner"] for cell in cells}
    if 1 not in owners or 2 not in owners:
        raise ConditionValidationError("每名玩家至少需要一个初始归属格")

    practice_trials = _require_int(payload.get("practice_trials"), "practice_trials")
    formal_trials = _require_int(payload.get("formal_trials"), "formal_trials")
    if practice_trials < 0:
        raise ConditionValidationError("练习 trial 数不能为负")
    if formal_trials < 1:
        raise ConditionValidationError("正式 trial 数至少为 1")
    trial_params = payload.get("trial_params")
    expected_params = practice_trials + formal_trials
    if not isinstance(trial_params, list) or len(trial_params) != expected_params:
        raise ConditionValidationError(f"trial_params 长度必须等于 {expected_params}")
    for index, entry in enumerate(trial_params):
        if not isinstance(entry, dict):
            raise ConditionValidationError("trial_params 的每一项必须是对象")
        if entry.get("sourceIndex") != index:
            raise ConditionValidationError(f"trial_params[{index}].sourceIndex 必须等于 {index}")
        is_practice = entry.get("isPractice")
        if not isinstance(is_practice, bool):
            raise ConditionValidationError(f"trial_params[{index}].isPractice 必须是布尔值")
        if is_practice != (index < practice_trials):
            raise ConditionValidationError(f"trial_params[{index}].isPractice 与练习 trial 数不一致")
        expected_formal = 0 if is_practice else index - practice_trials + 1
        if entry.get("formalTrial") != expected_formal:
            raise ConditionValidationError(f"trial_params[{index}].formalTrial 必须等于 {expected_formal}")
        if _require_int(entry.get("baseSoldiersA"), f"trial_params[{index}].baseSoldiersA") <= 0:
            raise ConditionValidationError(f"trial_params[{index}].baseSoldiersA 必须大于 0")
        if _require_int(entry.get("baseSoldiersB"), f"trial_params[{index}].baseSoldiersB") <= 0:
            raise ConditionValidationError(f"trial_params[{index}].baseSoldiersB 必须大于 0")
        _validate_overrides(
            entry.get("reinforcementOverrides"), total, f"trial_params[{index}].reinforcementOverrides"
        )

    for field in ("turn_count", "turn_seconds", "rest_seconds"):
        if _require_int(payload.get(field), field) <= 0:
            raise ConditionValidationError(f"{field} 必须大于 0")
    if not isinstance(payload.get("randomize_formal"), bool):
        raise ConditionValidationError("randomize_formal 必须是布尔值")
    if not isinstance(payload.get("metadata", {}), dict):
        raise ConditionValidationError("metadata 必须是对象")


def condition_content_hash(payload: dict) -> str:
    canonical = {
        "name": payload["name"],
        "description": payload.get("description"),
        "schemaVersion": payload.get("schema_version", CONDITION_SCHEMA_VERSION),
        "rows": payload["rows"],
        "cols": payload["cols"],
        "cells": payload["cells"],
        "visuals": payload["visuals"],
        "baseAIndex": payload["base_a_index"],
        "baseBIndex": payload["base_b_index"],
        "trialParams": payload["trial_params"],
        "practiceTrials": payload["practice_trials"],
        "formalTrials": payload["formal_trials"],
        "turnCount": payload["turn_count"],
        "turnSeconds": payload["turn_seconds"],
        "restSeconds": payload["rest_seconds"],
        "randomizeFormal": payload["randomize_formal"],
        "metadata": payload.get("metadata", {}),
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    import hashlib

    return "sha256:" + hashlib.sha256(encoded).hexdigest()


async def collect_asset_ids(db: AsyncSession) -> set[str]:
    rows = await db.execute(select(MediaAsset.id))
    return set(rows.scalars().all())


def serialize_condition(condition: ConditionVersion) -> dict:
    return {
        "id": condition.id,
        "name": condition.name,
        "version": condition.version,
        "schemaVersion": condition.schema_version,
        "description": condition.description,
        "rows": condition.rows,
        "cols": condition.cols,
        "cells": condition.cells_json,
        "visuals": condition.visuals_json,
        "baseAIndex": condition.base_a_index,
        "baseBIndex": condition.base_b_index,
        "practiceTrials": condition.practice_trials,
        "formalTrials": condition.formal_trials,
        "turnCount": condition.turn_count,
        "turnSeconds": condition.turn_seconds,
        "restSeconds": condition.rest_seconds,
        "randomizeFormal": condition.randomize_formal,
        "trialParams": condition.trial_params_json,
        "metadata": condition.metadata_json,
        "status": condition.status,
        "contentHash": condition.content_hash,
        "publishedAt": isoformat_utc(condition.published_at),
        "createdAt": isoformat_utc(condition.created_at),
    }


def serialize_condition_snapshot(condition: ConditionVersion) -> dict:
    data = serialize_condition(condition)
    data.pop("status", None)
    data.pop("createdAt", None)
    return data


def _payload_from_create(data: dict) -> dict:
    payload = dict(data)
    payload.setdefault("schema_version", CONDITION_SCHEMA_VERSION)
    return payload


async def next_condition_version(db: AsyncSession, name: str) -> int:
    rows = await db.execute(select(ConditionVersion.version).where(ConditionVersion.name == name))
    versions = rows.scalars().all()
    return max(versions) + 1 if versions else 1


async def create_condition(db: AsyncSession, data: dict) -> ConditionVersion:
    asset_ids = await collect_asset_ids(db)
    validate_condition_payload(data, asset_ids)
    version = await next_condition_version(db, data["name"])
    condition = ConditionVersion(
        name=data["name"],
        version=version,
        schema_version=CONDITION_SCHEMA_VERSION,
        description=data.get("description"),
        rows=data["rows"],
        cols=data["cols"],
        cells_json=data["cells"],
        visuals_json=data["visuals"],
        base_a_index=data["base_a_index"],
        base_b_index=data["base_b_index"],
        trial_params_json=data["trial_params"],
        practice_trials=data["practice_trials"],
        formal_trials=data["formal_trials"],
        turn_count=data["turn_count"],
        turn_seconds=data["turn_seconds"],
        rest_seconds=data["rest_seconds"],
        randomize_formal=data["randomize_formal"],
        metadata_json=data.get("metadata", {}),
        status=VERSION_DRAFT,
    )
    condition.content_hash = condition_content_hash(_payload_from_create(data))
    db.add(condition)
    await db.flush()
    return condition


def _merge_patch(condition: ConditionVersion, patch: dict) -> dict:
    payload = {
        "name": patch.get("name", condition.name),
        "description": patch.get("description", condition.description),
        "rows": patch.get("rows", condition.rows),
        "cols": patch.get("cols", condition.cols),
        "cells": patch.get("cells", condition.cells_json),
        "visuals": patch.get("visuals", condition.visuals_json),
        "base_a_index": patch.get("base_a_index", condition.base_a_index),
        "base_b_index": patch.get("base_b_index", condition.base_b_index),
        "trial_params": patch.get("trial_params", condition.trial_params_json),
        "practice_trials": patch.get("practice_trials", condition.practice_trials),
        "formal_trials": patch.get("formal_trials", condition.formal_trials),
        "turn_count": patch.get("turn_count", condition.turn_count),
        "turn_seconds": patch.get("turn_seconds", condition.turn_seconds),
        "rest_seconds": patch.get("rest_seconds", condition.rest_seconds),
        "randomize_formal": patch.get("randomize_formal", condition.randomize_formal),
        "metadata": patch.get("metadata", condition.metadata_json),
    }
    return payload


async def update_condition(db: AsyncSession, condition: ConditionVersion, patch: dict) -> ConditionVersion:
    if condition.status != VERSION_DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "已发布的条件版本不可修改，请创建新版本")
    payload = _merge_patch(condition, patch)
    asset_ids = await collect_asset_ids(db)
    validate_condition_payload(payload, asset_ids)
    condition.name = payload["name"]
    condition.description = payload["description"]
    condition.rows = payload["rows"]
    condition.cols = payload["cols"]
    condition.cells_json = payload["cells"]
    condition.visuals_json = payload["visuals"]
    condition.base_a_index = payload["base_a_index"]
    condition.base_b_index = payload["base_b_index"]
    condition.trial_params_json = payload["trial_params"]
    condition.practice_trials = payload["practice_trials"]
    condition.formal_trials = payload["formal_trials"]
    condition.turn_count = payload["turn_count"]
    condition.turn_seconds = payload["turn_seconds"]
    condition.rest_seconds = payload["rest_seconds"]
    condition.randomize_formal = payload["randomize_formal"]
    condition.metadata_json = payload["metadata"]
    condition.content_hash = condition_content_hash(_payload_from_create(payload))
    await db.flush()
    return condition


async def publish_condition(db: AsyncSession, condition: ConditionVersion) -> ConditionVersion:
    asset_ids = await collect_asset_ids(db)
    previous_rows = await db.execute(
        select(ConditionVersion).where(
            ConditionVersion.name == condition.name,
            ConditionVersion.status == VERSION_PUBLISHED,
            ConditionVersion.id != condition.id,
        )
    )
    for previous in previous_rows.scalars().all():
        previous.status = VERSION_ARCHIVED
    payload = {
        "name": condition.name,
        "description": condition.description,
        "rows": condition.rows,
        "cols": condition.cols,
        "cells": condition.cells_json,
        "visuals": condition.visuals_json,
        "base_a_index": condition.base_a_index,
        "base_b_index": condition.base_b_index,
        "trial_params": condition.trial_params_json,
        "practice_trials": condition.practice_trials,
        "formal_trials": condition.formal_trials,
        "turn_count": condition.turn_count,
        "turn_seconds": condition.turn_seconds,
        "rest_seconds": condition.rest_seconds,
        "randomize_formal": condition.randomize_formal,
        "metadata": condition.metadata_json,
    }
    validate_condition_payload(payload, asset_ids)
    condition.status = VERSION_PUBLISHED
    condition.published_at = utcnow()
    condition.content_hash = condition_content_hash(_payload_from_create(payload))
    await db.flush()
    return condition


async def seed_presets(db: AsyncSession) -> None:
    for name in PRESET_DEFINITIONS:
        existing = await db.execute(
            select(ConditionVersion).where(
                ConditionVersion.name == name, ConditionVersion.status == VERSION_PUBLISHED
            )
        )
        if existing.scalars().first() is not None:
            continue
        payload = preset_payload(name)
        asset_ids = await collect_asset_ids(db)
        validate_condition_payload(payload, asset_ids)
        condition = ConditionVersion(
            name=name,
            version=await next_condition_version(db, name),
            schema_version=CONDITION_SCHEMA_VERSION,
            description=payload["description"],
            rows=payload["rows"],
            cols=payload["cols"],
            cells_json=payload["cells"],
            visuals_json=payload["visuals"],
            base_a_index=payload["base_a_index"],
            base_b_index=payload["base_b_index"],
            trial_params_json=payload["trial_params"],
            practice_trials=payload["practice_trials"],
            formal_trials=payload["formal_trials"],
            turn_count=payload["turn_count"],
            turn_seconds=payload["turn_seconds"],
            rest_seconds=payload["rest_seconds"],
            randomize_formal=payload["randomize_formal"],
            metadata_json=payload["metadata"],
            status=VERSION_PUBLISHED,
            content_hash=condition_content_hash(payload),
            published_at=utcnow(),
        )
        db.add(condition)
    await db.commit()
